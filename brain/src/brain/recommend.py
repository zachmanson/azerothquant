"""The Decision Engine: Vendor vs Sell for Holdings, and Flips (#23), and Hold under a
Prediction, both for Holdings and for buying (#26, ADR-0006).

Each Market the player has Characters in is valued as of its latest Scan: Fair Value
from that Scan, and Sell Rate from the Observation Windows before it. All amounts are
copper.
"""

import math
import sqlite3
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
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
from brain.predictions import Prediction
from brain.sell_rate import SellRate, observation_window_hours, sell_rates


class Action(StrEnum):
    VENDOR = "Vendor"
    SELL = "Sell"
    HOLD = "Hold"  # only ever under a Prediction (ADR-0006)


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
    # The Shopping List's gold to spend on it, or for a Hold the gold it ties up: what
    # letting the units go would bring today.
    cost: float | None = None
    prediction: str = ""  # the Prediction the Action depends on, if any
    # A Prediction buy's Max Loss for the whole quantity: what's lost if the Prediction is
    # wrong and the units are let go at today's prices.
    max_loss: float | None = None


@dataclass(frozen=True)
class _Buy:
    """Units of one Listing worth buying, and the Action to take them out by."""

    item_key: str
    action: Action
    unit_buyout: int
    quantity: int
    unit_profit: float
    sale_events: int | None = None


@dataclass(frozen=True)
class _HoldBuy:
    """Units of one Listing worth buying to Hold under a Prediction."""

    item_key: str
    prediction: str
    unit_buyout: int
    quantity: int
    unit_max_loss: float


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
    # The Shopping List's own section for buying to Hold under a Prediction, whose upside
    # is unknown (ADR-0006).
    prediction_buys: list[Row] = field(default_factory=list)
    prediction_cost: int = 0


def recommend(
    conn: sqlite3.Connection, config: Config, predictions: Sequence[Prediction] = ()
) -> list[MarketRecommendations]:
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
        gold = pooled_gold(conn, market.era, market.realm, market.faction)
        today = date.fromtimestamp(now)
        active = [p for p in predictions if p.active_on(today)]
        caps = _Caps(gold, config)
        bound = {k: h.bags_bound + h.bank_bound for k, h in held.items()}
        rows = _hold(rows, active, bound, vendor, caps)
        # Most expected profit first; rows without a number to rank by go last.
        rows.sort(key=lambda r: (r.profit is None, -(r.profit or 0)))
        for_sale: dict[str, list[tuple[int, int]]] = {}
        for listing in listings(conn, market):
            if listing.last_seen == now and not listing.own:
                for_sale.setdefault(listing.item_key, []).append(
                    (listing.unit_buyout, listing.quantity)
                )
        under = {k: p.name for p in active for k in p.item_keys}
        hold_buys = [
            buy
            for item_key, offers in sorted(for_sale.items())
            if item_key in under
            for buy in _hold_buys(
                item_key,
                under[item_key],
                offers,
                supply[item_key],
                rates.get(item_key),
                vendor.get(_item_id(item_key)),
                held[item_key].bags + held[item_key].bank if item_key in held else 0,
                cut,
                config,
            )
        ]
        buys = [
            buy
            for item_key, offers in sorted(for_sale.items())
            if item_key not in under
            for buy in _flips(
                item_key,
                offers,
                supply[item_key],
                rates.get(item_key),
                vendor.get(_item_id(item_key)),
                cut,
                config,
            )
        ]
        shopping = _shopping_list(buys, gold)
        shopping_cost = sum(r.cost for r in shopping)
        prediction_buys = _spend_on_predictions(hold_buys, gold - shopping_cost, caps)
        result.append(
            MarketRecommendations(
                market,
                now,
                gold,
                window_hours=observation_window_hours(conn, market, config, now),
                holdings=rows,
                shopping_list=shopping,
                shopping_cost=shopping_cost,
                prediction_buys=prediction_buys,
                prediction_cost=sum(r.cost for r in prediction_buys),
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
            sellable_units(
                rate,
                config.sell_rate_prior_hours_holdings,
                config.sale_size_prior_events_holdings,
                config.sale_horizon_seconds,
            ),
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


class _Caps:
    """The gold still allowed under each Prediction and under all of them together, as
    shares of the Market's pooled gold (ADR-0006)."""

    def __init__(self, gold: int, config: Config):
        self._each = gold * config.prediction_cap_share
        self._total_left = gold * config.predictions_cap_share
        self._used: Counter[str] = Counter()

    def room(self, prediction: str) -> float:
        return min(self._each - self._used[prediction], self._total_left)

    def spend(self, prediction: str, gold: float) -> None:
        self._used[prediction] += gold
        self._total_left -= gold


def _hold(
    rows: list[Row],
    predictions: list[Prediction],
    bound: dict[str, int],
    vendor: dict[int, int],
    caps: _Caps,
) -> list[Row]:
    """`rows` with the units of each Prediction's Item Keys switched to Hold under it, as
    many as its caps allow.

    Held units tie up what letting them go would bring today, so the ones with the
    cheapest exit are Held first. Units without enough data to choose an exit count at
    the Vendor Price, the least they'd bring, or nothing without one. Bound units can't be
    sold after the Catalyst either, and are never Held.
    """
    taken: Counter[int] = Counter()  # units Held, by index into rows
    holds = []
    for p in predictions:
        units = []  # (gold per unit, index into rows, units that could be Held)
        for i, r in enumerate(rows):
            if r.item_key in p.item_keys:
                n = r.quantity - (bound.get(r.item_key, 0) if r.action is Action.VENDOR else 0)
                if r.profit is not None:
                    value = r.profit / r.quantity
                else:
                    value = vendor.get(_item_id(r.item_key), 0)
                units.append((value, i, n))
        held: dict[str, Row] = {}
        for value, i, n in sorted(units):
            if value:
                n = min(n, max(0, math.floor(caps.room(p.name) / value)))
            if not n:
                continue
            caps.spend(p.name, n * value)
            taken[i] += n
            key = rows[i].item_key
            h = held.get(key, Row(key, Action.HOLD, 0, cost=0, prediction=p.name))
            held[key] = replace(h, quantity=h.quantity + n, cost=h.cost + n * value)
        holds += held.values()
    rest = [_fewer(r, r.quantity - taken[i]) for i, r in enumerate(rows) if r.quantity > taken[i]]
    return rest + holds


def _fewer(row: Row, quantity: int) -> Row:
    if quantity == row.quantity:
        return row
    profit = None if row.profit is None else row.profit / row.quantity * quantity
    return replace(row, quantity=quantity, profit=profit)


def _flips(
    item_key: str,
    offers: list[tuple[int, int]],
    supply: Supply,
    rate: SellRate | None,
    vendor_price: int | None,
    cut: float,
    config: Config,
) -> list[_Buy]:
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
    room = sellable_units(
        rate,
        config.sell_rate_prior_hours_flips,
        config.sale_size_prior_events_flips,
        config.sale_horizon_seconds,
    )
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
    buys = []
    if to_sell:
        resale = _resale(supply, to_sell, cut, config)
        buys = [
            _Buy(item_key, Action.SELL, unit, quantity, resale - unit, rate.sale_events)
            for unit, quantity in to_sell
        ]
    if vendor_price is not None:
        buys += [
            _Buy(item_key, Action.VENDOR, unit, quantity, vendor_price - unit)
            for unit, quantity in _without(offers, to_sell)
            if unit < vendor_price
        ]
    return buys


def _hold_buys(
    item_key: str,
    prediction: str,
    offers: list[tuple[int, int]],
    supply: Supply,
    rate: SellRate | None,
    vendor_price: int | None,
    held: int,
    cut: float,
    config: Config,
) -> list[_HoldBuy]:
    """What's worth buying of an Item Key to Hold under a Prediction, from other players'
    (unit buyout, quantity) offers, cheapest first: the units whose Max Loss is small
    enough. `supply` is every unit on sale, and `held` the units the player could sell.

    A unit's Max Loss is its buyout less its exit without the Prediction. That's Sell, at
    the resale a Flip would get, for the units that would sell within the Sale Horizon if
    the Prediction were wrong, after the `held` ones, judged as strictly as a Flip. The
    rest can only be Vendored, or are worth nothing without a Vendor Price.
    """
    room = max(
        0,
        sellable_units(
            rate,
            config.sell_rate_prior_hours_flips,
            config.sale_size_prior_events_flips,
            config.sale_horizon_seconds,
        )
        - held,
    )
    bought: Supply = []
    buys = []
    for unit, quantity in sorted(offers):
        take = min(quantity, room)
        resale = _resale(supply, [*bought, (unit, take)], cut, config) if take else None
        parts = [(take, max(resale or 0, vendor_price or 0)), (quantity - take, vendor_price or 0)]
        for n, exit_value in parts:
            if not n:
                continue
            max_loss = unit - exit_value
            if max_loss > unit * config.prediction_max_loss_share:
                return buys
            buys.append(_HoldBuy(item_key, prediction, unit, n, max_loss))
        bought.append((unit, take))
        room -= take
    return buys


def _spend_on_predictions(buys: list[_HoldBuy], gold: int, caps: _Caps) -> list[Row]:
    """The Prediction buys that fit in `gold` and the caps, lowest Max Loss for the gold
    spent first, as one row per Item Key in that order."""
    rows: dict[str, Row] = {}
    for buy in sorted(buys, key=lambda buy: buy.unit_max_loss / buy.unit_buyout):
        room = min(gold, caps.room(buy.prediction))
        quantity = min(buy.quantity, max(0, math.floor(room / buy.unit_buyout)))
        if not quantity:
            continue
        cost = quantity * buy.unit_buyout
        gold -= cost
        caps.spend(buy.prediction, cost)
        empty = Row(buy.item_key, Action.HOLD, 0, price=0, cost=0, max_loss=0)
        r = rows.get(buy.item_key, replace(empty, prediction=buy.prediction))
        rows[buy.item_key] = replace(
            r,
            quantity=r.quantity + quantity,
            price=max(r.price, buy.unit_buyout),
            cost=r.cost + cost,
            max_loss=r.max_loss + quantity * buy.unit_max_loss,
        )
    return list(rows.values())


def sellable_units(
    rate: SellRate | None, prior_hours: float, prior_events: float, horizon_seconds: int
) -> int:
    """Units that should sell within the Sale Horizon; none without Sell Rate evidence.

    Sell Rate is discounted by the Sell Rate Prior, as if `prior_hours` more hours had been
    watched with no sales, so a sale or two in a short Observation Window doesn't read as
    a fast seller (#25). Its average Sale Event size is shrunk by the Sale Size Prior, as
    if `prior_events` more Sale Events of the typical size had been seen, so one big buyer
    doesn't read as an Item Key that sells in bulk (#24). Both fade as evidence builds up.
    """
    if rate is None or not rate.sale_events:
        return 0
    mean_size = rate.sale_units / rate.sale_events
    shrunk_size = (rate.sale_units + prior_events * rate.typical_sale_size) / (
        rate.sale_events + prior_events
    )
    # units / (hours + prior) * 24 * shrunk / mean, written so that no priors leave the
    # rate exactly as is.
    per_day = (
        rate.units_per_day
        * rate.window_hours
        / (rate.window_hours + prior_hours)
        * (shrunk_size / mean_size)
    )
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


def _shopping_list(buys: list[_Buy], gold: int) -> list[Row]:
    """The buys that fit in `gold`, most profit per gold spent first, as one row per Item
    Key and Action in that order.

    A Flip to Sell cut short by gold keeps the resale worked out for all of it, which is
    a little high: some of the cheap units it expected gone are still on sale.
    """
    rows: dict[tuple[str, Action], Row] = {}
    for buy in sorted(buys, key=lambda buy: -buy.unit_profit / buy.unit_buyout):
        quantity = min(buy.quantity, gold // buy.unit_buyout)
        if not quantity:
            continue
        gold -= quantity * buy.unit_buyout
        buy = replace(buy, quantity=quantity)
        cost = buy.unit_buyout * buy.quantity
        profit = buy.unit_profit * buy.quantity
        key = (buy.item_key, buy.action)
        if key not in rows:
            rows[key] = Row(
                buy.item_key,
                buy.action,
                buy.quantity,
                buy.unit_buyout,
                profit,
                sale_events=buy.sale_events,
                cost=cost,
            )
        else:
            r = rows[key]
            rows[key] = replace(
                r,
                quantity=r.quantity + buy.quantity,
                price=max(r.price, buy.unit_buyout),
                profit=r.profit + profit,
                cost=r.cost + cost,
            )
    return list(rows.values())


def _item_id(item_key: str) -> int:
    """The itemID of a stored Item Key ("itemID" or "itemID:bonus1:..."): Vendor Price
    belongs to it, not to the random suffix."""
    return int(item_key.split(":", 1)[0])
