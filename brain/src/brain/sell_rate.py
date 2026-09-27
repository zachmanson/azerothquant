"""Sell Rate: units of an Item Key sold per day in a Market, from Observation Windows
only (ADR-0004)."""

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import median

from brain.config import Config
from brain.history import Market, listings
from brain.observation import observation_windows_between, sell_rate_evidence, window_hours


@dataclass(frozen=True)
class SellRate:
    units_per_day: float
    # The evidence behind it, so the Decision Engine can discount thin data (#25).
    sale_events: int  # Observation Windows it was seen to sell in (ADR-0012)
    window_hours: float  # the Market's, shared by every Item Key in it
    reposts: int
    coincidences: int
    # For the Sale Size Prior (#24): the units in those Sale Events, and the typical size
    # of one to shrink their average size toward.
    sale_units: int = 0
    typical_sale_size: float = 1.0
    # The dearest unit buyout among those Sale Events, so a Flip never counts on reselling
    # above what's been seen to sell (#41). None without any.
    max_sale_price: int | None = None


def sell_rates(
    conn: sqlite3.Connection, market: Market, config: Config, now: int
) -> dict[str, SellRate]:
    """Sell Rate of every Item Key the Market has seen, from the Observation Windows
    ending in the range before `now`. Empty when there are none: no data is not 0."""
    since, until = _range(config, now)
    evidence = sell_rate_evidence(conn, market, config, since, until)
    if not evidence.window_hours:
        return {}
    seen = listings(conn, market)
    quantities: dict[str, list[int]] = defaultdict(list)
    for listing in seen:
        if listing.last_seen >= since and listing.first_seen < until:
            quantities[listing.item_key].append(listing.quantity)
    # Item Keys that stack: gear, only ever listed 1 at a time, would pull the Market's
    # usual Sale Event size down to 1.
    stacking = {item_key for item_key, q in quantities.items() if max(q) > 1}
    market_sizes = [e.units for e in evidence.sale_events if e.item_key in stacking]
    market_size = median(market_sizes) if market_sizes else None
    units: Counter[str] = Counter()
    max_price: dict[str, int] = {}
    for event in evidence.sale_events:
        units[event.item_key] += event.units
        max_price[event.item_key] = max(max_price.get(event.item_key, 0), event.unit_buyout)
    events = evidence.event_counts()
    reposts = evidence.repost_counts()
    coincidences = evidence.coincidence_counts()
    return {
        item_key: SellRate(
            units_per_day=units[item_key] / evidence.window_hours * 24,
            sale_events=events.get(item_key, 0),
            window_hours=evidence.window_hours,
            reposts=reposts.get(item_key, 0),
            coincidences=coincidences.get(item_key, 0),
            sale_units=units[item_key],
            typical_sale_size=_typical_sale_size(market_size, quantities.get(item_key, [])),
            max_sale_price=max_price.get(item_key),
        )
        for item_key in {listing.item_key for listing in seen}
    }


def _typical_sale_size(market_size: float | None, quantities: list[int]) -> float:
    """What the Sale Size Prior shrinks an Item Key's average Sale Event size toward: the
    smaller of the Market's usual Sale Event size among Item Keys that stack and the Item
    Key's usual quantity per Listing, both over the range. Just its Listings' when the
    Market has no Sale Events to go by, and 1 when the Item Key had no Listings there."""
    if not quantities:
        return 1
    listed = median(quantities)
    return listed if market_size is None else min(market_size, listed)


def observation_window_hours(
    conn: sqlite3.Connection, market: Market, config: Config, now: int
) -> float:
    """Hours of Observation Window in the Sell Rate range before `now`: how much watching
    every Sell Rate in the Market rests on."""
    return window_hours(observation_windows_between(conn, market, config, *_range(config, now)))


def _range(config: Config, now: int) -> tuple[int, int]:
    """Windows ending in (now - range, now], as the half-open [since, until)."""
    return now - config.sell_rate_range_seconds + 1, now + 1
