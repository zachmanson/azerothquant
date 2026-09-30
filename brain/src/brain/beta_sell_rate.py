"""Beta Sell Rate: Beta's Sale Events lent to a Prediction buy's Max Loss room early in
Live (#110, ADR-0024), the one place a decision reads the other Era.

At launch no Item Key has Live Sale Events, so a Prediction buy's exit at its post price
has no room, falls to the Vendor Price, and nothing is bought. For `beta_column_days`
from a Live Market's first Scan, that room may count Beta's Sale Events, each at
`beta_sell_rate_weight`. Only demand is borrowed, never a price: the post price is
Live's, and a Beta Sale Event counts at it when priced at or above it scaled by the
Item Key's Beta/Live Fair Value ratio.
"""

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from brain.beta_prior import DAY, beta_market
from brain.config import Config, Era
from brain.fair_value import FairValueCache
from brain.history import Market, latest_scan_times, scan_times
from brain.sell_rate import SellRate, sell_rates


@dataclass(frozen=True)
class BetaSellRate:
    """One Item Key's Beta Sell Rate, over all of the Beta Market's history."""

    rate: SellRate
    ratio: float  # its Beta Fair Value over its Live Fair Value
    weight: float  # what each Beta Sale Event and Observation Window hour counts for

    def pooled(self, live: SellRate | None, post_at: float) -> SellRate:
        """`live`, the Live demand at `post_at`, with the Beta Sale Events priced at or
        above `post_at` scaled by the ratio added, each at the weight, and so are Beta's
        Observation Window hours, whether or not any of them count. The rate is then a
        weighted average of the two, and Live takes over as its hours build."""
        beta = self.rate.at_or_above(post_at * self.ratio)
        w = self.weight
        base = live or SellRate(0, 0, 0, 0, 0, typical_sale_size=beta.typical_sale_size)
        hours = base.window_hours + w * beta.window_hours
        units = base.sale_units + w * beta.sale_units
        return replace(
            base,
            units_per_day=units / hours * 24,
            sale_events=base.sale_events + w * beta.sale_events,
            window_hours=hours,
            sale_units=units,
        )


def beta_sell_rates(
    conn: sqlite3.Connection,
    market: Market,
    config: Config,
    ratios: Mapping[str, float],
    fair_value_cache: FairValueCache | None = None,
) -> dict[str, BetaSellRate]:
    """The Beta Sell Rate of each Item Key in `ratios`, the `market`'s `beta_ratios`, by
    Item Key. Empty with a weight of 0, and when `ratios` is. An Item Key the Beta Market
    has no Sell Rate for is left out."""
    if not config.beta_sell_rate_weight or not ratios:
        return {}
    beta = beta_market(conn, market)
    if beta is None:
        return {}
    times = scan_times(conn, beta)
    all_history = replace(config, sell_rate_range_seconds=times[-1] - times[0] + 1)
    rates = sell_rates(conn, beta, all_history, times[-1], fair_value_cache=fair_value_cache)
    return {
        item_key: BetaSellRate(rates[item_key], ratio, config.beta_sell_rate_weight)
        for item_key, ratio in ratios.items()
        if item_key in rates
    }


def beta_ratios(
    conn: sqlite3.Connection,
    market: Market,
    config: Config,
    now: int,
    item_keys: Iterable[str],
    fair_value_cache: FairValueCache | None = None,
) -> dict[str, float]:
    """Each of `item_keys`' latest Beta Fair Value over its Live Fair Value in the Scan
    requested at `now`, for a Live `market` within `beta_column_days` of its first Scan:
    how Beta's prices scale to Live's. Empty for a Beta Market, which never borrows from
    itself, past those days, or without a Beta Market. An Item Key without both Fair
    Values is left out."""
    if market.era is not Era.LIVE:
        return {}
    times = scan_times(conn, market)
    if not times or now >= times[0] + config.beta_column_days * DAY:
        return {}
    beta = beta_market(conn, market)
    if beta is None:
        return {}
    cache = fair_value_cache or FairValueCache()
    live_values = cache.fair_values(conn, market, config, now)
    beta_values = cache.fair_values(conn, beta, config, latest_scan_times(conn, Era.BETA)[beta])
    return {
        item_key: beta_values[item_key] / live_values[item_key]
        for item_key in item_keys
        if live_values.get(item_key) and beta_values.get(item_key)
    }
