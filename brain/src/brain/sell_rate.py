"""Sell Rate: units of an Item Key sold per day in a Market, from Observation Windows
only (ADR-0004)."""

import sqlite3
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from statistics import median

from brain.config import Config
from brain.fair_value import FairValueCache
from brain.history import Listing, Market, listings
from brain.observation import observation_windows_between, sell_rate_evidence, window_hours


@dataclass(frozen=True)
class SellRate:
    units_per_day: float
    # The evidence behind it, so the Decision Engine can discount thin data (#25).
    # Observation Windows it was seen to sell in (ADR-0012). A held unit's Sell Rate counts
    # its Siblings' at a weight (#58), so there it and `sale_units` can be fractional.
    sale_events: float
    window_hours: float  # the Market's, shared by every Item Key in it
    reposts: int
    coincidences: int
    # For the Sale Size Prior (#24): the units in those Sale Events, and the typical size
    # of one to shrink their average size toward.
    sale_units: float = 0
    typical_sale_size: float = 1.0
    # Each Sale Event's (dearest unit buyout, units), so a buy to Sell can count only the
    # demand at the price it would post at (#107).
    sale_prices: tuple[tuple[int, int], ...] = ()

    @property
    def max_sale_price(self) -> int | None:
        """The dearest unit buyout among the Sale Events, so held units are never counted
        on selling above what's been seen to sell (#41). None without any."""
        return max((price for price, _ in self.sale_prices), default=None)

    def at_or_above(self, price: float) -> "SellRate":
        """This Sell Rate from only the Sale Events priced at or above `price` (#107): the
        demand a unit posted at `price` can count on. The window hours and the typical
        sale size stay the Market's and the Item Key's."""
        kept = tuple((p, units) for p, units in self.sale_prices if p >= price)
        units = sum(n for _, n in kept)
        return replace(
            self,
            units_per_day=units / self.window_hours * 24,
            sale_events=len(kept),
            sale_units=units,
            sale_prices=kept,
        )


def sell_rates(
    conn: sqlite3.Connection,
    market: Market,
    config: Config,
    now: int,
    seen: Sequence[Listing] | None = None,
    fair_value_cache: FairValueCache | None = None,
) -> dict[str, SellRate]:
    """Sell Rate of every Item Key the Market has seen, from the Observation Windows
    ending in the range before `now`. Empty when there are none: no data is not 0.
    `seen` is the Market's `listings`, when the caller has them already (#105), and
    `fair_value_cache` as in `sell_rate_evidence`."""
    seen = listings(conn, market) if seen is None else seen
    since, until = _range(config, now)
    evidence = sell_rate_evidence(
        conn, market, config, since, until, seen, fair_value_cache=fair_value_cache
    )
    if not evidence.window_hours:
        return {}
    in_range = [x for x in seen if x.last_seen >= since and x.first_seen < until]
    quantities: dict[str, list[int]] = defaultdict(list)
    for listing in in_range:
        quantities[listing.item_key].append(listing.quantity)
    # Item Keys that stack: gear, only ever listed 1 at a time, would pull the Market's
    # usual Sale Event size down to 1.
    stacking = _stacking(in_range)
    market_sizes = [e.units for e in evidence.sale_events if e.item_key in stacking]
    market_size = median(market_sizes) if market_sizes else None
    units: Counter[str] = Counter()
    prices: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for event in evidence.sale_events:
        units[event.item_key] += event.units
        prices[event.item_key].append((event.unit_buyout, event.units))
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
            sale_prices=tuple(prices.get(item_key, ())),
        )
        for item_key in {listing.item_key for listing in seen}
    }


def non_stacking(
    conn: sqlite3.Connection, market: Market, seen: Sequence[Listing] | None = None
) -> frozenset[str]:
    """Item Keys that don't stack (#73): no Listing of them ever seen in the Market had
    more than one unit. Sell Rate's usual Sale Event size uses the same test over its
    range only. `seen` as in `sell_rates`."""
    seen = listings(conn, market) if seen is None else seen
    return frozenset({listing.item_key for listing in seen} - _stacking(seen))


def _stacking(seen: Iterable[Listing]) -> set[str]:
    """The Item Keys some Listing in `seen` had more than one unit of."""
    return {listing.item_key for listing in seen if listing.quantity > 1}


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
