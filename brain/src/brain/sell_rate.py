"""Sell Rate: units of an Item Key sold per day in a Market, from Observation Windows
only (ADR-0004)."""

import sqlite3
from collections import Counter
from dataclasses import dataclass

from brain.config import Config
from brain.history import Market, listings
from brain.observation import observation_windows_between, sell_rate_evidence, window_hours


@dataclass(frozen=True)
class SellRate:
    units_per_day: float
    # The evidence behind it, so the Decision Engine can discount thin data (#25).
    sale_events: int  # Partial Sales and Probable Sales
    window_hours: float  # the Market's, shared by every Item Key in it
    reposts: int
    coincidences: int


def sell_rates(
    conn: sqlite3.Connection, market: Market, config: Config, now: int
) -> dict[str, SellRate]:
    """Sell Rate of every Item Key the Market has seen, from the Observation Windows
    ending in the range before `now`. Empty when there are none: no data is not 0."""
    evidence = sell_rate_evidence(conn, market, config, *_range(config, now))
    if not evidence.window_hours:
        return {}
    units: Counter[str] = Counter()
    for event in evidence.sale_events:
        units[event.item_key] += event.units
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
        )
        for item_key in {listing.item_key for listing in listings(conn, market)}
    }


def observation_window_hours(
    conn: sqlite3.Connection, market: Market, config: Config, now: int
) -> float:
    """Hours of Observation Window in the Sell Rate range before `now`: how much watching
    every Sell Rate in the Market rests on."""
    return window_hours(observation_windows_between(conn, market, config, *_range(config, now)))


def _range(config: Config, now: int) -> tuple[int, int]:
    """Windows ending in (now - range, now], as the half-open [since, until)."""
    return now - config.sell_rate_range_seconds + 1, now + 1
