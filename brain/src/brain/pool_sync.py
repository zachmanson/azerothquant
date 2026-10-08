"""The sync step between the Brain and the Scan Pool (ADR-0026).

Push uploads every own Scan that hasn't gone up yet, stripped. Pull downloads the Scans
other members added since the last pull, archives them under pool/ and imports them, and
takes out whatever the pool rolled back. A network error warns and ends the step: nothing
is lost, and the next cycle carries on from where this one got to.
"""

import logging
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field

from brain.archive import Archive
from brain.config import Config
from brain.history import (
    ImportReport,
    Market,
    has_pooled_scan,
    import_pooled_scans,
    open_history,
    pool_cursor,
    record_upload,
    roll_back_pooled,
    scans_to_push,
    set_pool_cursor,
)
from brain.pool import Pool, PoolBusy, PoolEntry, PoolError, strip_scan

log = logging.getLogger(__name__)

DAY_SECONDS = 24 * 3600

# A pull with this many Pooled Scans to import on one page takes long enough (~4 s each)
# that the player's own Scan, waiting behind it, would look lost: the Addon is told (#159).
CATCHING_UP_SCANS = 10


@dataclass
class SyncReport:
    pushed: int = 0
    pulled: int = 0
    # Pooled Scans left out: truncated (the completeness guard), or whose body doesn't
    # match its index entry (#149).
    rejected: int = 0
    # Pooled Scans older than their Market's latest, so re-matched its tail.
    rematched: int = 0
    rolled_back: int = 0
    # The pool couldn't be reached or refused: the rest waits for the next sync.
    failed: bool = False
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        log.warning(message)
        self.warnings.append(message)

    def summary(self) -> str:
        return (
            f"Scan Pool: pushed {self.pushed}, pulled {self.pulled}, rejected {self.rejected},"
            f" re-matched {self.rematched}, rolled back {self.rolled_back}"
        )

    def merge(self, other: "SyncReport") -> None:
        self.pushed += other.pushed
        self.pulled += other.pulled
        self.rejected += other.rejected
        self.rematched += other.rematched
        self.rolled_back += other.rolled_back
        self.failed = self.failed or other.failed
        self.warnings.extend(other.warnings)

    def add(self, report: ImportReport) -> None:
        self.pulled += report.scans_imported
        self.rejected += report.scans_incomplete
        self.rematched += report.scans_rematched
        self.rolled_back += report.scans_rolled_back
        # Already logged by the import.
        self.warnings.extend(report.warnings)


def push(conn: sqlite3.Connection, pool: Pool, config: Config) -> SyncReport:
    """Upload the player's archived Scans that the pool doesn't have yet, newest first."""
    report = SyncReport()
    if config.archive_dir is None:
        return report
    archive = Archive(config.archive_dir)
    busy: set[Market] = set()
    for market, at in scans_to_push(conn):
        if market in busy:
            continue
        try:
            raw = archive.own_scan(market.era, market.realm, market.faction, at)
        except (OSError, ValueError) as e:
            report.warn(f"Can't push the Scan at {at} for {market}: not in the Archive ({e})")
            continue
        try:
            pool_id = pool.push(market.era, strip_scan(raw))
        except PoolBusy:
            # One upload per Market per 10 minutes: the rest wait for the next cycle.
            busy.add(market)
            continue
        except PoolError as e:
            report.warn(f"Couldn't push to the Scan Pool; will try again: {e}")
            report.failed = True
            break
        record_upload(conn, market, at, pool_id)
        report.pushed += 1
    return report


def pull(
    conn: sqlite3.Connection,
    pool: Pool,
    config: Config,
    now: int,
    since: int | None = None,
    catching_up: Callable[[], None] | None = None,
) -> SyncReport:
    """Download and import what other members added to the pool since the last pull, and
    take out what it rolled back.

    The first pull reaches back pool_backfill_days from `now`; `since` (Unix time) reaches
    back to then instead, going over the whole index again. `catching_up` is called once,
    before the downloads, if a page has CATCHING_UP_SCANS or more to import.
    """
    report = SyncReport()
    cursor = pool_cursor(conn)
    start = cursor
    oldest = None
    if since is not None:
        start, oldest = None, since
    elif cursor is None:
        oldest = now - config.pool_backfill_days * DAY_SECONDS
    try:
        while True:
            page = pool.list_since(start)
            wanted = [
                entry
                for entry in sorted(page.entries, key=lambda e: e.requested_at)
                if not (
                    entry.mine
                    or (oldest is not None and entry.requested_at < oldest)
                    or has_pooled_scan(
                        conn,
                        entry.id,
                        Market(entry.realm, entry.faction, entry.era),
                        entry.requested_at,
                    )
                )
            ]
            if catching_up is not None and len(wanted) >= CATCHING_UP_SCANS:
                catching_up()
                catching_up = None
            for entry in wanted:
                raw = pool.fetch(entry.id)
                if not _matches(raw, entry):
                    report.rejected += 1
                    report.warn(
                        f"Left out Pooled Scan {entry.id}: it doesn't match its index entry"
                    )
                    continue
                report.add(import_pooled_scans(conn, [(entry.id, raw)], entry.era, config))
            report.add(roll_back_pooled(conn, page.rolled_back, config))
            # A pull `since` a date starts over from the beginning; never move back.
            set_pool_cursor(conn, max(page.cursor, cursor or 0))
            start = page.cursor
            if not page.more:
                return report
    except PoolError as e:
        report.warn(f"Couldn't pull from the Scan Pool; will try again: {e}")
        report.failed = True
        return report


def _matches(raw: dict, entry: PoolEntry) -> bool:
    """Whether a Pooled Scan's body says the same Market and requestedAt as its index entry.

    The Worker checks only the headers, and the Brain imports the body. One whose date is
    off can leave its Market waiting for `brain rebuild` for every member (#149). So a
    mismatch is neither archived nor imported, or a rebuild would bring it back.

    The Worker already rejects a requestedAt header more than 10 minutes past the upload,
    by its own clock (pool/src/index.ts), so matching it here keeps the body from being
    dated after the upload too, without trusting this PC's clock. The era isn't in the
    body: the Scan is imported under the entry's.
    """
    return (raw.get("realm"), raw.get("faction"), raw.get("requestedAt")) == (
        entry.realm,
        entry.faction,
        entry.requested_at,
    )


# What the Addon tells the player while the pool can't be reached (#115).
UNREACHABLE = "Couldn't reach the guild scan server. Using your own Scans for now."


class PoolSyncer:
    """When `brain watch` syncs with the pool: a pull right before each import of the
    player's Scans, so they're matched against the freshest pool and late Scans stay rare,
    a push right after, once they're archived, and both every pool_sync_minutes.

    Nothing here ever stops the watcher: a failed sync warns, and the next one catches up.
    """

    def __init__(
        self,
        config: Config,
        pool: Pool,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], float] = time.time,
        announce: Callable[[int | None, str | None], None] | None = None,
    ):
        """`announce(catching_up_since, problem)` tells the Addon a long pull started (at
        that Unix time) or, with None, that it ended, along with the pool's problem."""
        self.config = config
        self.pool = pool
        self.clock = clock
        self.now = now
        self.announce = announce
        # Due straight away, so a watcher that just started catches up.
        self.due_at = clock()
        self.unreachable = False

    @property
    def problem(self) -> str | None:
        """What to tell the player about the pool: that the last sync couldn't reach it,
        until a pull gets through again. None when all is well."""
        return UNREACHABLE if self.unreachable else None

    def tick(self) -> None:
        """Sync if pool_sync_minutes have passed since the last pull."""
        if self.clock() >= self.due_at:
            self.sync()

    def before_import(self) -> None:
        self._run(do_push=False, do_pull=True)

    def after_import(self) -> None:
        self._run(do_push=True, do_pull=False)

    def sync(self) -> None:
        self._run(do_push=True, do_pull=True)

    def _run(self, do_push: bool, do_pull: bool) -> None:
        report = SyncReport()
        announced = False

        def catching_up() -> None:
            nonlocal announced
            announced = True
            self._announce(int(self.now()))

        try:
            self.config.history_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(open_history(self.config.history_path)) as conn:
                # A push before a pull, so a Scan that failed to go up last time goes first.
                if do_push:
                    report.merge(push(conn, self.pool, self.config))
                if do_pull:
                    report.merge(
                        pull(
                            conn,
                            self.pool,
                            self.config,
                            now=int(self.now()),
                            catching_up=catching_up,
                        )
                    )
                    self.due_at = self.clock() + self.config.pool_sync_seconds
        except Exception:
            log.exception("Syncing with the Scan Pool failed; will try again")
        else:
            # A push with nothing to push never calls the pool, so only a pull says it's back.
            if report.failed:
                self.unreachable = True
            elif do_pull:
                self.unreachable = False
            if any(
                (
                    report.pushed,
                    report.pulled,
                    report.rejected,
                    report.rematched,
                    report.rolled_back,
                )
            ):
                log.info(report.summary())
        # However the pull ended, the Addon mustn't go on saying one is running.
        if announced:
            self._announce(None)

    def _announce(self, catching_up_since: int | None) -> None:
        if self.announce is None:
            return
        try:
            self.announce(catching_up_since, self.problem)
        except Exception:
            log.exception("Couldn't tell the Addon about the pull from the Scan Pool")
