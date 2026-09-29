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

import logging
import math
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from brain.archive import Archive
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
from brain.scan import ItemKey, ItemStringError, Scan, ScanFormatError

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
    UNIQUE (market_id, requested_at)
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

CREATE TABLE IF NOT EXISTS partial_sale (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listing (id),
    scan_id INTEGER NOT NULL REFERENCES scan (id),  -- the Scan where the drop was seen
    units_sold INTEGER NOT NULL,
    UNIQUE (listing_id, scan_id)
);

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
    # Older than the latest Scan already imported for its Market.
    scans_out_of_order: int = 0
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


def import_file(conn: sqlite3.Connection, path: Path, config: Config) -> ImportReport:
    """Import every Scan, Mailbox Read and Character Read in the Addon's SavedVariables file.

    The Era comes from which configured install folder the file is in, since the Scans
    themselves don't say.
    """
    era = _era_of(path, config)
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
    report = import_scans(conn, scans, era, config)
    import_mailbox_reads(conn, reads, era, config, report)
    import_character_reads(conn, character_reads, era, config, report)
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
    conn: sqlite3.Connection, raw_scans: list[object], era: Era, config: Config
) -> ImportReport:
    """Import the Addon's Scans (entries of AzerothQuantDB.scans), oldest first.

    Importing a Scan that is already there does nothing, so the same file can be
    imported any number of times. A Scan older than the latest one already imported
    for its Market is rejected, since history is never re-matched.

    With an archive folder configured, each Scan is written to the Archive before
    it is imported (ADR-0005). If that write fails the error propagates and the Scan
    stays out of the history, so the Addon doesn't prune it and it's retried later.
    """
    report = ImportReport()
    archive = Archive(config.archive_dir) if config.archive_dir is not None else None
    scans = []
    for raw in raw_scans:
        try:
            scans.append((Scan.from_saved(raw), raw))
        except ScanFormatError as e:
            report.scans_unreadable += 1
            report.warn(f"Skipped a Scan the Brain can't read: {e}")

    for scan, raw in sorted(scans, key=lambda s: s[0].requested_at):
        if archive is not None:
            archive.write(era, raw)
        with conn:
            _import_scan(conn, scan, era, config, report)
            source = f"Scan at {scan.requested_at}"
            _record_vendor_prices(conn, era, raw, scan.requested_at, source, report)
            _record_item_info(conn, era, raw, scan.requested_at, source, report)
    return report


def _import_scan(
    conn: sqlite3.Connection, scan: Scan, era: Era, config: Config, report: ImportReport
) -> None:
    market = Market(realm=scan.realm, faction=scan.faction, era=era)
    market_id = _market_id(conn, market)

    latest = conn.execute(
        "SELECT id, requested_at FROM scan WHERE market_id = ? ORDER BY requested_at DESC LIMIT 1",
        (market_id,),
    ).fetchone()
    latest_id, latest_at = latest if latest else (None, None)
    exists = conn.execute(
        "SELECT 1 FROM scan WHERE market_id = ? AND requested_at = ?",
        (market_id, scan.requested_at),
    ).fetchone()
    if exists:
        report.scans_already_imported += 1
        return
    if latest_at is not None and scan.requested_at < latest_at:
        report.scans_out_of_order += 1
        report.warn(
            f"Rejected the Scan at {scan.requested_at} for {market}: it is older than the "
            f"latest imported one ({latest_at}), and history isn't re-matched."
        )
        return

    scan_id = conn.execute(
        "INSERT INTO scan (market_id, requested_at, character, dropped_rows, inexact_rows,"
        " unreadable_rows) VALUES (?, ?, ?, ?, ?, ?)",
        (
            market_id,
            scan.requested_at,
            scan.character,
            scan.dropped_rows,
            scan.inexact_rows,
            scan.unreadable_rows,
        ),
    ).lastrowid
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

    previous = _live_listings(conn, latest_id) if latest_id is not None else []
    gap = scan.requested_at - latest_at if latest_at is not None else 0
    result = match(previous, scan.rows, gap, config.time_left_max_seconds)

    conn.executemany(
        # A Listing first seen before the Addon recorded names picks one up when it can.
        "UPDATE listing SET last_seen_scan_id = ?, quantity = ?, time_left = ?,"
        " item_name = COALESCE(item_name, ?) WHERE id = ?",
        [(scan_id, c.quantity, c.time_left, c.item_name, p.id) for p, c in result.matched],
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


def import_mailbox_reads(
    conn: sqlite3.Connection,
    raw_reads: list[object],
    era: Era,
    config: Config,
    report: ImportReport | None = None,
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
    bind_type, cooldown, reagents = (
        recipe.get("bindType"),
        recipe.get("cooldown"),
        recipe.get("reagents"),
    )
    if (
        not all(_whole(f) for f in fields)
        or not (bind_type is None or _whole(bind_type))
        or not (cooldown is None or _number(cooldown))
        or not isinstance(reagents, list)
    ):
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
    return (*fields, bind_type, cooldown), basic


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
    rows = conn.execute(
        "SELECT l.item_key, l.unit_buyout, l.own, l.quantity, l.time_left,"
        " first.requested_at, last.requested_at, l.item_name"
        " FROM listing l"
        " JOIN market m ON m.id = l.market_id"
        " JOIN scan first ON first.id = l.first_seen_scan_id"
        " JOIN scan last ON last.id = l.last_seen_scan_id"
        f" WHERE {_MARKET_FILTER} ORDER BY l.id",
        _market_params(market),
    )
    return [Listing(k, u, bool(o), q, t, f, la, n) for k, u, o, q, t, f, la, n in rows]


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
    conn: sqlite3.Connection, market: Market, at: int, others_only: bool = False
) -> dict[str, list[tuple[int, int]]]:
    """The Market's Scan requested at `at`, as (unit buyout, quantity) per Item Key, or
    only other players' Listings in it with `others_only`. A Listing's quantity is stored
    as of its last-seen Scan, so the Partial Sales seen after `at` are added back to get
    what it held then."""
    rows = conn.execute(
        "SELECT l.item_key, l.unit_buyout, l.quantity + COALESCE(("
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
    result: dict[str, list[tuple[int, int]]] = {}
    for item_key, unit_buyout, quantity in rows:
        result.setdefault(item_key, []).append((unit_buyout, quantity))
    return result


def latest_scan_times(conn: sqlite3.Connection, era: Era) -> dict[Market, int]:
    """requested_at of the latest Scan imported for each Market in the Era."""
    rows = conn.execute(
        "SELECT m.realm, m.faction, MAX(s.requested_at) FROM scan s"
        " JOIN market m ON m.id = s.market_id"
        " WHERE m.era = ? GROUP BY m.id ORDER BY m.realm, m.faction",
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


def vendor_prices(conn: sqlite3.Connection, era: Era) -> dict[int, int]:
    """Copper a vendor pays for one unit, by itemID, as last seen in the Era."""
    rows = conn.execute("SELECT item_id, price FROM vendor_price WHERE era = ?", (era.value,))
    return dict(rows)


def item_info(conn: sqlite3.Connection, era: Era) -> dict[int, ItemInfo]:
    """What the client said about each itemID, as last seen in the Era."""
    rows = conn.execute(
        "SELECT item_id, item_level, quality, class_id, equip_loc FROM item_info WHERE era = ?",
        (era.value,),
    )
    return {item_id: ItemInfo(*fields) for item_id, *fields in rows}


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


def merchant_costs(conn: sqlite3.Connection, market: Market) -> dict[int, float]:
    """Copper per unit by itemID: each Character in the Market's latest-seen Merchant Cost
    for it, then the lowest of those, since any of them could buy it."""
    characters = _market_characters(conn, market)
    latest: dict[tuple[str, int], tuple[int, float]] = {}
    for character, item_id, read_at, cost in conn.execute(
        "SELECT r.character, m.item_id, r.read_at, m.cost"
        " FROM merchant_cost m JOIN character_read r ON m.character_read_id = r.id"
        " WHERE r.realm = ? AND r.era = ?",
        (market.realm, market.era.value),
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
