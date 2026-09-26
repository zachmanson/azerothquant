"""The first Decision Engine slice (#23): Vendor vs Sell for Holdings, and Flips.

Each Market the player has Characters in is valued as of its latest Scan: Fair Value
from that Scan, and Sell Rate from the Observation Windows before it. All amounts are
copper.
"""

import math
import sqlite3
from collections import Counter
from dataclasses import dataclass, field, replace
from enum import StrEnum

from brain.config import Config
from brain.fair_value import Supply, fair_value
from brain.history import (
    Holding,
    Market,
    character_markets,
    holdings,
    listings,
    pooled_gold,
    scan_times,
    supply_at,
    vendor_prices,
)
from brain.sell_rate import SellRate, observation_window_hours, sell_rates


class Action(StrEnum):
    VENDOR = "Vendor"
    SELL = "Sell"


@dataclass(frozen=True)
class Row:
    """One line of the table: what to do with `quantity` units of an Item Key."""

    item_key: str
    action: Action | None  # None when there isn't enough data to choose one
    quantity: int
    # Per unit: Fair Value to Sell at or the Vendor Price for Holdings, and the most to
    # pay for the Shopping List.
    price: float | None = None
    profit: float | None = None  # expected copper for the whole quantity
    margin: float | None = None  # per unit, a Sell's proceeds over the Vendor Price
    sale_events: int | None = None  # the evidence behind the Sell Rate
    note: str = ""
    cost: int | None = None  # the Shopping List's gold to spend on it


@dataclass(frozen=True)
class _Lot:
    """Units of one Listing worth buying, and the Action to take them out by."""

    item_key: str
    action: Action
    unit_buyout: int
    quantity: int
    unit_profit: float
    sale_events: int | None = None


@dataclass(frozen=True)
class MarketRecommendations:
    market: Market
    as_of: int  # requested_at of the Scan it was valued at
    gold: int  # the Market's pooled gold, what the Shopping List can spend
    # Observation Window hours in the Sell Rate range: how much watching every Sell Rate
    # in the Market rests on, shown instead of a per-row "thin" flag (#25).
    window_hours: float = 0.0
    holdings: list[Row] = field(default_factory=list)
    shopping_list: list[Row] = field(default_factory=list)
    shopping_cost: int = 0


def recommend(conn: sqlite3.Connection, config: Config) -> list[MarketRecommendations]:
    """Recommendations for every Market the player has Characters in."""
    result = []
    for market, characters in character_markets(conn).items():
        times = scan_times(conn, market)
        if not times:
            continue
        now = times[-1]
        supply = supply_at(conn, market, now)
        rates = sell_rates(conn, market, config, now)
        vendor = vendor_prices(conn, market.era)
        cut = config.neutral_ah_cut if market.faction == "Neutral" else config.ah_cut
        held = _market_holdings(conn, market, characters)
        rows = [
            row
            for item_key, holding in held.items()
            for row in _holding_rows(
                item_key,
                holding,
                fair_value(supply.get(item_key, []), config),
                rates.get(item_key),
                vendor.get(_item_id(item_key)),
                cut,
                config,
            )
        ]
        # Most expected profit first; rows without a number to rank by go last.
        rows.sort(key=lambda r: (r.profit is None, -(r.profit or 0)))
        for_sale: dict[str, list[tuple[int, int]]] = {}
        for listing in listings(conn, market):
            if listing.last_seen == now and not listing.own:
                for_sale.setdefault(listing.item_key, []).append(
                    (listing.unit_buyout, listing.quantity)
                )
        lots = [
            lot
            for item_key, offers in sorted(for_sale.items())
            for lot in _flips(
                item_key,
                offers,
                supply[item_key],
                rates.get(item_key),
                vendor.get(_item_id(item_key)),
                cut,
                config,
            )
        ]
        gold = pooled_gold(conn, market.era, market.realm, market.faction)
        shopping = _shopping_list(lots, gold)
        result.append(
            MarketRecommendations(
                market,
                now,
                gold,
                window_hours=observation_window_hours(conn, market, config, now),
                holdings=rows,
                shopping_list=shopping,
                shopping_cost=sum(r.cost for r in shopping),
            )
        )
    return result


def _market_holdings(
    conn: sqlite3.Connection, market: Market, characters: list[str]
) -> dict[str, Holding]:
    """What the Market's Characters hold between them, by Item Key. Mail moves items
    between them, so the Sale Horizon applies to the total."""
    total: dict[str, Holding] = {}
    for character in characters:
        for item_key, h in holdings(conn, market.era, market.realm, character).items():
            t = total.get(item_key, Holding())
            total[item_key] = Holding(
                t.bags + h.bags,
                t.bags_bound + h.bags_bound,
                t.bank + h.bank,
                t.bank_bound + h.bank_bound,
            )
    return dict(sorted(total.items()))


def _holding_rows(
    item_key: str,
    holding: Holding,
    value: float | None,
    rate: SellRate | None,
    vendor_price: int | None,
    cut: float,
    config: Config,
) -> list[Row]:
    rows = []
    vendoring = holding.bags_bound + holding.bank_bound  # bound can't go on the AH
    unbound = holding.bags + holding.bank
    if unbound and (value is None or rate is None or not rate.sale_events):
        # No sale seen yet mostly means not watched long enough, not unsellable.
        rows.append(Row(item_key, None, unbound, note="no data"))
    elif unbound:
        sell_price = value * (1 - cut)
        selling = min(
            unbound,
            _sellable(rate, config.sell_rate_prior_hours_holdings, config.sale_horizon_seconds),
        )
        margin = None if vendor_price is None else sell_price - vendor_price
        if not selling or (margin is not None and margin <= 0):
            selling = 0
        else:
            rows.append(
                Row(
                    item_key,
                    Action.SELL,
                    selling,
                    price=value,
                    profit=selling * sell_price,
                    margin=margin,
                    sale_events=rate.sale_events,
                )
            )
        vendoring += unbound - selling
    if vendoring and vendor_price is None:
        rows.append(Row(item_key, Action.VENDOR, vendoring, note="no Vendor Price"))
    elif vendoring:
        rows.append(
            Row(
                item_key,
                Action.VENDOR,
                vendoring,
                price=vendor_price,
                profit=vendoring * vendor_price,
            )
        )
    return rows


def _flips(
    item_key: str,
    offers: list[tuple[int, int]],
    supply: Supply,
    rate: SellRate | None,
    vendor_price: int | None,
    cut: float,
    config: Config,
) -> list[_Lot]:
    """What's worth buying of an Item Key, from other players' (unit buyout, quantity)
    offers, cheapest first. `supply` is every unit on sale, the player's own included.

    Buy to Sell takes no more than sells within the Sale Horizon, and prices the resale
    at the Fair Value of what's left once they're bought: buying the cheap units moves
    the price, and a lone cheap Listing is left out of Fair Value as an outlier, though
    it's the one most worth buying. Anything else under the Vendor Price is bought to
    Vendor.
    """
    offers = sorted(offers)
    to_sell: Supply = []
    room = _sellable(rate, config.sell_rate_prior_hours_flips, config.sale_horizon_seconds)
    for unit, quantity in offers:
        take = min(quantity, room)
        if not take:
            break
        resale = _resale(supply, [*to_sell, (unit, take)], cut, config)
        if resale is None or resale - unit < max(
            unit * config.flip_min_margin_share, config.flip_min_margin_copper
        ):
            break
        if vendor_price is not None and resale <= vendor_price:
            break  # a vendor pays more, so it's a Flip to Vendor
        to_sell.append((unit, take))
        room -= take
    lots = []
    if to_sell:
        resale = _resale(supply, to_sell, cut, config)
        lots = [
            _Lot(item_key, Action.SELL, unit, quantity, resale - unit, rate.sale_events)
            for unit, quantity in to_sell
        ]
    if vendor_price is not None:
        lots += [
            _Lot(item_key, Action.VENDOR, unit, quantity, vendor_price - unit)
            for unit, quantity in _without(offers, to_sell)
            if unit < vendor_price
        ]
    return lots


def _sellable(rate: SellRate | None, prior_hours: float, horizon_seconds: int) -> int:
    """Units that should sell within the Sale Horizon; none without Sell Rate evidence.

    Sell Rate is discounted by the Sell Rate Prior, as if `prior_hours` more hours had been
    watched with no sales, so a sale or two in a short Observation Window doesn't read as
    a fast seller (#25). The discount fades as real window hours build up.
    """
    if rate is None or not rate.sale_events:
        return 0
    # units / (hours + prior) * 24, written so that no prior leaves the rate exactly as is.
    per_day = rate.units_per_day * rate.window_hours / (rate.window_hours + prior_hours)
    return math.floor(per_day * horizon_seconds / 86400)


def _resale(supply: Supply, bought: Supply, cut: float, config: Config) -> float | None:
    """What one unit brings in after the cut, at the Fair Value of the supply left once
    `bought` is gone."""
    value = fair_value(_without(supply, bought), config)
    return None if value is None else value * (1 - cut)


def _without(supply: Supply, bought: Supply) -> Supply:
    left = Counter()
    for unit, quantity in supply:
        left[unit] += quantity
    for unit, quantity in bought:
        left[unit] -= quantity
    return [(unit, quantity) for unit, quantity in sorted(left.items()) if quantity > 0]


def _shopping_list(lots: list[_Lot], gold: int) -> list[Row]:
    """The lots that fit in `gold`, most profit per gold spent first, as one row per Item
    Key and Action in that order.

    A Flip to Sell cut short by gold keeps the resale worked out for all of it, which is
    a little high: some of the cheap units it expected gone are still on sale.
    """
    rows: dict[tuple[str, Action], Row] = {}
    for lot in sorted(lots, key=lambda lot: -lot.unit_profit / lot.unit_buyout):
        quantity = min(lot.quantity, gold // lot.unit_buyout)
        if not quantity:
            continue
        gold -= quantity * lot.unit_buyout
        lot = replace(lot, quantity=quantity)
        cost = lot.unit_buyout * lot.quantity
        profit = lot.unit_profit * lot.quantity
        key = (lot.item_key, lot.action)
        if key not in rows:
            rows[key] = Row(
                lot.item_key,
                lot.action,
                lot.quantity,
                lot.unit_buyout,
                profit,
                sale_events=lot.sale_events,
                cost=cost,
            )
        else:
            r = rows[key]
            rows[key] = replace(
                r,
                quantity=r.quantity + lot.quantity,
                price=max(r.price, lot.unit_buyout),
                profit=r.profit + profit,
                cost=r.cost + cost,
            )
    return list(rows.values())


def _item_id(item_key: str) -> int:
    """The itemID of a stored Item Key ("itemID" or "itemID:bonus1:..."): Vendor Price
    belongs to it, not to the random suffix."""
    return int(item_key.split(":", 1)[0])
