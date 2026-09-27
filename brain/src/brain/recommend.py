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
from datetime import date, datetime
from enum import StrEnum

from brain.config import Config
from brain.fair_value import Supply, fair_value
from brain.history import (
    Holding,
    KnownRecipe,
    Market,
    character_markets,
    holdings,
    known_recipes,
    listings,
    merchant_costs,
    outcomes,
    pooled_gold,
    purchases,
    scan_times,
    supply_at,
    vendor_prices,
)
from brain.lots import Held, Lot, ended_at, link_sales, lots, settle, start_of
from brain.mailbox import MailKind
from brain.predictions import Prediction
from brain.sell_rate import SellRate, observation_window_hours, sell_rates


class Action(StrEnum):
    VENDOR = "Vendor"
    SELL = "Sell"
    # From held reagents, valued one step deep (ADR-0008), or on the Shopping List a Flip
    # to Craft that buys the missing ones (ADR-0009).
    CRAFT = "Craft"
    HOLD = "Hold"  # only ever under a Prediction (ADR-0006)


@dataclass(frozen=True)
class ReagentBuy:
    """A Flip to Craft's buys of one reagent: on the Auction House at up to
    `max_unit_price` each, or from a merchant at its Merchant Cost."""

    item_key: str
    quantity: int
    max_unit_price: float
    merchant: bool = False


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
    # Per unit, a Flip to Sell's price to post at, which its Profit rests on, before the
    # cut (#59): just under the cheapest other player's Listing left once it's bought (#62).
    post_at: float | None = None
    margin: float | None = None  # per unit, a Sell's proceeds over the Vendor Price
    sale_events: int | None = None  # the evidence behind the Sell Rate
    note: str = ""
    # The Shopping List's gold to spend on it, or for a Hold the gold it ties up: what its
    # units cost, by their Lots or else what letting them go would bring today (_hold).
    cost: float | None = None
    prediction: str = ""  # the Prediction the Action depends on, if any
    # A Prediction buy's Max Loss for the whole quantity: what's lost if the Prediction is
    # wrong and the units are let go at today's prices.
    max_loss: float | None = None
    buys: tuple[ReagentBuy, ...] = ()  # a Flip to Craft's reagents to buy


@dataclass(frozen=True)
class _Buy:
    """Units of one Listing worth buying, and the Action to take them out by."""

    item_key: str
    action: Action
    unit_buyout: int
    quantity: int
    unit_profit: float
    sale_events: int | None = None
    post_at: float | None = None  # a Flip to Sell's resale, before the cut

    @property
    def per_gold(self) -> float:
        return self.unit_profit / self.unit_buyout


@dataclass(frozen=True)
class _HoldBuy:
    """Units of one Listing worth buying to Hold under a Prediction."""

    item_key: str
    prediction: str
    unit_buyout: int
    quantity: int
    unit_max_loss: float


@dataclass(frozen=True)
class Grade:
    """A Prediction's realized result, fixed at its grading moment (ADR-0006): its sold
    units after the Auction House cut, plus its open units at their Best Exit Value
    without it then, against what all of them cost."""

    prediction: str
    graded_at: int
    proceeds: float
    open_value: float
    cost: int

    @property
    def return_(self) -> float | None:
        """Gain over cost, or None if its units cost nothing."""
        if not self.cost:
            return None
        return (self.proceeds + self.open_value - self.cost) / self.cost


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
    # Sold Outcomes whose item name gave no single Item Key, so they close no Lot
    # (ADR-0007). If this isn't zero in practice, Character Reads should record names.
    unlinked_sales: int = 0
    # The graded Predictions' record, shown rather than applied except for the brake: the
    # caps are halved while their pooled return is negative (ADR-0006).
    grades: list[Grade] = field(default_factory=list)
    pooled_return: float | None = None  # None with nothing graded


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
        cut = _cut(market, config)
        valuer = _Valuer(supply, rates, vendor, cut, config)
        today = date.fromtimestamp(now)
        active = [p for p in predictions if p.active_on(today)]
        under = {k: p.name for p in active for k in p.item_keys}
        plans = _plans(known_recipes(conn, market), now)
        merchant = {str(item_id): cost for item_id, cost in merchant_costs(conn, market).items()}
        crafting = _crafts(
            _market_holdings(conn, market, characters), plans, merchant, valuer, set(under), config
        )
        held, crafted = crafting.after, crafting.counts
        rows = [
            _with_note(row, f"incl. {crafted[item_key]} crafted" if crafted[item_key] else "")
            for item_key, holding in held.items()
            for row in valuer.rows(item_key, holding)
        ] + crafting.rows
        gold = pooled_gold(conn, market.era, market.realm, market.faction)
        graded = grades(conn, config, market, predictions, now)
        pooled = pooled_return(graded)
        caps = _Caps(gold, config, brake=pooled is not None and pooled < 0)
        bound = {k: h.bags_bound + h.bank_bound for k, h in held.items()}
        rows = _hold(rows, active, bound, vendor, caps, _lot_costs(conn, config, market, active))
        # Most expected profit first; rows without a number to rank by go last.
        rows.sort(key=lambda r: (r.profit is None, -(r.profit or 0)))
        market_listings = listings(conn, market)
        for_sale: dict[str, list[tuple[int, int]]] = {}
        for listing in market_listings:
            if listing.last_seen == now and not listing.own:
                for_sale.setdefault(listing.item_key, []).append(
                    (listing.unit_buyout, listing.quantity)
                )
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
        outlets = {
            plan.output: _outlet(
                plan.recipe.bind_type in _BOUND_ON_CRAFT,
                supply.get(plan.output, []),
                for_sale.get(plan.output, []),
                rates.get(plan.output),
                vendor.get(_item_id(plan.output)),
                _unbound(held.get(plan.output, Holding())),
                [(b.unit_buyout, b.quantity) for b in buys if b.item_key == plan.output],
                cut,
                config,
            )
            for plan in plans
        }
        asks = {
            key: _without(offers, [(b.unit_buyout, b.quantity) for b in buys if b.item_key == key])
            for key, offers in for_sale.items()
        }
        crafts = _flips_to_craft(
            plans, crafting, asks, merchant, valuer, outlets, set(under), gold, config
        )
        shopping = _shopping_list(buys, crafts, gold)
        shopping_cost = round(sum(r.cost for r in shopping))
        prediction_buys = _spend_on_predictions(hold_buys, gold - shopping_cost, caps)
        linked = link_sales(outcomes(conn, market), market_listings, purchases(conn, market))
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
                unlinked_sales=sum(o.kind is MailKind.SOLD and o.item_key is None for o in linked),
                grades=graded,
                pooled_return=pooled,
            )
        )
    return result


def held_at_writing(
    conn: sqlite3.Connection, config: Config, market: Market, predictions: Sequence[Prediction]
) -> list[Held]:
    """The units of each Prediction's Item Keys the Market's Characters held at the start
    of its written day, costed at what their best Action would have brought then, as of
    the latest Scan up to that moment (ADR-0007). Bound units are never Held."""
    characters = character_markets(conn).get(market, [])
    result = []
    for p in predictions:
        at = start_of(p.written)
        held = _market_holdings(conn, market, characters, as_of=at)
        for item_key in p.item_keys:
            h = held.get(item_key)
            if h is None or not h.bags + h.bank:
                continue
            units = h.bags + h.bank
            cost = _exit_value(conn, config, market, item_key, units, at)
            result.append(Held(p.name, item_key, units, round(cost)))
    return result


def grades(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    predictions: Sequence[Prediction],
    now: int,
) -> list[Grade]:
    """The Grade of each Prediction a Sale Horizon has passed since it ended, by `now`."""
    due = [p for p in predictions if ended_at(p) + config.sale_horizon_seconds <= now]
    if not due:
        return []
    market_lots = _market_lots(conn, config, market, predictions)
    result = []
    for p in due:
        graded_at = ended_at(p) + config.sale_horizon_seconds
        settled = settle(p, market_lots, graded_at, _cut(market, config))
        open_value = sum(
            _exit_value(conn, config, market, item_key, units, graded_at)
            for item_key, units in settled.open_units.items()
            if units
        )
        result.append(Grade(p.name, graded_at, settled.proceeds, open_value, settled.cost))
    return result


def _market_lots(
    conn: sqlite3.Connection, config: Config, market: Market, predictions: Sequence[Prediction]
) -> list[Lot]:
    market_purchases = purchases(conn, market)
    linked = link_sales(outcomes(conn, market), listings(conn, market), market_purchases)
    held = held_at_writing(conn, config, market, predictions)
    return lots(market_purchases, linked, predictions, held)


def _lot_costs(
    conn: sqlite3.Connection, config: Config, market: Market, predictions: Sequence[Prediction]
) -> dict[tuple[str, str], list[tuple[float, int]]]:
    """The open units of each Prediction's Lots and what each of them cost, oldest Lot
    first, by (Prediction, Item Key)."""
    if not predictions:
        return {}
    result: dict[tuple[str, str], list[tuple[float, int]]] = {}
    for lot in _market_lots(conn, config, market, predictions):
        if lot.prediction is not None and lot.open_units:
            result.setdefault((lot.prediction, lot.item_key), []).append(
                (lot.cost / lot.units, lot.open_units)
            )
    return result


def pooled_return(graded: Sequence[Grade]) -> float | None:
    """The realized return on all the gold graded Predictions tied up together, or None
    with nothing graded."""
    cost = sum(g.cost for g in graded)
    if not cost:
        return None
    return sum(g.proceeds + g.open_value - g.cost for g in graded) / cost


def _exit_value(
    conn: sqlite3.Connection, config: Config, market: Market, item_key: str, units: int, at: int
) -> float:
    """What `units` of an Item Key would have brought by their best Action, as of the
    latest Scan up to `at`. Vendor Prices are the latest seen, since a vendor's price
    doesn't move. Units without enough data to choose an exit count at the Vendor Price,
    as when Holding them (_hold)."""
    scanned = [t for t in scan_times(conn, market) if t <= at]
    supply = supply_at(conn, market, scanned[-1]) if scanned else {}
    rates = sell_rates(conn, market, config, scanned[-1]) if scanned else {}
    vendor = vendor_prices(conn, market.era)
    valuer = _Valuer(supply, rates, vendor, _cut(market, config), config)
    return valuer.worth(item_key, Holding(bags=units))


class _Valuer:
    """A Market's Sell/Vendor split of held units, as of one Scan."""

    def __init__(
        self,
        supply: dict[str, Supply],
        rates: dict[str, SellRate],
        vendor: dict[int, int],
        cut: float,
        config: Config,
    ):
        self._supply, self._rates, self._vendor = supply, rates, vendor
        self._cut, self._config = cut, config

    def rows(self, item_key: str, holding: Holding) -> list[Row]:
        return _holding_rows(
            item_key,
            holding,
            fair_value(self._supply.get(item_key, []), self._config),
            self._rates.get(item_key),
            self._vendor.get(_item_id(item_key)),
            self._cut,
            self._config,
        )

    def has_data(self, item_key: str) -> bool:
        """Whether there's a Fair Value and a Sell Rate with sales to value it by."""
        rate = self._rates.get(item_key)
        value = fair_value(self._supply.get(item_key, []), self._config)
        return value is not None and rate is not None and bool(rate.sale_events)

    def worth(self, item_key: str, holding: Holding) -> float:
        """What the units would bring by their best Actions. Units without enough data to
        choose an exit count at the Vendor Price, or nothing without one."""
        vendor = self._vendor.get(_item_id(item_key), 0)
        return sum(
            r.profit if r.profit is not None else r.quantity * vendor
            for r in self.rows(item_key, holding)
        )


def _cut(market: Market, config: Config) -> float:
    return config.neutral_ah_cut if market.faction == "Neutral" else config.ah_cut


def _market_holdings(
    conn: sqlite3.Connection, market: Market, characters: list[str], as_of: int | None = None
) -> dict[str, Holding]:
    """What the Market's Characters hold between them, by Item Key. Mail moves items
    between them, so the Sale Horizon applies to the total."""
    total: dict[str, Holding] = {}
    for character in characters:
        for item_key, h in holdings(conn, market.era, market.realm, character, as_of).items():
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


# Enum.ItemBind values whose items can't go on the Auction House: Bind on Pickup and
# quest items.
_BOUND_ON_CRAFT = {1, 4}


@dataclass
class _Plan:
    """The crafts chosen so far of one Known Recipe."""

    recipe: KnownRecipe
    character: str  # one that knows it
    limit: int | None = None  # the most crafts, for a cooldown recipe
    # When the first Character's cooldown ends, if none has passed as of its read.
    until: float | None = None
    crafts: int = 0
    gain: float = 0.0
    used: Counter[str] = field(default_factory=Counter)  # reagent units, bought ones included
    bought: Counter[str] = field(default_factory=Counter)

    @property
    def output(self) -> str:
        return str(self.recipe.output_item_id)

    @property
    def needs(self) -> dict[str, int]:
        needs: Counter[str] = Counter()
        for reagent in self.recipe.reagents:
            needs[str(reagent.item_id)] += reagent.quantity
        return needs

    def row(self) -> Row:
        uses = ", ".join(
            f"{n} of {key}" + (f" (buy {self.bought[key]})" if self.bought[key] else "")
            for key, n in self.used.items()
        )
        return Row(
            self.output,
            Action.CRAFT,
            self.crafts,
            profit=self.gain,
            note=f"on {self.character}: uses {uses}",
        )


def _plans(recipes: list[KnownRecipe], now: int) -> list[_Plan]:
    """One plan per recipe across the Characters that know it.

    A recipe with a cooldown crafts at most once per Character that knows it and whose
    cooldown has passed as of its read. The client may give no cooldown for one that's
    ready, so it's only limited when some Character's read caught it cooling down.
    """
    by_id: dict[int, list[KnownRecipe]] = {}
    for r in recipes:
        by_id.setdefault(r.recipe_id, []).append(r)
    plans = []
    for known in by_id.values():
        ready = [k for k in known if not k.cooldown or k.read_at + k.cooldown <= now]
        has_cooldown = any(k.cooldown is not None for k in known)
        first = (ready or known)[0]
        plans.append(
            _Plan(
                first,
                first.character,
                limit=len({k.character for k in ready}) if has_cooldown else None,
                until=None if ready else min(k.read_at + k.cooldown for k in known),
            )
        )
    return plans


@dataclass(frozen=True)
class _Crafting:
    """The Craft Actions chosen from held reagents (ADR-0008)."""

    rows: list[Row]
    held: dict[str, Holding]  # what's left of the Holdings once crafted from
    crafted: dict[str, Holding]  # the outputs made

    @property
    def after(self) -> dict[str, Holding]:
        """The Holdings once the crafts are made."""
        after = dict(self.held)
        for key, h in self.crafted.items():
            after[key] = _plus(after.get(key, Holding()), h)
        return dict(sorted(after.items()))

    @property
    def counts(self) -> Counter[str]:
        """The units crafted of each output."""
        return Counter({key: _units(h) for key, h in self.crafted.items()})


def _crafts(
    held: dict[str, Holding],
    plans: list[_Plan],
    merchant: dict[str, float],
    valuer: _Valuer,
    under: set[str],
    config: Config,
) -> _Crafting:
    """The Craft Actions (ADR-0008), counted into `plans`.

    Greedy at the margin: each step makes the one craft that gains the most, the output's
    worth with its units added less the reagents' worth lost and any Merchant Cost paid,
    until the best gain is no more than `craft_min_gain`. Outputs are valued by Sell and
    Vendor only, never crafted further.
    """
    held = dict(held)
    crafted: dict[str, Holding] = {}
    craftable, blocked = [], []
    for plan in plans:
        if plan.output in under:
            continue  # its Held units would include ones not made yet
        reason = _blocked(plan, merchant, valuer)
        if reason is None and plan.until is not None:
            reason = f"on cooldown until {datetime.fromtimestamp(plan.until):%Y-%m-%d %H:%M}"
        if reason is None:
            craftable.append(plan)
        elif _step(plan, held, crafted, merchant, valuer, under) is not None:
            # Only shown when the reagents are there, or every recipe would be.
            blocked.append(Row(plan.output, Action.CRAFT, 0, note=f"on {plan.character}: {reason}"))
    while True:
        best = None
        for plan in craftable:
            if plan.limit is not None and plan.crafts >= plan.limit:
                continue
            step = _step(plan, held, crafted, merchant, valuer, under)
            if step is not None and (best is None or step[0] > best[1][0]):
                best = (plan, step)
        if best is None or best[1][0] <= config.craft_min_gain:
            break
        plan, (gain, takes) = best
        plan.crafts += 1
        plan.gain += gain
        for key, (take, buy) in takes.items():
            held[key] = _take(held[key], take) if take else held.get(key, Holding())
            plan.used[key] += take + buy
            plan.bought[key] += buy
        crafted[plan.output] = _crafted(plan, crafted.get(plan.output, Holding()))
    return _Crafting([p.row() for p in craftable if p.crafts] + blocked, held, crafted)


def _blocked(plan: _Plan, merchant: dict[str, float], valuer: _Valuer) -> str | None:
    """Why the recipe can't be valued, if it can't. The guesses lean toward crafting less:
    a reagent with no market data would be undervalued at its Vendor Price."""
    if plan.recipe.bind_type is None:
        return "unknown bind type"
    for key in plan.needs:
        if key not in merchant and not valuer.has_data(key):
            return f"no data for {key}"
    return None


def _step(
    plan: _Plan,
    held: dict[str, Holding],
    crafted: dict[str, Holding],
    merchant: dict[str, float],
    valuer: _Valuer,
    under: set[str],
) -> tuple[float, dict[str, tuple[int, int]]] | None:
    """What one more craft gains, and per reagent the held units it uses and the units it
    buys; None if the reagents aren't there. Crafted units and units Held under a
    Prediction are never reagents."""
    loss = 0.0
    takes = {}
    for key, n in plan.needs.items():
        have = Holding() if key in under else held.get(key, Holding())
        take = min(n, _units(have))
        buy = n - take
        if key in merchant:
            loss += n * merchant[key]
        elif buy:
            return None
        else:
            now = _plus(have, crafted.get(key, Holding()))
            loss += valuer.worth(key, now) - valuer.worth(key, _take(now, take))
        takes[key] = (take, buy)
    if not any(take for take, _ in takes.values()):
        # Crafts are from held reagents: with merchant ones alone the loop wouldn't end
        # whenever a vendor pays more for the output than the merchant charges.
        return None
    now = _plus(held.get(plan.output, Holding()), crafted.get(plan.output, Holding()))
    gain = valuer.worth(plan.output, _crafted(plan, now)) - valuer.worth(plan.output, now)
    return gain - loss, takes


@dataclass
class _Outlet:
    """Where a Flip to Craft's output goes: `room` more units Sell for `resale` each
    after the cut, and the rest are Vendored."""

    room: int
    resale: float | None
    vendor_price: int
    bound: bool

    def value(self, units: int) -> tuple[float, int]:
        """What `units` more would bring, and how many of them Sell."""
        if self.bound or self.resale is None or self.resale <= self.vendor_price:
            return units * self.vendor_price, 0
        selling = min(units, self.room)
        return selling * self.resale + (units - selling) * self.vendor_price, selling


def _outlet(
    bound: bool,
    supply: Supply,
    others: Supply,
    rate: SellRate | None,
    vendor_price: int | None,
    held: int,
    flipped: Supply,
    cut: float,
    config: Config,
) -> _Outlet:
    """A Flip to Craft output's Sell room, judged as strictly as a Flip's: what sells
    within the Sale Horizon under the Flip priors, less the `held` units and the ones
    `flipped` to Sell. It resells like them, posted under what's left once they're bought.
    `others` is other players' asks."""
    room, resale = _flip_room(rate, config), None
    if room:
        room = max(0, room - held - sum(n for _, n in flipped))
        resale = _resale(supply, others, flipped, cut, config, rate.max_sale_price)
    return _Outlet(room, resale, vendor_price or 0, bound)


@dataclass(frozen=True)
class _CraftBuy:
    """One Flip to Craft: a craft of `plan` whose missing reagents are bought."""

    plan: _Plan
    gold: float  # spent on the Auction House and at merchants
    profit: float  # the output's worth less the reagents' cost, held ones included
    takes: dict[str, tuple[int, int]]  # per reagent, held units used and units bought
    asks: dict[str, Supply]  # the Auction House asks it buys
    buys: tuple[ReagentBuy, ...]
    selling: int  # output units that Sell

    @property
    def per_gold(self) -> float:
        return self.profit / self.gold


def _flips_to_craft(
    plans: list[_Plan],
    crafting: _Crafting,
    asks: dict[str, Supply],
    merchant: dict[str, float],
    valuer: _Valuer,
    outlets: dict[str, _Outlet],
    under: set[str],
    gold: float,
    config: Config,
) -> list[_CraftBuy]:
    """The Flips to Craft worth making once the held-only crafts are (ADR-0009), in the
    order chosen.

    Greedy like the Craft Action: each step takes the craft that profits most among those
    clearing the Flip margin against the gold they spend, until none does or the gold
    runs out. Leftover held reagents are used first, then merchant ones are bought at
    their Merchant Cost and the rest at the cheapest `asks` left.
    """
    held = dict(crafting.held)
    asks = dict(asks)
    made: Counter[int] = Counter()  # Flips to Craft per recipe
    # A recipe on cooldown for every Character has a limit of 0.
    candidates = [
        p
        for p in plans
        if p.recipe.bind_type is not None
        and p.output not in under
        and not any(key in under for key in p.needs)
    ]
    result = []
    while True:
        best = None
        for plan in candidates:
            if plan.limit is not None and plan.crafts + made[plan.recipe.recipe_id] >= plan.limit:
                continue
            step = _flip_step(
                plan, held, crafting.crafted, asks, merchant, valuer, outlets[plan.output]
            )
            if step is None or step.gold > gold:
                continue
            if step.profit < max(
                step.gold * config.flip_min_margin_share, config.flip_min_margin_copper
            ):
                continue
            if best is None or step.profit > best.profit:
                best = step
        if best is None:
            break
        result.append(best)
        gold -= best.gold
        made[best.plan.recipe.recipe_id] += 1
        for key, (take, _) in best.takes.items():
            if take:
                held[key] = _take(held[key], take)
        for key, bought in best.asks.items():
            asks[key] = _without(asks[key], bought)
        outlets[best.plan.output].room -= best.selling
    return result


def _flip_step(
    plan: _Plan,
    held: dict[str, Holding],
    crafted: dict[str, Holding],
    asks: dict[str, Supply],
    merchant: dict[str, float],
    valuer: _Valuer,
    outlet: _Outlet,
) -> _CraftBuy | None:
    """One more Flip to Craft of `plan`; None if the reagents can't be had, or if nothing
    needs buying, since that's a Craft Action. A held reagent is only used if there's
    market data to value it by, and crafted units never are."""
    cost = gold = 0.0
    takes, bought, buys = {}, {}, []
    for key, n in plan.needs.items():
        have = held.get(key, Holding())
        if key in merchant:
            take = min(n, _units(have))
            cost += n * merchant[key]
            gold += (n - take) * merchant[key]
            if n - take:
                buys.append(ReagentBuy(key, n - take, merchant[key], merchant=True))
        else:
            take = min(n, _units(have)) if valuer.has_data(key) else 0
            now = _plus(have, crafted.get(key, Holding()))
            cost += valuer.worth(key, now) - valuer.worth(key, _take(now, take))
            if n - take:
                cheapest = _cheapest(asks.get(key, []), n - take)
                if cheapest is None:
                    return None
                paid = sum(unit * q for unit, q in cheapest)
                cost += paid
                gold += paid
                bought[key] = cheapest
                buys.append(ReagentBuy(key, n - take, max(unit for unit, _ in cheapest)))
        takes[key] = (take, n - take)
    if not gold:
        return None
    value, selling = outlet.value(plan.recipe.quantity_min)
    return _CraftBuy(plan, gold, value - cost, takes, bought, tuple(buys), selling)


def _cheapest(asks: Supply, n: int) -> Supply | None:
    """The cheapest `n` units of sorted (unit buyout, quantity) asks; None if too few."""
    taken = []
    for unit, quantity in asks:
        if not n:
            break
        take = min(n, quantity)
        taken.append((unit, take))
        n -= take
    return None if n else taken


def _unbound(h: Holding) -> int:
    return h.bags + h.bank


def _crafted(plan: _Plan, holding: Holding) -> Holding:
    """`holding` with one more craft's output added, at the recipe's least quantity."""
    q = plan.recipe.quantity_min
    if plan.recipe.bind_type in _BOUND_ON_CRAFT:
        return replace(holding, bags_bound=holding.bags_bound + q)
    return replace(holding, bags=holding.bags + q)


def _units(h: Holding) -> int:
    return h.bags + h.bags_bound + h.bank + h.bank_bound


def _plus(a: Holding, b: Holding) -> Holding:
    return Holding(
        a.bags + b.bags, a.bags_bound + b.bags_bound, a.bank + b.bank, a.bank_bound + b.bank_bound
    )


def _take(h: Holding, n: int) -> Holding:
    """`h` less `n` units, bound ones first: they'd only ever be Vendored."""
    left = {}
    for place in ("bags_bound", "bank_bound", "bags", "bank"):
        taken = min(n, getattr(h, place))
        left[place] = getattr(h, place) - taken
        n -= taken
    return Holding(**left)


def _with_note(row: Row, note: str) -> Row:
    if not note:
        return row
    return replace(row, note=f"{row.note}, {note}" if row.note else note)


class _Caps:
    """The gold still allowed under each Prediction and under all of them together, as
    shares of the Market's pooled gold (ADR-0006), halved while the brake is on."""

    def __init__(self, gold: int, config: Config, brake: bool = False):
        share = 0.5 if brake else 1.0
        self._each = gold * config.prediction_cap_share * share
        self._total_left = gold * config.predictions_cap_share * share
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
    lot_costs: dict[tuple[str, str], list[tuple[float, int]]],
) -> list[Row]:
    """`rows` with the units of each Prediction's Item Keys switched to Hold under it, as
    many as its caps allow.

    Held units tie up what they cost: the open units of the Prediction's Lots what their
    Lot cost (ADR-0007), and any beyond those what letting them go would bring today. The
    cheapest are Held first. Units without enough data to choose an exit count at the
    Vendor Price, the least they'd bring, or nothing without one. Bound units can't be
    sold after the Catalyst either, and are never Held.
    """
    taken: Counter[int] = Counter()  # units Held, by index into rows
    holds = []
    for p in predictions:
        units = []  # (gold per unit, index into rows, units that could be Held)
        for item_key in p.item_keys:
            today = []
            for i, r in enumerate(rows):
                if r.item_key == item_key:
                    n = r.quantity - (bound.get(item_key, 0) if r.action is Action.VENDOR else 0)
                    if r.profit is not None:
                        value = r.profit / r.quantity
                    else:
                        value = vendor.get(_item_id(item_key), 0)
                    today.append((value, i, n))
            units += _costed(sorted(today), lot_costs.get((p.name, item_key), []))
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
    # A row is dropped once Held empties it; a blocked Craft's row has no units to start with.
    rest = [
        _fewer(r, r.quantity - taken[i])
        for i, r in enumerate(rows)
        if not taken[i] or r.quantity > taken[i]
    ]
    return rest + holds


def _costed(
    today: list[tuple[float, int, int]], lot_costs: list[tuple[float, int]]
) -> list[tuple[float, int, int]]:
    """Today's (gold per unit, index into rows, units) with as many units as the open
    Lots cover costed at their Lot's cost per unit instead, oldest Lot first."""
    lots_left = list(lot_costs)
    result = []
    for value, i, n in today:
        while n and lots_left:
            cost, open_units = lots_left[0]
            covered = min(n, open_units)
            result.append((cost, i, covered))
            n -= covered
            if covered == open_units:
                lots_left.pop(0)
            else:
                lots_left[0] = (cost, open_units - covered)
        if n:
            result.append((value, i, n))
    return result


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

    Buy to Sell takes no more than sells within the Sale Horizon, and posts just under
    the cheapest other player's Listing left once they're bought (`_post_at`), so they
    sell first. A cheap Listing that would undercut the resale is worth buying through,
    so every run of the cheapest offers is tried, and the one with the most profit whose
    every unit clears the Flip margin is bought (#62). The resale is never above the
    dearest Sale Event behind the Sell Rate, so a lone ask far above every sale isn't
    taken at its word (#41). Nothing is bought to Sell unless the Sell Rate rests on the
    minimum of Sale Events for a Flip (#57). Anything else under the Vendor Price is
    bought to Vendor.
    """
    offers = sorted(offers)
    to_sell: Supply = []
    best_profit = 0.0
    prefix: Supply = []
    room = _flip_room(rate, config)
    for unit, quantity in offers:
        take = min(quantity, room)
        if not take:
            break
        prefix = [*prefix, (unit, take)]
        room -= take
        resale = _resale(supply, offers, prefix, cut, config, rate.max_sale_price)
        # Offers are cheapest first, so if the dearest unit clears the margin, all do.
        if resale is None or resale - unit < max(
            unit * config.flip_min_margin_share, config.flip_min_margin_copper
        ):
            continue
        if vendor_price is not None and resale <= vendor_price:
            continue  # a vendor pays more, so it's a Flip to Vendor
        profit = sum((resale - u) * n for u, n in prefix)
        if profit > best_profit:
            to_sell, best_profit = prefix, profit
    buys = []
    if to_sell:
        post_at = _post_at(supply, offers, to_sell, config, rate.max_sale_price)
        resale = post_at * (1 - cut)
        buys = [
            _Buy(item_key, Action.SELL, unit, quantity, resale - unit, rate.sale_events, post_at)
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
    room = max(0, _flip_room(rate, config) - held)
    bought: Supply = []
    buys = []
    for unit, quantity in sorted(offers):
        take = min(quantity, room)
        resale = _resale(supply, offers, [*bought, (unit, take)], cut, config) if take else None
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


def _flip_room(rate: SellRate | None, config: Config) -> int:
    """Units bought to resell that should sell within the Sale Horizon, judged under the
    Flip priors. None unless the Sell Rate rests on the minimum of Sale Events for a
    Flip: one or two Disappearances can be one seller cancelling (#57)."""
    if rate is None or rate.sale_events < config.flip_min_sale_events:
        return 0
    return sellable_units(
        rate,
        config.sell_rate_prior_hours_flips,
        config.sale_size_prior_events_flips,
        config.sale_horizon_seconds,
    )


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


def _resale(
    supply: Supply,
    others: Supply,
    bought: Supply,
    cut: float,
    config: Config,
    cap: int | None = None,
) -> float | None:
    """What one unit brings in after the cut, posted at `_post_at`."""
    value = _post_at(supply, others, bought, config, cap)
    return None if value is None else value * (1 - cut)


def _post_at(
    supply: Supply, others: Supply, bought: Supply, config: Config, cap: int | None = None
) -> float | None:
    """The price to post one unit at once `bought` is gone from other players' `others`
    (#62): just under the cheapest of them left, so it sells first, or `cap` if that's
    lower. The player's own Listings, the rest of `supply`, are matched rather than
    undercut. None if no Listing is left to price against."""
    left = _without(others, bought)
    own = _without(supply, others)
    prices = [left[0][0] - config.post_undercut_copper] if left else []
    prices += [own[0][0]] if own else []
    if not prices:
        return None
    value = min(prices)
    return value if cap is None else min(value, cap)


def _without(supply: Supply, bought: Supply) -> Supply:
    left = Counter()
    for unit, quantity in supply:
        left[unit] += quantity
    for unit, quantity in bought:
        left[unit] -= quantity
    return [(unit, quantity) for unit, quantity in sorted(left.items()) if quantity > 0]


def _shopping_list(buys: list[_Buy], crafts: list[_CraftBuy], gold: float) -> list[Row]:
    """The buys and Flips to Craft that fit in `gold`, most profit per gold spent first,
    as one row per Item Key and Action, or per recipe, in that order.

    A Flip to Sell cut short by gold keeps the resale worked out for all of it, which is
    a little high: some of the cheap units it expected gone are still on sale. Likewise a
    Flip to Craft left out leaves the asks it would have bought idle. Once one is left
    out, so are the later crafts of its recipe, which were costed after it.
    """
    rows: dict[object, Row] = {}
    plans: dict[int, _Plan] = {}  # the Flips to Craft taken of each recipe
    cut: set[int] = set()
    for buy in sorted([*buys, *crafts], key=lambda buy: -buy.per_gold):
        if isinstance(buy, _CraftBuy):
            recipe_id = buy.plan.recipe.recipe_id
            if recipe_id in cut or buy.gold > gold:
                cut.add(recipe_id)
                continue
            gold -= buy.gold
            plan = plans.setdefault(recipe_id, _Plan(buy.plan.recipe, buy.plan.character))
            plan.crafts += 1
            plan.gain += buy.profit
            for key, (take, bought) in buy.takes.items():
                plan.used[key] += take + bought
                plan.bought[key] += bought
            r = rows.get(recipe_id, replace(plan.row(), cost=0))
            rows[recipe_id] = replace(
                plan.row(), cost=r.cost + buy.gold, buys=_merged(r.buys, buy.buys)
            )
            continue
        quantity = min(buy.quantity, int(gold // buy.unit_buyout))
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
                post_at=buy.post_at,
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


def _merged(a: tuple[ReagentBuy, ...], b: tuple[ReagentBuy, ...]) -> tuple[ReagentBuy, ...]:
    """Two crafts' reagent buys as one per reagent and place to buy it."""
    merged: dict[tuple[str, bool], ReagentBuy] = {}
    for buy in (*a, *b):
        key = (buy.item_key, buy.merchant)
        m = merged.get(key)
        merged[key] = (
            buy
            if m is None
            else replace(
                m,
                quantity=m.quantity + buy.quantity,
                max_unit_price=max(m.max_unit_price, buy.max_unit_price),
            )
        )
    return tuple(merged.values())


def _item_id(item_key: str) -> int:
    """The itemID of a stored Item Key ("itemID" or "itemID:bonus1:..."): Vendor Price
    belongs to it, not to the random suffix."""
    return int(item_key.split(":", 1)[0])
