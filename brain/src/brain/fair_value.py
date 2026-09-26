"""Fair Value: the price an Item Key can realistically be sold at in its Market.

Built from a supply of (unit buyout, quantity) pairs rather than a Scan, so a Flip can
ask what the Item Key is worth once the units it buys are gone (#23).
"""

import math
import sqlite3
from statistics import median

from brain.config import Config
from brain.history import Market, scan_times, supply_at

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
