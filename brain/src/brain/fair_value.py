"""Fair Value: the price an Item Key can realistically be sold at in its Market.

Built from a supply of (unit buyout, quantity) pairs rather than a Scan, so a Flip can
ask what the Item Key is worth once the units it buys are gone (#23).
"""

import math
import sqlite3
from statistics import median

from brain.config import Config
from brain.history import Listing, Market, ScanStamp, listings, scan_stamps, scan_times, supply_at
from brain.timings import Timings, timed

Supply = list[tuple[int, int]]  # (unit buyout, quantity), in any order


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

    It also keeps each Market's `listings` for one pass, so the Valuer and the Beta Prior
    load them once (#141). Those do change with a new Scan, so a pass never reuses the
    last one's: a pass starts after the import that brought the Scan. `this_pass` holds
    anything else worked out from them, for the rest of the pass.

    And it keeps what Sell Rate takes from each Observation Window's two Scans
    (`kept_for_window`), so a new Scan only adds its own window to the tally (#142)."""

    def __init__(self) -> None:
        self._last_pass: dict[_ScanKey, dict[str, float]] = {}
        self._this_pass: dict[_ScanKey, dict[str, float]] = {}
        self._listings: dict[Market, list[Listing]] = {}
        # Keyed by (the type of what's kept, Market).
        self.this_pass: dict[tuple[type, Market], object] = {}
        self._windows_last_pass: dict[_WindowKey, object] = {}
        self._windows_this_pass: dict[_WindowKey, object] = {}
        # Each Market's `scan_stamps` as of the last pass that read it, and the Markets this
        # pass has checked against them.
        self._stamps: dict[Market, list[ScanStamp]] = {}
        self._checked: set[Market] = set()
        # Set by the caller for a pass: the Fair Values computed, not found here, are timed
        # in it (#131).
        self.timings: Timings | None = None

    def start_pass(self) -> None:
        self._last_pass, self._this_pass = self._this_pass, {}
        self._listings = {}
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

    def listings(self, conn: sqlite3.Connection, market: Market) -> list[Listing]:
        """The Market's `listings`, loaded once this pass."""
        if market not in self._listings:
            self._listings[market] = listings(conn, market)
        return self._listings[market]

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
                    self._this_pass[key] = fair_values(conn, market, config, at=at)
        return self._this_pass[key]

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
