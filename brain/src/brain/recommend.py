"""The Decision Engine: Vendor vs Sell for Holdings, and Flips (#23), and Hold under a
Prediction, both for Holdings and for buying (#26, ADR-0006).

Each Market the player has Characters in is valued as of its latest Scan: every Sell
posted just under the Listings left in that Scan once its Flips are bought (#62, #64),
and Sell Rate from the Observation Windows before it. All amounts are copper.
"""

import math
import sqlite3
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from enum import StrEnum
from functools import cache, cached_property
from itertools import groupby
from types import MappingProxyType

from brain.config import Config
from brain.disenchant import DisenchantTable, Group, ItemInfo, load_table
from brain.fair_value import Supply, fair_value
from brain.grades_file import Grade, freeze_grade, freeze_held, load_frozen
from brain.history import (
    Holding,
    KnownRecipe,
    Market,
    character_markets,
    cheapest_seen,
    enchanting_skills,
    holdings,
    item_info,
    known_recipes,
    listings,
    market_budget,
    merchant_costs,
    outcomes,
    pooled_gold,
    purchases,
    scan_times,
    supply_at,
    vendor_prices,
)
from brain.lots import Held, Lot, deposits, ended_at, link_sales, lots, settle, start_of
from brain.mailbox import MailKind
from brain.predictions import Prediction
from brain.sell_rate import SellRate, non_stacking, observation_window_hours, sell_rates


class Action(StrEnum):
    VENDOR = "Vendor"
    SELL = "Sell"
    # From held reagents (ADR-0008), or on the Shopping List a Flip to Craft that buys the
    # missing ones (ADR-0009). A short reagent can be Sub-crafted first (ADR-0014).
    CRAFT = "Craft"
    # A held unit into its expected mats, by a Character with the Enchanting skill (#76).
    DISENCHANT = "Disenchant"
    HOLD = "Hold"  # only ever under a Prediction (ADR-0006)


@dataclass(frozen=True)
class MatYield:
    """A Disenchant row's expected `quantity` of one mat (ADR-0018)."""

    item_key: str
    quantity: float


@dataclass(frozen=True)
class ReagentBuy:
    """A Flip to Craft's buys of one reagent: on the Auction House at up to
    `max_unit_price` each, or from a merchant at its Merchant Cost."""

    item_key: str
    quantity: int
    max_unit_price: float
    merchant: bool = False


@dataclass(frozen=True)
class ReagentUse:
    """A Craft's use of `quantity` held units of one reagent."""

    item_key: str
    quantity: int


@dataclass(frozen=True)
class SubCraft:
    """A Sub-craft (#33, ADR-0014): `crafts` crafts on `character` of the Known Recipe that
    makes `item_key`, a reagent short further up a Craft's chain."""

    item_key: str
    crafts: int
    character: str


@dataclass(frozen=True)
class CraftOutput:
    """What a Flip to Craft makes: `units` of its output, `selling` of them to post at
    `post_at` and the rest to Vendor. The replay grades it by that (#80)."""

    units: int
    selling: int
    post_at: float | None


class BlockReason(StrEnum):
    NO_DATA = "noData"  # a reagent with no market data, Merchant Cost or Sub-craft
    UNKNOWN_BIND_TYPE = "unknownBindType"  # the output's, so whether it can be sold


@dataclass(frozen=True)
class Blocked:
    """Why a recipe can't be valued (#75). The Addon names `item_key`, a NO_DATA reagent."""

    reason: BlockReason
    item_key: str = ""

    def __str__(self) -> str:
        if self.reason is BlockReason.NO_DATA:
            return f"no data for {self.item_key}"
        return "unknown bind type"


@dataclass(frozen=True)
class Row:
    """One line of the table: what to do with `quantity` units of an Item Key."""

    item_key: str
    action: Action | None  # None when there isn't enough data to choose one
    quantity: int
    # Per unit: the price to post at for a Sell or the Vendor Price for Holdings (#64), and
    # the most to pay for the Shopping List.
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
    # A Craft's Character, the one that knows the recipe, or a Disenchant's, the one with
    # the Enchanting skill.
    character: str = ""
    mats: tuple[MatYield, ...] = ()  # a Disenchant's expected mats
    uses: tuple[ReagentUse, ...] = ()  # a Craft's held reagents, not the ones it buys
    blocked: Blocked | None = None  # why a Craft can't be made, for the Addon to name
    via: tuple[SubCraft, ...] = ()  # a Craft's Sub-crafts, deepest first (#33)
    # A Craft Action's gold spent at merchants, and a Flip to Craft's output, for the
    # replay (#80). Plumbing, not part of the Recommendation: not written to
    # Recommendations.lua, nor compared.
    merchant_gold: float = field(default=0.0, compare=False)
    made: CraftOutput | None = field(default=None, compare=False)
    # A Sell or Vendor row's Paid (#50): per unit, what the Item Key's held units its open
    # Purchase Lots cover cost, and how many units that is. Split rows share it.
    paid: float | None = None
    paid_units: int | None = None
    # (exit per unit after the cut - Paid) / Paid, and whether it's a Sell good enough to
    # hint at (`roi_hint`). Only a hint: the Action stands either way (ADR-0003).
    roi: float | None = None
    roi_hint: bool = False
    # A Flip to Sell's or Flip to Vendor's clicks and wait (#98): the Listings it buys,
    # the stacks it posts, and the days until its last unit sells (None for a Flip to
    # Vendor, which sells now). Not compared, so rows are checked on them apart.
    listings: int | None = field(default=None, compare=False)
    posts: int | None = field(default=None, compare=False)
    days: float | None = field(default=None, compare=False)


@dataclass(frozen=True)
class _VendorBuy:
    """Units of one Listing worth buying to Vendor. Each pays on its own."""

    item_key: str
    unit_buyout: int
    quantity: int
    unit_profit: float

    @property
    def per_gold(self) -> float:
        return self.unit_profit / self.unit_buyout


@dataclass(frozen=True)
class _SellRun:
    """A run of the cheapest Listings of an Item Key bought to Sell, posted at `post_at`
    once they're gone, whose every unit clears the Flip margin."""

    units: Supply
    post_at: float
    profit: float
    days: float  # until its last unit sells, behind the held units (#98)

    @property
    def cost(self) -> int:
        return sum(unit * quantity for unit, quantity in self.units)

    @property
    def quantity(self) -> int:
        return sum(quantity for _, quantity in self.units)

    @property
    def dearest(self) -> int:
        """The highest unit buyout paid, the run's last Listing."""
        return self.units[-1][0]

    @property
    def listings(self) -> int:
        """The Listings bought: `units` has one entry per Listing (#98)."""
        return len(self.units)


@dataclass(frozen=True)
class _FlipToSell:
    """An Item Key's Flip to Sell: every run of its cheapest Listings that clears the
    Flip margin, cheapest first. It's bought whole or as the best run that fits, never
    split into units, since a unit's profit rests on the rest of its run (ADR-0011)."""

    item_key: str
    runs: tuple[_SellRun, ...]
    sale_events: int
    stack: float  # the units posted per stack: the usual Sale Event size (#98)

    @property
    def whole(self) -> _SellRun:
        """The run that makes the most profit, the one bought when gold is no object."""
        return max(self.runs, key=lambda run: run.profit)

    @property
    def per_gold(self) -> float:
        return self.whole.profit / self.whole.cost

    def fitting(self, gold: float) -> _SellRun | None:
        """The run that makes the most profit on no more than `gold`, if any."""
        runs = [run for run in self.runs if run.cost <= gold]
        return max(runs, key=lambda run: run.profit) if runs else None


@dataclass(frozen=True)
class _HoldBuy:
    """Units of one Listing worth buying to Hold under a Prediction."""

    item_key: str
    prediction: str
    unit_buyout: int
    quantity: int
    unit_max_loss: float


@dataclass(frozen=True)
class _Queue:
    """The order an Item Key's posted units sell in (#78, ADR-0013): unbound held units
    first, then Flips to Sell, then Flip to Craft outputs. Unit i waits i / units_per_hour
    and loses a `deposit` for every posting that expires first."""

    units_per_hour: float
    deposit: float  # per unit per posting
    post_hours: float

    def lost(self, i: int) -> float:
        """The deposits unit i of the queue (0-based) is expected to lose."""
        if not self.deposit or not self.units_per_hour:
            return 0.0
        # A hair over, so a unit exactly on an expiry isn't rounded down to before it.
        return math.floor(i / self.units_per_hour / self.post_hours + 1e-9) * self.deposit

    def lost_by(self, start: int, units: int) -> float:
        """The deposits units `start` up to `start + units` are expected to lose in all."""
        return sum(self.lost(i) for i in range(start, start + units))


@dataclass(frozen=True)
class CharacterHolding:
    """How many units of an Item Key one Character holds. `bound` is the part of
    `bags` and `bank` that can't be mailed or sold."""

    character: str
    bags: int = 0
    bank: int = 0
    bound: int = 0


@dataclass(frozen=True)
class BuyUnder:
    """The most one unit of an Item Key is worth paying on the Auction House, from its best
    way out less the Flip margin (#88). It isn't an Action: the Addon only flags Listings
    at or under it, and the player buys (ADR-0003). A Disenchant source group's has no
    Item Key but the `group`: the most any item in it is worth paying to Disenchant.

    `units` is how many units it's good for, None for no limit. `seen` is how many
    distinct Scans in the last `window_days` saw another player's Listing at or under it,
    and `listed_now` whether the latest one did. A Craft way names its recipe, output and
    crafter, a Disenchant way its disenchanter and the expected mats of one Disenchant."""

    item_key: str | None
    price: int
    way: Action
    units: int | None
    seen: int
    window_days: int
    listed_now: bool = False
    recipe_id: int | None = None
    output: str | None = None
    crafter: str | None = None
    disenchanter: str | None = None
    mats: tuple[MatYield, ...] = ()
    group: Group | None = None


@dataclass(frozen=True)
class MarketRecommendations:
    market: Market
    as_of: int  # requested_at of the Scan it was valued at
    gold: int  # the Market's pooled gold
    # The most the player will spend, set in game (#86); None for all the gold. Each
    # Shopping List option and the Prediction buys spend up to the lesser of the two.
    budget: int | None = None
    # Observation Window hours in the Sell Rate range: how much watching every Sell Rate
    # in the Market rests on, shown instead of a per-row "thin" flag (#25).
    window_hours: float = 0.0
    holdings: list[Row] = field(default_factory=list)
    # Options, each sized as if it were the only buy, most profit first (#86).
    shopping_list: list[Row] = field(default_factory=list)
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
    # Where the held units are, by Item Key: the raw Holdings before any craft uses them.
    # Recommendations pool the Characters; this only says whose they are (#38).
    held: dict[str, list[CharacterHolding]] = field(default_factory=dict)
    # Buy Unders, most profit per unit at the Buy Under first (#88). No Budget applies.
    buy_under: list[BuyUnder] = field(default_factory=list)

    @property
    def spend(self) -> int:
        """What each Shopping List option, and the Prediction buys, may spend (#86)."""
        return _spend(self.gold, self.budget)


def _spend(gold: int, budget: int | None) -> int:
    return gold if budget is None else min(gold, budget)


def recommend(
    conn: sqlite3.Connection, config: Config, predictions: Sequence[Prediction] = ()
) -> list[MarketRecommendations]:
    """Recommendations for every Market the player has Characters in."""
    result = []
    for market in character_markets(conn):
        times = scan_times(conn, market)
        if times:
            result.append(recommend_market(conn, config, market, predictions, times[-1]))
    return result


def recommend_market(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    predictions: Sequence[Prediction],
    now: int,
    as_of: int | None = None,
    buy_under: bool = True,
) -> MarketRecommendations:
    """The Market's Recommendations as of its Scan requested at `now`. The Holdings and
    gold are the latest, or as of `as_of` (a replay, #80). Without `buy_under`, the Buy
    Unders are left out: a replay doesn't grade them (#88)."""
    characters = character_markets(conn).get(market, [])
    today = date.fromtimestamp(now)
    active = [p for p in predictions if p.active_on(today)]
    under = {k: p.name for p in active for k in p.item_keys}
    by_character = _by_character(conn, market, characters, as_of)
    holdings = _pooled(by_character)
    # Holdings and Craft Actions are valued with nothing on the Shopping List bought: its
    # options are alternatives, so none is assumed (#86).
    valuer, _ = _valuer(conn, config, market, now, set(under), _unbound_units(holdings))
    supply, for_sale, rates = valuer.supply, valuer.others, valuer.rates
    vendor, merchant, cut = valuer.vendor, valuer.merchant, valuer.cut
    plans = _plans(known_recipes(conn, market), now)
    crafting = _crafts(holdings, plans, merchant, valuer, set(under), config)
    held = crafting.after
    # The crafts change what's held, so the Flips are sized again after them (#67).
    valuer, buys = valuer.flips(set(under), _unbound_units(held))
    gold = pooled_gold(conn, market.era, market.realm, market.faction, as_of)
    budget = market_budget(conn, market.era, market.realm, market.faction, as_of)
    spend = _spend(gold, budget)
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
            vendor.get(item_id_of(item_key)),
            merchant.get(item_key),
            _unbound(held.get(item_key, Holding())),
            valuer.queue(item_key, flips=True),
            cut,
            config,
        )
    ]

    def outlet(plan: _Plan) -> _Outlet:
        return _outlet(
            plan.recipe.bind_type in BOUND_ON_CRAFT,
            supply.get(plan.output, []),
            for_sale.get(plan.output, []),
            rates.get(plan.output),
            vendor.get(item_id_of(plan.output)),
            merchant.get(plan.output),
            _unbound(held.get(plan.output, Holding())),
            valuer.effort(plan.output),
            valuer.queue(plan.output, flips=True),
            cut,
            config,
        )

    crafts = (
        [
            _flips_to_craft(
                plans, crafting, for_sale, merchant, valuer, outlet, set(under), spend, config, plan
            )
            for plan in plans
        ]
        if config.flips_to_craft
        else []
    )
    shopping = _options(buys, crafts, spend, config.shopping_list_rows, config.craft_list_rows)
    crafted = crafting.counts
    disenchanted, left = _disenchants(held, valuer, set(under))
    rows = (
        [
            _with_note(row, f"incl. {crafted[item_key]} crafted" if crafted[item_key] else "")
            for item_key, holding in left.items()
            for row in valuer.rows(item_key, holding)
        ]
        + disenchanted
        + crafting.rows
    )
    graded = grades(conn, config, market, predictions, now)
    pooled = pooled_return(graded)
    caps = _Caps(gold, config, brake=pooled is not None and pooled < 0)
    bound = {k: h.bags_bound + h.bank_bound for k, h in held.items()}
    rows = _hold(rows, active, bound, vendor, caps, _lot_costs(conn, config, market, active))
    rows = _with_roi(rows, _market_lots(conn, config, market, predictions), cut, config)
    # Most expected profit first; rows without a number to rank by go last.
    rows.sort(key=lambda r: (r.profit is None, -(r.profit or 0)))
    prediction_buys = _spend_on_predictions(hold_buys, spend, caps)
    linked = link_sales(outcomes(conn, market), listings(conn, market), purchases(conn, market))
    return MarketRecommendations(
        market,
        now,
        gold,
        budget=budget,
        window_hours=observation_window_hours(conn, market, config, now),
        holdings=rows,
        shopping_list=shopping,
        prediction_buys=prediction_buys,
        prediction_cost=sum(r.cost for r in prediction_buys),
        unlinked_sales=sum(o.kind is MailKind.SOLD and o.item_key is None for o in linked),
        grades=graded,
        pooled_return=pooled,
        held=_whose(by_character),
        buy_under=_buy_unders(conn, config, market, now, valuer, plans) if buy_under else [],
    )


@dataclass(frozen=True)
class _WayOut:
    """An Item Key's best way out for one unit bought (#88): what it brings before the
    Flip margin (`way_out_value`), and how many units it's good for (None: no limit)."""

    value: float
    way: Action
    units: int | None
    plan: "_Plan | None" = None  # a Craft way's
    disenchanter: str | None = None  # a Disenchant way's, with the expected mats of one
    mats: tuple[MatYield, ...] = ()


def _buy_unders(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    now: int,
    valuer: "_Valuer",
    plans: list["_Plan"],
) -> list[BuyUnder]:
    """The Buy Unders as of the Scan requested at `now` (#88): every Item Key whose best
    way out leaves a price that enough distinct Scans in the window saw another player's
    Listing at or under. The Holdings don't move them: a Craft way's other reagents come
    from their cheapest current source (ADR-0014's, with nothing held)."""
    window = config.buy_under_window_days
    sources = _Sources(
        held={},
        crafted={},
        asks=valuer.others,
        merchant=valuer.merchant,
        valuer=valuer,
        under=set(),
        plans=plans,
        spent=Counter(),
        config=config,
    )
    result: list[tuple[float, BuyUnder]] = []

    def add(
        item_key: str | None,
        group: Group | None,
        out: _WayOut | None,
        effort: int,
        cheapest: dict[int, int],
    ) -> None:
        if out is None:
            return
        net = out.value - effort
        price = _under_margin(net, config)
        seen = sum(unit <= price for unit in cheapest.values())
        if price <= 0 or seen < config.buy_under_min_sightings:
            return
        listed_now = cheapest.get(now, price + 1) <= price
        plan = out.plan
        buy = BuyUnder(
            item_key,
            price,
            out.way,
            out.units,
            seen,
            window,
            listed_now,
            plan.recipe.recipe_id if plan else None,
            plan.output if plan else None,
            plan.character if plan else None,
            out.disenchanter,
            out.mats,
            group,
        )
        result.append((net - price, buy))

    seen_by_key = cheapest_seen(conn, market, now - window * 86400, now)
    for item_key, cheapest in seen_by_key.items():
        add(
            item_key,
            None,
            _way_out(item_key, valuer, config, sources),
            valuer.effort(item_key),
            cheapest,
        )
    disenchanting = valuer.disenchanting
    for group, cheapest in _cheapest_by_group(seen_by_key, disenchanting).items():
        disenchanter = disenchanting.disenchanter(group) if disenchanting else None
        if disenchanter is None:
            continue
        expected = {str(mat): qty for mat, qty in group.expected.items()}
        # Armor and weapons don't stack, so buying one always costs the effort (#73).
        effort = config.non_stacking_effort_copper
        add(None, group, _disenchant_way(disenchanter, expected, sources, config), effort, cheapest)
    result.sort(key=lambda pair: -pair[0])
    return [buy for _, buy in result]


def _cheapest_by_group(
    seen_by_key: Mapping[str, Mapping[int, int]], disenchanting: "_Disenchanting | None"
) -> dict[Group, dict[int, int]]:
    """`cheapest_seen` by Disenchant source group: per Scan, the cheapest unit buyout of
    any item in the group that can be Disenchanted."""
    result: dict[Group, dict[int, int]] = {}
    for item_key, cheapest in seen_by_key.items():
        group = disenchanting.group(item_key) if disenchanting else None
        if group is None:
            continue
        by_scan = result.setdefault(group, {})
        for at, unit in cheapest.items():
            by_scan[at] = min(unit, by_scan.get(at, unit))
    return result


def _way_out(
    item_key: str, valuer: "_Valuer", config: Config, sources: "_Sources | None" = None
) -> _WayOut | None:
    """The best of an Item Key's ways out for one more unit, or None without any: Vendor,
    Sell, or with `sources` a Craft it's a reagent of or Disenchant. A way with no units
    left isn't one."""
    ways = [_sell_way(item_key, valuer, config)]
    vendor = valuer.vendor.get(item_id_of(item_key))
    if vendor is not None:
        ways.append(_WayOut(vendor, Action.VENDOR, None))
    if sources is not None:
        ways += [_craft_way(item_key, plan, sources, config) for plan in sources.uses(item_key)]
        disenchant = valuer.disenchanting and valuer.disenchanting.way(item_key)
        if disenchant:
            ways.append(_disenchant_way(*disenchant, sources, config))
    return max((w for w in ways if w is not None), key=lambda w: w.value, default=None)


def _disenchant_way(
    disenchanter: str, expected: Mapping[str, float], sources: "_Sources", config: Config
) -> _WayOut | None:
    """One unit Disenchanted: its expected mats, each at its own way out (a Craft way
    included, never another Buy Under, so the margin is charged once). It's good for no
    limit when every mat's way out is, else for as many Disenchants as the most limited
    mat has room for. A mat with no way out adds nothing, but is still an expected mat."""
    value, units = 0.0, None
    for mat, qty in expected.items():
        out = _way_out(mat, sources.valuer, config, sources)
        if out is None:
            continue
        value += qty * out.value
        if out.units is not None:
            room = math.floor(out.units / qty)
            units = room if units is None else min(units, room)
    if units == 0:
        return None
    mats = tuple(MatYield(mat, qty) for mat, qty in expected.items())
    return _WayOut(value, Action.DISENCHANT, units, None, disenchanter, mats)


def _craft_way(item_key: str, plan: "_Plan", sources: "_Sources", config: Config) -> _WayOut | None:
    """One unit of a reagent of `plan`: its share of the output's way out (Sell or Vendor
    only, never crafted further, ADR-0014), after the other reagents' cheapest current
    source and the effort of buying them. None if the others can't be sourced."""
    chain = sources.chain_without(plan, item_key)
    if chain is None:
        return None
    needs, made = plan.needs, plan.recipe.quantity_min
    # One whose bind type is unknown counts as bound: it may not sell.
    bound = plan.recipe.bind_type is None or plan.recipe.bind_type in BOUND_ON_CRAFT
    out = _way_out(plan.output, sources.valuer, config) if not bound else None
    vendor = sources.valuer.vendor.get(item_id_of(plan.output))
    if bound and vendor is not None:
        out = _WayOut(vendor, Action.VENDOR, None)
    if out is None:
        return None
    value = (out.value * made - sources.cost(chain)) / needs[item_key]
    units = None if out.units is None else out.units // made * needs[item_key]
    return _WayOut(value, Action.CRAFT, units, plan) if units != 0 else None


def _sell_way(item_key: str, valuer: "_Valuer", config: Config) -> _WayOut | None:
    """One more unit posted as a Flip would post it (`_Valuer.post_at`), after the cut,
    the effort of posting it and the deposits it's expected to lose queued behind the
    unbound held units. It's good for what sells within the Sale Horizon after them."""
    held = valuer.held.get(item_key, 0)
    room = _flip_room(valuer.rates.get(item_key), config) - held
    post_at = valuer.post_at(item_key)
    if room <= 0 or post_at is None:
        return None
    lost, _ = valuer.flip_lost(item_key, 1)
    value = post_at * (1 - valuer.cut) - valuer.effort(item_key) - lost
    return _WayOut(value, Action.SELL, room)


def _under_margin(net: float, config: Config) -> int:
    """The price B that leaves the Flip margin out of `net`, floored to the copper:
    B + max(flip_min_margin_copper, flip_min_margin_share × B) = net."""
    share, floor = config.flip_min_margin_share, config.flip_min_margin_copper
    return math.floor(min(net / (1 + share), net - floor))


def held_at_writing(
    conn: sqlite3.Connection, config: Config, market: Market, predictions: Sequence[Prediction]
) -> list[Held]:
    """The units of each Prediction's Item Keys the Market's Characters held at the start
    of its written day, costed at what their best Action would have brought then, as of
    the latest Scan up to that moment (ADR-0007). Bound units are never Held.

    Once the Market has a Scan after its written day, a Prediction's are frozen in
    grades.toml and read from there from then on (#66)."""
    characters = character_markets(conn).get(market, [])
    frozen = load_frozen(config.grades_path, market).held
    times = scan_times(conn, market)
    result = []
    for p in predictions:
        if p.name in frozen:
            result += frozen[p.name]
            continue
        at = start_of(p.written)
        held = market_holdings(conn, market, characters, as_of=at)
        costed = []
        for item_key in p.item_keys:
            h = held.get(item_key)
            if h is None or not h.bags + h.bank:
                continue
            units = h.bags + h.bank
            cost = _exit_value(conn, config, market, item_key, units, at)
            costed.append(Held(p.name, item_key, units, round(cost)))
        day_passed = times and times[-1] >= start_of(p.written + timedelta(days=1))
        if config.grades_path is not None and day_passed:
            freeze_held(config.grades_path, market, p.name, costed)
        result += costed
    return result


def grades(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    predictions: Sequence[Prediction],
    now: int,
) -> list[Grade]:
    """The Grade of each Prediction a Sale Horizon has passed since it ended, by `now`.
    A Grade is frozen in grades.toml the first time the Market has a Scan at or after its
    grading moment, and read from there from then on (#66)."""
    due = [p for p in predictions if ended_at(p) + config.sale_horizon_seconds <= now]
    if not due:
        return []
    frozen = load_frozen(config.grades_path, market).grades
    if all(p.name in frozen for p in due):
        return [frozen[p.name] for p in due]
    market_lots = _market_lots(conn, config, market, predictions)
    times = scan_times(conn, market)
    result = []
    for p in due:
        if p.name in frozen:
            result.append(frozen[p.name])
            continue
        graded_at = ended_at(p) + config.sale_horizon_seconds
        settled = settle(p, market_lots, graded_at, auction_cut(market, config))
        open_value = sum(
            _exit_value(conn, config, market, item_key, units, graded_at)
            for item_key, units in settled.open_units.items()
            if units
        )
        grade = Grade(p.name, graded_at, settled.proceeds, open_value, settled.cost)
        # Once a Scan at or after its grading moment is in, what it rests on is too.
        if config.grades_path is not None and times and times[-1] >= graded_at:
            freeze_grade(config.grades_path, market, grade)
        result.append(grade)
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
    latest Scan up to `at`, with nothing on that Scan's Shopping List taken as bought
    (ADR-0017). Vendor Prices are the latest seen,
    since a vendor's price doesn't move, and so are Merchant Costs. Units without enough
    data to choose an exit count at the Vendor Price, as when Holding them (_hold)."""
    return exit_values(conn, config, market, {item_key: Holding(bags=units)}, at)[item_key]


def exit_values(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    held: Mapping[str, Holding],
    at: int,
) -> dict[str, float]:
    """What each Item Key's `held` units would have brought by their best Actions, as
    `_exit_value` values them, all at once."""
    scanned = [t for t in scan_times(conn, market) if t <= at]
    scan = scanned[-1] if scanned else None
    valuer, _ = _valuer(conn, config, market, scan, unbound=_unbound_units(dict(held)))
    return {item_key: valuer.best_exit(item_key, h) for item_key, h in held.items()}


def deposit_of(conn: sqlite3.Connection, config: Config, market: Market) -> Callable[[str], float]:
    """What posting one unit of an Item Key costs in the Market (`_Valuer.deposit`)."""
    return _valuer(conn, config, market, None)[0].deposit


def _valuer(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    at: int | None,
    under: set[str] = frozenset(),
    unbound: Mapping[str, int] = MappingProxyType({}),
) -> tuple["_Valuer", list[_VendorBuy | _FlipToSell]]:
    """The Market's Valuer as of its Scan requested at `at` (none without one), and the
    Flips in that Scan, none of them taken as bought (#86). Item Keys `under` a
    Prediction aren't Flipped. `unbound` is the player's unbound held units by Item Key,
    which take the Sale Horizon before any Flip to Sell (#67)."""
    scanned = at is not None
    supply = supply_at(conn, market, at) if scanned else {}
    others = supply_at(conn, market, at, others_only=True) if scanned else {}
    rates = sell_rates(conn, market, config, at) if scanned else {}
    vendor = vendor_prices(conn, market.era)
    merchant = _merchant(conn, market)
    cut = auction_cut(market, config)
    # Like Vendor Prices, the latest seen: a deposit rate doesn't move.
    linked = link_sales(outcomes(conn, market), listings(conn, market), purchases(conn, market))
    valuer = _Valuer(
        supply,
        others,
        {},
        rates,
        vendor,
        merchant,
        cut,
        non_stacking(conn, market),
        deposits(linked),
        config,
        disenchanting=_Disenchanting(
            _disenchant_table(), item_info(conn, market.era), enchanting_skills(conn, market)
        ),
    )
    return valuer.flips(under, unbound)


@cache
def _disenchant_table() -> DisenchantTable:
    return load_table()


@dataclass(frozen=True)
class _Disenchanting:
    """Who in a Market can Disenchant what (#76): an item's Disenchant source group from
    its Item Info, gated by the Characters' Enchanting skill like a Known Recipe."""

    table: DisenchantTable
    info: Mapping[int, ItemInfo]
    skills: Mapping[str, int]  # Enchanting skill by Character

    def group(self, item_key: str) -> Group | None:
        """The Item Key's Disenchant source group, or None if it can't be Disenchanted."""
        item_id = item_id_of(item_key)
        info = self.info.get(item_id)
        return self.table.group(item_id, info) if info else None

    def way(self, item_key: str) -> tuple[str, dict[str, float]] | None:
        """The Character to Disenchant an Item Key, and the expected mats of one
        Disenchant by Item Key, or None if nobody can."""
        info = self.info.get(item_id_of(item_key))
        group = self.group(item_key)
        need = self.table.required_skill(info.item_level) if group else None
        able = self._able(need)
        if not able:
            return None
        return able[0], {str(mat): q for mat, q in group.expected.items()}

    def disenchanter(self, group: Group) -> str | None:
        """The Character to Disenchant any item in the group: one whose skill meets what
        its highest item level needs. None if nobody can."""
        able = self._able(self.table.required_skill(group.max_level))
        return able[0] if able else None

    def _able(self, need: int | None) -> list[str]:
        return sorted(c for c, skill in self.skills.items() if need is not None and skill >= need)


class _Valuer:
    """A Market's Sell/Vendor split of held units, as of one Scan. `supply` is every unit
    on sale, `others` other players' Listings, and `flipped` the ones the Flips buy.
    `non_stacking` are the Item Keys that don't stack (#73)."""

    def __init__(
        self,
        supply: dict[str, Supply],
        others: dict[str, Supply],
        flipped: dict[str, Supply],
        rates: dict[str, SellRate],
        vendor: dict[int, int],
        merchant: dict[str, float],
        cut: float,
        non_stacking: frozenset[str],
        deposits: dict[str, float],
        config: Config,
        held: Mapping[str, int] = MappingProxyType({}),
        disenchanting: _Disenchanting | None = None,
    ):
        self.supply, self.others, self.flipped = supply, others, flipped
        self.rates, self.vendor, self.merchant = rates, vendor, merchant
        self.cut, self.non_stacking, self.deposits = cut, non_stacking, deposits
        self._config, self.held = config, held
        self.disenchanting = disenchanting
        self._worth: dict[tuple[str, Holding], float] = {}  # Sub-crafts ask it a lot (#33)

    def after(self, bought: dict[str, Supply], held: Mapping[str, int] | None = None) -> "_Valuer":
        """This Valuer with `bought` as the units taken off other players' Listings, and
        `held` as the unbound held units ahead of the Flips in the queue, if given."""
        return _Valuer(
            self.supply,
            self.others,
            bought,
            self.rates,
            self.vendor,
            self.merchant,
            self.cut,
            self.non_stacking,
            self.deposits,
            self._config,
            self.held if held is None else held,
            self.disenchanting,
        )

    def deposit(self, item_key: str) -> float:
        """What posting one unit of an Item Key costs (#78): as on its latest Sold invoice,
        else the config share of its Vendor Price, or nothing without one. Nothing when
        Deposits are switched off (a replay's ablation, #80)."""
        if not self._config.deposits:
            return 0.0
        if item_key in self.deposits:
            return self.deposits[item_key]
        return self._config.ah_deposit_share * self.vendor.get(item_id_of(item_key), 0)

    def queue(self, item_key: str, flips: bool) -> _Queue:
        """The Item Key's sale queue, at its Sell Rate under the Flip or Holdings priors."""
        c = self._config
        if flips:
            priors = (c.sell_rate_prior_hours_flips, c.sale_size_prior_events_flips)
        else:
            priors = (c.sell_rate_prior_hours_holdings, c.sale_size_prior_events_holdings)
        per_day = _units_per_day(self.rates.get(item_key), *priors)
        return _Queue(per_day / 24, self.deposit(item_key), c.post_duration_hours)

    def flip_lost(self, item_key: str, units: int) -> tuple[float, float]:
        """The deposits the last of `units` Flipped to Sell is expected to lose, and all of
        them, queued behind the unbound `held` units (#78)."""
        queue, held = self.queue(item_key, flips=True), self.held.get(item_key, 0)
        return queue.lost(held + units - 1), queue.lost_by(held, units)

    def effort(self, item_key: str) -> int:
        """What a Flip is charged for each unit of an Item Key it buys, and again for each
        it posts: nothing unless it doesn't stack (#73)."""
        return self._config.non_stacking_effort_copper if item_key in self.non_stacking else 0

    def flips(
        self, under: set[str], unbound: Mapping[str, int]
    ) -> tuple["_Valuer", list[_VendorBuy | _FlipToSell]]:
        """The Flips in this Scan, from Item Keys not `under` a Prediction, with the
        `unbound` held units taking the Sale Horizon, and the sale queue, first (#67, #78),
        and this Valuer with those held units ahead of them in the queue. Nothing is taken
        as bought: the Flips are Shopping List options (#86)."""
        buys = [
            buy
            for item_key, offers in sorted(self.others.items())
            if item_key not in under
            for buy in _flips(
                item_key,
                offers,
                self.supply[item_key],
                self.rates.get(item_key),
                self.vendor.get(item_id_of(item_key)),
                self.merchant.get(item_key),
                unbound.get(item_key, 0),
                self.queue(item_key, flips=True),
                self.effort(item_key),
                self.stack(item_key),
                self.cut,
                self._config,
            )
        ]
        return self.after({}, unbound), buys

    def stack(self, item_key: str) -> float:
        """The units of an Item Key a Flip posts per stack (#98): its usual Sale Event
        size under the Flip prior, or 1 if it doesn't stack."""
        if item_key in self.non_stacking:
            return 1.0
        return _sale_size(self.rates.get(item_key), self._config.sale_size_prior_events_flips)

    def post_at(self, item_key: str) -> float | None:
        """The price to post one unit at once `flipped` is bought (`_post_at`)."""
        rate = self.rates.get(item_key)
        return _post_at(
            self.supply.get(item_key, []),
            self.others.get(item_key, []),
            self.flipped.get(item_key, []),
            self._config,
            _ceiling(rate.max_sale_price if rate else None, self.merchant.get(item_key)),
        )

    def rows(self, item_key: str, holding: Holding) -> list[Row]:
        rate = self.rates.get(item_key)
        has_data = self.has_data(item_key)
        post_at = self.post_at(item_key) if has_data else None
        return _holding_rows(
            item_key,
            holding,
            has_data,
            post_at,
            rate,
            self.vendor.get(item_id_of(item_key)),
            self.queue(item_key, flips=False),
            self.cut,
            self._config,
        )

    def has_data(self, item_key: str) -> bool:
        """Whether there's a Fair Value and a Sell Rate with sales to value it by."""
        rate = self.rates.get(item_key)
        value = fair_value(self.supply.get(item_key, []), self._config)
        return value is not None and rate is not None and bool(rate.sale_events)

    def worth(self, item_key: str, holding: Holding) -> float:
        """What the units would bring by their best Actions. Units without enough data to
        choose an exit count at the Vendor Price, or nothing without one."""
        if (item_key, holding) not in self._worth:
            vendor = self.vendor.get(item_id_of(item_key), 0)
            self._worth[item_key, holding] = sum(
                r.profit if r.profit is not None else r.quantity * vendor
                for r in self.rows(item_key, holding)
            )
        return self._worth[item_key, holding]

    def best_exit(self, item_key: str, holding: Holding) -> float:
        """`worth`, with the Disenchant way too: Best Exit Value (#76)."""
        rows, left = _disenchants({item_key: holding}, self)
        return sum(r.profit for r in rows) + self.worth(item_key, left[item_key])

    def worth_with(self, item_key: str, holding: Holding, extra: float) -> float:
        """`worth` of `holding` plus `extra` unbound units, a fraction of a unit counting
        that fraction of the next whole unit's worth (expected Disenchant mats, #76)."""
        whole = math.floor(extra)
        below = self.worth(item_key, _plus(holding, Holding(bags=whole)))
        if extra == whole:
            return below
        above = self.worth(item_key, _plus(holding, Holding(bags=whole + 1)))
        return below + (extra - whole) * (above - below)


def _disenchants(
    held: Mapping[str, Holding], valuer: _Valuer, under: set[str] = frozenset()
) -> tuple[list[Row], dict[str, Holding]]:
    """The Disenchant Actions (#76) and what's left of `held` after them. Item Keys
    `under` a Prediction are Held instead.

    The same marginal rule as Craft (ADR-0008): each step Disenchants the one unit that
    gains the most, its expected mats' worth less what the unit would bring by Sell or
    Vendor, until no unit gains. A mat's worth is that of its Holdings with the expected
    mats added, on top of the ones earlier steps are expected to yield, a fraction of a unit
    counting that fraction of the next whole unit. Bound units go first, since they'd only
    be Vendored.
    """
    left = dict(held)
    ways = {
        key: way
        for key in held
        if key not in under
        and valuer.disenchanting
        and (way := valuer.disenchanting.way(key)) is not None
    }
    added: Counter[str] = Counter()  # expected mats from the steps so far, in fractions
    done: Counter[str] = Counter()
    proceeds: Counter[str] = Counter()
    while True:
        best = None
        for key, (_, mats) in ways.items():
            if not _units(left[key]):
                continue
            value = sum(
                valuer.worth_with(mat, held.get(mat, Holding()), added[mat] + q)
                - valuer.worth_with(mat, held.get(mat, Holding()), added[mat])
                for mat, q in mats.items()
            )
            gain = value - (valuer.worth(key, left[key]) - valuer.worth(key, _take(left[key], 1)))
            if gain > 0 and (best is None or gain > best[0]):
                best = (gain, key, value)
        if best is None:
            break
        _, key, value = best
        left[key] = _take(left[key], 1)
        added.update(ways[key][1])
        done[key] += 1
        proceeds[key] += value
    rows = [
        Row(
            key,
            Action.DISENCHANT,
            n,
            profit=proceeds[key],
            note=f"on {ways[key][0]}: expect "
            + ", ".join(f"{q * n:.2f} of {mat}" for mat, q in ways[key][1].items()),
            character=ways[key][0],
            mats=tuple(MatYield(mat, q * n) for mat, q in ways[key][1].items()),
        )
        for key, n in done.items()
    ]
    return rows, left


def _merchant(conn: sqlite3.Connection, market: Market) -> dict[str, float]:
    """The Market's Merchant Costs by Item Key."""
    return {str(item_id): cost for item_id, cost in merchant_costs(conn, market).items()}


def auction_cut(market: Market, config: Config) -> float:
    return config.neutral_ah_cut if market.faction == "Neutral" else config.ah_cut


def market_holdings(
    conn: sqlite3.Connection, market: Market, characters: list[str], as_of: int | None = None
) -> dict[str, Holding]:
    """What the Market's Characters hold between them, by Item Key. Mail moves items
    between them, so the Sale Horizon applies to the total."""
    return _pooled(_by_character(conn, market, characters, as_of))


def _by_character(
    conn: sqlite3.Connection, market: Market, characters: list[str], as_of: int | None
) -> dict[str, dict[str, Holding]]:
    """What each of the Market's Characters holds, by Character, then Item Key."""
    return {c: holdings(conn, market.era, market.realm, c, as_of) for c in characters}


def _pooled(by_character: dict[str, dict[str, Holding]]) -> dict[str, Holding]:
    total: dict[str, Holding] = {}
    for held in by_character.values():
        for item_key, h in held.items():
            t = total.get(item_key, Holding())
            total[item_key] = Holding(
                t.bags + h.bags,
                t.bags_bound + h.bags_bound,
                t.bank + h.bank,
                t.bank_bound + h.bank_bound,
            )
    return dict(sorted(total.items()))


def _whose(by_character: dict[str, dict[str, Holding]]) -> dict[str, list[CharacterHolding]]:
    """Which Characters hold each Item Key, and how many where, Characters by name."""
    whose: dict[str, list[CharacterHolding]] = {}
    for character, held in sorted(by_character.items()):
        for item_key, h in held.items():
            whose.setdefault(item_key, []).append(
                CharacterHolding(
                    character,
                    bags=h.bags + h.bags_bound,
                    bank=h.bank + h.bank_bound,
                    bound=h.bags_bound + h.bank_bound,
                )
            )
    return dict(sorted(whose.items()))


def _holding_rows(
    item_key: str,
    holding: Holding,
    has_data: bool,
    post_at: float | None,
    rate: SellRate | None,
    vendor_price: int | None,
    queue: _Queue,
    cut: float,
    config: Config,
) -> list[Row]:
    """How held units split between Sell, posted at `post_at` like a Flip (#64), and
    Vendor. With no Listing to price against there's no `post_at`, and they're Vendored.
    A held unit Sells only while it beats the Vendor Price less the deposits it's expected
    to lose waiting its turn in the `queue` (#78), so the tail of a slow seller is Vendored."""
    rows = []
    vendoring = holding.bags_bound + holding.bank_bound  # bound can't go on the AH
    unbound = holding.bags + holding.bank
    if unbound and not has_data:
        # No sale seen yet mostly means not watched long enough, not unsellable.
        rows.append(Row(item_key, None, unbound, note="no data"))
    elif unbound:
        sell_price = 0.0 if post_at is None else post_at * (1 - cut)
        sellable = min(
            unbound,
            sellable_units(
                rate,
                config.sell_rate_prior_hours_holdings,
                config.sale_size_prior_events_holdings,
                config.sale_horizon_seconds,
            ),
        )
        selling = 0
        if post_at is not None:
            while selling < sellable and sell_price - queue.lost(selling) > (vendor_price or 0):
                selling += 1
        if selling:
            profit = selling * sell_price - queue.lost_by(0, selling)
            rows.append(
                Row(
                    item_key,
                    Action.SELL,
                    selling,
                    price=post_at,
                    profit=profit,
                    margin=None if vendor_price is None else profit / selling - vendor_price,
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
BOUND_ON_CRAFT = {1, 4}


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
    gold: float = 0.0  # a Craft Action's, spent at merchants
    # Raw reagent units across the chain, bought ones included, and the ones bought.
    used: Counter[str] = field(default_factory=Counter)
    bought: Counter[str] = field(default_factory=Counter)
    # The Sub-crafts by (Item Key, Character), with the deepest each was made at.
    via: dict[tuple[str, str], SubCraft] = field(default_factory=dict)
    via_depth: Counter[tuple[str, str]] = field(default_factory=Counter)

    @property
    def output(self) -> str:
        return str(self.recipe.output_item_id)

    @property
    def needs(self) -> dict[str, int]:
        needs: Counter[str] = Counter()
        for reagent in self.recipe.reagents:
            needs[str(reagent.item_id)] += reagent.quantity
        return needs

    def add(self, chain: "_Chain") -> None:
        """Count one more craft's chain into the row."""
        for key in chain.taken:
            bought = chain.bought(key)
            if chain.taken[key] + bought:
                self.used[key] += chain.taken[key] + bought
                self.bought[key] += bought
        for depth, sub in chain.via:
            at = (sub.item_key, sub.character)
            had = self.via.get(at)
            self.via[at] = sub if had is None else replace(had, crafts=had.crafts + sub.crafts)
            self.via_depth[at] = max(self.via_depth[at], depth)

    def row(self) -> Row:
        uses = ", ".join(
            f"{n} of {key}" + (f" (buy {self.bought[key]})" if self.bought[key] else "")
            for key, n in self.used.items()
        )
        via = tuple(
            sorted(self.via.values(), key=lambda sub: -self.via_depth[sub.item_key, sub.character])
        )
        note = f"on {self.character}: uses {uses}"
        if via:
            note += ", via " + ", ".join(
                f"{sub.crafts} of {sub.item_key} on {sub.character}" for sub in via
            )
        return Row(
            self.output,
            Action.CRAFT,
            self.crafts,
            profit=self.gain,
            note=note,
            character=self.character,
            uses=tuple(
                ReagentUse(key, n - self.bought[key])
                for key, n in self.used.items()
                if n > self.bought[key]
            ),
            via=via,
            merchant_gold=self.gold,
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
    crafted: dict[str, Holding]  # the outputs made, and the Sub-crafts' leftovers
    spent: Counter[int]  # crafts per recipe, Sub-crafts included, for cooldown limits

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
    worth with its units added less what its chain costs (_Sources), until the best gain
    is no more than `craft_min_gain`. A short reagent can be Sub-crafted (ADR-0014), but
    outputs are valued by Sell and Vendor only.
    """
    held = dict(held)
    crafted: dict[str, Holding] = {}
    spent: Counter[int] = Counter()
    sources = _Sources(
        held=held,
        crafted=crafted,
        asks=None,
        merchant=merchant,
        valuer=valuer,
        under=under,
        plans=plans,
        spent=spent,
        config=config,
    )
    craftable, blocked = [], []
    for plan in plans:
        if plan.output in under:
            continue  # its Held units would include ones not made yet
        why_blocked = _blocked(plan, sources)
        reason = str(why_blocked) if why_blocked else None
        if reason is None and plan.until is not None:
            reason = f"on cooldown until {datetime.fromtimestamp(plan.until):%Y-%m-%d %H:%M}"
        if reason is None:
            craftable.append(plan)
        elif _on_hand(plan, held, merchant, under):
            # Only shown when the reagents are there, or every recipe would be.
            blocked.append(
                Row(
                    plan.output,
                    Action.CRAFT,
                    0,
                    note=f"on {plan.character}: {reason}",
                    character=plan.character,
                    blocked=why_blocked,
                )
            )
    while True:
        best = None
        for plan in craftable:
            if plan.limit is not None and spent[plan.recipe.recipe_id] >= plan.limit:
                continue
            step = _step(plan, sources)
            if step is not None and (best is None or step[0] > best[1][0]):
                best = (plan, step)
        if best is None or best[1][0] <= config.craft_min_gain:
            break
        plan, (gain, chain) = best
        plan.crafts += 1
        plan.gain += gain
        plan.gold += sources.gold(chain)
        plan.add(chain)
        sources.commit(plan, chain)
        crafted[plan.output] = _crafted(plan, crafted.get(plan.output, Holding()))
    rows = [p.row() for p in craftable if p.crafts]
    return _Crafting(rows + blocked, held, crafted, spent)


def _blocked(plan: _Plan, sources: "_Sources") -> Blocked | None:
    """Why the recipe can't be valued, if it can't. The guesses lean toward crafting less:
    a reagent with no market data would be undervalued at its Vendor Price, so it's only
    ever Sub-crafted, and blocks the recipe when no Known Recipe can make it for this one."""
    if plan.recipe.bind_type is None:
        return Blocked(BlockReason.UNKNOWN_BIND_TYPE)
    for key in plan.needs:
        if key in sources.merchant or sources.valuer.has_data(key):
            continue
        path = frozenset({plan.output})
        if not any(
            sources.may_use(maker, key, 1, 1, path) for maker in sources.makers.get(key, [])
        ):
            return Blocked(BlockReason.NO_DATA, key)
    return None


def _on_hand(
    plan: _Plan, held: dict[str, Holding], merchant: dict[str, float], under: set[str]
) -> bool:
    """Whether one craft's reagents are held, or sold by a merchant, some of them held."""
    held_any = False
    for key, n in plan.needs.items():
        units = 0 if key in under else _units(held.get(key, Holding()))
        if units < n and key not in merchant:
            return False
        held_any = held_any or units > 0
    return held_any


def _step(plan: _Plan, sources: "_Sources") -> tuple[float, "_Chain"] | None:
    """What one more craft gains, and its chain; None if its reagents can't be had."""
    chain = sources.chain(plan)
    if chain is None or not any(chain.taken.values()):
        # Crafts are from held reagents: with merchant ones alone the loop wouldn't end
        # whenever a vendor pays more for the output than the merchant charges.
        return None
    out, valuer = plan.output, sources.valuer
    now = _plus(sources.held.get(out, Holding()), sources.crafted.get(out, Holding()))
    gain = valuer.worth(out, _crafted(plan, now)) - valuer.worth(out, now)
    return gain - sources.cost(chain), chain


@dataclass
class _Chain:
    """One craft's reagents, sourced (ADR-0014), down through its Sub-crafts."""

    taken: Counter[str] = field(default_factory=Counter)  # held units used, by reagent
    merchant: Counter[str] = field(default_factory=Counter)  # units bought from a merchant
    asks: dict[str, Supply] = field(default_factory=dict)  # Auction House units bought
    via: list[tuple[int, SubCraft]] = field(default_factory=list)  # with how deep
    leftovers: dict[str, Holding] = field(default_factory=dict)
    recipes: Counter[int] = field(default_factory=Counter)  # Sub-crafts per recipe

    def copy(self) -> "_Chain":
        return _Chain(
            Counter(self.taken),
            Counter(self.merchant),
            {key: list(units) for key, units in self.asks.items()},
            list(self.via),
            dict(self.leftovers),
            Counter(self.recipes),
        )

    def bought(self, key: str) -> int:
        """The units of `key` bought, from a merchant or on the Auction House."""
        return self.merchant[key] + sum(n for _, n in self.asks.get(key, []))


@dataclass
class _Sources:
    """Where a craft's reagents come from (ADR-0014): held units first, then a merchant's
    at their Merchant Cost, then for each reagent still short one source, whichever costs
    less: a Sub-craft, whose own reagents are sourced the same way, or, when `asks` are
    given (a Flip to Craft), the cheapest Auction House asks. `held`, `crafted`, `asks`
    and `spent` are the live state of the greedy loop using it.

    A held reagent without market data isn't used, since it can't be valued, and neither
    is a crafted unit or one Held under a Prediction. A Sub-craft's recipe can't make or
    use an Item Key already on its path, and a chain is at most `craft_chain_depth` crafts
    deep. A Disenchant step would be one more source here (#76)."""

    held: dict[str, Holding]
    crafted: dict[str, Holding]
    asks: dict[str, Supply] | None
    merchant: dict[str, float]
    valuer: _Valuer
    under: set[str]
    plans: list[_Plan]
    spent: Counter[int]  # crafts per recipe so far, for cooldown limits
    config: Config

    @cached_property
    def makers(self) -> dict[str, list[_Plan]]:
        makers: dict[str, list[_Plan]] = {}
        for plan in self.plans:
            makers.setdefault(plan.output, []).append(plan)
        return makers

    @cached_property
    def _uses(self) -> dict[str, list[_Plan]]:
        uses: dict[str, list[_Plan]] = {}
        for plan in self.plans:
            for key in plan.needs:
                uses.setdefault(key, []).append(plan)
        return uses

    def uses(self, item_key: str) -> list[_Plan]:
        """The plans that take `item_key` as a reagent."""
        return self._uses.get(item_key, [])

    def chain(self, plan: _Plan) -> _Chain | None:
        """One craft of `plan` with its reagents sourced; None if they can't be."""
        return self._craft(plan, 1, 1, frozenset({plan.output}), _Chain())

    def chain_without(self, plan: _Plan, item_key: str) -> _Chain | None:
        """One craft of `plan` with every reagent but `item_key` sourced, and `item_key`
        never Sub-crafted on the way (a Buy Under's Craft way, #88); None if they can't
        be."""
        chain: _Chain | None = _Chain()
        path = frozenset({plan.output, item_key})
        for key, n in plan.needs.items():
            if key != item_key and chain is not None:
                chain = self._source(key, n, 1, path, chain)
        return chain

    def _craft(
        self, plan: _Plan, crafts: int, depth: int, path: frozenset[str], chain: _Chain
    ) -> _Chain | None:
        for key, n in plan.needs.items():
            chain = self._source(key, n * crafts, depth, path, chain)
            if chain is None:
                return None
        return chain

    def _source(
        self, key: str, n: int, depth: int, path: frozenset[str], chain: _Chain
    ) -> _Chain | None:
        chain = chain.copy()
        have = Holding() if key in self.under else self.held.get(key, Holding())
        left = _units(have) - chain.taken[key]
        if key in self.merchant:
            take = min(n, left)
            chain.taken[key] += take
            chain.merchant[key] += n - take
            return chain
        take = min(n, left) if self.valuer.has_data(key) else 0
        chain.taken[key] += take
        short = n - take
        if not short:
            return chain
        options = [self._bought(key, short, chain)] + [
            self._subcrafted(maker, key, short, depth, path, chain)
            for maker in self.makers.get(key, [])
        ]
        options = [option for option in options if option is not None]
        return min(options, key=self.cost) if options else None

    def _bought(self, key: str, short: int, chain: _Chain) -> _Chain | None:
        if self.asks is None or key in self.under:
            return None
        bought = cheapest(without(self.asks.get(key, []), chain.asks.get(key, [])), short)
        if bought is None:
            return None
        chain = chain.copy()
        chain.asks.setdefault(key, []).extend(bought)
        return chain

    def may_use(
        self, maker: _Plan, key: str, crafts: int, depth: int, path: frozenset[str], taken: int = 0
    ) -> bool:
        """Whether `crafts` Sub-crafts of `maker` may make `key` for a recipe `depth` deep,
        `path` being the Item Keys above it and `taken` the crafts the chain already
        takes of `maker` (the guards of ADR-0014)."""
        if depth >= self.config.craft_chain_depth or key in path or key in self.under:
            return False
        if any(k in path or k == key or k in self.under for k in maker.needs):
            return False
        spent = self.spent[maker.recipe.recipe_id] + taken
        return maker.limit is None or spent + crafts <= maker.limit

    def _subcrafted(
        self, maker: _Plan, key: str, short: int, depth: int, path: frozenset[str], chain: _Chain
    ) -> _Chain | None:
        crafts = math.ceil(short / maker.recipe.quantity_min)
        recipe_id = maker.recipe.recipe_id
        if not self.may_use(maker, key, crafts, depth, path, chain.recipes[recipe_id]):
            return None
        chain = self._craft(maker, crafts, depth + 1, path | {key}, chain)
        if chain is None:
            return None
        chain.recipes[recipe_id] += crafts
        chain.via.append((depth + 1, SubCraft(key, crafts, maker.character)))
        leftover = crafts * maker.recipe.quantity_min - short
        if leftover:
            # One whose bind type is unknown counts as bound: it may not sell.
            bound = maker.recipe.bind_type is None or maker.recipe.bind_type in BOUND_ON_CRAFT
            h = Holding(bags_bound=leftover) if bound else Holding(bags=leftover)
            chain.leftovers[key] = _plus(chain.leftovers.get(key, Holding()), h)
        return chain

    def gold(self, chain: _Chain) -> float:
        """What the chain spends at merchants and on the Auction House."""
        return sum(n * self.merchant[key] for key, n in chain.merchant.items()) + sum(
            unit * n for units in chain.asks.values() for unit, n in units
        )

    def cost(self, chain: _Chain) -> float:
        """What the chain costs: the gold it spends, the effort of buying each unit that
        doesn't stack (#73), a held merchant reagent at its Merchant Cost, and what the held
        units it uses would have brought, less what its leftovers bring."""
        cost = self.gold(chain)
        cost += sum(
            self.valuer.effort(key) * n for key, units in chain.asks.items() for _, n in units
        )
        for key in {*chain.taken, *chain.leftovers}:
            if key in self.merchant:
                cost += chain.taken[key] * self.merchant[key]
                continue
            if not chain.taken[key] and key not in chain.leftovers:
                continue
            now = _plus(self.held.get(key, Holding()), self.crafted.get(key, Holding()))
            after = _plus(_take(now, chain.taken[key]), chain.leftovers.get(key, Holding()))
            cost += self.valuer.worth(key, now) - self.valuer.worth(key, after)
        return cost

    def commit(self, plan: _Plan, chain: _Chain) -> None:
        """Take one more craft of `plan` by `chain` out of the live state."""
        for key, n in chain.taken.items():
            if n:
                self.held[key] = _take(self.held[key], n)
        for key, h in chain.leftovers.items():
            self.crafted[key] = _plus(self.crafted.get(key, Holding()), h)
        if self.asks is not None:
            for key, bought in chain.asks.items():
                self.asks[key] = without(self.asks[key], bought)
        self.spent[plan.recipe.recipe_id] += 1
        self.spent.update(chain.recipes)


@dataclass
class _Outlet:
    """Where a Flip to Craft's output goes: `room` more units Sell for `resale` each
    after the cut, less the `effort` of posting each (#73) and the deposits each is
    expected to lose behind the `queued` units ahead of it (#78), while that beats the
    Vendor Price. The rest are Vendored."""

    room: int
    post_at: float | None
    resale: float | None
    vendor_price: int
    bound: bool
    effort: int
    queue: _Queue
    queued: int

    def value(self, units: int) -> tuple[float, int]:
        """What `units` more would bring, and how many of them Sell."""
        sold, selling = 0.0, 0
        while not self.bound and self.resale is not None and selling < min(units, self.room):
            net = self.resale - self.effort - self.queue.lost(self.queued + selling)
            if net <= self.vendor_price:
                break  # the units after it wait longer
            sold += net
            selling += 1
        return sold + (units - selling) * self.vendor_price, selling

    def take(self, selling: int) -> None:
        """Take `selling` units' room, and their places in the queue."""
        self.room -= selling
        self.queued += selling


def _outlet(
    bound: bool,
    supply: Supply,
    others: Supply,
    rate: SellRate | None,
    vendor_price: int | None,
    merchant_cost: float | None,
    held: int,
    effort: int,
    queue: _Queue,
    cut: float,
    config: Config,
) -> _Outlet:
    """A Flip to Craft output's Sell room, judged as strictly as a Flip's: what sells
    within the Sale Horizon under the Flip priors, less the `held` units. It resells like
    them, posted under the cheapest other Listing, as if the Flip to Craft were the only
    buy (#86), and never above what a merchant charges (#63). `others` is other players'
    asks."""
    room, post_at, queued = _flip_room(rate, config), None, held
    if room:
        room = max(0, room - queued)
        cap = _ceiling(rate.max_sale_price, merchant_cost)
        post_at = _post_at(supply, others, [], config, cap)
    resale = None if post_at is None else post_at * (1 - cut)
    return _Outlet(room, post_at, resale, vendor_price or 0, bound, effort, queue, queued)


@dataclass(frozen=True)
class _CraftBuy:
    """One Flip to Craft: a craft of `plan` whose missing reagents are bought."""

    plan: _Plan
    gold: float  # spent on the Auction House and at merchants
    profit: float  # the output's worth less the chain's cost, held reagents included
    chain: _Chain
    buys: tuple[ReagentBuy, ...]
    selling: int  # output units that Sell
    post_at: float | None  # what they're posted at

    @property
    def per_gold(self) -> float:
        return self.profit / self.gold


def _flips_to_craft(
    plans: list[_Plan],
    crafting: _Crafting,
    asks: dict[str, Supply],
    merchant: dict[str, float],
    valuer: _Valuer,
    outlet: Callable[[_Plan], _Outlet],
    under: set[str],
    gold: float,
    config: Config,
    plan: _Plan,
) -> list[_CraftBuy]:
    """The Flips to Craft of `plan` worth making once the held-only crafts are
    (ADR-0009), as if they were the only buy (#86), in the order chosen.

    Greedy like the Craft Action: each step takes one more craft if it clears the Flip
    margin against the gold it spends, until one doesn't or the gold runs out. Its
    reagents are sourced like a Craft Action's, Sub-crafted with any of the `plans`, but
    what's still short can be bought at the cheapest `asks` left (_Sources).
    """
    if (
        plan.recipe.bind_type is None
        or plan.output in under
        or any(key in under for key in plan.needs)
    ):
        return []
    sources = _Sources(
        held=dict(crafting.held),
        crafted=dict(crafting.crafted),
        asks=dict(asks),
        merchant=merchant,
        valuer=valuer,
        under=under,
        plans=plans,
        spent=Counter(crafting.spent),
        config=config,
    )
    out = outlet(plan)
    result = []
    # A recipe on cooldown for every Character has a limit of 0.
    while plan.limit is None or sources.spent[plan.recipe.recipe_id] < plan.limit:
        step = _flip_step(plan, sources, out)
        if step is None or step.gold > gold:
            break
        if step.profit < max(
            step.gold * config.flip_min_margin_share, config.flip_min_margin_copper
        ):
            break
        result.append(step)
        gold -= step.gold
        sources.commit(step.plan, step.chain)
        out.take(step.selling)
    return result


def _flip_step(plan: _Plan, sources: _Sources, outlet: _Outlet) -> _CraftBuy | None:
    """One more Flip to Craft of `plan`; None if the reagents can't be had, or if nothing
    needs buying, since that's a Craft Action."""
    chain = sources.chain(plan)
    if chain is None:
        return None
    gold = sources.gold(chain)
    if not gold:
        return None
    buys = []
    for key in chain.taken:
        if chain.merchant[key]:
            buys.append(ReagentBuy(key, chain.merchant[key], sources.merchant[key], merchant=True))
        if chain.asks.get(key):
            units = chain.asks[key]
            buys.append(ReagentBuy(key, sum(n for _, n in units), max(unit for unit, _ in units)))
    value, selling = outlet.value(plan.recipe.quantity_min)
    return _CraftBuy(
        plan, gold, value - sources.cost(chain), chain, tuple(buys), selling, outlet.post_at
    )


def cheapest(asks: Supply, n: int) -> Supply | None:
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


def _unbound_units(held: dict[str, Holding]) -> dict[str, int]:
    return {key: _unbound(h) for key, h in held.items()}


def _crafted(plan: _Plan, holding: Holding) -> Holding:
    """`holding` with one more craft's output added, at the recipe's least quantity."""
    q = plan.recipe.quantity_min
    if plan.recipe.bind_type in BOUND_ON_CRAFT:
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
                        value = vendor.get(item_id_of(item_key), 0)
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


def held_units(rows: Sequence[Row]) -> Counter[str]:
    """How many units of each Item Key the Holdings rows hold, which a Paid covers some or
    all of: every row but a Craft's, whose units are made rather than held."""
    held: Counter[str] = Counter()
    for r in rows:
        if r.action is not Action.CRAFT:
            held[r.item_key] += r.quantity
    return held


def _with_roi(rows: list[Row], market_lots: list[Lot], cut: float, config: Config) -> list[Row]:
    """`rows` with each Sell and Vendor row's Paid and ROI (#50). An Item Key's held units
    are costed by its newest open Purchase Lots not tied to a Prediction (ADR-0007): open
    units beyond the held ones are taken to be the oldest, gone without a Sold Outcome."""
    held = held_units(rows)
    # By Item Key, what the held units the Lots cover cost in all, and how many they are.
    covered: dict[str, tuple[float, int]] = {}
    for lot in reversed(market_lots):  # newest first
        cost, units = covered.get(lot.item_key, (0.0, 0))
        uncovered = held[lot.item_key] - units
        if lot.prediction is not None or not lot.open_units or uncovered <= 0:
            continue
        taken = min(uncovered, lot.open_units)
        covered[lot.item_key] = (cost + taken * lot.cost / lot.units, units + taken)
    result = []
    for r in rows:
        roi = None
        if r.item_key in covered and r.action in (Action.SELL, Action.VENDOR) and r.price:
            cost, units = covered[r.item_key]
            paid = cost / units
            net = r.price * (1 - cut) if r.action is Action.SELL else r.price
            roi = (net - paid) / paid if paid else None
        if roi is None:
            result.append(r)
            continue
        hint = r.action is Action.SELL and roi >= config.roi_hint
        result.append(replace(r, paid=paid, paid_units=units, roi=roi, roi_hint=hint))
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
    merchant_cost: float | None,
    held: int,
    queue: _Queue,
    effort: int,
    stack: float,
    cut: float,
    config: Config,
) -> list[_VendorBuy | _FlipToSell]:
    """What's worth buying of an Item Key, from other players' (unit buyout, quantity)
    offers, cheapest first. `supply` is every unit on sale, the player's own included.

    Buy to Sell takes no more than sells within the Sale Horizon after the `held`
    unbound units, which take it first (#67), and posts just under the cheapest other
    player's Listing left once they're bought (`_post_at`), so they sell first. A cheap
    Listing that would undercut the resale is worth buying through, so every run of the
    cheapest offers is tried, and the one with the most profit whose every unit clears
    the Flip margin is bought (#62); the shorter runs that clear it are kept for when
    gold can't buy that one (ADR-0011). The resale is never above the
    dearest Sale Event behind the Sell Rate, so a lone ask far above every sale isn't
    taken at its word (#41), nor above what a merchant charges for it (#63). Nothing is
    bought to Sell unless the Sell Rate rests on the minimum of Sale Events for a Flip
    (#57). Anything else under the Vendor Price is bought to Vendor. Each unit bought
    costs the `effort` of buying it, and one bought to Sell the effort of posting it too
    (#73), and the deposits it's expected to lose waiting its turn in the `queue` after
    the `held` units (#78).
    """
    offers = sorted(offers)
    runs: list[_SellRun] = []
    prefix: Supply = []
    room = max(0, _flip_room(rate, config) - held)
    cap = _ceiling(rate.max_sale_price if rate else None, merchant_cost)
    for unit, quantity in offers:
        take = min(quantity, room)
        if not take:
            break
        prefix = [*prefix, (unit, take)]
        room -= take
        post_at = _post_at(supply, offers, prefix, config, cap)
        resale = None if post_at is None else post_at * (1 - cut)
        # Offers are cheapest first and the last unit waits longest, so if the dearest unit
        # clears the margin after its deposits, all do.
        bought = sum(n for _, n in prefix)
        if not _resells(resale, unit, vendor_price, effort, queue.lost(held + bought - 1), config):
            continue
        profit = sum((resale - 2 * effort - u) * n for u, n in prefix) - queue.lost_by(held, bought)
        days = (held + bought) / (queue.units_per_hour * 24)
        runs.append(_SellRun(prefix, post_at, profit, days))
    buys: list[_VendorBuy | _FlipToSell] = []
    to_sell: Supply = []
    if runs:
        flip = _FlipToSell(item_key, tuple(runs), rate.sale_events, stack)
        buys.append(flip)
        to_sell = flip.whole.units
    if vendor_price is not None:
        buys += [
            _VendorBuy(item_key, unit, quantity, vendor_price - effort - unit)
            for unit, quantity in _listings_left(offers, to_sell)
            if vendor_price - effort - unit > 0
        ]
    return buys


def _hold_buys(
    item_key: str,
    prediction: str,
    offers: list[tuple[int, int]],
    supply: Supply,
    rate: SellRate | None,
    vendor_price: int | None,
    merchant_cost: float | None,
    held: int,
    queue: _Queue,
    cut: float,
    config: Config,
) -> list[_HoldBuy]:
    """What's worth buying of an Item Key to Hold under a Prediction, from other players'
    (unit buyout, quantity) offers, cheapest first: the units whose Max Loss is small
    enough. `supply` is every unit on sale, and `held` the units the player could sell.

    A unit's Max Loss is its buyout less its exit without the Prediction. That's Sell, at
    the resale a Flip would get, for the units that would sell within the Sale Horizon if
    the Prediction were wrong, after the `held` ones, judged as strictly as a Flip and
    never above what a merchant charges (#63), less the deposits each is expected to lose
    waiting its turn in the `queue` (#78). The rest can only be Vendored, or are worth
    nothing without a Vendor Price.
    """
    room = max(0, _flip_room(rate, config) - held)
    bought: Supply = []
    buys = []
    for unit, quantity in sorted(offers):
        take = min(quantity, room)
        resale = (
            _resale(supply, offers, [*bought, (unit, take)], cut, config, merchant_cost)
            if take
            else None
        )
        queued = held + sum(n for _, n in bought)
        exits = [
            max((resale or 0) - queue.lost(queued + i), vendor_price or 0) for i in range(take)
        ] + [vendor_price or 0] * (quantity - take)
        parts = [(len(list(same)), exit_value) for exit_value, same in groupby(exits)]
        for n, exit_value in parts:
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
    """Units that should sell within the Sale Horizon; none without Sell Rate evidence."""
    return math.floor(_units_per_day(rate, prior_hours, prior_events) * horizon_seconds / 86400)


def _units_per_day(rate: SellRate | None, prior_hours: float, prior_events: float) -> float:
    """Units that should sell a day; none without Sell Rate evidence.

    Sell Rate is discounted by the Sell Rate Prior, as if `prior_hours` more hours had been
    watched with no sales, so a sale or two in a short Observation Window doesn't read as
    a fast seller (#25). Its average Sale Event size is shrunk by the Sale Size Prior, as
    if `prior_events` more Sale Events of the typical size had been seen, so one big buyer
    doesn't read as an Item Key that sells in bulk (#24). Both fade as evidence builds up.
    """
    if rate is None or not rate.sale_events:
        return 0.0
    mean_size = rate.sale_units / rate.sale_events
    # units / (hours + prior) * 24 * shrunk / mean, written so that no priors leave the
    # rate exactly as is.
    return (
        rate.units_per_day
        * rate.window_hours
        / (rate.window_hours + prior_hours)
        * (_sale_size(rate, prior_events) / mean_size)
    )


def _sale_size(rate: SellRate | None, prior_events: float) -> float:
    """The Item Key's average Sale Event size shrunk by the Sale Size Prior (#24), or 1
    without Sale Events."""
    if rate is None or not rate.sale_events:
        return 1.0
    return (rate.sale_units + prior_events * rate.typical_sale_size) / (
        rate.sale_events + prior_events
    )


def _resale(
    supply: Supply,
    others: Supply,
    bought: Supply,
    cut: float,
    config: Config,
    cap: float | None = None,
) -> float | None:
    """What one unit brings in after the cut, posted at `_post_at`."""
    value = _post_at(supply, others, bought, config, cap)
    return None if value is None else value * (1 - cut)


def _post_at(
    supply: Supply, others: Supply, bought: Supply, config: Config, cap: float | None = None
) -> float | None:
    """The price to post one unit at once `bought` is gone from other players' `others`
    (#62): just under the cheapest of them left, so it sells first, or `cap` if that's
    lower. The player's own Listings, the rest of `supply`, are matched rather than
    undercut. None if no Listing is left to price against."""
    left = without(others, bought)
    own = without(supply, others)
    prices = [left[0][0] - config.post_undercut_copper] if left else []
    prices += [own[0][0]] if own else []
    if not prices:
        return None
    value = min(prices)
    return value if cap is None else min(value, cap)


def _ceiling(*caps: float | None) -> float | None:
    """The lowest of the caps on a Sell price that apply, or None if none do."""
    known = [c for c in caps if c is not None]
    return min(known) if known else None


def _listings_left(offers: Supply, bought: Supply) -> Supply:
    """`offers` less the units `bought`, still one entry per Listing, cheapest first:
    unlike `without`, same-price Listings aren't merged, so they can be counted (#98)."""
    taken = Counter()
    for unit, quantity in bought:
        taken[unit] += quantity
    left = []
    for unit, quantity in sorted(offers):
        take = min(quantity, taken[unit])
        taken[unit] -= take
        if quantity > take:
            left.append((unit, quantity - take))
    return left


def without(supply: Supply, bought: Supply) -> Supply:
    left = Counter()
    for unit, quantity in supply:
        left[unit] += quantity
    for unit, quantity in bought:
        left[unit] -= quantity
    return [(unit, quantity) for unit, quantity in sorted(left.items()) if quantity > 0]


def _option(
    buys: list[_VendorBuy | _FlipToSell], crafts: list[_CraftBuy], gold: float
) -> list[Row]:
    """One Shopping List option's row (#86): one Item Key's Flip to Sell or its buys to
    Vendor, cheapest first, or one recipe's Flips to Craft, in the order chosen, as much
    of it as fits in `gold`.

    A Flip to Sell buys the most profitable run `gold` covers, or nothing (ADR-0011). Once
    a Flip to Craft is left out, so are the later crafts of its recipe, which were costed
    after it.
    """
    rows: dict[object, Row] = {}
    plans: dict[int, _Plan] = {}  # the Flips to Craft taken of each recipe
    cut: set[int] = set()
    # A recipe's crafts keep the order the greedy loop chose them in.
    for buy in [*sorted(buys, key=lambda buy: -buy.per_gold), *crafts]:
        if isinstance(buy, _CraftBuy):
            recipe_id = buy.plan.recipe.recipe_id
            if recipe_id in cut or buy.gold > gold:
                cut.add(recipe_id)
                continue
            gold -= buy.gold
            plan = plans.setdefault(recipe_id, _Plan(buy.plan.recipe, buy.plan.character))
            plan.crafts += 1
            plan.gain += buy.profit
            plan.add(buy.chain)
            r = rows.get(recipe_id, replace(plan.row(), cost=0))
            selling = buy.selling + (r.made.selling if r.made else 0)
            made = CraftOutput(plan.crafts * plan.recipe.quantity_min, selling, buy.post_at)
            rows[recipe_id] = replace(
                plan.row(), cost=r.cost + buy.gold, buys=_merged(r.buys, buy.buys), made=made
            )
            continue
        if isinstance(buy, _FlipToSell):
            run = buy.fitting(gold)
            if run is None:
                continue
            gold -= run.cost
            key = (buy.item_key, Action.SELL)
            rows[key] = Row(
                buy.item_key,
                Action.SELL,
                run.quantity,
                run.dearest,
                run.profit,
                post_at=run.post_at,
                sale_events=buy.sale_events,
                cost=run.cost,
                listings=run.listings,
                # A hair under, so 4 units in stacks of 2.0000001 are still 2 posts.
                posts=math.ceil(run.quantity / buy.stack - 1e-9),
                days=run.days,
            )
            continue
        quantity = min(buy.quantity, int(gold // buy.unit_buyout))
        if not quantity:
            continue
        gold -= quantity * buy.unit_buyout
        buy = replace(buy, quantity=quantity)
        cost = buy.unit_buyout * buy.quantity
        profit = buy.unit_profit * buy.quantity
        key = (buy.item_key, Action.VENDOR)
        if key not in rows:
            rows[key] = Row(
                buy.item_key,
                Action.VENDOR,
                buy.quantity,
                buy.unit_buyout,
                profit,
                cost=cost,
                listings=1,
                posts=0,
            )
        else:
            r = rows[key]
            rows[key] = replace(
                r,
                quantity=r.quantity + buy.quantity,
                price=max(r.price, buy.unit_buyout),
                profit=r.profit + profit,
                cost=r.cost + cost,
                listings=r.listings + 1,
            )
    return list(rows.values())


def _resells(
    resale: float | None,
    unit: float,
    vendor_price: int | None,
    effort: int,
    lost: float,
    config: Config,
) -> bool:
    """Whether a unit bought at `unit` and resold for `resale` after the cut is a Flip to
    Sell: less the `effort` of buying and of posting it (#73) and the deposits it's
    expected to have `lost` (#78), it clears the Flip margin, and no vendor pays as much
    (that's a Flip to Vendor, which isn't posted)."""
    if resale is None or resale - 2 * effort - lost - unit < max(
        unit * config.flip_min_margin_share, config.flip_min_margin_copper
    ):
        return False
    return vendor_price is None or resale - effort - lost > vendor_price


def _options(
    buys: list[_VendorBuy | _FlipToSell],
    crafts: list[list[_CraftBuy]],
    gold: float,
    flip_rows: int,
    craft_rows: int,
) -> list[Row]:
    """The Shopping List (#86): each Item Key's Flip to Sell and Flip to Vendor, and each
    recipe's Flips to Craft, sized as if it were the only buy within `gold`, most
    profitable first. The Flips to Sell and to Vendor are cut to those in the top
    `flip_rows` by any of Profit, Per click, Per day (Flips to Sell only) or ROI (#98),
    and the Flips to Craft,
    apart, to the top `craft_rows` by Profit (#87). A Flip to Sell is priced on the run it
    buys (ADR-0011)."""
    groups: dict[object, list[_VendorBuy | _FlipToSell]] = {}
    for buy in buys:
        groups.setdefault((buy.item_key, isinstance(buy, _FlipToSell)), []).append(buy)
    flips = [row for group in groups.values() for row in _option(group, [], gold)]
    crafted = [row for recipe in crafts if recipe for row in _option([], recipe, gold)]
    kept: set[int] = set()
    selling = [r for r in flips if r.action is Action.SELL]
    for measure, rows in (
        (_profit, flips),
        (per_click, flips),
        # Every Flip to Vendor ties at "now", so Per day ranks the Flips to Sell alone.
        (per_day, selling),
        (return_on_cost, flips),
    ):
        # Ties go to the most profit.
        top = sorted(rows, key=lambda r: (-measure(r), -r.profit))[:flip_rows]
        kept |= {id(r) for r in top}
    crafted.sort(key=lambda r: -r.profit)
    # One list again, most profit first: Replay takes the options in that order.
    return sorted(
        [r for r in flips if id(r) in kept] + crafted[:craft_rows], key=lambda r: -r.profit
    )


def _profit(row: Row) -> float:
    return row.profit


def per_click(row: Row) -> float:
    """A Flip's Profit for each Listing bought and stack posted (#98)."""
    return row.profit / (row.listings + row.posts)


def per_day(row: Row) -> float:
    """A Flip's Profit for each day until its last unit sells: a Flip to Vendor sells now,
    before any Flip to Sell (#98)."""
    return math.inf if row.days is None else row.profit / row.days


def return_on_cost(row: Row) -> float:
    """A Flip's Profit on its Cost (#98), not a Holdings row's `roi` on what was Paid."""
    return row.profit / row.cost


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


def item_id_of(item_key: str) -> int:
    """The itemID of a stored Item Key ("itemID" or "itemID:bonus1:..."): Vendor Price
    belongs to it, not to the random suffix."""
    return int(item_key.split(":", 1)[0])
