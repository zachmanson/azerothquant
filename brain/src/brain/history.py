"""The Brain's persistent history: Scans imported into SQLite as Listing lifetimes,
Mailbox Reads as the Outcomes and Purchases in them, and Character Reads as each
Character's gold and Holdings. Scans and Character Reads also carry each item's Vendor
Price, kept per Era as last seen.

Each Listing is stored once, with the first and last Scan it was seen in (ADR-0002).
A Listing whose last Scan isn't its Market's latest one has disappeared. Each drop in
a Listing's quantity is stored as a Partial Sale.

Each Auction House mail is stored once too, however many Mailbox Reads it shows up in:
mail stays in the inbox until taken, so each Read is matched against the one before.
"""

import json
import logging
import math
import os
import sqlite3
import statistics
from array import array
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from brain.archive import Archive, ArchivedScan
from brain.config import Config, Era
from brain.disenchant import DisenchantResult, ItemInfo
from brain.mailbox import (
    OUTCOME_KINDS,
    AuctionMail,
    LiveMail,
    MailFormatError,
    MailKind,
    arrived_at,
    faction_of,
    match_mails,
    parse_mail,
)
from brain.matching import match
from brain.savedvariables import parse_savedvariables
from brain.scan import ItemKey, ItemStringError, Scan, ScanFormatError, ScanSource
from brain.timings import Timings, timed

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS market (
    id INTEGER PRIMARY KEY,
    realm TEXT NOT NULL,
    faction TEXT NOT NULL,
    era TEXT NOT NULL,
    UNIQUE (realm, faction, era)
);

CREATE TABLE IF NOT EXISTS scan (
    id INTEGER PRIMARY KEY,
    market_id INTEGER NOT NULL REFERENCES market (id),
    requested_at INTEGER NOT NULL,  -- Unix time; with the Market, the Scan's identity
    character TEXT NOT NULL,
    dropped_rows INTEGER NOT NULL,
    inexact_rows INTEGER NOT NULL,
    unreadable_rows INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'own',  -- own or pool (a Pooled Scan, ADR-0026)
    pool_id TEXT,          -- the pool's ID: a Pooled Scan's, or an own Scan's once uploaded
    readable_rows INTEGER, -- rows the Brain could read; NULL in Scans from before #122
    UNIQUE (market_id, requested_at)
);

-- The items a Scan dropped rows of for missing item data (#150). Their Listings may
-- have been missed rather than gone, so the Observation Windows either side of the Scan
-- leave those items out.
CREATE TABLE IF NOT EXISTS scan_dropped_item (
    scan_id INTEGER NOT NULL REFERENCES scan (id),
    item_id INTEGER NOT NULL,
    PRIMARY KEY (scan_id, item_id)
);

-- A Scan's Fair Values, kept so a restarted Brain doesn't work them out again (#145).
-- `worked_out_with` names the code and config that made them; a re-match deletes them
-- with their Scan. One row a Scan: Fair Values worked out another way replace it.
CREATE TABLE IF NOT EXISTS scan_fair_values (
    scan_id INTEGER PRIMARY KEY REFERENCES scan (id),
    worked_out_with TEXT NOT NULL,
    fair_values TEXT NOT NULL  -- JSON: {item key: Fair Value}
);

-- Every Pooled Scan downloaded into the Archive, imported or not, so a pull skips it and a
-- rollback can find it (#122).
CREATE TABLE IF NOT EXISTS pooled_scan (
    pool_id TEXT PRIMARY KEY,
    market_id INTEGER NOT NULL REFERENCES market (id),
    requested_at INTEGER NOT NULL
);

-- Where the last pull from the Scan Pool got to. One row at most.
CREATE TABLE IF NOT EXISTS pool_cursor (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cursor INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS listing (
    id INTEGER PRIMARY KEY,
    market_id INTEGER NOT NULL REFERENCES market (id),
    item_key TEXT NOT NULL,
    unit_buyout INTEGER NOT NULL,  -- copper
    own INTEGER NOT NULL,          -- 0 or 1
    first_seen_scan_id INTEGER NOT NULL REFERENCES scan (id),
    last_seen_scan_id INTEGER NOT NULL REFERENCES scan (id),
    quantity INTEGER NOT NULL,     -- as of the last-seen Scan
    time_left INTEGER NOT NULL,    -- bucket 1-4, as of the last-seen Scan
    item_name TEXT                 -- own Listings only, and NULL in Scans from before #17
);
CREATE INDEX IF NOT EXISTS listing_by_last_seen ON listing (last_seen_scan_id);
CREATE INDEX IF NOT EXISTS listing_by_first_seen ON listing (first_seen_scan_id);

CREATE TABLE IF NOT EXISTS partial_sale (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listing (id),
    scan_id INTEGER NOT NULL REFERENCES scan (id),  -- the Scan where the drop was seen
    units_sold INTEGER NOT NULL,
    UNIQUE (listing_id, scan_id)
);

-- Each drop in a Listing's time-left bucket, so a re-match can rewind it (#118).
CREATE TABLE IF NOT EXISTS time_left_drop (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listing (id),
    scan_id INTEGER NOT NULL REFERENCES scan (id),  -- the Scan where the drop was seen
    time_left_before INTEGER NOT NULL,
    UNIQUE (listing_id, scan_id)
);
-- The Scan where a Listing first seen as not own was seen as own (#119), so a re-match
-- can take own back. Once own, a Listing stays own, so it turns own at most once.
CREATE TABLE IF NOT EXISTS turned_own (
    listing_id INTEGER PRIMARY KEY REFERENCES listing (id),
    scan_id INTEGER NOT NULL REFERENCES scan (id)
);
CREATE INDEX IF NOT EXISTS turned_own_by_scan ON turned_own (scan_id);
-- A re-match deletes the drops seen in its Market's tail by Scan.
CREATE INDEX IF NOT EXISTS partial_sale_by_scan ON partial_sale (scan_id);
CREATE INDEX IF NOT EXISTS time_left_drop_by_scan ON time_left_drop (scan_id);

-- One row per imported Mailbox Read; its mail is read back from the Archive.
CREATE TABLE IF NOT EXISTS mailbox_read (
    id INTEGER PRIMARY KEY,
    era TEXT NOT NULL,
    realm TEXT NOT NULL,
    character TEXT NOT NULL,
    read_at INTEGER NOT NULL,  -- Unix time; with era, realm and character, its identity
    mails INTEGER NOT NULL,    -- Auction House mails in it
    UNIQUE (era, realm, character, read_at)
);

-- One row per Auction House mail, however many Mailbox Reads it was in. Kinds sold,
-- cancelled and expired are Outcomes; won is a Purchase.
CREATE TABLE IF NOT EXISTS auction_mail (
    id INTEGER PRIMARY KEY,
    era TEXT NOT NULL,
    realm TEXT NOT NULL,
    character TEXT NOT NULL,       -- whose inbox it was in
    market_id INTEGER REFERENCES market (id),  -- NULL when the sender isn't known
    kind TEXT NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    item_name TEXT NOT NULL,
    item_key TEXT,                 -- NULL for sale mail, which has no attachment
    count INTEGER NOT NULL,
    price INTEGER,                 -- copper for the stack; NULL for cancelled and expired
    money INTEGER NOT NULL,        -- copper attached
    deposit INTEGER,               -- copper a sale's posting cost (#78); NULL for other mail
    arrived_at INTEGER,            -- Unix time; NULL until daysLeft starts counting down
    first_read_at INTEGER NOT NULL,
    last_read_at INTEGER NOT NULL,
    live INTEGER NOT NULL          -- 1 while it may still be in the inbox
);
CREATE INDEX IF NOT EXISTS auction_mail_live ON auction_mail (era, realm, character, live);

-- One row per imported Character Read.
CREATE TABLE IF NOT EXISTS character_read (
    id INTEGER PRIMARY KEY,
    era TEXT NOT NULL,
    realm TEXT NOT NULL,
    character TEXT NOT NULL,
    read_at INTEGER NOT NULL,  -- Unix time; with era, realm and character, its identity
    faction TEXT,
    money INTEGER,             -- copper
    has_bank INTEGER NOT NULL, -- 0 or 1: the bank was opened that session
    bank_read_at INTEGER,      -- when the bank was last read while open
    has_profession_list INTEGER NOT NULL DEFAULT 0, -- 0 or 1: the client said which
    budget INTEGER,            -- copper: the Market's Budget as set then; NULL for none
    days_to_sell REAL,         -- the Market's Days to Sell as set then; NULL for none
    UNIQUE (era, realm, character, read_at)
);

-- The professions a Character has, as of one Character Read that could say.
CREATE TABLE IF NOT EXISTS character_profession (
    character_read_id INTEGER NOT NULL REFERENCES character_read (id),
    profession_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS character_profession_by_read
    ON character_profession (character_read_id);

-- The items in one Character Read, one row per filled slot.
CREATE TABLE IF NOT EXISTS character_item (
    id INTEGER PRIMARY KEY,
    character_read_id INTEGER NOT NULL REFERENCES character_read (id),
    place TEXT NOT NULL,       -- 'bags' or 'bank'
    item_key TEXT NOT NULL,
    count INTEGER NOT NULL,
    bound INTEGER NOT NULL     -- 0 or 1; bound items can't go on the Auction House
);
CREATE INDEX IF NOT EXISTS character_item_by_read ON character_item (character_read_id);

-- Vendor Price per itemID (every random suffix shares it), from Scans and Character Reads.
CREATE TABLE IF NOT EXISTS vendor_price (
    era TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    price INTEGER NOT NULL,    -- copper; 0 when a vendor won't buy it
    seen_at INTEGER NOT NULL,  -- requestedAt or readAt of the Scan or Read it came from
    PRIMARY KEY (era, item_id)
);

-- What the client says about an itemID, from Scans and Character Reads: a Disenchant
-- source group's inputs, kept only for armor and weapons that could be Disenchanted.
CREATE TABLE IF NOT EXISTS item_info (
    era TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    item_level INTEGER NOT NULL,
    quality INTEGER NOT NULL,
    class_id INTEGER NOT NULL,
    equip_loc TEXT NOT NULL,   -- empty when it can't be equipped
    seen_at INTEGER NOT NULL,  -- requestedAt or readAt of the Scan or Read it came from
    PRIMARY KEY (era, item_id)
);

-- What each Disenchant the player cast yielded (#76), carried on the Character Read of its
-- session. The item's fields are NULL when the Addon couldn't tell which item it was.
CREATE TABLE IF NOT EXISTS disenchant_result (
    id INTEGER PRIMARY KEY,
    character_read_id INTEGER NOT NULL REFERENCES character_read (id),
    at INTEGER NOT NULL,
    item_id INTEGER,
    item_level INTEGER,
    quality INTEGER,
    class_id INTEGER
);
CREATE INDEX IF NOT EXISTS disenchant_result_by_read ON disenchant_result (character_read_id);

CREATE TABLE IF NOT EXISTS disenchant_result_mat (
    disenchant_result_id INTEGER NOT NULL REFERENCES disenchant_result (id),
    item_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL
);

-- Each craft the player made with a Known Recipe (#44), carried on the Character Read of
-- its session as crafts. What its recipe makes and uses is as that Read's profession
-- window read had it: NULL and no reagents when the Read didn't have the recipe.
CREATE TABLE IF NOT EXISTS craft (
    id INTEGER PRIMARY KEY,
    character_read_id INTEGER NOT NULL REFERENCES character_read (id),
    at INTEGER NOT NULL,
    recipe_id INTEGER NOT NULL,
    quantity INTEGER,          -- output units made; NULL when the Addon couldn't read it
    output_item_id INTEGER,    -- NULL when the recipe makes no item
    quantity_min INTEGER       -- the recipe's fewest output units
);
CREATE INDEX IF NOT EXISTS craft_by_read ON craft (character_read_id);

-- The Basic reagent slots of one craft's recipe.
CREATE TABLE IF NOT EXISTS craft_reagent (
    craft_id INTEGER NOT NULL REFERENCES craft (id),
    item_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS craft_reagent_by_craft ON craft_reagent (craft_id);

-- One row per profession window read carried on a Character Read (its professions map).
CREATE TABLE IF NOT EXISTS known_profession (
    id INTEGER PRIMARY KEY,
    character_read_id INTEGER NOT NULL REFERENCES character_read (id),
    profession_id INTEGER NOT NULL,
    read_at INTEGER NOT NULL,  -- when the window was read; cooldowns are as of then
    skill_level INTEGER,       -- NULL when the Read didn't say (before #76)
    max_skill_level INTEGER
);
CREATE INDEX IF NOT EXISTS known_profession_by_read ON known_profession (character_read_id);

-- The Known Recipes in one profession window read that make an item.
CREATE TABLE IF NOT EXISTS known_recipe (
    id INTEGER PRIMARY KEY,
    known_profession_id INTEGER NOT NULL REFERENCES known_profession (id),
    recipe_id INTEGER NOT NULL,
    output_item_id INTEGER NOT NULL,
    quantity_min INTEGER NOT NULL,
    quantity_max INTEGER NOT NULL,
    bind_type INTEGER,         -- the output's; NULL when the client hadn't cached it
    cooldown REAL              -- seconds left as of known_profession.read_at; NULL if none
);
CREATE INDEX IF NOT EXISTS known_recipe_by_profession ON known_recipe (known_profession_id);

-- A Known Recipe's Basic reagent slots. Optional ones aren't kept.
CREATE TABLE IF NOT EXISTS known_recipe_reagent (
    known_recipe_id INTEGER NOT NULL REFERENCES known_recipe (id),
    item_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS known_recipe_reagent_by_recipe
    ON known_recipe_reagent (known_recipe_id);

-- What a merchant charged one Character for one unit, from one Character Read.
CREATE TABLE IF NOT EXISTS merchant_cost (
    character_read_id INTEGER NOT NULL REFERENCES character_read (id),
    item_id INTEGER NOT NULL,
    cost REAL NOT NULL         -- copper per unit; fractional when sold in stacks
);
CREATE INDEX IF NOT EXISTS merchant_cost_by_read ON merchant_cost (character_read_id);
"""

# Enum.CraftingReagentType.Basic: the reagents a craft always uses up.
_BASIC_REAGENT = 1

# The Enchanting skill line's professionID.
ENCHANTING = 333


@dataclass(frozen=True)
class Market:
    realm: str
    faction: str
    era: Era


@dataclass(frozen=True)
class Reagent:
    item_id: int
    quantity: int


@dataclass(frozen=True)
class KnownRecipe:
    """A recipe a Character knows that makes an item, as of the latest read of its
    profession window."""

    character: str
    profession_id: int
    recipe_id: int
    output_item_id: int
    quantity_min: int
    quantity_max: int
    bind_type: int | None  # None when the client hadn't cached the output
    cooldown: float | None  # seconds left as of read_at; None if it has none
    read_at: int  # when the profession window was read
    reagents: tuple[Reagent, ...]  # Basic slots only


@dataclass(frozen=True, order=True)
class Listing:
    item_key: str
    unit_buyout: int
    own: bool
    quantity: int
    time_left: int
    first_seen: int  # requested_at of the first Scan it was in
    last_seen: int  # requested_at of the last Scan it was in
    item_name: str | None = None  # own Listings only, once the Addon recorded it (#17)


@dataclass(frozen=True, order=True)
class PartialSale:
    item_key: str
    unit_buyout: int
    own: bool
    seen_at: int  # requested_at of the Scan where the quantity had dropped
    units_sold: int


@dataclass(frozen=True)
class Outcome:
    """What happened to one stack the player posted (CONTEXT.md: Outcome)."""

    character: str
    kind: MailKind  # sold, cancelled or expired
    item_name: str
    item_key: str | None  # None for Sold: the sale mail names the item but doesn't attach it
    count: int
    price: int | None  # gross copper for the stack when Sold
    money: int  # copper paid out: for Sold, after the cut and with the deposit back
    arrived_at: int | None
    first_seen: int  # read_at of the first Mailbox Read it was in
    deposit: int | None = None  # copper a Sold one's posting cost, from its invoice (#78)


@dataclass(frozen=True)
class Purchase:
    """One stack the player bought on the Auction House (CONTEXT.md: Purchase)."""

    character: str
    item_name: str
    item_key: str
    count: int
    price: int  # copper for the stack
    arrived_at: int | None
    first_seen: int


@dataclass(frozen=True)
class CraftResult:
    """One craft the player made with a Known Recipe (CONTEXT.md: Craft Result)."""

    at: int
    character: str
    recipe_id: int
    quantity: int | None = None  # output units; None when the Addon couldn't read it
    # What its recipe makes and uses, as the profession window read on the Character Read
    # that carried it had it (None and none when that Read didn't have the recipe).
    output_item_id: int | None = None  # None when the recipe makes no item
    quantity_min: int | None = None
    reagents: tuple[Reagent, ...] = ()  # Basic slots only, for one craft


@dataclass(frozen=True)
class Holding:
    """How many of one Item Key a Character holds, by where and whether bound."""

    bags: int = 0
    bags_bound: int = 0
    bank: int = 0
    bank_bound: int = 0


@dataclass
class ImportReport:
    scans_imported: int = 0
    scans_already_imported: int = 0
    # Of scans_imported, how many were older than their Market's latest, so re-matched
    # its tail.
    scans_rematched: int = 0
    # Older than their Market's latest by more than pool_rematch_hours (or with no Archive
    # to re-match from): archived, and imported by the next `brain rebuild`.
    scans_waiting_for_rebuild: int = 0
    # Pooled Scans with too few Listings next to their Market's recent Scans: archived,
    # not imported (ADR-0026).
    scans_incomplete: int = 0
    # Pooled Scans the pool rolled back, taken out of the Archive (and history).
    scans_rolled_back: int = 0
    # Missing a field the Brain needs.
    scans_unreadable: int = 0
    inexact_rows: int = 0
    mailbox_reads_imported: int = 0
    mailbox_reads_already_imported: int = 0
    # Missing its realm, character or readAt, so it can't be named.
    mailbox_reads_unreadable: int = 0
    # Older than a Read already interpreted for its Character: archived and recorded, but
    # its mail is only interpreted by `brain rebuild`.
    mailbox_reads_out_of_order: int = 0
    outcomes_found: int = 0
    purchases_found: int = 0
    # New mail whose sender isn't a known Auction House, so it has no Market.
    mails_unassigned: int = 0
    # Mail the Brain can't read, say an unrecognized subject; left in the Archive.
    mails_unreadable: int = 0
    character_reads_imported: int = 0
    character_reads_already_imported: int = 0
    # Missing its realm, character or readAt, so it can't be named.
    character_reads_unreadable: int = 0
    # Items in a Character Read the Brain can't read, say a battle pet; left in the Archive.
    character_items_unreadable: int = 0
    unreadable_rows: int = 0
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        log.warning(message)
        self.warnings.append(message)


class ImportFileError(Exception):
    """A SavedVariables file the Brain can't import at all."""


def open_history(path: str | Path) -> sqlite3.Connection:
    """Open (or create) the history database."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    _add_column(conn, "listing", "item_name", "TEXT")  # #17
    _add_column(conn, "character_read", "has_profession_list", "INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "auction_mail", "deposit", "INTEGER")  # #78
    _add_column(conn, "character_read", "budget", "INTEGER")  # #86
    _add_column(conn, "character_read", "days_to_sell", "REAL")  # #109
    _add_column(conn, "known_profession", "skill_level", "INTEGER")  # #76
    _add_column(conn, "known_profession", "max_skill_level", "INTEGER")  # #76
    _add_column(conn, "craft", "output_item_id", "INTEGER")  # #44
    _add_column(conn, "craft", "quantity_min", "INTEGER")  # #44
    _add_column(conn, "scan", "source", "TEXT NOT NULL DEFAULT 'own'")  # #122
    _add_column(conn, "scan", "pool_id", "TEXT")  # #122
    _add_column(conn, "scan", "readable_rows", "INTEGER")  # #122
    return conn


def _add_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    """Add a column to a history made before it existed.

    CREATE TABLE IF NOT EXISTS leaves an existing table as it was. `brain rebuild` would
    fix that too, but a stale history shouldn't break `brain watch` in the meantime.
    """
    columns = {name for _, name, *_ in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        with conn:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def import_file(
    conn: sqlite3.Connection, path: Path, config: Config, timings: Timings | None = None
) -> ImportReport:
    """Import every Scan, Mailbox Read and Character Read in the Addon's SavedVariables file.

    The Era comes from which configured install folder the file is in, since the Scans
    themselves don't say. Reading the file and writing the Archive are timed in `timings`.
    """
    era = _era_of(path, config)
    with timed(timings, "SavedVariables"):
        data = parse_savedvariables(path.read_text(encoding="utf-8")).get("AzerothQuantDB")
    if not isinstance(data, dict):
        raise ImportFileError(f"{path}: no AzerothQuantDB table")
    scans = data.get("scans", [])
    if not isinstance(scans, list):
        raise ImportFileError(f"{path}: AzerothQuantDB.scans must be a sequence")
    reads = data.get("mailboxReads", [])
    if not isinstance(reads, list):
        raise ImportFileError(f"{path}: AzerothQuantDB.mailboxReads must be a sequence")
    character_reads = data.get("characterReads", [])
    if not isinstance(character_reads, list):
        raise ImportFileError(f"{path}: AzerothQuantDB.characterReads must be a sequence")
    report = import_scans(conn, scans, era, config, timings)
    import_mailbox_reads(conn, reads, era, config, report, timings)
    import_character_reads(conn, character_reads, era, config, report, timings)
    return report


def _era_of(path: Path, config: Config) -> Era:
    def normalized(p: Path) -> Path:
        # Windows paths compare case-insensitively.
        return Path(os.path.normcase(p.resolve()))

    file = normalized(path)
    for install in config.installs:
        if file.is_relative_to(normalized(install.path)):
            return install.era
    raise ImportFileError(f"{path} isn't inside any install folder in the config")


def import_scans(
    conn: sqlite3.Connection,
    raw_scans: list[object],
    era: Era,
    config: Config,
    timings: Timings | None = None,
) -> ImportReport:
    """Import the Addon's Scans (entries of AzerothQuantDB.scans), oldest first.

    Importing a Scan that is already there does nothing, so the same file can be
    imported any number of times. A Scan older than the latest one already imported
    for its Market re-matches the Market's tail from the Archive, so history comes out
    as if every Scan had arrived in time order (ADR-0026). One older than that by more
    than pool_rematch_hours is archived and waits for `brain rebuild`.

    With an archive folder configured, each Scan is written to the Archive before
    it is imported (ADR-0005). If that write fails the error propagates and the Scan
    stays out of the history, so the Addon doesn't prune it and it's retried later.
    """
    entries = [ArchivedScan(raw) for raw in raw_scans]
    return _import(conn, entries, era, config, archived=False, timings=timings)


def import_pooled_scans(
    conn: sqlite3.Connection, pooled: list[tuple[str, dict]], era: Era, config: Config
) -> ImportReport:
    """Import Pooled Scans, as (pool ID, Scan) pairs downloaded from the Scan Pool.

    Each is archived under its Market's pool/ folder and recorded as downloaded, then
    imported as `import_scans` does, except that one with too few Listings next to its
    Market's recent Scans is left out (ADR-0026).
    """
    entries = [ArchivedScan(raw, ScanSource.POOL, pool_id) for pool_id, raw in pooled]
    return _import(conn, entries, era, config, archived=False)


def import_archived_scans(
    conn: sqlite3.Connection, scans: list[ArchivedScan], era: Era, config: Config
) -> ImportReport:
    """Import Scans, own and Pooled, that are already in the Archive (`brain rebuild`)."""
    return _import(conn, scans, era, config, archived=True)


def _import(
    conn: sqlite3.Connection,
    entries: list[ArchivedScan],
    era: Era,
    config: Config,
    archived: bool,
    timings: Timings | None = None,
) -> ImportReport:
    report = ImportReport()
    archive = Archive(config.archive_dir) if config.archive_dir is not None else None
    scans = []
    for entry in entries:
        try:
            scans.append((Scan.from_saved(entry.raw), entry))
        except ScanFormatError as e:
            report.scans_unreadable += 1
            report.warn(f"Skipped a Scan the Brain can't read: {e}")

    # At the same requestedAt the own Scan goes first, and so wins.
    for scan, entry in sorted(
        scans, key=lambda s: (s[0].requested_at, s[1].source is ScanSource.POOL)
    ):
        if archive is not None and not archived:
            with timed(timings, "Archive"):
                if entry.source is ScanSource.POOL:
                    archive.write_pooled(era, entry.raw, entry.pool_id)
                else:
                    archive.write(era, entry.raw)
        with conn:
            if entry.source is ScanSource.POOL:
                conn.execute(
                    "INSERT OR IGNORE INTO pooled_scan (pool_id, market_id, requested_at)"
                    " VALUES (?, ?, ?)",
                    (
                        entry.pool_id,
                        _market_id(conn, Market(scan.realm, scan.faction, era)),
                        scan.requested_at,
                    ),
                )
            _import_scan(conn, scan, entry, era, config, archive, report)
            # Only from own Scans: a rolled-back Pooled Scan's would outlive it (#129), and
            # own Scans see every item on the player's Market anyway.
            if entry.source is ScanSource.OWN:
                source = f"Scan at {scan.requested_at}"
                _record_vendor_prices(conn, era, entry.raw, scan.requested_at, source, report)
                _record_item_info(conn, era, entry.raw, scan.requested_at, source, report)
    return report


def _import_scan(
    conn: sqlite3.Connection,
    scan: Scan,
    entry: ArchivedScan,
    era: Era,
    config: Config,
    archive: Archive | None,
    report: ImportReport,
) -> None:
    market = Market(realm=scan.realm, faction=scan.faction, era=era)
    market_id = _market_id(conn, market)
    exists = conn.execute(
        "SELECT source FROM scan WHERE market_id = ? AND requested_at = ?",
        (market_id, scan.requested_at),
    ).fetchone()
    # An own Scan takes the place of a Pooled one from the same second, as `brain rebuild`
    # would have it: the re-match below finds the own one first in the Archive.
    replaces_pooled = (
        exists is not None and exists[0] == ScanSource.POOL and entry.source is ScanSource.OWN
    )
    if exists and not replaces_pooled:
        report.scans_already_imported += 1
        return
    if not _complete_enough(conn, market_id, scan, entry.source, config):
        report.scans_incomplete += 1
        report.warn(
            f"Left out the Pooled Scan at {scan.requested_at} for {market}: it has only "
            f"{len(scan.rows)} Listings, too few next to the Market's recent Scans to be whole."
        )
        return

    _, latest_at = _latest_scan(conn, market_id)
    if latest_at is None or scan.requested_at > latest_at:
        _insert_scan(conn, market_id, scan, entry.source, entry.pool_id, config)
    else:
        # A late Scan re-matches the Market's tail (ADR-0026): every Scan from it on, the
        # late one included, comes back from the Archive in time order.
        tail = None
        if archive is not None and latest_at - scan.requested_at <= config.pool_rematch_seconds:
            tail = _archived_tail(archive, market, scan.requested_at)
        if tail is None:
            report.scans_waiting_for_rebuild += 1
            report.warn(
                f"Left the Scan at {scan.requested_at} for {market} for `brain rebuild`: it is "
                f"older than the latest imported one ({latest_at}), and its Market's Scans "
                "from it on can't be re-matched."
            )
            return
        _rematch_tail(conn, market_id, scan.requested_at, tail, config)
        report.scans_rematched += 1
    report.scans_imported += 1
    report.inexact_rows += scan.inexact_rows
    report.unreadable_rows += scan.unreadable_rows
    if scan.inexact_rows:
        report.warn(
            f"Scan at {scan.requested_at} for {market}: left out {scan.inexact_rows} rows whose "
            "buyout isn't a whole number of copper per unit."
        )
    if scan.unreadable_rows:
        report.warn(
            f"Scan at {scan.requested_at} for {market}: left out {scan.unreadable_rows} rows "
            "the Brain can't read."
        )


def _archived_tail(
    archive: Archive, market: Market, since: int
) -> list[tuple[Scan, ArchivedScan]] | None:
    """The Market's archived Scans from `since` on, oldest first, or None if one can't be
    read. Read before anything is rewound, so a bad file leaves the history as it was."""
    try:
        entries = archive.market_scans(market.era, market.realm, market.faction, since=since)
        return [(Scan.from_saved(e.raw), e) for e in entries]
    except (OSError, ValueError, KeyError, ScanFormatError) as e:
        log.warning("Can't read the Archive from the Scan at %s: %s", since, e)
        return None


def _rematch_tail(
    conn: sqlite3.Connection,
    market_id: int,
    since: int,
    tail: list[tuple[Scan, ArchivedScan]],
    config: Config,
) -> None:
    """Rewind the Market to before `since`, then import `tail`, its archived Scans from
    there on, in time order, as if they had arrived in that order."""
    # An own Scan's pool ID is only in the history, so it's kept across the rewind.
    uploaded = dict(
        conn.execute(
            "SELECT requested_at, pool_id FROM scan WHERE market_id = ? AND requested_at >= ?"
            " AND source = 'own' AND pool_id IS NOT NULL",
            (market_id, since),
        ).fetchall()
    )
    _rewind(conn, market_id, since)
    previous_at = None
    for tail_scan, entry in tail:
        # A Pooled Scan from the same second as an own one comes after it, and loses.
        if tail_scan.requested_at == previous_at:
            continue
        if not _complete_enough(conn, market_id, tail_scan, entry.source, config):
            continue
        pool_id = entry.pool_id or uploaded.get(tail_scan.requested_at)
        _insert_scan(conn, market_id, tail_scan, entry.source, pool_id, config)
        previous_at = tail_scan.requested_at


def _complete_enough(
    conn: sqlite3.Connection, market_id: int, scan: Scan, source: ScanSource, config: Config
) -> bool:
    """False for a Pooled Scan with fewer readable Listings than pool_min_completeness of
    the median of the Market's last pool_completeness_window Scans before it: most likely
    cut short, and importing it would make a Disappearance of everything it missed. The
    player's own Scans always pass, and so does any Scan with under 3 Scans to compare."""
    if source is not ScanSource.POOL:
        return True
    counts = [
        n
        for (n,) in conn.execute(
            "SELECT readable_rows FROM scan WHERE market_id = ? AND requested_at < ?"
            " AND readable_rows IS NOT NULL ORDER BY requested_at DESC LIMIT ?",
            (market_id, scan.requested_at, config.pool_completeness_window),
        )
    ]
    if len(counts) < 3:
        return True
    return len(scan.rows) >= config.pool_min_completeness * statistics.median(counts)


def _latest_scan(conn: sqlite3.Connection, market_id: int) -> tuple[int | None, int | None]:
    """The ID and requestedAt of the Market's latest imported Scan, if it has one."""
    latest = conn.execute(
        "SELECT id, requested_at FROM scan WHERE market_id = ? ORDER BY requested_at DESC LIMIT 1",
        (market_id,),
    ).fetchone()
    return latest if latest else (None, None)


# What a Scan saw happen to a Listing, one row per (Listing, Scan). A re-match deletes them.
_SEEN_IN_A_SCAN = ("partial_sale", "time_left_drop", "turned_own")


def _rewind(conn: sqlite3.Connection, market_id: int, since: int) -> None:
    """Put the Market's history back as it was before its Scans from `since` on were
    imported. Those Scans go, with the Listings first seen in them and every drop and turn
    to own seen in them. A Listing seen both before and in them gets back its last Scan,
    quantity, time-left and own as of the latest Scan before `since`."""
    tail = "SELECT id FROM scan WHERE market_id = ? AND requested_at >= ?"
    in_tail = (market_id, since)
    born_in_tail = f"SELECT id FROM listing WHERE first_seen_scan_id IN ({tail})"
    for table in _SEEN_IN_A_SCAN:
        conn.execute(f"DELETE FROM {table} WHERE listing_id IN ({born_in_tail})", in_tail)
    conn.execute(f"DELETE FROM listing WHERE id IN ({born_in_tail})", in_tail)

    before = conn.execute(
        "SELECT id FROM scan WHERE market_id = ? AND requested_at < ?"
        " ORDER BY requested_at DESC LIMIT 1",
        in_tail,
    ).fetchone()
    if before is not None:
        # The oldest time-left drop in the tail holds the bucket the Listing had before it.
        conn.execute(
            "UPDATE listing SET last_seen_scan_id = ?,"
            " quantity = quantity + (SELECT COALESCE(SUM(p.units_sold), 0) FROM partial_sale p"
            f"  WHERE p.listing_id = listing.id AND p.scan_id IN ({tail})),"
            " time_left = COALESCE((SELECT d.time_left_before FROM time_left_drop d"
            "  JOIN scan s ON s.id = d.scan_id"
            f"  WHERE d.listing_id = listing.id AND d.scan_id IN ({tail})"
            "  ORDER BY s.requested_at LIMIT 1), time_left)"
            f" WHERE last_seen_scan_id IN ({tail})",
            (before[0], *in_tail, *in_tail, *in_tail),
        )
    conn.execute(
        "UPDATE listing SET own = 0 WHERE id IN (SELECT listing_id FROM turned_own"
        f" WHERE scan_id IN ({tail}))",
        in_tail,
    )
    for table in _SEEN_IN_A_SCAN:
        conn.execute(f"DELETE FROM {table} WHERE scan_id IN ({tail})", in_tail)
    # Not in _SEEN_IN_A_SCAN: it belongs to the Scan alone, with no Listing to rewind.
    conn.execute(f"DELETE FROM scan_dropped_item WHERE scan_id IN ({tail})", in_tail)
    conn.execute(f"DELETE FROM scan_fair_values WHERE scan_id IN ({tail})", in_tail)
    conn.execute(f"DELETE FROM scan WHERE id IN ({tail})", in_tail)


def _insert_scan(
    conn: sqlite3.Connection,
    market_id: int,
    scan: Scan,
    source: ScanSource,
    pool_id: str | None,
    config: Config,
) -> None:
    """Add a Scan newer than every other in its Market, matched against the latest one."""
    latest_id, latest_at = _latest_scan(conn, market_id)
    scan_id = conn.execute(
        "INSERT INTO scan (market_id, requested_at, character, dropped_rows, inexact_rows,"
        " unreadable_rows, source, pool_id, readable_rows) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            market_id,
            scan.requested_at,
            # A Pooled Scan has no character; the column predates them.
            scan.character or "",
            scan.dropped_rows,
            scan.inexact_rows,
            scan.unreadable_rows,
            source.value,
            pool_id,
            len(scan.rows),
        ),
    ).lastrowid

    conn.executemany(
        "INSERT INTO scan_dropped_item (scan_id, item_id) VALUES (?, ?)",
        [(scan_id, item_id) for item_id in sorted(scan.dropped_item_ids)],
    )

    previous = _live_listings(conn, latest_id) if latest_id is not None else []
    gap = scan.requested_at - latest_at if latest_at is not None else 0
    result = match(previous, scan.rows, gap, config.time_left_max_seconds)

    conn.executemany(
        # A Listing first seen before the Addon recorded names picks one up when it can.
        # Once own, always own (ADR-0002).
        "UPDATE listing SET last_seen_scan_id = ?, quantity = ?, time_left = ?,"
        " own = own OR ?, item_name = COALESCE(item_name, ?) WHERE id = ?",
        [(scan_id, c.quantity, c.time_left, c.own, c.item_name, p.id) for p, c in result.matched],
    )
    conn.executemany(
        "INSERT INTO partial_sale (listing_id, scan_id, units_sold) VALUES (?, ?, ?)",
        [
            (p.id, scan_id, p.quantity - c.quantity)
            for p, c in result.matched
            if c.quantity < p.quantity
        ],
    )
    conn.executemany(
        # Kept so a re-match can put the Listing's bucket back (_rewind).
        "INSERT INTO time_left_drop (listing_id, scan_id, time_left_before) VALUES (?, ?, ?)",
        [(p.id, scan_id, p.time_left) for p, c in result.matched if c.time_left < p.time_left],
    )
    conn.executemany(
        # Kept so a re-match can take own back (_rewind).
        "INSERT INTO turned_own (listing_id, scan_id) VALUES (?, ?)",
        [(p.id, scan_id) for p, c in result.matched if c.own and not p.own],
    )
    conn.executemany(
        "INSERT INTO listing (market_id, item_key, unit_buyout, own, first_seen_scan_id,"
        " last_seen_scan_id, quantity, time_left, item_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                market_id,
                c.item_key,
                c.unit_buyout,
                c.own,
                scan_id,
                scan_id,
                c.quantity,
                c.time_left,
                c.item_name,
            )
            for c in result.new
        ],
    )


# --- the Scan Pool's side of the history (#122, ADR-0026) ---


def scans_to_push(conn: sqlite3.Connection) -> list[tuple[Market, int]]:
    """The player's own Scans not yet uploaded to the pool, as (Market, requestedAt),
    newest first so the latest Scans go up before an old backlog."""
    rows = conn.execute(
        "SELECT m.realm, m.faction, m.era, s.requested_at FROM scan s"
        " JOIN market m ON m.id = s.market_id"
        " WHERE s.source = 'own' AND s.pool_id IS NULL ORDER BY s.requested_at DESC, m.id"
    )
    return [(Market(realm, faction, Era(era)), at) for realm, faction, era, at in rows]


def record_upload(
    conn: sqlite3.Connection, market: Market, requested_at: int, pool_id: str
) -> None:
    """Note the pool ID an own Scan was uploaded as, so it isn't pushed again."""
    with conn:
        conn.execute(
            "UPDATE scan SET pool_id = ? WHERE requested_at = ? AND source = 'own'"
            " AND market_id = (SELECT id FROM market WHERE realm = ? AND faction = ? AND era = ?)",
            (pool_id, requested_at, *_market_params(market)),
        )


def has_pooled_scan(conn: sqlite3.Connection, pool_id: str, market: Market, at: int) -> bool:
    """Whether a pull can skip this pool entry: it was downloaded already, or the Market
    already has a Scan from that second (an own one always wins, and a Pooled one got
    there first)."""
    return bool(
        conn.execute(
            "SELECT 1 FROM pooled_scan WHERE pool_id = ? UNION ALL"
            " SELECT 1 FROM scan s JOIN market m ON m.id = s.market_id"
            f" WHERE {_MARKET_FILTER} AND s.requested_at = ?",
            (pool_id, *_market_params(market), at),
        ).fetchone()
    )


def pool_cursor(conn: sqlite3.Connection) -> int | None:
    """Where the last pull got to in the pool's index, or None before the first one."""
    row = conn.execute("SELECT cursor FROM pool_cursor WHERE id = 1").fetchone()
    return row[0] if row else None


def set_pool_cursor(conn: sqlite3.Connection, cursor: int) -> None:
    with conn:
        conn.execute(
            "INSERT INTO pool_cursor (id, cursor) VALUES (1, ?)"
            " ON CONFLICT (id) DO UPDATE SET cursor = excluded.cursor",
            (cursor,),
        )


def copy_pool_state(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    """Carry what only the history knows about the pool into a rebuilt one: which own
    Scans were uploaded, and where the last pull got to. (Pooled Scans' IDs are in the
    Archive.)"""
    uploads = source.execute(
        "SELECT m.realm, m.faction, m.era, s.requested_at, s.pool_id FROM scan s"
        " JOIN market m ON m.id = s.market_id WHERE s.source = 'own' AND s.pool_id IS NOT NULL"
    ).fetchall()
    for realm, faction, era, at, pool_id in uploads:
        record_upload(target, Market(realm, faction, Era(era)), at, pool_id)
    cursor = pool_cursor(source)
    if cursor is not None:
        set_pool_cursor(target, cursor)


def roll_back_pooled(conn: sqlite3.Connection, pool_ids: list[str], config: Config) -> ImportReport:
    """Take the Scans the pool rolled back out of the Archive and the history.

    An own Scan is never deleted: one uploaded as a Scan the pool already had got that
    Scan's ID, so it only forgets the ID and is pushed again. A Pooled Scan's file is
    deleted, and if it was imported its Market's tail is re-matched without it, unless
    that reaches back further than pool_rematch_hours: then it stays in the history until
    the next `brain rebuild`, which won't find it.
    """
    report = ImportReport()
    if not pool_ids:
        return report
    marks = ",".join("?" * len(pool_ids))
    archive = Archive(config.archive_dir) if config.archive_dir is not None else None
    with conn:
        conn.execute(
            f"UPDATE scan SET pool_id = NULL WHERE source = 'own' AND pool_id IN ({marks})",
            pool_ids,
        )
        found = conn.execute(
            "SELECT p.pool_id, p.market_id, p.requested_at, m.realm, m.faction, m.era,"
            " EXISTS (SELECT 1 FROM scan s WHERE s.market_id = p.market_id"
            "  AND s.requested_at = p.requested_at AND s.pool_id = p.pool_id)"
            f" FROM pooled_scan p JOIN market m ON m.id = p.market_id WHERE p.pool_id IN ({marks})",
            pool_ids,
        ).fetchall()
        conn.execute(f"DELETE FROM pooled_scan WHERE pool_id IN ({marks})", pool_ids)
    rematch_from: dict[tuple[int, Market], int] = {}
    for _, market_id, at, realm, faction, era, imported in found:
        market = Market(realm, faction, Era(era))
        if archive is not None:
            archive.delete_pooled(market.era, realm, faction, at)
        report.scans_rolled_back += 1
        if imported:
            key = (market_id, market)
            rematch_from[key] = min(at, rematch_from.get(key, at))

    for (market_id, market), since in rematch_from.items():
        _, latest_at = _latest_scan(conn, market_id)
        tail = None
        if archive is not None and latest_at - since <= config.pool_rematch_seconds:
            tail = _archived_tail(archive, market, since)
        if tail is None:
            report.scans_waiting_for_rebuild += 1
            report.warn(
                f"The pool rolled back a Scan at {since} for {market}. It's out of the Archive,"
                " but too old to re-match now: run `brain rebuild` to take it out of the history."
            )
            continue
        with conn:
            _rematch_tail(conn, market_id, since, tail, config)
        report.scans_rematched += 1
    return report


def import_mailbox_reads(
    conn: sqlite3.Connection,
    raw_reads: list[object],
    era: Era,
    config: Config,
    report: ImportReport | None = None,
    timings: Timings | None = None,
) -> ImportReport:
    """Import the Addon's Mailbox Reads (entries of AzerothQuantDB.mailboxReads), oldest
    first, turning their mail into Outcomes and Purchases.

    Importing a Read that is already there does nothing. A Read older than one already
    imported for its Character is recorded but not interpreted, since each Read is
    matched against the one before it; `brain rebuild` puts it in its place. As with
    Scans, a Read whose archive write fails isn't recorded, so the Addon keeps it.
    """
    report = report if report is not None else ImportReport()
    archive = Archive(config.archive_dir) if config.archive_dir is not None else None
    reads = []
    for raw in raw_reads:
        if not _nameable_read(raw):
            report.mailbox_reads_unreadable += 1
            report.warn(f"Skipped a Mailbox Read the Brain can't place: {raw!r:.200}")
            continue
        reads.append(raw)

    for raw in sorted(reads, key=lambda r: r["readAt"]):
        if archive is not None:
            with timed(timings, "Archive"):
                archive.write_mailbox_read(era, raw)
        with conn:
            _import_mailbox_read(conn, raw, era, report)
    return report


def _import_mailbox_read(
    conn: sqlite3.Connection, raw: dict, era: Era, report: ImportReport
) -> None:
    owner = (era.value, raw["realm"], raw["character"])
    read_at = raw["readAt"]
    mails = raw.get("mails")
    mails = mails if isinstance(mails, list) else []
    latest = conn.execute(
        "SELECT MAX(read_at) FROM mailbox_read WHERE era = ? AND realm = ? AND character = ?",
        owner,
    ).fetchone()[0]
    inserted = conn.execute(
        "INSERT OR IGNORE INTO mailbox_read (era, realm, character, read_at, mails)"
        " VALUES (?, ?, ?, ?, ?)",
        (*owner, read_at, len(mails)),
    ).rowcount
    if not inserted:
        report.mailbox_reads_already_imported += 1
        return
    report.mailbox_reads_imported += 1
    if latest is not None and read_at < latest:
        report.mailbox_reads_out_of_order += 1
        report.warn(
            f"The Mailbox Read at {read_at} for {raw['character']} is older than one already "
            f"imported ({latest}); its mail is left out until `brain rebuild`."
        )
        return

    current = []
    unreadable = 0
    for raw_mail in mails:
        try:
            parsed = parse_mail(raw_mail)
        except MailFormatError as e:
            unreadable += 1
            report.mails_unreadable += 1
            report.warn(f"Mailbox Read at {read_at} for {raw['character']}: skipped a mail: {e}")
            continue
        if parsed is not None:
            mail, days_left = parsed
            current.append((mail, arrived_at(read_at, days_left)))

    live = _live_mails(conn, owner)
    matches = match_mails(live, current)
    for (mail, arrival), live_id in zip(current, matches, strict=True):
        if live_id is None:
            _insert_mail(conn, owner, mail, arrival, read_at, report)
        else:
            conn.execute(
                "UPDATE auction_mail SET last_read_at = ?,"
                " arrived_at = COALESCE(arrived_at, ?) WHERE id = ?",
                (read_at, arrival, live_id),
            )

    # Over 50 mails, the inbox shows only some: a mail missing from an incomplete Read
    # may just be hidden, so it stays live. So may one the Brain can't read, such as a
    # header or invoice the client hadn't loaded yet (#100).
    if raw.get("shownCount") == raw.get("totalCount") and unreadable == 0:
        seen = set(matches)
        conn.executemany(
            "UPDATE auction_mail SET live = 0 WHERE id = ?",
            [(m.id,) for m in live if m.id not in seen],
        )


def _insert_mail(
    conn: sqlite3.Connection,
    owner: tuple[str, str, str],
    mail: AuctionMail,
    arrival: int | None,
    read_at: int,
    report: ImportReport,
) -> None:
    era, realm, character = owner
    faction = faction_of(mail.sender)
    market_id = None
    if faction is None:
        report.mails_unassigned += 1
        report.warn(
            f"{character}'s mail {mail.subject!r} is from {mail.sender!r}, which isn't a known "
            "Auction House, so it has no Market. It is kept in the Archive."
        )
    else:
        market_id = _market_id(conn, Market(realm=realm, faction=faction, era=Era(era)))
    if mail.kind in OUTCOME_KINDS:
        report.outcomes_found += 1
    else:
        report.purchases_found += 1
    conn.execute(
        "INSERT INTO auction_mail (era, realm, character, market_id, kind, sender, subject,"
        " item_name, item_key, count, price, money, deposit, arrived_at, first_read_at,"
        " last_read_at, live) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
        (
            *owner,
            market_id,
            mail.kind.value,
            mail.sender,
            mail.subject,
            mail.item_name,
            mail.item_key,
            mail.count,
            mail.price,
            mail.money,
            mail.deposit,
            arrival,
            read_at,
            read_at,
        ),
    )


def _live_mails(conn: sqlite3.Connection, owner: tuple[str, str, str]) -> list[LiveMail]:
    rows = conn.execute(
        "SELECT id, kind, sender, subject, item_name, item_key, count, price, money, arrived_at"
        " FROM auction_mail WHERE era = ? AND realm = ? AND character = ? AND live = 1"
        " ORDER BY id",
        owner,
    )
    return [
        LiveMail(id=i, mail=AuctionMail(MailKind(kind), *fields), arrived_at=at)
        for i, kind, *fields, at in rows
    ]


def import_character_reads(
    conn: sqlite3.Connection,
    raw_reads: list[object],
    era: Era,
    config: Config,
    report: ImportReport | None = None,
    timings: Timings | None = None,
) -> ImportReport:
    """Import the Addon's Character Reads (entries of AzerothQuantDB.characterReads).

    Each Read stands alone, so unlike Mailbox Reads they can be imported in any order.
    Importing a Read that is already there does nothing. As with Scans, a Read whose
    archive write fails isn't recorded, so the Addon keeps it.
    """
    report = report if report is not None else ImportReport()
    archive = Archive(config.archive_dir) if config.archive_dir is not None else None
    for raw in raw_reads:
        if not _nameable_read(raw):
            report.character_reads_unreadable += 1
            report.warn(f"Skipped a Character Read the Brain can't place: {raw!r:.200}")
            continue
        if archive is not None:
            with timed(timings, "Archive"):
                archive.write_character_read(era, raw)
        with conn:
            _import_character_read(conn, raw, era, report)
            source = f"Character Read at {raw['readAt']} for {raw['character']}"
            _record_vendor_prices(conn, era, raw, raw["readAt"], source, report)
            _record_item_info(conn, era, raw, raw["readAt"], source, report)
    return report


def _import_character_read(
    conn: sqlite3.Connection, raw: dict, era: Era, report: ImportReport
) -> None:
    bank = raw.get("bank")
    has_bank = isinstance(bank, list)
    profession_ids = _profession_ids(raw.get("professionList"))
    faction, money = raw.get("faction"), raw.get("money")
    budget = raw.get("budget")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
        budget = None
    days_to_sell = raw.get("daysToSell")
    if (
        isinstance(days_to_sell, bool)
        or not isinstance(days_to_sell, (int, float))
        or not 0 < days_to_sell < math.inf
    ):
        days_to_sell = None
    if not isinstance(faction, str) or not isinstance(money, int) or isinstance(money, bool):
        # Kept, with its items, but its gold can't be pooled.
        faction = money = None
    cursor = conn.execute(
        "INSERT OR IGNORE INTO character_read (era, realm, character, read_at, faction,"
        " money, has_bank, bank_read_at, has_profession_list, budget, days_to_sell)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            era.value,
            raw["realm"],
            raw["character"],
            raw["readAt"],
            faction,
            money,
            has_bank,
            raw.get("bankReadAt") if has_bank else None,
            profession_ids is not None,
            budget,
            days_to_sell,
        ),
    )
    if not cursor.rowcount:
        report.character_reads_already_imported += 1
        return
    report.character_reads_imported += 1
    read_id = cursor.lastrowid
    if money is None:
        report.warn(
            f"Character Read at {raw['readAt']} for {raw['character']} has no readable gold"
            " or faction, so none of its gold is pooled."
        )
    rows = []
    for place, entries in (("bags", raw.get("bags")), ("bank", bank)):
        for entry in entries if isinstance(entries, list) else []:
            try:
                key, count, bound = _held_item(entry)
            except ValueError as e:
                report.character_items_unreadable += 1
                report.warn(f"Character Read at {raw['readAt']} for {raw['character']}: {e}")
                continue
            rows.append((read_id, place, key, count, bound))
    conn.executemany(
        "INSERT INTO character_item (character_read_id, place, item_key, count, bound)"
        " VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.executemany(
        "INSERT INTO character_profession (character_read_id, profession_id) VALUES (?, ?)",
        [(read_id, profession_id) for profession_id in profession_ids or ()],
    )
    _import_known_recipes(conn, read_id, raw, report)
    costs, unreadable = _merchant_costs(raw)
    if unreadable:
        report.warn(
            f"Character Read at {raw['readAt']} for {raw['character']}: skipped"
            f" {unreadable} Merchant Costs the Brain can't read."
        )
    conn.executemany(
        "INSERT INTO merchant_cost (character_read_id, item_id, cost) VALUES (?, ?, ?)",
        [(read_id, item_id, cost) for item_id, cost in costs.items()],
    )
    _import_disenchant_results(conn, read_id, raw, report)
    _import_crafts(conn, read_id, raw, report)


def _import_disenchant_results(
    conn: sqlite3.Connection, read_id: int, raw: dict, report: ImportReport
) -> None:
    unreadable = 0
    for entry in _entries(raw.get("disenchantResults")):
        parsed = _disenchant_result(entry)
        if parsed is None:
            unreadable += 1
            continue
        fields, mats = parsed
        cursor = conn.execute(
            "INSERT INTO disenchant_result (character_read_id, at, item_id, item_level, quality,"
            " class_id) VALUES (?, ?, ?, ?, ?, ?)",
            (read_id, *fields),
        )
        conn.executemany(
            "INSERT INTO disenchant_result_mat (disenchant_result_id, item_id, quantity)"
            " VALUES (?, ?, ?)",
            [(cursor.lastrowid, item_id, qty) for item_id, qty in mats.items()],
        )
    if unreadable:
        report.warn(
            f"Character Read at {raw['readAt']} for {raw['character']}: skipped"
            f" {unreadable} Disenchant Results the Brain can't read."
        )


def _disenchant_result(entry: dict) -> tuple[tuple, dict[int, int]] | None:
    """(at, item_id, item_level, quality, class_id) and the mats of one Result, or None if
    it can't be read. The item's fields may each be None; the Addon leaves them out when
    it couldn't tell which item it was."""
    at, mats = entry.get("at"), entry.get("mats")
    if not _whole(at) or not isinstance(mats, dict):
        return None
    quantities = {}
    for item_id, qty in mats.items():
        if isinstance(item_id, str) and item_id.isdigit():
            item_id = int(item_id)
        if not _whole(item_id) or not _whole(qty) or qty < 1:
            return None
        quantities[item_id] = qty
    fields = [entry.get(k) for k in ("itemID", "itemLevel", "quality", "classID")]
    if not all(f is None or _whole(f) for f in fields):
        return None
    return (at, *fields), quantities


def _import_crafts(conn: sqlite3.Connection, read_id: int, raw: dict, report: ImportReport) -> None:
    entries = _entries(raw.get("crafts"))
    recipes = _read_recipes(raw)
    imported = 0
    for entry in entries:
        at, recipe_id, quantity = (entry.get(k) for k in ("at", "recipeID", "quantity"))
        readable_quantity = quantity is None or (_whole(quantity) and quantity >= 1)
        if not (_whole(at) and _whole(recipe_id) and readable_quantity):
            continue
        output, quantity_min, reagents = recipes.get(recipe_id, (None, None, []))
        cursor = conn.execute(
            "INSERT INTO craft (character_read_id, at, recipe_id, quantity, output_item_id,"
            " quantity_min) VALUES (?, ?, ?, ?, ?, ?)",
            (read_id, at, recipe_id, quantity, output, quantity_min),
        )
        conn.executemany(
            "INSERT INTO craft_reagent (craft_id, item_id, quantity) VALUES (?, ?, ?)",
            [(cursor.lastrowid, item_id, units) for item_id, units in reagents],
        )
        imported += 1
    unreadable = len(entries) - imported
    if unreadable:
        report.warn(
            f"Character Read at {raw['readAt']} for {raw['character']}: skipped"
            f" {unreadable} Craft Results the Brain can't read."
        )


def _read_recipes(raw: dict) -> dict[int, tuple[int | None, int | None, list[tuple[int, int]]]]:
    """By recipeID, (output itemID, fewest output units, Basic reagents) of each recipe in
    the Read's profession windows the Brain can read, with None and None for one that
    makes no item. The Known Recipes import warns about the rest."""
    result = {}
    for entry in _entries(raw.get("professions")):
        recipes = entry.get("recipes")
        for recipe in recipes if isinstance(recipes, list) else []:
            if not isinstance(recipe, dict) or not _whole(recipe.get("recipeID")):
                continue
            output, quantity_min = recipe.get("outputItemID"), recipe.get("quantityMin")
            try:
                reagents = _basic_reagents(recipe)
            except ValueError:
                continue
            if output is None:
                result[recipe["recipeID"]] = (None, None, reagents)
            elif _whole(output) and _whole(quantity_min):
                result[recipe["recipeID"]] = (output, quantity_min, reagents)
    return result


def _merchant_costs(raw: dict) -> tuple[dict[int, float], int]:
    """The Addon's itemID -> copper-per-unit map and how many entries couldn't be read.
    Shaped like vendorPrices (see _vendor_prices), but a cost can be fractional."""
    entries = raw.get("merchantCosts", {})  # left out when no merchant was visited
    if isinstance(entries, list):
        entries = dict(enumerate(entries, start=1))
    if not isinstance(entries, dict):
        return {}, 1
    costs = {}
    for item_id, cost in entries.items():
        if isinstance(item_id, str) and item_id.isdigit():
            item_id = int(item_id)
        if _whole(item_id) and _number(cost):
            costs[item_id] = cost
    return costs, len(entries) - len(costs)


def _profession_ids(entries: object) -> list[int] | None:
    """The professionIDs in a Read's professionList, or None if it has none: the client
    couldn't say, which isn't the same as having no professions."""
    if not isinstance(entries, list):
        return None
    return [e["professionID"] for e in entries if isinstance(e, dict) and "professionID" in e]


def _import_known_recipes(
    conn: sqlite3.Connection, read_id: int, raw: dict, report: ImportReport
) -> None:
    source = f"Character Read at {raw['readAt']} for {raw['character']}"
    for entry in _entries(raw.get("professions")):
        profession_id, read_at = entry.get("professionID"), entry.get("readAt")
        if not _whole(profession_id):
            report.warn(f"{source}: skipped a profession with no professionID.")
            continue
        skill, max_skill = entry.get("skillLevel"), entry.get("maxSkillLevel")
        cursor = conn.execute(
            "INSERT INTO known_profession (character_read_id, profession_id, read_at,"
            " skill_level, max_skill_level) VALUES (?, ?, ?, ?, ?)",
            (
                read_id,
                profession_id,
                read_at if _whole(read_at) else raw["readAt"],
                skill if _whole(skill) else None,
                max_skill if _whole(max_skill) else None,
            ),
        )
        profession_row = cursor.lastrowid
        recipes = entry.get("recipes")
        for recipe in recipes if isinstance(recipes, list) else []:
            try:
                parsed = _known_recipe(recipe)
            except ValueError as e:
                report.warn(f"{source}: {e}")
                continue
            if parsed is None:
                continue
            fields, reagents = parsed
            cursor = conn.execute(
                "INSERT INTO known_recipe (known_profession_id, recipe_id, output_item_id,"
                " quantity_min, quantity_max, bind_type, cooldown) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (profession_row, *fields),
            )
            conn.executemany(
                "INSERT INTO known_recipe_reagent (known_recipe_id, item_id, quantity)"
                " VALUES (?, ?, ?)",
                [(cursor.lastrowid, item_id, quantity) for item_id, quantity in reagents],
            )


def _known_recipe(recipe: object) -> tuple[tuple, list[tuple[int, int]]] | None:
    """(recipe_id, output_item_id, quantity_min, quantity_max, bind_type, cooldown) and
    the Basic reagents of one recipe the Addon kept, None if it makes no item, or
    ValueError if it can't be read."""
    if not isinstance(recipe, dict):
        raise ValueError(f"skipped a recipe that isn't a table: {recipe!r:.200}")
    if recipe.get("outputItemID") is None:
        # Makes no item (most enchants), so it can't be a Craft.
        return None
    fields = [recipe.get(k) for k in ("recipeID", "outputItemID", "quantityMin", "quantityMax")]
    bind_type, cooldown = recipe.get("bindType"), recipe.get("cooldown")
    if (
        not all(_whole(f) for f in fields)
        or not (bind_type is None or _whole(bind_type))
        or not (cooldown is None or _number(cooldown))
    ):
        raise ValueError(f"skipped a recipe the Brain can't read: {recipe!r:.200}")
    return (*fields, bind_type, cooldown), _basic_reagents(recipe)


def _basic_reagents(recipe: dict) -> list[tuple[int, int]]:
    """(itemID, quantity) of a recipe's Basic reagents, or ValueError if they can't be
    read."""
    reagents = recipe.get("reagents")
    if not isinstance(reagents, list):
        raise ValueError(f"skipped a recipe the Brain can't read: {recipe!r:.200}")
    basic = []
    for reagent in reagents:
        if not isinstance(reagent, dict):
            raise ValueError(f"skipped a recipe with a reagent it can't read: {recipe!r:.200}")
        if reagent.get("reagentType") != _BASIC_REAGENT:
            continue
        item_id, quantity = reagent.get("itemID"), reagent.get("quantity")
        if not _whole(item_id) or not _whole(quantity):
            raise ValueError(f"skipped a recipe with a reagent it can't read: {recipe!r:.200}")
        basic.append((item_id, quantity))
    return basic


def _whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: object) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _entries(entries: object) -> list[dict]:
    """The values of a map the Addon keys by number, however it arrived: a dict with int
    keys from SavedVariables, string keys from the Archive's JSON, or a list when empty."""
    if isinstance(entries, dict):
        entries = list(entries.values())
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict)]


def _nameable_read(raw: object) -> bool:
    return (
        isinstance(raw, dict)
        and isinstance(raw.get("realm"), str)
        and isinstance(raw.get("character"), str)
        and isinstance(raw.get("readAt"), int)
        and not isinstance(raw.get("readAt"), bool)
    )


def _record_vendor_prices(
    conn: sqlite3.Connection, era: Era, raw: dict, seen_at: int, source: str, report: ImportReport
) -> None:
    prices, unreadable = _vendor_prices(raw)
    if unreadable:
        report.warn(f"{source}: skipped {unreadable} Vendor Prices the Brain can't read.")
    conn.executemany(
        # The newest one wins, whatever order Scans and Reads are imported in.
        "INSERT INTO vendor_price (era, item_id, price, seen_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (era, item_id) DO UPDATE SET price = excluded.price,"
        " seen_at = excluded.seen_at WHERE excluded.seen_at >= vendor_price.seen_at",
        [(era.value, item_id, price, seen_at) for item_id, price in prices.items()],
    )


def _vendor_prices(raw: dict) -> tuple[dict[int, int], int]:
    """The Addon's itemID -> copper map, however it arrived, and how many entries in it
    couldn't be read.

    From SavedVariables the keys are ints, and an empty map reads as a list (a Lua table
    with keys 1..n does). From the Archive's JSON the keys are strings.
    """
    # Scans and Reads from before #20 have none.
    entries = raw.get("vendorPrices", {})
    if isinstance(entries, list):
        entries = dict(enumerate(entries, start=1))
    if not isinstance(entries, dict):
        return {}, 1
    prices = {}
    for item_id, price in entries.items():
        if isinstance(item_id, str) and item_id.isdigit():
            item_id = int(item_id)
        if not _whole_copper(item_id) or not _whole_copper(price):
            continue
        prices[item_id] = price
    return prices, len(entries) - len(prices)


def _record_item_info(
    conn: sqlite3.Connection, era: Era, raw: dict, seen_at: int, source: str, report: ImportReport
) -> None:
    infos, unreadable = _item_info(raw)
    if unreadable:
        report.warn(f"{source}: skipped {unreadable} Item Info entries the Brain can't read.")
    conn.executemany(
        # The newest one wins, like Vendor Prices.
        "INSERT INTO item_info (era, item_id, item_level, quality, class_id, equip_loc, seen_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (era, item_id) DO UPDATE SET"
        " item_level = excluded.item_level, quality = excluded.quality,"
        " class_id = excluded.class_id, equip_loc = excluded.equip_loc,"
        " seen_at = excluded.seen_at WHERE excluded.seen_at >= item_info.seen_at",
        [
            (era.value, item_id, i.item_level, i.quality, i.class_id, i.equip_loc, seen_at)
            for item_id, i in infos.items()
        ],
    )


def _item_info(raw: dict) -> tuple[dict[int, ItemInfo], int]:
    """The Scan's or Read's itemID -> ItemInfo map, keyed however it arrived (see _vendor_prices),
    and how many entries in it couldn't be read."""
    entries = raw.get("itemInfo", {})  # Scans from before #76 have none
    if isinstance(entries, list):
        entries = dict(enumerate(entries, start=1))
    if not isinstance(entries, dict):
        return {}, 1
    infos = {}
    for item_id, entry in entries.items():
        if isinstance(item_id, str) and item_id.isdigit():
            item_id = int(item_id)
        if not _whole(item_id) or not isinstance(entry, dict):
            continue
        fields = [entry.get(k) for k in ("itemLevel", "quality", "classID")]
        equip_loc = entry.get("equipLoc", "")
        if all(_whole(f) for f in fields) and isinstance(equip_loc, str):
            infos[item_id] = ItemInfo(*fields, equip_loc)
    return infos, len(entries) - len(infos)


def _whole_copper(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass(frozen=True)
class _StoredListing:
    """A Listing as of its last-seen Scan, for matching against the next one."""

    id: int
    item_key: str
    unit_buyout: int
    own: bool
    quantity: int
    time_left: int


def _live_listings(conn: sqlite3.Connection, scan_id: int) -> list[_StoredListing]:
    rows = conn.execute(
        "SELECT id, item_key, unit_buyout, own, quantity, time_left FROM listing"
        " WHERE last_seen_scan_id = ?",
        (scan_id,),
    )
    return [_StoredListing(i, k, u, bool(o), q, t) for i, k, u, o, q, t in rows]


def _market_id(conn: sqlite3.Connection, market: Market) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO market (realm, faction, era) VALUES (?, ?, ?)",
        _market_params(market),
    )
    return conn.execute(
        "SELECT id FROM market WHERE realm = ? AND faction = ? AND era = ?",
        _market_params(market),
    ).fetchone()[0]


# --- reading the history back ---

_MARKET_FILTER = "m.realm = ? AND m.faction = ? AND m.era = ?"


def _market_params(market: Market) -> tuple[str, str, str]:
    return (market.realm, market.faction, market.era.value)


def listings(conn: sqlite3.Connection, market: Market) -> list[Listing]:
    """Every Listing ever seen in the Market, oldest first."""
    return listings_by_id(conn, market)[1]


def listings_by_id(conn: sqlite3.Connection, market: Market) -> tuple[array, list[Listing]]:
    """`listings`, and each one's ID in the history (ascending) at the same place."""
    return _listings_where(conn, _MARKET_FILTER, _market_params(market))


def listings_last_seen_in(
    conn: sqlite3.Connection, scan_ids: Sequence[int]
) -> tuple[array, list[Listing]]:
    """The Listings last seen in any of the Scans `scan_ids`, as `listings_by_id`. After a
    Market's newest Scans are imported, these are the only Listings they changed or added
    (#155): each Scan is matched only against the one before it."""
    marks = ", ".join("?" * len(scan_ids))
    return _listings_where(conn, f"l.last_seen_scan_id IN ({marks})", tuple(scan_ids))


def listings_first_seen_in(
    conn: sqlite3.Connection, market: Market, times: Sequence[int]
) -> list[Listing]:
    """The Market's Listings first seen in a Scan at any of `times`, with the quantity and
    time-left bucket they had there, not as of their last Scan: their Partial Sales put
    back, and their bucket before its first drop."""
    if not times:
        return []
    marks = ", ".join("?" * len(times))
    rows = conn.execute(
        "SELECT l.item_key, l.unit_buyout, l.own,"
        " l.quantity + COALESCE("
        "(SELECT SUM(p.units_sold) FROM partial_sale p WHERE p.listing_id = l.id), 0),"
        " COALESCE("
        "(SELECT MAX(d.time_left_before) FROM time_left_drop d WHERE d.listing_id = l.id),"
        " l.time_left),"
        " first.requested_at, last.requested_at, l.item_name"
        " FROM listing l"
        " JOIN market m ON m.id = l.market_id"
        " JOIN scan first ON first.id = l.first_seen_scan_id"
        " JOIN scan last ON last.id = l.last_seen_scan_id"
        f" WHERE {_MARKET_FILTER} AND first.requested_at IN ({marks}) ORDER BY l.id",
        (*_market_params(market), *times),
    )
    return [Listing(k, u, bool(o), q, t, f, la, n) for k, u, o, q, t, f, la, n in rows]


def item_keys_turned_own_in(conn: sqlite3.Connection, scan_ids: Sequence[int]) -> set[str]:
    """The Item Keys with a Listing first seen as another player's that turned own in any
    of the Scans `scan_ids`."""
    marks = ", ".join("?" * len(scan_ids))
    rows = conn.execute(
        "SELECT DISTINCT l.item_key FROM turned_own t JOIN listing l ON l.id = t.listing_id"
        f" WHERE t.scan_id IN ({marks})",
        tuple(scan_ids),
    )
    return {item_key for (item_key,) in rows}


def _listings_where(
    conn: sqlite3.Connection, where: str, params: tuple
) -> tuple[array, list[Listing]]:
    rows = conn.execute(
        "SELECT l.id, l.item_key, l.unit_buyout, l.own, l.quantity, l.time_left,"
        " first.requested_at, last.requested_at, l.item_name"
        " FROM listing l"
        " JOIN market m ON m.id = l.market_id"
        " JOIN scan first ON first.id = l.first_seen_scan_id"
        " JOIN scan last ON last.id = l.last_seen_scan_id"
        f" WHERE {where} ORDER BY l.id",
        params,
    )
    ids, found = array("q"), []
    for id_, k, u, o, q, t, f, la, n in rows:
        ids.append(id_)
        found.append(Listing(k, u, bool(o), q, t, f, la, n))
    return ids, found


def partial_sales(conn: sqlite3.Connection, market: Market) -> list[PartialSale]:
    """Every Partial Sale seen in the Market, oldest first."""
    rows = conn.execute(
        "SELECT l.item_key, l.unit_buyout, l.own, s.requested_at, p.units_sold"
        " FROM partial_sale p"
        " JOIN listing l ON l.id = p.listing_id"
        " JOIN scan s ON s.id = p.scan_id"
        " JOIN market m ON m.id = l.market_id"
        f" WHERE {_MARKET_FILTER} ORDER BY s.requested_at, p.id",
        _market_params(market),
    )
    return [PartialSale(k, u, bool(o), at, n) for k, u, o, at, n in rows]


def supply_at(
    conn: sqlite3.Connection,
    market: Market,
    at: int,
    others_only: bool = False,
    exclude: frozenset[int] = frozenset(),
) -> dict[str, list[tuple[int, int]]]:
    """The Market's Scan requested at `at`, as (unit buyout, quantity) per Item Key, or
    only other players' Listings in it with `others_only`, leaving out the Listing ids in
    `exclude` (a Backtest's bought ones, #212)."""
    result: dict[str, list[tuple[int, int]]] = {}
    for listing_id, item_key, unit_buyout, quantity in listings_at(conn, market, at, others_only):
        if listing_id not in exclude:
            result.setdefault(item_key, []).append((unit_buyout, quantity))
    return result


def listings_at(
    conn: sqlite3.Connection, market: Market, at: int, others_only: bool = False
) -> list[tuple[int, str, int, int]]:
    """The Listings in the Market's Scan requested at `at` (only other players' with
    `others_only`), as (Listing id, Item Key, unit buyout, quantity), by id. A Listing's
    quantity is stored as of its last-seen Scan, so the Partial Sales seen after `at` are
    added back to get what it held then."""
    rows = conn.execute(
        "SELECT l.id, l.item_key, l.unit_buyout, l.quantity + COALESCE(("
        "   SELECT SUM(p.units_sold) FROM partial_sale p JOIN scan ps ON ps.id = p.scan_id"
        "   WHERE p.listing_id = l.id AND ps.requested_at > ?), 0)"
        " FROM listing l"
        " JOIN market m ON m.id = l.market_id"
        " JOIN scan first ON first.id = l.first_seen_scan_id"
        " JOIN scan last ON last.id = l.last_seen_scan_id"
        f" WHERE {_MARKET_FILTER} AND first.requested_at <= ? AND last.requested_at >= ?"
        + (" AND NOT l.own" if others_only else "")
        + " ORDER BY l.id",
        (at, *_market_params(market), at, at),
    )
    return list(rows)


def latest_scan_times(conn: sqlite3.Connection, era: Era) -> dict[Market, int]:
    """requested_at of the latest Scan imported for each Market in the Era."""
    rows = conn.execute(
        "SELECT m.realm, m.faction, MAX(s.requested_at) FROM scan s"
        " JOIN market m ON m.id = s.market_id"
        " WHERE m.era = ? GROUP BY m.id ORDER BY m.realm, m.faction",
        (era.value,),
    )
    return {Market(realm, faction, era): at for realm, faction, at in rows}


def latest_own_scan_times(conn: sqlite3.Connection, era: Era) -> dict[Market, int]:
    """requested_at of the latest of the player's own Scans imported for each Market in the
    Era: what the Addon may prune its stored Scans up to. Pooled Scans don't count, since
    the Addon never had them."""
    rows = conn.execute(
        "SELECT m.realm, m.faction, MAX(s.requested_at) FROM scan s"
        " JOIN market m ON m.id = s.market_id"
        " WHERE m.era = ? AND s.source = 'own' GROUP BY m.id ORDER BY m.realm, m.faction",
        (era.value,),
    )
    return {Market(realm, faction, era): at for realm, faction, at in rows}


def latest_mailbox_read_times(conn: sqlite3.Connection, era: Era) -> dict[tuple[str, str], int]:
    """read_at of the latest Mailbox Read imported for each (realm, character) in the Era."""
    rows = conn.execute(
        "SELECT realm, character, MAX(read_at) FROM mailbox_read"
        " WHERE era = ? GROUP BY realm, character ORDER BY realm, character",
        (era.value,),
    )
    return {(realm, character): at for realm, character, at in rows}


def latest_character_read_times(conn: sqlite3.Connection, era: Era) -> dict[tuple[str, str], int]:
    """read_at of the latest Character Read imported for each (realm, character) in the Era."""
    rows = conn.execute(
        "SELECT realm, character, MAX(read_at) FROM character_read"
        " WHERE era = ? GROUP BY realm, character ORDER BY realm, character",
        (era.value,),
    )
    return {(realm, character): at for realm, character, at in rows}


def cheapest_seen(
    conn: sqlite3.Connection, market: Market, since: int, until: int
) -> dict[str, dict[int, int]]:
    """Per Item Key, the cheapest unit buyout among other players' Listings that each of
    the Market's Scans requested from `since` to `until` saw, by the Scan's requested_at.
    A Scan saw a Listing when it's between the Listing's first and last-seen Scans (#88)."""
    rows = conn.execute(
        "SELECT l.item_key, s.requested_at, MIN(l.unit_buyout) FROM scan s"
        " JOIN market m ON m.id = s.market_id"
        " JOIN listing l ON l.market_id = s.market_id AND NOT l.own"
        " JOIN scan first ON first.id = l.first_seen_scan_id"
        " JOIN scan last ON last.id = l.last_seen_scan_id"
        f" WHERE {_MARKET_FILTER} AND s.requested_at BETWEEN ? AND ?"
        " AND first.requested_at <= s.requested_at AND last.requested_at >= s.requested_at"
        " GROUP BY l.item_key, s.id ORDER BY l.item_key, s.requested_at",
        (*_market_params(market), since, until),
    )
    result: dict[str, dict[int, int]] = {}
    for item_key, at, unit in rows:
        result.setdefault(item_key, {})[at] = unit
    return result


def scan_times(conn: sqlite3.Connection, market: Market) -> list[int]:
    """requested_at of every Scan imported for the Market, oldest first."""
    rows = conn.execute(
        "SELECT s.requested_at FROM scan s JOIN market m ON m.id = s.market_id"
        f" WHERE {_MARKET_FILTER} ORDER BY s.requested_at",
        _market_params(market),
    )
    return [at for (at,) in rows]


def dropped_item_ids(conn: sqlite3.Connection, market: Market) -> dict[int, frozenset[int]]:
    """The itemIDs each of the Market's Scans dropped rows of, by its requested_at. Scans
    that dropped none, or didn't say which, are left out."""
    rows = conn.execute(
        "SELECT s.requested_at, d.item_id FROM scan_dropped_item d"
        " JOIN scan s ON s.id = d.scan_id JOIN market m ON m.id = s.market_id"
        f" WHERE {_MARKET_FILTER}",
        _market_params(market),
    )
    result: dict[int, set[int]] = {}
    for at, item_id in rows:
        result.setdefault(at, set()).add(item_id)
    return {at: frozenset(ids) for at, ids in result.items()}


def dropped_at(conn: sqlite3.Connection, market: Market, at: int) -> frozenset[int]:
    """The itemIDs the Market's Scan requested at `at` dropped rows of: none if it didn't
    say which."""
    rows = conn.execute(
        "SELECT d.item_id FROM scan_dropped_item d"
        " JOIN scan s ON s.id = d.scan_id JOIN market m ON m.id = s.market_id"
        f" WHERE {_MARKET_FILTER} AND s.requested_at = ?",
        (*_market_params(market), at),
    )
    return frozenset(item_id for (item_id,) in rows)


ScanStamp = tuple[int, int, str, str | None]  # requested_at, ID, source, pool ID if Pooled


def scan_stamps(conn: sqlite3.Connection, market: Market) -> list[ScanStamp]:
    """A `ScanStamp` for every Scan imported for the Market, oldest first. A re-match
    deletes and imports again every Scan from the late one on (ADR-0026), and always
    changes one of these from there: a Scan added or gone, an own one in place of a Pooled
    one from the same second, or another Pooled one in place of one the pool rolled back
    (IDs can come back, so not the ID alone). So what's kept from a Scan is only stale
    from where its Market's stamps first differ. An own Scan's pool ID is left out: it's
    set on upload, which changes nothing in the history."""
    rows = conn.execute(
        "SELECT s.requested_at, s.id, s.source,"
        " CASE WHEN s.source = 'pool' THEN s.pool_id END"
        " FROM scan s JOIN market m ON m.id = s.market_id"
        f" WHERE {_MARKET_FILTER} ORDER BY s.requested_at",
        _market_params(market),
    )
    return [(at, scan_id, source, pool_id) for at, scan_id, source, pool_id in rows]


def kept_fair_values(
    conn: sqlite3.Connection, scan_id: int, worked_out_with: str
) -> dict[str, float] | None:
    """The Fair Values `keep_fair_values` kept for the Scan, or None."""
    row = conn.execute(
        "SELECT fair_values FROM scan_fair_values WHERE scan_id = ? AND worked_out_with = ?",
        (scan_id, worked_out_with),
    ).fetchone()
    return json.loads(row[0]) if row else None


def keep_fair_values(
    conn: sqlite3.Connection, scan_id: int, worked_out_with: str, values: dict[str, float]
) -> None:
    """Keep the Scan's Fair Values, worked out with `worked_out_with`, in place of any it
    had, so `kept_fair_values` finds them after a restart (#145)."""
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO scan_fair_values (scan_id, worked_out_with, fair_values)"
            " VALUES (?, ?, ?)",
            (scan_id, worked_out_with, json.dumps(values)),
        )


_MAIL_COLUMNS = (
    "a.character, a.kind, a.item_name, a.item_key, a.count, a.price, a.money, a.arrived_at,"
    " a.first_read_at"
)


def outcomes(conn: sqlite3.Connection, market: Market) -> list[Outcome]:
    """Every Outcome in the Market, in the order the Brain first saw them."""
    rows = conn.execute(
        f"SELECT {_MAIL_COLUMNS}, a.deposit FROM auction_mail a"
        f" JOIN market m ON m.id = a.market_id"
        f" WHERE {_MARKET_FILTER} AND a.kind != ? ORDER BY a.first_read_at, a.id",
        (*_market_params(market), MailKind.WON.value),
    )
    return [
        Outcome(ch, MailKind(kind), name, key, n, price, money, at, first, deposit)
        for ch, kind, name, key, n, price, money, at, first, deposit in rows
    ]


def purchases(conn: sqlite3.Connection, market: Market) -> list[Purchase]:
    """Every Purchase in the Market, in the order the Brain first saw them."""
    rows = conn.execute(
        f"SELECT {_MAIL_COLUMNS} FROM auction_mail a JOIN market m ON m.id = a.market_id"
        f" WHERE {_MARKET_FILTER} AND a.kind = ? ORDER BY a.first_read_at, a.id",
        (*_market_params(market), MailKind.WON.value),
    )
    return [
        Purchase(ch, name, key, n, price, at, first)
        for ch, _, name, key, n, price, _, at, first in rows
    ]


def pooled_gold(
    conn: sqlite3.Connection, era: Era, realm: str, faction: str, at: int | None = None
) -> int:
    """Copper held by the Characters on the realm and faction, each as of its latest
    Character Read, or its latest up to `at`. Mail can't move gold any further, so this
    is what sizing can use."""
    (total,) = conn.execute(
        "SELECT COALESCE(SUM(money), 0) FROM character_read r"
        " WHERE era = ? AND realm = ? AND faction = ? AND read_at = ("
        " SELECT MAX(read_at) FROM character_read WHERE era = r.era AND realm = r.realm"
        " AND character = r.character AND (? IS NULL OR read_at <= ?))",
        (era.value, realm, faction, at, at),
    ).fetchone()
    return total


def market_budget(
    conn: sqlite3.Connection, era: Era, realm: str, faction: str, at: int | None = None
) -> int | None:
    """The Budget in copper the player set for the realm and faction, as the Market's
    latest Character Read (up to `at`) carried it (#86). None means all the gold."""
    row = conn.execute(
        "SELECT budget FROM character_read WHERE era = ? AND realm = ? AND faction = ?"
        " AND (? IS NULL OR read_at <= ?) ORDER BY read_at DESC, id DESC LIMIT 1",
        (era.value, realm, faction, at, at),
    ).fetchone()
    return row[0] if row else None


def market_days_to_sell(
    conn: sqlite3.Connection, era: Era, realm: str, faction: str, at: int | None = None
) -> int | None:
    """The Days to Sell the player set for the realm and faction, in seconds, as the
    Market's latest Character Read (up to `at`) carried it (#109). None means not set."""
    row = conn.execute(
        "SELECT days_to_sell FROM character_read WHERE era = ? AND realm = ? AND faction = ?"
        " AND (? IS NULL OR read_at <= ?) ORDER BY read_at DESC, id DESC LIMIT 1",
        (era.value, realm, faction, at, at),
    ).fetchone()
    return None if row is None or row[0] is None else round(row[0] * 86400)


def character_markets(conn: sqlite3.Connection) -> dict[Market, list[str]]:
    """The player's Characters in each Market, by the faction of each one's latest
    Character Read. A Character whose faction isn't known is left out."""
    rows = conn.execute(
        "SELECT era, realm, faction, character FROM (SELECT * FROM character_read r"
        " WHERE read_at = (SELECT MAX(read_at) FROM character_read"
        " WHERE era = r.era AND realm = r.realm AND character = r.character))"
        " WHERE faction IS NOT NULL ORDER BY era, realm, faction, character"
    )
    result: dict[Market, list[str]] = {}
    for era, realm, faction, character in rows:
        result.setdefault(Market(realm, faction, Era(era)), []).append(character)
    return result


def _eras_to_read(era: Era) -> tuple[Era, ...]:
    """The Eras a Vendor Price or item info is read from, fallback first so the Era's own wins.
    Live falls back to Beta: a fresh Live Brain has seen almost no items yet."""
    return (Era.BETA, Era.LIVE) if era is Era.LIVE else (era,)


def vendor_prices(conn: sqlite3.Connection, era: Era) -> dict[int, int]:
    """Copper a vendor pays for one unit, by itemID, as last seen in the Era (or Beta, for an
    item Live hasn't seen yet)."""
    result: dict[int, int] = {}
    for source in _eras_to_read(era):
        rows = conn.execute(
            "SELECT item_id, price FROM vendor_price WHERE era = ?", (source.value,)
        )
        result.update(rows)
    return result


def item_info(conn: sqlite3.Connection, era: Era) -> dict[int, ItemInfo]:
    """What the client said about each itemID, as last seen in the Era (or Beta, for an item
    Live hasn't seen yet)."""
    result: dict[int, ItemInfo] = {}
    for source in _eras_to_read(era):
        rows = conn.execute(
            "SELECT item_id, item_level, quality, class_id, equip_loc FROM item_info WHERE era = ?",
            (source.value,),
        )
        result.update({item_id: ItemInfo(*fields) for item_id, *fields in rows})
    return result


def disenchant_results(conn: sqlite3.Connection, era: Era) -> list[DisenchantResult]:
    """Every Disenchant Result recorded in the Era, oldest first."""
    rows = conn.execute(
        "SELECT d.id, d.at, r.character, d.item_id, d.item_level, d.quality, d.class_id"
        " FROM disenchant_result d JOIN character_read r ON d.character_read_id = r.id"
        " WHERE r.era = ? ORDER BY d.at, d.id",
        (era.value,),
    ).fetchall()
    mats: dict[int, dict[int, int]] = {}
    for result_id, item_id, qty in conn.execute(
        "SELECT m.disenchant_result_id, m.item_id, m.quantity FROM disenchant_result_mat m"
        " JOIN disenchant_result d ON m.disenchant_result_id = d.id"
        " JOIN character_read r ON d.character_read_id = r.id WHERE r.era = ?",
        (era.value,),
    ):
        mats.setdefault(result_id, {})[item_id] = qty
    return [
        DisenchantResult(at, character, mats.get(result_id, {}), *fields)
        for result_id, at, character, *fields in rows
    ]


def crafts(conn: sqlite3.Connection, market: Market) -> list[CraftResult]:
    """Every Craft Result recorded in the Market, by the faction of the Character Read that
    carried it, oldest first."""
    rows = conn.execute(
        "SELECT c.id, c.at, r.character, c.recipe_id, c.quantity, c.output_item_id,"
        " c.quantity_min FROM craft c JOIN character_read r ON c.character_read_id = r.id"
        " WHERE r.realm = ? AND r.faction = ? AND r.era = ? ORDER BY c.at, c.id",
        _market_params(market),
    ).fetchall()
    reagents: dict[int, list[Reagent]] = {}
    for craft_id, item_id, quantity in conn.execute(
        "SELECT g.craft_id, g.item_id, g.quantity FROM craft_reagent g"
        " JOIN craft c ON g.craft_id = c.id JOIN character_read r ON c.character_read_id = r.id"
        " WHERE r.realm = ? AND r.faction = ? AND r.era = ? ORDER BY g.rowid",
        _market_params(market),
    ):
        reagents.setdefault(craft_id, []).append(Reagent(item_id, quantity))
    return [
        CraftResult(*fields, reagents=tuple(reagents.get(craft_id, ())))
        for craft_id, *fields in rows
    ]


def character_read_times(conn: sqlite3.Connection, market: Market) -> dict[str, list[int]]:
    """When each Character on the Market's realm was read, oldest first."""
    result: dict[str, list[int]] = {}
    for character, read_at in conn.execute(
        "SELECT character, read_at FROM character_read WHERE realm = ? AND era = ?"
        " ORDER BY read_at",
        (market.realm, market.era.value),
    ):
        result.setdefault(character, []).append(read_at)
    return result


def _market_characters(
    conn: sqlite3.Connection, market: Market, as_of: int | None = None
) -> set[str]:
    """The Characters in the Market, by the faction of each one's latest Character Read
    (up to `as_of`)."""
    rows = conn.execute(
        "SELECT character FROM character_read r"
        " WHERE era = ? AND realm = ? AND faction = ? AND read_at = ("
        " SELECT MAX(read_at) FROM character_read WHERE era = r.era AND realm = r.realm"
        " AND character = r.character AND (? IS NULL OR read_at <= ?))",
        (market.era.value, market.realm, market.faction, as_of, as_of),
    )
    return {character for (character,) in rows}


def merchant_costs(
    conn: sqlite3.Connection, market: Market, as_of: int | None = None
) -> dict[int, float]:
    """Copper per unit by itemID: each Character in the Market's latest-seen Merchant Cost
    for it, then the lowest of those, since any of them could buy it. With `as_of`, only
    Reads taken up to that moment count."""
    characters = _market_characters(conn, market, as_of)
    latest: dict[tuple[str, int], tuple[int, float]] = {}
    for character, item_id, read_at, cost in conn.execute(
        "SELECT r.character, m.item_id, r.read_at, m.cost"
        " FROM merchant_cost m JOIN character_read r ON m.character_read_id = r.id"
        " WHERE r.realm = ? AND r.era = ? AND (? IS NULL OR r.read_at <= ?)",
        (market.realm, market.era.value, as_of, as_of),
    ):
        key = (character, item_id)
        if character in characters and (key not in latest or read_at > latest[key][0]):
            latest[key] = (read_at, cost)
    lowest: dict[int, float] = {}
    for (_, item_id), (_, cost) in latest.items():
        lowest[item_id] = min(cost, lowest.get(item_id, cost))
    return lowest


def enchanting_skills(
    conn: sqlite3.Connection, market: Market, as_of: int | None = None
) -> dict[str, int]:
    """The Enchanting skill of each of the Market's Characters that still has Enchanting,
    from its latest Character Read with an Enchanting window that says it. With `as_of`,
    only Reads taken up to that moment count."""
    has = _professions(conn, market, as_of)
    characters = _market_characters(conn, market, as_of)
    latest: dict[str, tuple[int, int]] = {}
    for character, read_at, skill in conn.execute(
        "SELECT r.character, r.read_at, p.skill_level"
        " FROM known_profession p JOIN character_read r ON p.character_read_id = r.id"
        " WHERE r.realm = ? AND r.era = ? AND p.profession_id = ? AND p.skill_level IS NOT NULL"
        " AND (? IS NULL OR r.read_at <= ?)",
        (market.realm, market.era.value, ENCHANTING, as_of, as_of),
    ):
        if character not in latest or read_at > latest[character][0]:
            latest[character] = (read_at, skill)
    return {
        character: skill
        for character, (_, skill) in sorted(latest.items())
        if character in characters and ENCHANTING in has.get(character, ())
    }


def _professions(
    conn: sqlite3.Connection, market: Market, as_of: int | None = None
) -> dict[str, set[int]]:
    """The professionIDs each Character has, as of its latest Read that could say (up to
    `as_of`)."""
    has: dict[str, set[int]] = {}
    for character, profession_id in conn.execute(
        "SELECT r.character, c.profession_id FROM character_read r"
        " LEFT JOIN character_profession c ON c.character_read_id = r.id"
        " WHERE r.realm = ? AND r.era = ? AND r.has_profession_list AND r.read_at = ("
        " SELECT MAX(read_at) FROM character_read WHERE era = r.era AND realm = r.realm"
        " AND character = r.character AND has_profession_list AND (? IS NULL OR read_at <= ?))",
        (market.realm, market.era.value, as_of, as_of),
    ):
        has.setdefault(character, set()).add(profession_id)
    return has


def known_recipes(
    conn: sqlite3.Connection, market: Market, as_of: int | None = None
) -> list[KnownRecipe]:
    """The Known Recipes of every Character in the Market: for each profession,
    the ones in the latest Character Read that has that profession's window read. Only
    the professions the Character has as of its latest Read that could say count, so a
    dropped profession's recipes don't come back. With `as_of`, only Reads taken up to
    that moment count."""
    characters = _market_characters(conn, market, as_of)
    has = _professions(conn, market, as_of)
    current: dict[tuple[str, int], tuple[int, int, int]] = {}
    for character, profession_id, row, read_at, character_read_at in conn.execute(
        "SELECT r.character, p.profession_id, p.id, p.read_at, r.read_at"
        " FROM known_profession p JOIN character_read r ON p.character_read_id = r.id"
        " WHERE r.realm = ? AND r.era = ? AND (? IS NULL OR r.read_at <= ?)",
        (market.realm, market.era.value, as_of, as_of),
    ):
        if character not in characters:
            continue
        key = (character, profession_id)
        if key not in current or character_read_at > current[key][2]:
            current[key] = (row, read_at, character_read_at)
    result = []
    for (character, profession_id), (row, read_at, _) in sorted(current.items()):
        if profession_id not in has.get(character, ()):
            continue
        for recipe_row, *fields in conn.execute(
            "SELECT id, recipe_id, output_item_id, quantity_min, quantity_max, bind_type,"
            " cooldown FROM known_recipe WHERE known_profession_id = ? ORDER BY recipe_id",
            (row,),
        ):
            reagents = conn.execute(
                "SELECT item_id, quantity FROM known_recipe_reagent WHERE known_recipe_id = ?"
                " ORDER BY rowid",
                (recipe_row,),
            )
            result.append(
                KnownRecipe(
                    character,
                    profession_id,
                    *fields,
                    read_at=read_at,
                    reagents=tuple(Reagent(*r) for r in reagents),
                )
            )
    return result


def _held_item(entry: object) -> tuple[str, int, bool]:
    """(Item Key, count, bound) of one filled slot, or ValueError if it can't be read."""
    if not isinstance(entry, dict):
        raise ValueError(f"an item must be a table, got {entry!r:.200}")
    link, count = entry.get("link"), entry.get("count")
    if not isinstance(link, str) or not isinstance(count, int) or isinstance(count, bool):
        raise ValueError(f"skipped an item with no link or count: {entry!r:.200}")
    try:
        key = ItemKey.from_link(link)
    except ItemStringError as e:
        raise ValueError(f"skipped an item: {e}") from None
    return str(key), count, entry.get("isBound") is True


def holdings(
    conn: sqlite3.Connection, era: Era, realm: str, character: str, as_of: int | None = None
) -> dict[str, Holding]:
    """What the Character holds, by Item Key: bags as of its latest Character Read, and
    the bank as of the latest Read that has one (the bank can't change while closed).
    With `as_of`, only Reads taken up to that moment count."""
    latest = (
        "SELECT id FROM character_read WHERE era = ? AND realm = ? AND character = ?"
        " AND read_at <= ? {} ORDER BY read_at DESC LIMIT 1"
    )
    owner = (era.value, realm, character, as_of if as_of is not None else 2**62)
    rows = conn.execute(
        "SELECT place, item_key, bound, SUM(count) FROM character_item"
        f" WHERE (place = 'bags' AND character_read_id = ({latest.format('')}))"
        f" OR (place = 'bank' AND character_read_id = ({latest.format('AND has_bank')}))"
        " GROUP BY place, item_key, bound ORDER BY item_key",
        (*owner, *owner),
    )
    counts: dict[str, dict[str, int]] = {}
    for place, key, bound, count in rows:
        counts.setdefault(key, {})[f"{place}_bound" if bound else place] = count
    return {key: Holding(**c) for key, c in counts.items()}
