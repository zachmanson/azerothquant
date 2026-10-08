"""Fair Value: the price an Item Key can realistically be sold at in its Market.

Built from a supply of (unit buyout, quantity) pairs rather than a Scan, so a Flip can
ask what the Item Key is worth once the units it buys are gone (#23).
"""

import math
import sqlite3
from collections.abc import Callable
from statistics import median

from brain.config import Config
from brain.history import (
    Listing,
    Market,
    ScanStamp,
    keep_fair_values,
    kept_fair_values,
    listings,
    scan_stamps,
    scan_times,
    supply_at,
)
from brain.timings import Timings, timed

Supply = list[tuple[int, int]]  # (unit buyout, quantity), in any order

# Bump it whenever a change to `fair_value` or `supply_at` changes what a Scan's Fair Values
# come to, so a Brain doesn't load ones the old code kept in the history (#145).
FAIR_VALUE_VERSION = 1


def _worked_out_with(config: Config) -> str:
    """What a Scan's Fair Values kept in the history were worked out with: the code's
    version and the config fields `fair_value` reads."""
    return (
        f"v{FAIR_VALUE_VERSION} slice {config.fair_value_slice_share!r}"
        f" outlier {config.fair_value_outlier_share!r}"
    )


def fair_value(supply: Supply, config: Config) -> float | None:
    """The unit-weighted mean of the cheapest share of units, leaving out units priced
    far under that slice's median. The slice can end partway through a Listing, so one
    big stack at the edge doesn't pull the price up. None when no units are left."""
    total = sum(quantity for _, quantity in supply)
    if not total:
        return None
    wanted = max(1, math.ceil(total * config.fair_value_slice_share))
    cheap: Supply = []
    for unit_buyout, quantity in sorted(supply):
        take = min(quantity, wanted)
        cheap.append((unit_buyout, take))
        wanted -= take
        if not wanted:
            break
    floor = median(u for u, q in cheap for _ in range(q)) * config.fair_value_outlier_share
    kept = [(u, q) for u, q in cheap if u >= floor]
    return sum(u * q for u, q in kept) / sum(q for _, q in kept)


def fair_values(
    conn: sqlite3.Connection, market: Market, config: Config, at: int | None = None
) -> dict[str, float]:
    """Fair Value of every Item Key in one Scan of the Market: the one requested at `at`,
    or the latest. Only that Scan is the supply for now; several Scans could smooth it
    once there's real history."""
    if at is None:
        times = scan_times(conn, market)
        if not times:
            return {}
        at = times[-1]
    return {item_key: fair_value(s, config) for item_key, s in supply_at(conn, market, at).items()}


class FairValueCache:
    """Fair Values by Scan, kept by `brain watch` from one pass to the next (#105). A
    Scan's supply doesn't change once it's imported, since `supply_at` adds back the
    Partial Sales seen after it, so neither do its Fair Values under the same config.
    A pass keeps only the Scans the pass before it used, so it doesn't grow forever.
    A re-match imports a Market's Scans again from the late one on (ADR-0026), so what
    was kept from those Scans goes (#142).

    It also keeps what's worked out from a Market's Scans alone (`scan_only`): its
    `listings`, Sell Rates, supply and others' lows (#143). A reload with no new Scan
    reuses them; any change to the Market's Scans drops them all. `this_pass` holds
    anything else worked out from the Listings, for the rest of the pass only.

    And it keeps what Sell Rate takes from each Observation Window's two Scans
    (`kept_for_window`), so a new Scan only adds its own window to the tally (#142).

    With `keep_in_history`, as `brain watch` makes it, each Scan's Fair Values are also
    kept in the history, so a restarted Brain loads them rather than working them all out
    again (#145)."""

    def __init__(self, keep_in_history: bool = False) -> None:
        self._keep_in_history = keep_in_history
        self._last_pass: dict[_ScanKey, dict[str, float]] = {}
        self._this_pass: dict[_ScanKey, dict[str, float]] = {}
        self._scan_only_last_pass: dict[tuple[Market, tuple], object] = {}
        self._scan_only_this_pass: dict[tuple[Market, tuple], object] = {}
        # Keyed by (the type of what's kept, Market).
        self.this_pass: dict[tuple[type, Market], object] = {}
        self._windows_last_pass: dict[_WindowKey, object] = {}
        self._windows_this_pass: dict[_WindowKey, object] = {}
        # Each Market's `scan_stamps` as of the last pass that read it, and the Markets this
        # pass has checked against them.
        self._stamps: dict[Market, list[ScanStamp]] = {}
        self._checked: set[Market] = set()
        # Set by the caller for a pass: the Fair Values computed or loaded from the history,
        # not found here, are timed in it (#131).
        self.timings: Timings | None = None

    def start_pass(self) -> None:
        self._last_pass, self._this_pass = self._this_pass, {}
        self._scan_only_last_pass, self._scan_only_this_pass = self._scan_only_this_pass, {}
        self.this_pass = {}
        self._windows_last_pass, self._windows_this_pass = self._windows_this_pass, {}
        self._checked = set()

    def _check_scans(self, conn: sqlite3.Connection, market: Market) -> None:
        """Once a pass for each Market: compare its `scan_stamps` with the last pass's,
        and drop what's kept from the first Scan that differs on."""
        if market in self._checked:
            return
        self._checked.add(market)
        now = scan_stamps(conn, market)
        last = self._stamps.get(market, [])
        self._stamps[market] = now
        if now != last:
            for kept in (self._scan_only_last_pass, self._scan_only_this_pass):
                for key in [k for k in kept if k[0] == market]:
                    del kept[key]
        unchanged = 0
        while unchanged < min(len(last), len(now)) and last[unchanged] == now[unchanged]:
            unchanged += 1
        if unchanged == len(last):
            return  # only Scans after every one seen before, if any
        first_new = now[unchanged][0] if unchanged < len(now) else math.inf
        stale_from = min(first_new, last[unchanged][0])
        for kept in (self._last_pass, self._this_pass):
            for key in [k for k in kept if k[0] == market and k[1] >= stale_from]:
                del kept[key]
        # A window ending at or after it was between Scans that changed.
        for windows in (self._windows_last_pass, self._windows_this_pass):
            for key in [k for k in windows if k[0] == market and k[2] >= stale_from]:
                del windows[key]

    def scan_only[T](
        self, conn: sqlite3.Connection, market: Market, what: tuple, work: Callable[[], T]
    ) -> T:
        """What `work` works out from the Market's Scans alone, named by `what` (its kind
        and arguments): kept across passes until any of the Market's Scans changes (#143).
        Nobody may change what it returns."""
        self._check_scans(conn, market)
        key = (market, what)
        if key not in self._scan_only_this_pass:
            if key in self._scan_only_last_pass:
                self._scan_only_this_pass[key] = self._scan_only_last_pass[key]
            else:
                self._scan_only_this_pass[key] = work()
        return self._scan_only_this_pass[key]  # type: ignore[return-value]

    def listings(self, conn: sqlite3.Connection, market: Market) -> list[Listing]:
        """The Market's `listings`, loaded again only once its Scans change."""
        return self.scan_only(conn, market, ("listings",), lambda: listings(conn, market))

    def fair_values(
        self, conn: sqlite3.Connection, market: Market, config: Config, at: int
    ) -> dict[str, float]:
        """`fair_values` of the Market's Scan requested at `at`."""
        # The Scan, and the config fields `fair_value` reads.
        key = (market, at, config.fair_value_slice_share, config.fair_value_outlier_share)
        self._check_scans(conn, market)
        if key not in self._this_pass:
            if key in self._last_pass:
                self._this_pass[key] = self._last_pass[key]
            else:
                with timed(self.timings, "Fair Values"):
                    self._this_pass[key] = self._kept_or_worked_out(conn, market, config, at)
        return self._this_pass[key]

    def _kept_or_worked_out(
        self, conn: sqlite3.Connection, market: Market, config: Config, at: int
    ) -> dict[str, float]:
        scan_id = next((id_ for at_, id_, _, _ in self._stamps[market] if at_ == at), None)
        if not self._keep_in_history or scan_id is None:
            return fair_values(conn, market, config, at=at)
        worked_out_with = _worked_out_with(config)
        values = kept_fair_values(conn, scan_id, worked_out_with)
        if values is None:
            values = fair_values(conn, market, config, at=at)
            keep_fair_values(conn, scan_id, worked_out_with, values)
        return values

    def kept_for_window(
        self,
        conn: sqlite3.Connection,
        market: Market,
        start: int,
        end: int,
        config_fields: tuple,
    ) -> object | None:
        """What `keep_for_window` kept for the Observation Window between the Market's Scans
        at `start` and `end`, worked out with `config_fields`, or
        None. Good until either Scan changes."""
        self._check_scans(conn, market)
        key = (market, start, end, config_fields)
        if key not in self._windows_this_pass and key in self._windows_last_pass:
            self._windows_this_pass[key] = self._windows_last_pass[key]
        return self._windows_this_pass.get(key)

    def keep_for_window(
        self, market: Market, start: int, end: int, config_fields: tuple, value: object
    ) -> None:
        self._windows_this_pass[(market, start, end, config_fields)] = value


_ScanKey = tuple[Market, int, float, float]
_WindowKey = tuple[Market, int, int, tuple]
