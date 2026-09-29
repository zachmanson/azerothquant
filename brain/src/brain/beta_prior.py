"""Beta Prior: a Beta price shown beside each Recommendation Table row early in Live (#90).

Display only: the Decision Engine never reads it (ADR-0015), so nothing here feeds a
Recommendation. The Brain writes it into Recommendations.lua since the Addon never sees
the Archive.
"""

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, replace
from statistics import median

from brain.config import Config, Era
from brain.fair_value import FairValueCache
from brain.history import Market, latest_scan_times, scan_times
from brain.sell_rate import sell_rates

DAY = 24 * 3600
# Sale Events count over Beta's last SOLD_DAYS, and give the price from MIN_SALE_EVENTS.
SOLD_DAYS = 14
MIN_SALE_EVENTS = 3
# Otherwise the price is the median of the daily Fair Values over Beta's last LISTED_DAYS.
LISTED_DAYS = 7


@dataclass(frozen=True)
class BetaPrice:
    price: int  # copper a unit
    # True for the median Sale Event price; False for the median daily Fair Value, which
    # is listed, not sold.
    sold: bool
    sale_events: int  # in Beta's last SOLD_DAYS
    units_per_day: float | None  # the Beta Sell Rate; None without Observation Windows


@dataclass(frozen=True)
class BetaPrior:
    market: Market  # the Beta Market the prices come from
    prices: dict[str, BetaPrice]  # by Item Key; one without a Beta number is left out


def beta_prior(
    conn: sqlite3.Connection,
    market: Market,
    config: Config,
    now: int,
    item_keys: Iterable[str],
    fair_value_cache: FairValueCache | None = None,
) -> BetaPrior | None:
    """The Beta Prior of `item_keys` for `market` as of `now`: None once
    `beta_column_days` have passed since the Market's first Scan, or with no Beta Market.
    A Beta Market gets its own, so the column can be checked on Beta data.
    `fair_value_cache` is the pass's, which `recommend` has filled already."""
    times = scan_times(conn, market)
    if not times or now >= times[0] + config.beta_column_days * DAY:
        return None
    beta = _beta_market(conn, market)
    if beta is None:
        return None
    beta_now = latest_scan_times(conn, Era.BETA)[beta]
    sold_config = replace(config, sell_rate_range_seconds=SOLD_DAYS * DAY)
    rates = sell_rates(conn, beta, sold_config, beta_now, fair_value_cache=fair_value_cache)
    daily = _daily_fair_values(conn, beta, config, beta_now, fair_value_cache or FairValueCache())
    prices = {}
    for item_key in item_keys:
        rate = rates.get(item_key)
        sale_events = rate.sale_events if rate else 0
        units_per_day = rate.units_per_day if rate else None
        if rate is not None and sale_events >= MIN_SALE_EVENTS:
            price, sold = median(p for p, _ in rate.sale_prices), True
        elif daily.get(item_key):
            price, sold = median(daily[item_key]), False
        else:
            continue
        prices[item_key] = BetaPrice(round(price), sold, sale_events, units_per_day)
    return BetaPrior(market=beta, prices=prices)


def _daily_fair_values(
    conn: sqlite3.Connection, market: Market, config: Config, now: int, cache: FairValueCache
) -> dict[str, list[float]]:
    """Per Item Key, its Fair Value on each of the last LISTED_DAYS before `now` it was
    listed on: the mean over that day's Scans. Days are 24 h back from `now`, not calendar
    days, as in the replay."""
    by_day: dict[str, dict[int, list[float]]] = {}
    for at in scan_times(conn, market):
        day = (now - at) // DAY
        if 0 <= day < LISTED_DAYS:
            for item_key, value in cache.fair_values(conn, market, config, at).items():
                by_day.setdefault(item_key, {}).setdefault(day, []).append(value)
    return {
        item_key: [sum(values) / len(values) for values in days.values()]
        for item_key, days in by_day.items()
    }


def _beta_market(conn: sqlite3.Connection, market: Market) -> Market | None:
    """The Beta Market of the same faction, or else the Alliance one: of the same realm when
    there is one, so a Beta Market gets its own."""
    markets = sorted(
        latest_scan_times(conn, Era.BETA), key=lambda m: (m.realm != market.realm, m.realm)
    )
    for faction in (market.faction, "Alliance"):
        for beta in markets:
            if beta.faction == faction:
                return beta
    return None
