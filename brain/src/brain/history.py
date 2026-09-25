"""The Brain's persistent history: Scans imported into SQLite as Listing lifetimes.

Each Listing is stored once, with the first and last Scan it was seen in (ADR-0002).
A Listing whose last Scan isn't its Market's latest one has disappeared. Each drop in
a Listing's quantity is stored as a Partial Sale.
"""

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from brain.config import Config, Era
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
    time_left INTEGER NOT NULL     -- bucket 1-4, as of the last-seen Scan
);
CREATE INDEX IF NOT EXISTS listing_by_last_seen ON listing (last_seen_scan_id);

CREATE TABLE IF NOT EXISTS partial_sale (
    id INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listing (id),
    scan_id INTEGER NOT NULL REFERENCES scan (id),  -- the Scan where the drop was seen
    units_sold INTEGER NOT NULL,
    UNIQUE (listing_id, scan_id)
);
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


@dataclass(frozen=True, order=True)
class PartialSale:
    item_key: str
    unit_buyout: int
    own: bool
    seen_at: int  # requested_at of the Scan where the quantity had dropped
    units_sold: int


@dataclass
class ImportReport:
    scans_imported: int = 0
    scans_already_imported: int = 0
    # Older than the latest Scan already imported for its Market.
    scans_out_of_order: int = 0
    # Missing a field the Brain needs.
    scans_unreadable: int = 0
    inexact_rows: int = 0
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
    return conn


def import_file(conn: sqlite3.Connection, path: Path, config: Config) -> ImportReport:
    """Import every Scan in the Addon's SavedVariables file.

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
    return import_scans(conn, scans, era, config)


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
    """
    report = ImportReport()
    scans = []
    for raw in raw_scans:
        try:
            scans.append(Scan.from_saved(raw))
        except ScanFormatError as e:
            report.scans_unreadable += 1
            report.warn(f"Skipped a Scan the Brain can't read: {e}")

    for scan in sorted(scans, key=lambda s: s.requested_at):
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
        "UPDATE listing SET last_seen_scan_id = ?, quantity = ?, time_left = ? WHERE id = ?",
        [(scan_id, c.quantity, c.time_left, p.id) for p, c in result.matched],
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
        " last_seen_scan_id, quantity, time_left) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (market_id, c.item_key, c.unit_buyout, c.own, scan_id, scan_id, c.quantity, c.time_left)
            for c in result.new
        ],
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
        " first.requested_at, last.requested_at"
        " FROM listing l"
        " JOIN market m ON m.id = l.market_id"
        " JOIN scan first ON first.id = l.first_seen_scan_id"
        " JOIN scan last ON last.id = l.last_seen_scan_id"
        f" WHERE {_MARKET_FILTER} ORDER BY l.id",
        _market_params(market),
    )
    return [Listing(k, u, bool(o), q, t, f, la) for k, u, o, q, t, f, la in rows]


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
