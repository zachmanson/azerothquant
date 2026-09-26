"""The Brain's persistent history: Scans imported into SQLite as Listing lifetimes,
and Mailbox Reads as the Outcomes and Purchases in them.

Each Listing is stored once, with the first and last Scan it was seen in (ADR-0002).
A Listing whose last Scan isn't its Market's latest one has disappeared. Each drop in
a Listing's quantity is stored as a Partial Sale.

Each Auction House mail is stored once too, however many Mailbox Reads it shows up in:
mail stays in the inbox until taken, so each Read is matched against the one before.
"""

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from brain.archive import Archive
from brain.config import Config, Era
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
from brain.scan import Scan, ScanFormatError

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
    arrived_at INTEGER,            -- Unix time; NULL until daysLeft starts counting down
    first_read_at INTEGER NOT NULL,
    last_read_at INTEGER NOT NULL,
    live INTEGER NOT NULL          -- 1 while it may still be in the inbox
);
CREATE INDEX IF NOT EXISTS auction_mail_live ON auction_mail (era, realm, character, live);
"""


@dataclass(frozen=True)
class Market:
    realm: str
    faction: str
    era: Era


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
    _add_listing_item_name(conn)
    return conn


def _add_listing_item_name(conn: sqlite3.Connection) -> None:
    """Add listing.item_name (#17) to a history made before it existed.

    CREATE TABLE IF NOT EXISTS leaves an existing table as it was. `brain rebuild` would
    fix that too, but a stale history shouldn't break `brain watch` in the meantime.
    """
    columns = {name for _, name, *_ in conn.execute("PRAGMA table_info(listing)")}
    if "item_name" not in columns:
        with conn:
            conn.execute("ALTER TABLE listing ADD COLUMN item_name TEXT")


def import_file(conn: sqlite3.Connection, path: Path, config: Config) -> ImportReport:
    """Import every Scan and Mailbox Read in the Addon's SavedVariables file.

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
    report = import_scans(conn, scans, era, config)
    import_mailbox_reads(conn, reads, era, config, report)
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
        if not _nameable_mailbox_read(raw):
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
    for raw_mail in mails:
        try:
            parsed = parse_mail(raw_mail)
        except MailFormatError as e:
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
    # may just be hidden, so it stays live.
    if raw.get("shownCount") == raw.get("totalCount"):
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
        " item_name, item_key, count, price, money, arrived_at, first_read_at, last_read_at,"
        " live) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
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


def _nameable_mailbox_read(raw: object) -> bool:
    return (
        isinstance(raw, dict)
        and isinstance(raw.get("realm"), str)
        and isinstance(raw.get("character"), str)
        and isinstance(raw.get("readAt"), int)
        and not isinstance(raw.get("readAt"), bool)
    )


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
        f"SELECT {_MAIL_COLUMNS} FROM auction_mail a JOIN market m ON m.id = a.market_id"
        f" WHERE {_MARKET_FILTER} AND a.kind != ? ORDER BY a.first_read_at, a.id",
        (*_market_params(market), MailKind.WON.value),
    )
    return [
        Outcome(ch, MailKind(kind), name, key, n, price, money, at, first)
        for ch, kind, name, key, n, price, money, at, first in rows
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
