"""Fair Value: the price an Item Key can realistically be sold at in its Market.

Built from a supply of (unit buyout, quantity) pairs rather than a Scan, so a Flip can
ask what the Item Key is worth once the units it buys are gone (#23).
"""

import math
import sqlite3
from statistics import median

from brain.config import Config
from brain.history import Listing, Market, listings, scan_times, supply_at
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

    It also keeps each Market's `listings` for one pass, so the Valuer and the Beta Prior
    load them once (#141). Those do change with a new Scan, so a pass never reuses the
    last one's: a pass starts after the import that brought the Scan."""

    def __init__(self) -> None:
        self._last_pass: dict[_ScanKey, dict[str, float]] = {}
        self._this_pass: dict[_ScanKey, dict[str, float]] = {}
        self._listings: dict[Market, list[Listing]] = {}
        # Set by the caller for a pass: the Fair Values computed, not found here, are timed
        # in it (#131).
        self.timings: Timings | None = None

    def start_pass(self) -> None:
        self._last_pass, self._this_pass = self._this_pass, {}
        self._listings = {}

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
        if key not in self._this_pass:
            if key in self._last_pass:
                self._this_pass[key] = self._last_pass[key]
            else:
                with timed(self.timings, "Fair Values"):
                    self._this_pass[key] = fair_values(conn, market, config, at=at)
        return self._this_pass[key]


_ScanKey = tuple[Market, int, float, float]
