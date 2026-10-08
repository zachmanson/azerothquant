"""The Decision Engine: Vendor vs Sell for Holdings, and Flips (#23), and Hold under a
Prediction, both for Holdings and for buying (#26, ADR-0006).

Each Market the player has Characters in is valued as of its latest Scan: every Sell
posted just under the Listings left in that Scan once its Flips are bought (#62, #64),
and Sell Rate from the Observation Windows before it. All amounts are copper.
"""

import bisect
import math
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from enum import StrEnum
from functools import cache, cached_property
from itertools import groupby
from types import MappingProxyType
from typing import NamedTuple

from brain.beta_sell_rate import BetaSellRate, beta_ratios, beta_sell_rates
from brain.config import Config
from brain.disenchant import DisenchantTable, Group, ItemInfo, load_table
from brain.fair_value import FairValueCache, Supply, fair_value
from brain.grades_file import (
    Grade,
    Named,
    NamedBuy,
    NamedCraft,
    freeze_grade,
    freeze_held,
    freeze_named,
    freeze_shown,
    freeze_shown_crafts,
    load_frozen,
)
from brain.history import (
    Holding,
    KnownRecipe,
    Listing,
    Market,
    Purchase,
    character_markets,
    character_read_times,
    cheapest_seen,
    crafts,
    dropped_at,
    enchanting_skills,
    holdings,
    item_info,
    known_recipes,
    listings,
    market_budget,
    market_days_to_sell,
    merchant_costs,
    outcomes,
    pooled_gold,
    purchases,
    scan_times,
    supply_at,
    vendor_prices,
)
from brain.lots import (
    GroupKey,
    Held,
    Lot,
    LotCraftResult,
    LotsWithCrafts,
    NamedSet,
    bought_under,
    deposits,
    ended_at,
    happened_at,
    is_for_use,
    item_names,
    link_sales,
    lots,
    lots_with_crafts,
    scan_before,
    settle,
    start_of,
)
from brain.mailbox import MailKind
from brain.predictions import Prediction
from brain.scan import item_id_of
from brain.sell_rate import SellRate, non_stacking, observation_window_hours, sell_rates

# A replay's stand-in for the own-Market Sell Rate (#84, ADR-0015): (Item Key, the cheapest
# other player's unit price left once the buys are made, None if none) -> the price to
# post at, or None without one. Only the replay builds one: a baseline is never a Brain
# price. Given one, it prices every Sell and Flip, there's no room limit on what sells
# within the Sale Horizon, and no deposits are expected lost waiting to sell.
Pricer = Callable[[str, int | None], float | None]


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
class ListingBuy:
    """One other player's Listing a Flip to Disenchant buys (#89): one unit at `price`."""

    item_key: str
    price: int


@dataclass(frozen=True)
class DisenchantFlip:
    """What makes a Shopping List row a Flip to Disenchant (#89): the Disenchant source
    `group` it buys, and the Listings it buys, cheapest first."""

    group: Group
    buys: tuple[ListingBuy, ...]


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


class Check(StrEnum):
    """The Shopping List's checks on a Flip to Sell or Vendor, in the order the Brain
    makes them (#108)."""

    SALE_EVENTS = "Sale Events"
    ROOM = "Room"
    MARGIN = "Flip margin"
    DROPPED = "Dropped rows"  # the Scan dropped rows of the item (#156)
    BUDGET = "Budget"
    ROW_CAP = "Row cap"


@dataclass(frozen=True)
class BetaRoom:
    """How much of a Prediction buy's Max Loss room came from the Beta Sell Rate (#110):
    the `room` at `post_at` with it, `from_beta` more units than without it. Negative when
    Beta's hours, with too few Sale Events at the price, water Live's rate down."""

    post_at: float
    room: int
    from_beta: int


@dataclass(frozen=True)
class WhyNot:
    """Why an Item Key with other players' Listings is or isn't on the Shopping List as a
    Flip to Sell or Vendor (#108): the first Check it `failed`, None if it made the list,
    and the numbers behind each Check."""

    item_key: str
    failed: Check | None
    # Where the Checks are priced (`_Valuer.clearing_run`): the post price of the shortest
    # run of the cheapest Listings that would clear the Flip margin if room were no limit,
    # and the units that run `needs`. A run of many Listings at one price only clears once
    # all of them are bought, posted above them. Without such a run, where the cheapest
    # Listing alone posts once bought, needing 1. None without a price to post at.
    post_at: float | None
    needs: int
    # At or above `post_at`.
    sale_events: int
    min_sale_events: int
    # What sells within Days to Sell at `post_at` (#109), and the unbound held units that
    # take it first (#67), ahead of the units it `needs`.
    room: int
    held: int
    # The cheapest other player's ask, and the most one unit of it could cost and clear
    # the Flip margin: the Buy Under's way value once the run is bought (ADR-0019), less
    # effort and the margin. None without a way out.
    ask: int
    clear_at: int | None
    # The cheapest run that clears, against what an option may spend (#86). None unless
    # one clears.
    cost: int | None
    spend: int
    # Its row's best place by any of the Shopping List's measures (#98), against the
    # places kept. None unless a row was built.
    rank: int | None
    rows: int
    name: str | None = None  # only if the player has listed, bought or sold it
    # The Scan the stretch of cheaper Listings began in, when `sale_events` counts only the
    # ones since (#132, #135, ADR-0029). None if they all count.
    cheap_since: int | None = None
    # Whether any Observation Window hours came after `cheap_since` (#135).
    watched_since: bool = True
    # The Scans with no cheaper Listing the stretch was kept through (#139), oldest first.
    cheap_breaks: tuple[int, ...] = ()


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


class NodeKind(StrEnum):
    """What a Craft Chain node does with its units (#77). DISENCHANT is reserved (#76)."""

    SELL = "sell"
    VENDOR = "vendor"
    CRAFT = "craft"
    USE = "use"  # held units
    BUY = "buy"  # on the Auction House
    MERCHANT = "merchant"
    LEFTOVER = "leftover"  # a Sub-craft's units beyond what's short
    DISENCHANT = "disenchant"


@dataclass(frozen=True)
class ChainNode:
    """One node of a Craft row's Craft Chain (#77): `quantity` units of an Item Key, the
    row's total, and their signed `gold`. A source costs what `_Sources.cost` counts for
    it, a `leftover` brings its worth and an exit its net after the cut and deposits. A
    `craft` node's gold is the sum of the sources under it, so every node but a craft
    adds up to the row's Profit. `children` are what feed it."""

    kind: NodeKind
    item_key: str
    quantity: int
    gold: float | None  # None where it's unknown, on a blocked row
    children: tuple["ChainNode", ...] = ()
    crafts: int | None = None  # a craft's
    character: str = ""  # a craft's
    post_at: float | None = None  # a sell's
    max_unit_price: float | None = None  # a buy's, on the Auction House
    # The gold's breakdown: a sell's cut and deposits, and the effort of buying or posting
    # units that don't stack (#73).
    cut: float | None = None
    deposit: float | None = None
    effort: float | None = None
    blocked: Blocked | None = None


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
    # A Flip to Craft's is its output's, None when it all goes to Vendor (#61).
    post_at: float | None = None
    margin: float | None = None  # per unit, a Sell's proceeds over the Vendor Price
    sale_events: int | None = None  # the evidence behind the Sell Rate
    # A held unit's sibling suffixes' Sale Events its Sell Rate counts, unweighted (#58).
    sibling_sales: int | None = None
    note: str = ""
    # The Shopping List's gold to spend on it, or for a Hold the gold it ties up: what its
    # units cost, by their Lots or else what letting them go would bring today (_hold).
    cost: float | None = None
    prediction: str = ""  # the Prediction the Action depends on, if any
    # A Prediction buy's Max Loss for the whole quantity: what's lost if the Prediction is
    # wrong and the units are let go at today's prices.
    max_loss: float | None = None
    # A Prediction buy's room when the Beta Sell Rate counts for its Item Key (#110): the
    # room it was bought on, preferring one the Beta Sell Rate added to (#111), then the
    # biggest.
    beta_room: BetaRoom | None = None
    buys: tuple[ReagentBuy, ...] = ()  # a Flip to Craft's reagents to buy
    # A Craft's Character, the one that knows the recipe, or a Disenchant's, the one with
    # the Enchanting skill.
    character: str = ""
    mats: tuple[MatYield, ...] = ()  # a Disenchant's expected mats
    # A Flip to Disenchant's group and Listings (#89). Its `item_key` is "": it buys a group.
    disenchant: DisenchantFlip | None = None
    uses: tuple[ReagentUse, ...] = ()  # a Craft's held reagents, not the ones it buys
    blocked: Blocked | None = None  # why a Craft can't be made, for the Addon to name
    via: tuple[SubCraft, ...] = ()  # a Craft's Sub-crafts, deepest first (#33)
    # A Craft's Craft Chain (#77): its exits, the last over the craft and its sources. Not
    # compared, so rows are checked on it apart.
    chain: tuple[ChainNode, ...] = field(default=(), compare=False)
    # A Craft Action's gold spent at merchants, and a Flip to Craft's output, for the
    # replay (#80). Plumbing, not part of the Recommendation: not written to
    # Recommendations.lua, nor compared.
    merchant_gold: float = field(default=0.0, compare=False)
    made: CraftOutput | None = field(default=None, compare=False)
    recipe_id: int | None = field(default=None, compare=False)  # a Craft's, for #114
    # A Sell or Vendor row's Paid (#50): per unit, what the Item Key's held units its open
    # Lots (a Purchase's or a craft's output, #44) cover cost, and how many units that is.
    # Split rows share it.
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


# The most Scans in a row with no cheaper Listing that don't end a stretch of them, when
# cheap stock is up again before them (#139).
SHORT_BREAK_SCANS = 2


class _Stretch(NamedTuple):
    since: int | None  # the Scan it began in
    breaks: tuple[int, ...]  # the Scans with none cheaper it was kept through, oldest first


@dataclass(frozen=True)
class _Cheap:
    """The cheapest other player's unit buyout of an Item Key in each Scan, as (Scan,
    unit buyout), from the latest Scan back to the last one before it with none listed,
    for a buy that takes the cheapest and posts above them (#132, #135, ADR-0029): the
    demand at its post price counts only since the stretch of cheaper stock began."""

    lows: tuple[tuple[int, int], ...]

    def since(self, post_at: float) -> int | None:
        """The Scan the stretch began in, as in `stretch`."""
        return self.stretch(post_at).since

    def stretch(self, post_at: float) -> _Stretch:
        """The stretch of Scans with another player's Listing under `post_at`, walking
        back from the latest, kept through breaks of up to SHORT_BREAK_SCANS with cheap
        stock again before them (#139). Its `since` is None if it's only the latest Scan,
        a Listing too new to judge, or none is under `post_at`, as for a Sell posted under
        the cheapest."""
        cheap = [low[1] < post_at for low in self.lows]
        start = None  # index into `lows`, latest first, as are `i` and `gap`
        skipped: list[int] = []
        i = 0
        while i < len(cheap) and cheap[i]:
            start = i
            i += 1
            gap = i
            while gap < len(cheap) and not cheap[gap] and gap - i < SHORT_BREAK_SCANS:
                gap += 1
            if gap > i and gap < len(cheap) and cheap[gap]:
                skipped += range(i, gap)
                i = gap
        if start is None or start == 0:
            return _Stretch(None, ())
        return _Stretch(self.lows[start][0], tuple(self.lows[s][0] for s in reversed(skipped)))

    @property
    def latest(self) -> int:
        """The Scan the cheapest Listings are from, the latest: only for a `since`."""
        return self.lows[0][0]


@dataclass(frozen=True)
class _SellRun:
    """A run of the cheapest Listings of an Item Key bought to Sell, posted at `post_at`
    once they're gone, whose every unit clears the Flip margin."""

    units: Supply
    post_at: float
    profit: float
    days: float  # until its last unit sells, behind the held units (#98)
    sale_events: int  # the Sale Events at or above `post_at` it counts on (#107)

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
    beta_room: BetaRoom | None = None


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
class LootValue:
    """One unit's Best Exit Value, and the Action it's by (#54)."""

    value: float
    way: Action


@dataclass(frozen=True)
class LootAlert:
    """What a drop must be worth for the Addon to flag it (#54): the `threshold` for one
    unit, and each Item Key in the Scan whose one unit alone is worth at least that."""

    threshold: int
    items: dict[str, LootValue] = field(default_factory=dict)


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
    # Each Item Key with other players' Listings, if asked for (#108).
    why_not: list[WhyNot] = field(default_factory=list)
    # Each active Prediction Item Key's Beta/Live Fair Value ratio, while the Beta Sell
    # Rate may count (#110).
    beta_ratios: dict[str, float] = field(default_factory=dict)
    loot_alert: LootAlert = field(default_factory=lambda: LootAlert(0))

    @property
    def spend(self) -> int:
        """What each Shopping List option, and the Prediction buys, may spend (#86)."""
        return _spend(self.gold, self.budget)


def _spend(gold: int, budget: int | None) -> int:
    return gold if budget is None else min(gold, budget)


def recommend(
    conn: sqlite3.Connection,
    config: Config,
    predictions: Sequence[Prediction] = (),
    fair_value_cache: FairValueCache | None = None,
    why_not: bool = False,
) -> list[MarketRecommendations]:
    """Recommendations for every Market the player has Characters in. `fair_value_cache`
    is the past Scans' Fair Values, kept from one pass to the next (#105). With `why_not`,
    each says why each Item Key on sale is or isn't a Flip on the Shopping List (#108)."""
    if fair_value_cache is not None:
        fair_value_cache.start_pass()
    result = []
    for market in character_markets(conn):
        times = scan_times(conn, market)
        if times:
            result.append(
                recommend_market(
                    conn,
                    config,
                    market,
                    predictions,
                    times[-1],
                    fair_value_cache=fair_value_cache,
                    why_not=why_not,
                )
            )
    return result


def recommend_market(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    predictions: Sequence[Prediction],
    now: int,
    as_of: int | None = None,
    buy_under: bool = True,
    fair_value_cache: FairValueCache | None = None,
    pricer: Pricer | None = None,
    why_not: bool = False,
    paid: bool = True,
    loot_alert: bool = True,
) -> MarketRecommendations:
    """The Market's Recommendations as of its Scan requested at `now`. The Holdings, gold,
    Known Recipes and Enchanting skills are the latest, or as of `as_of` (a replay, #80,
    #103). Without `buy_under`, the Buy
    Unders are left out: a replay doesn't grade them (#88). `fair_value_cache` as in
    `recommend`. A `pricer` replaces the Sell Rate (a replay's ablation, #84), but not in
    the Prediction buys, the Buy Unders or the Shopping List's Per day and Per click.
    `why_not` as in `recommend`. Without `paid`, the Holdings rows get no Paid or ROI:
    working out a past Scan, whose Lots may rest on what it named (#55), or a replay.
    Without `loot_alert`, the Loot Alert has no items: only the latest Scan's is shown
    (#54), and valuing every Item Key in a Scan adds up over a replay."""
    characters = character_markets(conn).get(market, [])
    days_to_sell = market_days_to_sell(conn, market.era, market.realm, market.faction, as_of)
    config = replace(config, days_to_sell_seconds=days_to_sell)
    today = date.fromtimestamp(now)
    active = [p for p in predictions if p.active_on(today)]
    under = {k: p.name for p in active for k in p.item_keys}
    by_character = _by_character(conn, market, characters, as_of)
    holdings = _pooled(by_character)
    # Loaded once for the whole pass: the Market's every Listing is the bulk of it (#105).
    if fair_value_cache is not None:
        seen = fair_value_cache.listings(conn, market)
    else:
        seen = listings(conn, market)
    # Holdings and Craft Actions are valued with nothing on the Shopping List bought: its
    # options are alternatives, so none is assumed (#86).
    valuer, _ = _valuer(
        conn,
        config,
        market,
        now,
        set(under),
        _unbound_units(holdings),
        seen,
        fair_value_cache=fair_value_cache,
        skills_as_of=as_of,
        pricer=pricer,
    )
    supply, for_sale, rates = valuer.supply, valuer.others, valuer.rates
    vendor, merchant, cut = valuer.vendor, valuer.merchant, valuer.cut
    plans = _plans(known_recipes(conn, market, as_of), now)
    crafting = _crafts(holdings, plans, merchant, valuer, set(under), config)
    held = crafting.after
    # The crafts change what's held, so the Flips are sized again after them (#67).
    valuer, cleared = valuer.flips(set(under), _unbound_units(held))
    # The Scan may have missed some Listings of an item it dropped rows of, so the cheapest
    # it saw may not be the cheapest up (#156).
    dropped = dropped_at(conn, market, now)
    buys = [b for b in cleared if item_id_of(b.item_key) not in dropped]
    gold = pooled_gold(conn, market.era, market.realm, market.faction, as_of)
    budget = market_budget(conn, market.era, market.realm, market.faction, as_of)
    spend = _spend(gold, budget)
    ratios = beta_ratios(conn, market, config, now, set(under), fair_value_cache)
    beta = beta_sell_rates(conn, market, config, ratios, fair_value_cache)
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
            beta.get(item_key),
            valuer.cheap(item_key),
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
            valuer.sale_queue(plan.output, flips=True),
            cut,
            config,
            valuer.priced(plan.output),
        )

    crafts = (
        [
            _flips_to_craft(
                plans, crafting, for_sale, merchant, valuer, outlet, set(under), spend, config, plan
            )
            for plan in plans
            if item_id_of(plan.output) not in dropped
        ]
        if config.flips_to_craft
        else []
    )
    disenchants = _flips_to_disenchant(valuer, plans, set(under), dropped, spend, config)
    shopping = _options(
        buys,
        crafts,
        disenchants,
        spend,
        config.shopping_list_rows,
        config.craft_list_rows,
        config.disenchant_list_rows,
    )
    crafted = crafting.counts
    disenchanted, left = _disenchants(held, valuer, set(under), _bound_by(by_character))
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
    bound = {k: _bound(h) for k, h in held.items()}
    lot_costs = _lot_costs(conn, config, market, active, seen)
    rows = _hold(rows, active, bound, vendor, caps, lot_costs)
    if paid:
        rows = _with_roi(rows, market_lots(conn, config, market, predictions, seen), cut, config)
    rows = [
        _with_note(row, PRICE_MAY_BE_OFF) if item_id_of(row.item_key) in dropped else row
        for row in rows
    ]
    # Most expected profit first; rows without a number to rank by go last.
    rows.sort(key=lambda r: (r.profit is None, -(r.profit or 0)))
    prediction_buys = _spend_on_predictions(hold_buys, spend, caps)
    market_purchases = purchases(conn, market)
    linked = link_sales(outcomes(conn, market), seen, market_purchases)
    names = item_names(linked, seen, market_purchases)
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
        buy_under=_buy_unders(conn, config, market, now, valuer, plans, fair_value_cache)
        if buy_under
        else [],
        why_not=_why_not(valuer, cleared, dropped, spend, set(under), names, config)
        if why_not
        else [],
        beta_ratios=ratios,
        loot_alert=_loot_alert(gold, valuer, plans, config, with_items=loot_alert),
    )


def _loot_alert(
    gold: int, valuer: "_Valuer", plans: list["_Plan"], config: Config, with_items: bool
) -> LootAlert:
    """The Loot Alert (#54): its threshold is a share of the pooled gold, never under the
    floor, and it keeps each Item Key in the Scan whose best way out for one unit is worth
    at least that. The unit is valued alone: no held unit takes a way's room ahead of it,
    since the question is what the drop is worth, not what it adds to the bags."""
    threshold = max(round(config.loot_alert_share * gold), config.loot_alert_floor_copper)
    if not with_items:
        return LootAlert(threshold)
    alone = valuer.after({}, {})
    sources = _nothing_held(alone, plans, config)
    items = {}
    for item_key in sorted(alone.supply):
        out = _way_out(item_key, alone, config, sources)
        if out is not None and out.value >= threshold:
            items[item_key] = LootValue(out.value, out.way)
    return LootAlert(threshold, items)


def named_set(m: MarketRecommendations) -> NamedSet:
    """What a Scan's Recommendations named to buy (#55, ADR-0025): its Shopping List's
    Flips to Sell and Vendor, at their dearest Listing, Flips to Craft's Auction House
    reagents, and Flips to Disenchant's items, each at its dearest Listing bought (#89),
    and its Buy Unders, each Item Key at the most any of them named."""
    items: dict[str, float] = {}
    groups: dict[GroupKey, float] = {}

    def name(at_most: dict, key: object, price: float) -> None:
        at_most[key] = max(price, at_most.get(key, price))

    for r in m.shopping_list:
        if r.action in (Action.SELL, Action.VENDOR) and r.price is not None:
            name(items, r.item_key, r.price)
        for buy in r.buys:
            if not buy.merchant:
                name(items, buy.item_key, buy.max_unit_price)
        for listing in r.disenchant.buys if r.disenchant else ():
            name(items, listing.item_key, listing.price)
    for b in m.buy_under:
        if b.group is not None:
            name(groups, b.group.key, b.price)
        elif b.item_key is not None:
            name(items, b.item_key, b.price)
    return NamedSet(items, groups)


def _why_not(
    valuer: "_Valuer",
    cleared: list[_VendorBuy | _FlipToSell],
    dropped: frozenset[int],
    spend: int,
    under: set[str],
    names: Mapping[str, str],
    config: Config,
) -> list[WhyNot]:
    """`recommend`'s `why_not` from the Valuer the Flips were sized on, the buys that
    `cleared` the Flip margin, the itemIDs the Scan `dropped` rows of, whose buys aren't
    options (#156), and what each option may `spend`, for the Item Keys not `under` a
    Prediction, with the item `names` known (#108)."""
    buys = [b for b in cleared if item_id_of(b.item_key) not in dropped]
    flips = _flip_options(buys, spend)
    rank: dict[str, int] = {}
    for row, place in zip(flips, _best_ranks(flips), strict=True):
        rank[row.item_key] = min(place, rank.get(row.item_key, place))
    cost: dict[str, int] = {}
    for buy in cleared:
        least = (
            min(run.cost for run in buy.runs) if isinstance(buy, _FlipToSell) else buy.unit_buyout
        )
        cost[buy.item_key] = min(least, cost.get(buy.item_key, least))
    rows = config.shopping_list_rows
    result = []
    for item_key in sorted(valuer.others):
        if item_key in under:
            continue
        cheapest = min(valuer.others[item_key])
        run = valuer.clearing_run(item_key)
        if run is None:
            bought, needs = valuer.after({item_key: [cheapest]}), 1
            post_at = bought.flip_post_at(item_key)
        else:
            bought, needs, post_at = valuer.after({item_key: run.units}), run.quantity, run.post_at
        rate = valuer.rates.get(item_key)
        cheap = valuer.cheap(item_key)
        demand = _demand_at(rate, post_at, cheap=cheap)
        sale_events = demand.sale_events if demand else 0
        cut = demand is not None and demand != rate.at_or_above(post_at)
        stretch = cheap.stretch(post_at) if cut else _Stretch(None, ())
        room = _room_at(
            rate, post_at, 0, config, config.days_to_sell_or_horizon_seconds, cheap=cheap
        )
        held = valuer.held.get(item_key, 0)
        out = _way_out(item_key, bought, config)
        clear_at = (
            None if out is None else _under_margin(out.value - valuer.effort(item_key), config)
        )
        # An Item Key with a Flip to Vendor gets past the checks a Flip to Sell alone makes.
        if item_key in rank:
            failed = Check.ROW_CAP if rank[item_key] > rows else None
        elif item_key in cost:
            failed = Check.DROPPED if item_id_of(item_key) in dropped else Check.BUDGET
        elif sale_events < config.flip_min_sale_events:
            failed = Check.SALE_EVENTS
        elif room < held + needs:
            failed = Check.ROOM
        else:
            failed = Check.MARGIN
        result.append(
            WhyNot(
                item_key,
                failed,
                post_at=post_at,
                needs=needs,
                sale_events=sale_events,
                min_sale_events=config.flip_min_sale_events,
                room=room,
                held=held,
                ask=cheapest[0],
                clear_at=clear_at,
                cost=cost.get(item_key),
                spend=spend,
                rank=rank.get(item_key),
                rows=rows,
                name=names.get(item_key),
                cheap_since=stretch.since,
                cheap_breaks=stretch.breaks,
                watched_since=not cut or demand.window_hours > 0,
            )
        )
    return result


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
    fair_value_cache: FairValueCache | None = None,
) -> list[BuyUnder]:
    """The Buy Unders as of the Scan requested at `now` (#88): every Item Key whose best
    way out leaves a price that enough distinct Scans in the window saw another player's
    Listing at or under. The Holdings don't move them: a Craft way's other reagents come
    from their cheapest current source (ADR-0014's, with nothing held). `fair_value_cache`
    as in `recommend`."""
    window = config.buy_under_window_days
    sources = _nothing_held(valuer, plans, config)
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

    since = now - window * 86400
    seen_by_key = _scan_only(
        fair_value_cache,
        conn,
        market,
        ("cheapest_seen", since, now),
        lambda: cheapest_seen(conn, market, since, now),
    )
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


def _nothing_held(valuer: "_Valuer", plans: list["_Plan"], config: Config) -> "_Sources":
    """Sources for a way out with nothing held: a Craft way's other reagents come from
    their cheapest current source (ADR-0014's)."""
    return _Sources(
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


def _flips_to_disenchant(
    valuer: "_Valuer",
    plans: list["_Plan"],
    under: set[str],
    dropped: frozenset[int],
    gold: float,
    config: Config,
) -> list[Row]:
    """The Flips to Disenchant in this Scan (#89): one option per Disenchant source group
    with a Character who can Disenchant it, sized alone within `gold` (ADR-0017). Its
    candidates are other players' Listings of the group's items not `under` a Prediction,
    nor of an item the Scan dropped rows of (#156), whose best way out for one unit is
    Disenchant, so it never repeats a better Flip to Sell or Vendor of the same Listing. A
    mat that feeds a Craft gets the Craft's credit through its way out, with the Flip
    margin charged once, as in a Buy Under."""
    disenchanting = valuer.disenchanting
    if disenchanting is None:
        return []
    sources = _Sources(
        held={},
        crafted={},
        asks=valuer.others,
        merchant=valuer.merchant,
        valuer=valuer,
        under=under,
        plans=plans,
        spent=Counter(),
        config=config,
    )
    candidates: dict[Group, list[tuple[int, str]]] = {}
    for item_key, offers in sorted(valuer.others.items()):
        group = disenchanting.group(item_key)
        if group is None or item_key in under or item_id_of(item_key) in dropped:
            continue
        out = _way_out(item_key, valuer, config, sources)
        if out is None or out.way is not Action.DISENCHANT:
            continue
        # Armor and weapons don't stack: a Listing is one unit.
        candidates.setdefault(group, []).extend((unit, item_key) for unit, _ in offers)
    rows = []
    for group, listed in candidates.items():
        disenchanter = disenchanting.disenchanter(group)
        if disenchanter is None:
            continue
        row = _flip_to_disenchant(group, disenchanter, listed, valuer, sources, gold, config)
        if row is not None:
            rows.append(row)
    return rows


def _flip_to_disenchant(
    group: Group,
    disenchanter: str,
    listed: list[tuple[int, str]],
    valuer: "_Valuer",
    sources: "_Sources",
    gold: float,
    config: Config,
) -> Row | None:
    """One group's Flip to Disenchant, greedy like a Flip to Craft: each step buys the
    cheapest `listed` (unit buyout, Item Key) left if one more Disenchant's expected mats,
    at their ways out on top of the held mats and the earlier steps', less the effort of
    buying it, clear the Flip margin on its buyout and it fits the gold left. It stops at
    the first that doesn't. None if none does."""
    expected = {str(mat): q for mat, q in group.expected.items()}
    share, floor = config.flip_min_margin_share, config.flip_min_margin_copper
    added: Counter[str] = Counter()  # expected mats from the steps so far, in fractions
    bought: list[ListingBuy] = []
    profit = 0.0
    for unit, item_key in sorted(listed):
        net = _mats_value(expected, added, valuer, sources, config)
        net -= config.non_stacking_effort_copper
        if unit > gold or net - unit < max(unit * share, floor):
            break
        bought.append(ListingBuy(item_key, unit))
        profit += net - unit
        gold -= unit
        added.update(expected)
    if not bought:
        return None
    n = len(bought)
    return Row(
        "",
        Action.DISENCHANT,
        n,
        price=bought[-1].price,
        profit=profit,
        cost=sum(b.price for b in bought),
        character=disenchanter,
        mats=tuple(MatYield(mat, q * n) for mat, q in expected.items()),
        listings=n,
        disenchant=DisenchantFlip(group, tuple(bought)),
    )


def _mats_value(
    expected: Mapping[str, float],
    added: Mapping[str, float],
    valuer: "_Valuer",
    sources: "_Sources",
    config: Config,
) -> float:
    """What one more Disenchant's `expected` mats bring, each at the margin (ADR-0018):
    the held units, then the `added` ones, take a mat's room first, and the part of it past
    one way's room goes to the next best."""
    value = 0.0
    for mat, q in expected.items():
        ahead, left = valuer.held.get(mat, 0) + added.get(mat, 0), q
        while left > 1e-9:
            at = valuer.after({}, {**valuer.held, mat: ahead})  # a fresh outlet, nothing bought
            out = _way_out(mat, at, config, sources)
            if out is None:
                break
            take = left if out.units is None else min(left, out.units)
            value += take * out.value
            left -= take
            ahead += take
    return value


def _way_out(
    item_key: str, valuer: "_Valuer", config: Config, sources: "_Sources | None" = None
) -> _WayOut | None:
    """The best of an Item Key's ways out for one more unit, or None without any: Vendor,
    Sell, or with `sources` a Craft it's a reagent of or Disenchant. A way with no units
    left isn't one.

    The Valuer remembers it for the pass (#141): the Buy Unders, the Loot Alert and the
    Flips to Disenchant ask ~26k times, and the Disenchant and Craft ways ask again
    inside. Nothing the answer reads changes while the Valuer is alive: a Valuer with
    other units held or bought is a new one (`after`), and these `sources` are never
    committed to. The entry holds `sources` and `config`, so neither id is reused."""
    key = (item_key, None if sources is None else id(sources))
    known = valuer.ways_out.get(key)
    if known is not None and known[0] is sources and known[1] is config:
        return known[2]
    out = _best_way_out(item_key, valuer, config, sources)
    valuer.ways_out[key] = (sources, config, out)
    return out


def _best_way_out(
    item_key: str, valuer: "_Valuer", config: Config, sources: "_Sources | None"
) -> _WayOut | None:
    """`_way_out` worked out afresh, with nothing remembered."""
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
    """One more unit posted as a Flip would post it (`_Valuer.flip_post_at`), after the
    cut, the effort of posting it and the deposits it's expected to lose queued behind the
    unbound held units. It's good for what sells within Days to Sell (#109) after
    them, counting only the Sale Events at or above that price (#107)."""
    held = valuer.held.get(item_key, 0)
    post_at = valuer.flip_post_at(item_key)
    demand = _demand_at(valuer.rates.get(item_key), post_at)
    room = _flip_room(demand, config, config.days_to_sell_or_horizon_seconds) - held
    if room <= 0:
        return None
    lost = _flip_queue(valuer.queue(item_key, flips=True), demand, config).lost(held)
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
    every_lot = prediction_lots(conn, config, market, predictions)
    times = scan_times(conn, market)
    result = []
    for p in due:
        if p.name in frozen:
            result.append(frozen[p.name])
            continue
        graded_at = ended_at(p) + config.sale_horizon_seconds
        settled = settle(p, every_lot, graded_at, auction_cut(market, config))
        # Valued together, so open units that yield the same mats share them (#102).
        open_units = {k: Holding(bags=units) for k, units in settled.open_units.items() if units}
        open_value = sum(exit_values(conn, config, market, open_units, graded_at).values())
        grade = Grade(p.name, graded_at, settled.proceeds, open_value, settled.cost)
        # Once a Scan at or after its grading moment is in, what it rests on is too.
        if config.grades_path is not None and times and times[-1] >= graded_at:
            freeze_grade(config.grades_path, market, grade)
        result.append(grade)
    return result


def market_lots(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    predictions: Sequence[Prediction],
    seen: Sequence[Listing] | None = None,
) -> list[Lot]:
    """The Market's Lots, For Use Purchases starting none (ADR-0025). `seen` is the
    Market's `listings`, when the caller has them already (#105)."""
    return market_lots_with_crafts(conn, config, market, predictions, seen).lots


def market_lots_with_crafts(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    predictions: Sequence[Prediction],
    seen: Sequence[Listing] | None = None,
) -> LotsWithCrafts:
    """`market_lots`, and the crafts that opened no Lot for uncosted reagents (#114)."""
    seen = listings(conn, market) if seen is None else seen
    market_purchases = purchases(conn, market)
    linked = link_sales(outcomes(conn, market), seen, market_purchases)
    held = held_at_writing(conn, config, market, predictions)
    kept = split_purchases(conn, config, market, predictions, market_purchases).kept
    return lots_with_crafts(kept, linked, predictions, held, lot_craft_results(conn, market))


def lot_craft_results(conn: sqlite3.Connection, market: Market) -> list[LotCraftResult]:
    """The Market's Craft Results as Lots see them (#44): the recipe's reagents used up,
    and its output units, the recipe's fewest when the Addon couldn't count them. Merchant
    Costs are as of the Character Read that carried the craft: the Addon records a
    session's Merchant Costs at logout, on that same Read, so a reagent first bought from
    a merchant that session has one."""
    read_times = character_read_times(conn, market)
    costs: dict[int, dict[int, float]] = {}
    result = []
    for craft in crafts(conn, market):
        times = read_times[craft.character]
        # Its session's Read, or the latest if a clock ran off.
        carried_at = times[min(bisect.bisect_left(times, craft.at), len(times) - 1)]
        if carried_at not in costs:
            costs[carried_at] = merchant_costs(conn, market, carried_at)
        merchant = costs[carried_at]
        used: Counter[str] = Counter()
        for reagent in craft.reagents:
            used[str(reagent.item_id)] += reagent.quantity
        result.append(
            LotCraftResult(
                craft.at,
                used,
                None if craft.output_item_id is None else str(craft.output_item_id),
                craft.quantity or craft.quantity_min or 0,
                {k: merchant[int(k)] for k in used if int(k) in merchant},
                craft.recipe_id,
            )
        )
    return result


def prediction_lots(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    predictions: Sequence[Prediction],
    seen: Sequence[Listing] | None = None,
) -> list[Lot]:
    """The Market's Prediction Lots, without working out what any Scan named: other Lots
    never close a Prediction's units, as those before it was written are folded into its
    held Lot and those after it ended are younger. `seen` as in `market_lots`."""
    if not predictions:
        return []
    seen = listings(conn, market) if seen is None else seen
    market_purchases = purchases(conn, market)
    linked = link_sales(outcomes(conn, market), seen, market_purchases)
    held = held_at_writing(conn, config, market, predictions)
    under = [p for p in market_purchases if bought_under(p, predictions) is not None]
    return lots(under, linked, predictions, held)


class Split(NamedTuple):
    """Purchases split by whether they start a Lot (ADR-0025)."""

    kept: list[Purchase]  # named by the Brain, or under a Prediction
    for_use: list[Purchase]


def split_purchases(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    predictions: Sequence[Prediction],
    bought: Sequence[Purchase],
) -> Split:
    """`bought` split into the Purchases that start Lots and the For Use ones (ADR-0025),
    working out what each Scan before one named the first time it's needed (`rework`).
    A Flip to Sell row frozen for a Scan names its Item Key too, so a Flip matched to a
    row frozen before its Scan's named set (ADR-0023) always has its Lots."""
    times = scan_times(conn, market)
    frozen = load_frozen(config.grades_path, market)
    named = dict(frozen.named)
    for p in bought:
        scan_at = scan_before(times, happened_at(p))
        if scan_at is None or scan_at in named or bought_under(p, predictions) is not None:
            continue
        named[scan_at] = rework(conn, config, market, predictions, scan_at).named
    for scan_at, rows in frozen.shown.items():
        if scan_at in named:
            items = dict(named[scan_at].items)
            for r in rows.values():
                items[r.item_key] = max(r.dearest, items.get(r.item_key, r.dearest))
            named[scan_at] = replace(named[scan_at], items=items)
    table = _disenchant_table()
    info = item_info(conn, market.era)

    def group_of(item_key: str) -> GroupKey | None:
        item_id = item_id_of(item_key)
        g = table.group(item_id, info[item_id]) if item_id in info else None
        return None if g is None else g.key

    result = Split([], [])
    for p in bought:
        use = is_for_use(p, predictions, times, named, group_of)
        (result.for_use if use else result.kept).append(p)
    return result


class Reworked(NamedTuple):
    """What a past Scan showed, worked out again."""

    shown: dict[str, Named]  # its Flip to Sell rows by Item Key (#60)
    named: NamedSet  # what it named to buy (#55)
    flips_to_craft: tuple[NamedCraft, ...]  # its Flip to Craft rows (#114)


def rework(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    predictions: Sequence[Prediction],
    scan_at: int,
) -> Reworked:
    """What the Scan requested at `scan_at` showed, worked out again the way the replay
    does (#80): its Flip to Sell rows by Item Key (#60), what it named to buy (#55), and
    its Flip to Craft rows (#114). Worked out once for all three, and frozen in grades.toml
    when there is one, where the caller reads them from later."""
    m = recommend_market(
        # Working out a past Scan never freezes a Prediction's Grade.
        conn,
        replace(config, grades_path=None),
        market,
        predictions,
        scan_at,
        as_of=scan_at,
        paid=False,
        loot_alert=False,
    )
    shown = {
        r.item_key: Named(
            r.item_key,
            r.quantity,
            int(r.price),
            r.post_at,
            r.profit,
            r.days,
            config.sale_horizon_seconds,
        )
        for r in m.shopping_list
        if r.action is Action.SELL
    }
    flips_to_craft = tuple(
        NamedCraft(
            r.item_key,
            r.recipe_id,
            r.character,
            r.made.units,
            tuple(
                NamedBuy(b.item_key, b.quantity, b.max_unit_price) for b in r.buys if not b.merchant
            ),
            r.post_at,
            r.profit,
            r.days,
            config.sale_horizon_seconds,
        )
        for r in m.shopping_list
        if r.action is Action.CRAFT and r.made is not None and r.recipe_id is not None
    )
    named = named_set(m)
    if config.grades_path is not None:
        horizon = config.sale_horizon_seconds
        freeze_shown(config.grades_path, market, scan_at, horizon, list(shown.values()))
        freeze_named(config.grades_path, market, scan_at, named)
        freeze_shown_crafts(config.grades_path, market, scan_at, horizon, flips_to_craft)
    return Reworked(shown, named, flips_to_craft)


def _lot_costs(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    predictions: Sequence[Prediction],
    seen: Sequence[Listing] | None = None,
) -> dict[tuple[str, str], list[tuple[float, int]]]:
    """The open units of each Prediction's Lots and what each of them cost, oldest Lot
    first, by (Prediction, Item Key). `seen` as in `market_lots`."""
    if not predictions:
        return {}
    result: dict[tuple[str, str], list[tuple[float, int]]] = {}
    for lot in prediction_lots(conn, config, market, predictions, seen):
        if lot.open_units:
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
    bound: Mapping[str, Mapping[str, int]] = MappingProxyType({}),
) -> dict[str, float]:
    """What each Item Key's `held` units would have brought by their best Actions, as
    `_exit_value` values them: Best Exit Value (#76). The Disenchant way is valued over
    all of `held` at once, as the Holdings Disenchant Actions are, so held mats and the
    mats other Item Keys yield take the Sale Horizon first (#102). Each Item Key gets its
    own Disenchant proceeds and the worth of its units left. `bound` is who holds the
    bound units (`_disenchants`); without it, none is Disenchanted."""
    scanned = [t for t in scan_times(conn, market) if t <= at]
    scan = scanned[-1] if scanned else None
    valuer, _ = _valuer(
        conn, config, market, scan, unbound=_unbound_units(dict(held)), skills_as_of=at
    )
    rows, left = _disenchants(held, valuer, bound=bound)
    proceeds: Counter[str] = Counter()
    for row in rows:
        proceeds[row.item_key] += row.profit
    return {key: proceeds[key] + valuer.worth(key, left[key]) for key in held}


def market_bound(
    conn: sqlite3.Connection, market: Market, characters: list[str], as_of: int | None = None
) -> dict[str, dict[str, int]]:
    """Who of the Market's Characters holds each Item Key's bound units, and how many."""
    return _bound_by(_by_character(conn, market, characters, as_of))


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
    seen: Sequence[Listing] | None = None,
    fair_value_cache: FairValueCache | None = None,
    skills_as_of: int | None = None,
    pricer: Pricer | None = None,
) -> tuple["_Valuer", list[_VendorBuy | _FlipToSell]]:
    """The Market's Valuer as of its Scan requested at `at` (none without one), and the
    Flips in that Scan, none of them taken as bought (#86). Item Keys `under` a
    Prediction aren't Flipped. `unbound` is the player's unbound held units by Item Key,
    which take the Sale Horizon before any Flip to Sell (#67). `seen` as in
    `market_lots`, and `fair_value_cache` as in `recommend`. The Enchanting skills are
    the latest, or as of `skills_as_of` (#103). `pricer` as in `recommend_market`."""
    # With a cache, its Listings: what it keeps below is worked out from them (#143).
    cache = fair_value_cache
    if cache is not None:
        seen = cache.listings(conn, market)
    elif seen is None:
        seen = listings(conn, market)
    scanned = at is not None
    supply = (
        _scan_only(cache, conn, market, ("supply_at", at), lambda: supply_at(conn, market, at))
        if scanned
        else {}
    )
    others = (
        _scan_only(
            cache,
            conn,
            market,
            ("others_at", at),
            lambda: supply_at(conn, market, at, others_only=True),
        )
        if scanned
        else {}
    )
    rates = sell_rates(conn, market, config, at, seen, fair_value_cache=cache) if scanned else {}
    vendor = vendor_prices(conn, market.era)
    merchant = _merchant(conn, market)
    cut = auction_cut(market, config)
    # Like Vendor Prices, the latest seen: a deposit rate doesn't move.
    linked = link_sales(outcomes(conn, market), seen, purchases(conn, market))
    valuer = _Valuer(
        supply,
        others,
        {},
        rates,
        vendor,
        merchant,
        cut,
        non_stacking(conn, market, seen),
        deposits(linked),
        config,
        disenchanting=_Disenchanting(
            _disenchant_table(),
            item_info(conn, market.era),
            enchanting_skills(conn, market, skills_as_of),
        ),
        pricer=pricer,
        listed=_scan_only(
            cache,
            conn,
            market,
            ("others_lows", at),
            lambda: _others_lows(seen, [t for t in scan_times(conn, market) if t <= at]),
        )
        if scanned
        else {},
    )
    return valuer.flips(under, unbound)


def _scan_only[T](
    cache: FairValueCache | None,
    conn: sqlite3.Connection,
    market: Market,
    what: tuple,
    work: Callable[[], T],
) -> T:
    """`work`, kept in the cache's `scan_only` if there's a cache."""
    return work() if cache is None else cache.scan_only(conn, market, what, work)


def _others_lows(
    seen: Sequence[Listing], scans: Sequence[int]
) -> dict[str, tuple[tuple[int, int], ...]]:
    """The cheapest other player's unit buyout per Item Key in each of `scans` (oldest
    first), as (Scan, unit buyout) from the latest back to the last before it with none
    of that Item Key listed (#135)."""
    # Each Listing as the range of `scans` it was up in, latest end first.
    spans: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for x in seen:
        first = bisect.bisect_left(scans, x.first_seen)
        end = bisect.bisect_right(scans, x.last_seen)
        if not x.own and first < end:
            spans[x.item_key].append((end, first, x.unit_buyout))
    stretches = {}
    for item_key, ranges in spans.items():
        ranges.sort(reverse=True)
        # Walk back from the latest Scan while the Listings' ranges leave no Scan out.
        start = len(scans)
        for end, first, _ in ranges:
            if end < start:
                break
            start = min(start, first)
        unit_at: dict[int, int] = {}
        for end, first, unit in ranges:
            for i in range(max(first, start), end):
                unit_at[i] = min(unit_at.get(i, unit), unit)
        if start < len(scans):
            stretches[item_key] = tuple(
                (scans[i], unit_at[i]) for i in reversed(range(start, len(scans)))
            )
    return stretches


def _by_item(rates: Mapping[str, SellRate]) -> dict[int, tuple[str, ...]]:
    """The Item Keys with a Sell Rate, by itemID: each random suffix of an item (#58)."""
    keys: dict[int, list[str]] = defaultdict(list)
    for item_key in sorted(rates):
        keys[item_id_of(item_key)].append(item_key)
    return {item_id: tuple(k) for item_id, k in keys.items()}


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
        able = self.disenchanters(item_key)
        if not able:
            return None
        group = self.group(item_key)
        return able[0], {str(mat): q for mat, q in group.expected.items()}

    def disenchanters(self, item_key: str) -> list[str]:
        """The Characters who can Disenchant an Item Key, by name."""
        info = self.info.get(item_id_of(item_key))
        group = self.group(item_key)
        return self._able(self.table.required_skill(info.item_level) if group else None)

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
    `non_stacking` are the Item Keys that don't stack (#73). A `pricer` replaces the Sell
    Rate in the Holdings rows, the Flips and the Flip to Craft outputs (#84). Held units
    also count their sibling suffixes' Sale Events (`held_rate`, #58); nothing else does."""

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
        pricer: Pricer | None = None,
        by_item: Mapping[int, tuple[str, ...]] | None = None,
        listed: Mapping[str, tuple[tuple[int, int], ...]] = MappingProxyType({}),
        own_cheapest: dict[str, int | None] | None = None,
    ):
        self.supply, self.others, self.flipped = supply, others, flipped
        self.listed = listed
        self.rates, self.vendor, self.merchant = rates, vendor, merchant
        self.cut, self.non_stacking, self.deposits = cut, non_stacking, deposits
        self._config, self.held = config, held
        self.disenchanting, self._pricer = disenchanting, pricer
        self._by_item = _by_item(rates) if by_item is None else by_item
        self._worth: dict[tuple[str, Holding], float] = {}  # Sub-crafts ask it a lot (#33)
        self._held_rates: dict[str, tuple[SellRate | None, int]] = {}
        # The cheapest of the player's own Listings by Item Key. `supply` and `others`
        # don't change, so every Valuer `after` this one shares it (#141).
        self._own_cheapest: dict[str, int | None] = {} if own_cheapest is None else own_cheapest
        # `_way_out`'s answers by (Item Key, id of its Sources), with the Sources and
        # Config they were for.
        self.ways_out: dict[
            tuple[str, int | None], tuple[_Sources | None, Config, _WayOut | None]
        ] = {}

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
            self._pricer,
            self._by_item,
            self.listed,
            self._own_cheapest,
        )

    def cheap(self, item_key: str) -> _Cheap:
        """The cheapest other player's Listing of an Item Key in each Scan back from this
        one, for a buy that takes the cheapest of them to Sell (#132, #135)."""
        return _Cheap(self.listed.get(item_key, ()))

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
        """The Item Key's sale queue, at its Sell Rate under the Flip priors, or at its
        held units' (`held_rate`) under the Holdings priors."""
        c = self._config
        if flips:
            rate = self.rates.get(item_key)
            priors = (c.sell_rate_prior_hours_flips, c.sale_size_prior_events_flips)
        else:
            rate, _ = self.held_rate(item_key)
            priors = (c.sell_rate_prior_hours_holdings, c.sale_size_prior_events_holdings)
        per_day = _units_per_day(rate, *priors)
        return _Queue(per_day / 24, self.deposit(item_key), c.post_duration_hours)

    def sale_queue(self, item_key: str, flips: bool) -> _Queue:
        """The queue a Sell or Flip waits in: `queue`, or with a pricer one that loses no
        deposits (#84)."""
        if self._pricer is None:
            return self.queue(item_key, flips)
        return _Queue(0.0, 0.0, self._config.post_duration_hours)

    def priced(self, item_key: str) -> Callable[[int | None], float | None] | None:
        """The pricer's price for an Item Key from the cheapest other player's unit price
        left, never above what a merchant charges (#63); None without a pricer."""
        if self._pricer is None:
            return None
        pricer, merchant = self._pricer, self.merchant.get(item_key)

        def price(cheapest: int | None) -> float | None:
            post_at = pricer(item_key, cheapest)
            return None if post_at is None else _ceiling(post_at, merchant)

        return price

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
            for item_key in sorted(self.others)
            if item_key not in under
            for buy in self._flips_of(item_key, unbound.get(item_key, 0), self.priced(item_key))
        ]
        return self.after({}, unbound), buys

    def clearing_run(self, item_key: str) -> "_SellRun | None":
        """The shortest run of an Item Key's cheapest offers that a Flip to Sell would
        clear the margin on if room were no limit, posted as `_flips` posts it, behind
        the held units, with the minimum of Sale Events at that price (#108). A wall only
        clears once all of it is bought. A pricer lifts `_flips`' room limit, so this one
        posts as `_flips` does without one."""
        own = _cheapest(without(self.supply[item_key], self.others[item_key]))
        merchant, config = self.merchant.get(item_key), self._config

        def undercut(cheapest: int | None) -> float | None:
            return _undercut(cheapest, own, config, merchant)

        flips = self._flips_of(item_key, self.held.get(item_key, 0), undercut)
        runs = [run for buy in flips if isinstance(buy, _FlipToSell) for run in buy.runs]
        least = self._config.flip_min_sale_events
        return next((run for run in runs if run.sale_events >= least), None)

    def _flips_of(
        self, item_key: str, held: int, pricer: Callable[[int | None], float | None] | None
    ) -> list[_VendorBuy | _FlipToSell]:
        """`_flips` of an Item Key in this Scan, behind `held` units, posted by `pricer`."""
        return _flips(
            item_key,
            self.others[item_key],
            self.supply[item_key],
            self.rates.get(item_key),
            self.vendor.get(item_id_of(item_key)),
            self.merchant.get(item_key),
            held,
            self.sale_queue(item_key, flips=True),
            self.effort(item_key),
            self.stack(item_key),
            self.cut,
            self._config,
            pricer,
            self.cheap(item_key),
        )

    def stack(self, item_key: str) -> float:
        """The units of an Item Key a Flip posts per stack (#98): its usual Sale Event
        size under the Flip prior, or 1 if it doesn't stack."""
        if item_key in self.non_stacking:
            return 1.0
        return _sale_size(self.rates.get(item_key), self._config.sale_size_prior_events_flips)

    def post_at(self, item_key: str) -> float | None:
        """The price to post one held unit at once `flipped` is bought (`_post_at`), never
        above the dearest Sale Event (#41), its own or a sibling suffix's (#58)."""
        rates = [self.rates.get(item_key), *self._sibling_rates(item_key)]
        dearest = [r.max_sale_price for r in rates if r is not None]
        return self._post_at_or_under(
            item_key, max((p for p in dearest if p is not None), default=None)
        )

    def held_rate(self, item_key: str) -> tuple[SellRate | None, int]:
        """The Sell Rate a held unit of an Item Key counts on, and how many sibling Sale
        Events are in it (#58, ADR-0022). Its own Sale Events, plus its siblings' (the
        Market's other suffixes of its itemID) priced at or above its `post_at`, each of
        those counting `suffix_pool_weight` of a Sale Event and of its units. Demand is
        pooled, never price: without a price to post at, no sibling counts."""
        if item_key not in self._held_rates:
            own, post_at = self.rates.get(item_key), self.post_at(item_key)
            kept = (
                [r.at_or_above(post_at) for r in self._sibling_rates(item_key)]
                if own is not None and post_at is not None
                else []
            )
            events = sum(r.sale_events for r in kept)
            if not events:
                self._held_rates[item_key] = own, 0
            else:
                w = self._config.suffix_pool_weight
                pooled = replace(
                    own,
                    units_per_day=own.units_per_day + w * sum(r.units_per_day for r in kept),
                    sale_events=own.sale_events + w * events,
                    sale_units=own.sale_units + w * sum(r.sale_units for r in kept),
                )
                self._held_rates[item_key] = pooled, events
        return self._held_rates[item_key]

    def _sibling_rates(self, item_key: str) -> list[SellRate]:
        """The Sell Rates of an Item Key's sibling suffixes, none when they don't count."""
        if not self._config.suffix_pool_weight:
            return []
        siblings = self._by_item.get(item_id_of(item_key), ())
        return [self.rates[k] for k in siblings if k != item_key]

    def flip_post_at(self, item_key: str) -> float | None:
        """The price to post one unit bought to Sell at once `flipped` is bought. Only a
        merchant caps it: the demand at the price does the rest (#107)."""
        return self._post_at_or_under(item_key, None)

    def _post_at_or_under(self, item_key: str, cap: float | None) -> float | None:
        if (price := self.priced(item_key)) is not None:
            left = without(self.others.get(item_key, []), self.flipped.get(item_key, []))
            return price(_cheapest(left))
        others = self.others.get(item_key, [])
        if item_key not in self._own_cheapest:
            self._own_cheapest[item_key] = cheapest_without(self.supply.get(item_key, []), others)
        return _undercut(
            cheapest_without(others, self.flipped.get(item_key, [])),
            self._own_cheapest[item_key],
            self._config,
            _ceiling(cap, self.merchant.get(item_key)),
        )

    def rows(self, item_key: str, holding: Holding) -> list[Row]:
        own = self.rates.get(item_key)
        rate, sibling_sales = self.held_rate(item_key)
        has_data = self.has_data(item_key)
        post_at = self.post_at(item_key) if has_data else None
        c = self._config
        room = (
            math.inf
            if self._pricer is not None
            else sellable_units(
                rate,
                c.sell_rate_prior_hours_holdings,
                c.sale_size_prior_events_holdings,
                c.sale_horizon_seconds,
            )
        )
        return _holding_rows(
            item_key,
            holding,
            has_data,
            post_at,
            room,
            own.sale_events if own else None,
            sibling_sales if self._pricer is None else 0,  # a pricer ignores Sell Rate
            self.vendor.get(item_id_of(item_key)),
            self.sale_queue(item_key, flips=False),
            self.cut,
        )

    def has_data(self, item_key: str) -> bool:
        """Whether there's a Fair Value and a Sell Rate with sales to value it by, or with
        a pricer, whether it has a price (#84)."""
        if self._pricer is not None:
            return self.post_at(item_key) is not None
        rate, _ = self.held_rate(item_key)
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

    def worth_with(self, item_key: str, holding: Holding, extra: float) -> float:
        """`worth` of `holding` plus `extra` unbound units, a fraction of a unit counting
        that fraction of the next whole unit's worth (expected Disenchant mats, #76)."""
        whole = math.floor(extra)
        below = self.worth(item_key, _plus(holding, Holding(bags=whole)))
        if extra == whole:
            return below
        above = self.worth(item_key, _plus(holding, Holding(bags=whole + 1)))
        return below + (extra - whole) * (above - below)


@dataclass(frozen=True)
class _NextUnit:
    """The next unit of an Item Key to Disenchant: who does it, what's left of the Item
    Key's Holding after it, and whether it's a bound one."""

    character: str
    left: Holding
    bound: bool


def _holders(
    bound: Mapping[str, int], disenchanting: _Disenchanting, item_key: str
) -> Counter[str]:
    """The bound units of an Item Key held by Characters who can Disenchant it, by holder."""
    able = set(disenchanting.disenchanters(item_key))
    return Counter({c: n for c, n in bound.items() if c in able})


def _disenchants(
    held: Mapping[str, Holding],
    valuer: _Valuer,
    under: set[str] = frozenset(),
    bound: Mapping[str, Mapping[str, int]] = MappingProxyType({}),
) -> tuple[list[Row], dict[str, Holding]]:
    """The Disenchant Actions (#76) and what's left of `held` after them. Item Keys
    `under` a Prediction are Held instead. `bound` is who holds the bound units, by Item
    Key, then Character.

    The same marginal rule as Craft (ADR-0008): each step Disenchants the one unit that
    gains the most, its expected mats' worth less what the unit would bring by Sell or
    Vendor, until no unit gains. A mat's worth is that of its Holdings with the expected
    mats added, on top of the ones earlier steps are expected to yield, a fraction of a unit
    counting that fraction of the next whole unit. Bound units go first, since they'd only
    be Vendored, but only those whose holder can Disenchant them: they can't be mailed
    (#102). Unbound units can, so any Character who can Disenchant them does.
    """
    left = dict(held)
    ways = {
        key: way
        for key in held
        if key not in under
        and valuer.disenchanting
        and (way := valuer.disenchanting.way(key)) is not None
    }
    holders = {key: _holders(bound.get(key, {}), valuer.disenchanting, key) for key in ways}

    def next_unit(key: str) -> _NextUnit | None:
        """Who Disenchants the Item Key's next unit, or None if no unit left can be."""
        h = left[key]
        holder = min((c for c, n in holders[key].items() if n), default=None)
        if holder is not None and _bound(h):
            return _NextUnit(holder, _take(h, 1), bound=True)
        if _unbound(h):
            return _NextUnit(ways[key][0], _take_unbound(h), bound=False)
        return None

    added: Counter[str] = Counter()  # expected mats from the steps so far, in fractions
    done: Counter[tuple[str, str]] = Counter()
    proceeds: Counter[tuple[str, str]] = Counter()
    while True:
        best = None
        for key, (_, mats) in ways.items():
            if (unit := next_unit(key)) is None:
                continue
            value = sum(
                valuer.worth_with(mat, held.get(mat, Holding()), added[mat] + q)
                - valuer.worth_with(mat, held.get(mat, Holding()), added[mat])
                for mat, q in mats.items()
            )
            gain = value - (valuer.worth(key, left[key]) - valuer.worth(key, unit.left))
            if gain > 0 and (best is None or gain > best[0]):
                best = (gain, key, value, unit)
        if best is None:
            break
        _, key, value, unit = best
        left[key] = unit.left
        if unit.bound:
            holders[key][unit.character] -= 1
        added.update(ways[key][1])
        done[key, unit.character] += 1
        proceeds[key, unit.character] += value
    rows = [
        Row(
            key,
            Action.DISENCHANT,
            n,
            profit=proceeds[key, who],
            note=f"on {who}: expect "
            + ", ".join(f"{q * n:.2f} of {mat}" for mat, q in ways[key][1].items()),
            character=who,
            mats=tuple(MatYield(mat, q * n) for mat, q in ways[key][1].items()),
        )
        for (key, who), n in done.items()
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


def _bound_by(by_character: dict[str, dict[str, Holding]]) -> dict[str, dict[str, int]]:
    """Who holds each Item Key's bound units, and how many: they can't be mailed."""
    bound: dict[str, dict[str, int]] = {}
    for character, held in by_character.items():
        for item_key, h in held.items():
            if _bound(h):
                bound.setdefault(item_key, {})[character] = _bound(h)
    return bound


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
    room: float,
    sale_events: int | None,
    sibling_sales: int,
    vendor_price: int | None,
    queue: _Queue,
    cut: float,
) -> list[Row]:
    """How held units split between Sell, posted at `post_at` like a Flip (#64), and
    Vendor. With no Listing to price against there's no `post_at`, and they're Vendored.
    At most `room` units Sell: those that sell within the Sale Horizon.
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
        sellable = min(unbound, room)
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
                    sale_events=sale_events,
                    sibling_sales=sibling_sales or None,
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


# A Craft Chain node: the craft it feeds (`_Part.at`), its kind and its Item Key.
_NodeId = tuple[tuple[str, ...], NodeKind, str]


@dataclass(frozen=True)
class _Part:
    """Some crafts' share of one Craft Chain node (#77). `at` is the craft it feeds, as
    the Item Keys from the top output down, or () for an exit."""

    at: tuple[str, ...]
    kind: NodeKind
    item_key: str
    quantity: int
    gold: float = 0.0
    crafts: int = 0
    character: str = ""
    max_unit_price: float | None = None
    post_at: float | None = None
    cut: float = 0.0
    deposit: float = 0.0
    effort: float = 0.0

    @property
    def id(self) -> "_NodeId":
        return self.at, self.kind, self.item_key

    def plus(self, other: "_Part") -> "_Part":
        return replace(
            self,
            quantity=self.quantity + other.quantity,
            gold=self.gold + other.gold,
            crafts=self.crafts + other.crafts,
            max_unit_price=max(
                (p for p in (self.max_unit_price, other.max_unit_price) if p is not None),
                default=None,
            ),
            post_at=other.post_at if other.post_at is not None else self.post_at,
            cut=self.cut + other.cut,
            deposit=self.deposit + other.deposit,
            effort=self.effort + other.effort,
        )

    def node(self, children: tuple[ChainNode, ...] = ()) -> ChainNode:
        kind = self.kind
        return ChainNode(
            kind,
            self.item_key,
            self.quantity,
            sum(c.gold for c in children) if kind is NodeKind.CRAFT else self.gold,
            children,
            crafts=self.crafts if kind is NodeKind.CRAFT else None,
            character=self.character,
            post_at=self.post_at,
            max_unit_price=self.max_unit_price,
            cut=self.cut if kind is NodeKind.SELL else None,
            deposit=self.deposit if kind is NodeKind.SELL else None,
            effort=self.effort if kind in (NodeKind.SELL, NodeKind.BUY) else None,
        )


def _exits(
    item_key: str,
    units: int,
    selling: int,
    sold: float,
    vendored: float,
    post_at: float | None,
    resale: float | None,
    effort: int,
) -> list[_Part]:
    """A craft's exit parts: `selling` of its `units` bring `sold`, posted at `post_at`
    and `resale` after the cut, less the `effort` of posting each, and the rest bring
    `vendored`."""
    if selling == units:
        sold, vendored = sold + vendored, 0.0
    parts = []
    if selling and post_at is not None and resale is not None:
        gross, cut, posting = selling * post_at, selling * (post_at - resale), selling * effort
        parts.append(
            _Part(
                (),
                NodeKind.SELL,
                item_key,
                selling,
                sold,
                post_at=post_at,
                cut=cut,
                deposit=gross - cut - posting - sold,
                effort=posting,
            )
        )
    if units - selling:
        parts.append(_Part((), NodeKind.VENDOR, item_key, units - selling, vendored))
    return parts


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
    # The Craft Chain's parts across the crafts, by node (#77).
    parts: dict[_NodeId, _Part] = field(default_factory=dict)

    @property
    def output(self) -> str:
        return str(self.recipe.output_item_id)

    @property
    def needs(self) -> dict[str, int]:
        needs: Counter[str] = Counter()
        for reagent in self.recipe.reagents:
            needs[str(reagent.item_id)] += reagent.quantity
        return needs

    def add(self, chain: "_Chain", parts: list[_Part]) -> None:
        """Count one more craft's chain, and its Craft Chain `parts`, into the row."""
        for part in parts:
            had = self.parts.get(part.id)
            self.parts[part.id] = part if had is None else had.plus(part)
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
            chain=self.chain(),
            merchant_gold=self.gold,
            recipe_id=self.recipe.recipe_id,
        )

    def chain(self) -> tuple[ChainNode, ...]:
        """The Craft Chain (#77): the exits, the last over the craft and its sources."""
        exits = [p.node() for p in self.parts.values() if not p.at]
        if not exits:
            return ()
        return (*exits[:-1], replace(exits[-1], children=(self.top(),)))

    def top(self) -> ChainNode:
        """The Craft Chain's craft node, over its sources."""
        return self._node(
            _Part(
                (),
                NodeKind.CRAFT,
                self.output,
                self.crafts * self.recipe.quantity_min,
                crafts=self.crafts,
                character=self.character,
            )
        )

    def _node(self, part: _Part) -> ChainNode:
        if part.kind is not NodeKind.CRAFT:
            return part.node()
        below = (*part.at, part.item_key)
        return part.node(tuple(self._node(p) for p in self.parts.values() if p.at == below))


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
                    chain=_blocked_chain(plan, why_blocked, sources),
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
        plan.add(chain, sources.parts(chain) + _held_exits(plan, sources))
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


def _blocked_chain(plan: _Plan, why: Blocked | None, sources: "_Sources") -> tuple[ChainNode, ...]:
    """A blocked Craft row's Craft Chain (#77): one craft as it would be sourced, with no
    exit. A reagent without data is used with no gold, and blocks it; an unknown bind type
    blocks the craft itself."""
    key = why.item_key if why else ""
    chain = sources.chain_without(plan, key) if key else sources.chain(plan)
    if chain is None:
        return ()
    one = _Plan(plan.recipe, plan.character, crafts=1)
    one.add(chain, sources.parts(chain))
    top = one.top()
    if key:
        use = ChainNode(NodeKind.USE, key, plan.needs[key], None, blocked=why)
        top = replace(top, gold=None, children=(*top.children, use))
    elif why:
        top = replace(top, blocked=why)
    return (top,)


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


def _held_exits(plan: _Plan, sources: "_Sources") -> list[_Part]:
    """One more Craft Action's exit parts (#77): the units its output adds to what Sells
    and what's Vendored, and what each brings, as `_step` gains them."""
    out, valuer = plan.output, sources.valuer
    now = _plus(sources.held.get(out, Holding()), sources.crafted.get(out, Holding()))
    after = _crafted(plan, now)

    def sells(holding: Holding) -> tuple[int, float, float | None]:
        """The units that Sell, what they bring, and their post price."""
        rows = [r for r in valuer.rows(out, holding) if r.action is Action.SELL]
        return (
            sum(r.quantity for r in rows),
            sum(r.profit or 0.0 for r in rows),
            rows[0].price if rows else None,
        )

    # Held units Sell first, so one more craft's units only add to what Sells.
    (selling_now, sold_now, _), (selling_after, sold_after, post_at) = sells(now), sells(after)
    sold = sold_after - sold_now
    gain = valuer.worth(out, after) - valuer.worth(out, now)
    return _exits(
        out,
        plan.recipe.quantity_min,
        selling_after - selling_now,
        sold,
        gain - sold,
        post_at,
        None if post_at is None else post_at * (1 - valuer.cut),
        effort=0,  # Holdings never pay it (#73)
    )


@dataclass
class _Chain:
    """One craft's reagents, sourced (ADR-0014), down through its Sub-crafts."""

    taken: Counter[str] = field(default_factory=Counter)  # held units used, by reagent
    merchant: Counter[str] = field(default_factory=Counter)  # units bought from a merchant
    asks: dict[str, Supply] = field(default_factory=dict)  # Auction House units bought
    via: list[tuple[int, SubCraft]] = field(default_factory=list)  # with how deep
    leftovers: dict[str, Holding] = field(default_factory=dict)
    recipes: Counter[int] = field(default_factory=Counter)  # Sub-crafts per recipe
    # Its Craft Chain parts (#77), held units and leftovers not valued yet (_Sources.parts).
    parts: list[_Part] = field(default_factory=list)

    def copy(self) -> "_Chain":
        return _Chain(
            Counter(self.taken),
            Counter(self.merchant),
            {key: list(units) for key, units in self.asks.items()},
            list(self.via),
            dict(self.leftovers),
            Counter(self.recipes),
            list(self.parts),
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
        return self._craft(plan, 1, 1, frozenset({plan.output}), _Chain(), (plan.output,))

    def chain_without(self, plan: _Plan, item_key: str) -> _Chain | None:
        """One craft of `plan` with every reagent but `item_key` sourced, and `item_key`
        never Sub-crafted on the way (a Buy Under's Craft way, #88); None if they can't
        be."""
        chain: _Chain | None = _Chain()
        path = frozenset({plan.output, item_key})
        for key, n in plan.needs.items():
            if key != item_key and chain is not None:
                chain = self._source(key, n, 1, path, chain, (plan.output,))
        return chain

    def _craft(
        self,
        plan: _Plan,
        crafts: int,
        depth: int,
        path: frozenset[str],
        chain: _Chain,
        at: tuple[str, ...],
    ) -> _Chain | None:
        """`crafts` crafts of `plan` with their reagents sourced, `at` being the Item Keys
        from the top output down to this one."""
        for key, n in plan.needs.items():
            chain = self._source(key, n * crafts, depth, path, chain, at)
            if chain is None:
                return None
        return chain

    def _source(
        self,
        key: str,
        n: int,
        depth: int,
        path: frozenset[str],
        chain: _Chain,
        at: tuple[str, ...],
    ) -> _Chain | None:
        chain = chain.copy()
        have = Holding() if key in self.under else self.held.get(key, Holding())
        left = _units(have) - chain.taken[key]
        if key in self.merchant:
            take, cost = min(n, left), self.merchant[key]
            chain.taken[key] += take
            chain.merchant[key] += n - take
            for kind, units in ((NodeKind.USE, take), (NodeKind.MERCHANT, n - take)):
                if units:
                    chain.parts.append(_Part(at, kind, key, units, -units * cost))
            return chain
        take = min(n, left) if self.valuer.has_data(key) else 0
        chain.taken[key] += take
        if take:
            chain.parts.append(_Part(at, NodeKind.USE, key, take))
        short = n - take
        if not short:
            return chain
        options = [self._bought(key, short, chain, at)] + [
            self._subcrafted(maker, key, short, depth, path, chain, at)
            for maker in self.makers.get(key, [])
        ]
        options = [option for option in options if option is not None]
        return min(options, key=self.cost) if options else None

    def _bought(self, key: str, short: int, chain: _Chain, at: tuple[str, ...]) -> _Chain | None:
        if self.asks is None or key in self.under:
            return None
        bought = cheapest(without(self.asks.get(key, []), chain.asks.get(key, [])), short)
        if bought is None:
            return None
        chain = chain.copy()
        chain.asks.setdefault(key, []).extend(bought)
        effort = self.valuer.effort(key) * short
        chain.parts.append(
            _Part(
                at,
                NodeKind.BUY,
                key,
                short,
                -(sum(unit * n for unit, n in bought) + effort),
                max_unit_price=max(unit for unit, _ in bought),
                effort=effort,
            )
        )
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
        self,
        maker: _Plan,
        key: str,
        short: int,
        depth: int,
        path: frozenset[str],
        chain: _Chain,
        at: tuple[str, ...],
    ) -> _Chain | None:
        crafts = math.ceil(short / maker.recipe.quantity_min)
        recipe_id = maker.recipe.recipe_id
        if not self.may_use(maker, key, crafts, depth, path, chain.recipes[recipe_id]):
            return None
        chain = self._craft(maker, crafts, depth + 1, path | {key}, chain, (*at, key))
        if chain is None:
            return None
        chain.recipes[recipe_id] += crafts
        chain.via.append((depth + 1, SubCraft(key, crafts, maker.character)))
        made = crafts * maker.recipe.quantity_min
        chain.parts.append(
            _Part(at, NodeKind.CRAFT, key, made, crafts=crafts, character=maker.character)
        )
        leftover = made - short
        if leftover:
            chain.parts.append(_Part((*at, key), NodeKind.LEFTOVER, key, leftover))
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
            given_up, left = self._held_worth(chain, key)
            cost += given_up - left
        return cost

    def _held_worth(self, chain: _Chain, key: str) -> tuple[float, float]:
        """What the held units of `key` the chain uses would have brought, and what its
        leftovers of `key` bring."""
        now = _plus(self.held.get(key, Holding()), self.crafted.get(key, Holding()))
        kept = _take(now, chain.taken[key])
        after = _plus(kept, chain.leftovers.get(key, Holding()))
        worth = self.valuer.worth(key, kept)
        return self.valuer.worth(key, now) - worth, self.valuer.worth(key, after) - worth

    def parts(self, chain: _Chain) -> list[_Part]:
        """The chain's Craft Chain parts, each as `cost` counts it (#77): held units at
        what they'd have brought and leftovers at what they bring, split across an Item
        Key's nodes by their units."""
        worth = {
            key: self._held_worth(chain, key)
            for key in {*chain.taken, *chain.leftovers}
            if key not in self.merchant
        }
        parts = []
        for part in chain.parts:
            key = part.item_key
            if part.kind is NodeKind.USE and key in worth:
                share = part.quantity / chain.taken[key]
                part = replace(part, gold=-worth[key][0] * share)
            elif part.kind is NodeKind.LEFTOVER:
                share = part.quantity / _units(chain.leftovers[key])
                part = replace(part, gold=worth[key][1] * share)
            parts.append(part)
        return parts

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
    pricer: Callable[[int | None], float | None] | None = None,
) -> _Outlet:
    """A Flip to Craft output's Sell room, judged as strictly as a Flip's: what sells within
    Days to Sell (#109) under the Flip priors, less the `held` units,
    counting only the Sale Events at or above its post price (#107), and its units wait in
    the `queue` at that rate. It resells like them, posted under the cheapest other Listing,
    as if the Flip to Craft were the only buy (#86), and never above what a merchant charges
    (#63). `others` is other players' asks. A `pricer` (`_Valuer.priced`) sets the post
    price instead, with no room limit (#84)."""
    if pricer is None:
        post_at = _post_at(supply, others, [], config, merchant_cost)
        room = _flip_room(_demand_at(rate, post_at), config, config.days_to_sell_or_horizon_seconds)
    else:
        post_at = pricer(min((unit for unit, _ in others), default=None))
        room = 0 if post_at is None else math.inf
    demand = _demand_at(rate, post_at)
    if room:
        room = max(0, room - held)
        queue = _flip_queue(queue, demand, config)
    else:
        post_at = None
    resale = None if post_at is None else post_at * (1 - cut)
    return _Outlet(room, post_at, resale, vendor_price or 0, bound, effort, queue, held)


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
    parts: list[_Part]  # its share of the Craft Chain (#77)

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
    units = plan.recipe.quantity_min
    value, selling = outlet.value(units)
    vendored = (units - selling) * outlet.vendor_price
    exits = _exits(
        plan.output,
        units,
        selling,
        value - vendored,
        vendored,
        outlet.post_at,
        outlet.resale,
        outlet.effort,
    )
    return _CraftBuy(
        plan,
        gold,
        value - sources.cost(chain),
        chain,
        tuple(buys),
        selling,
        outlet.post_at,
        sources.parts(chain) + exits,
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


def _bound(h: Holding) -> int:
    return h.bags_bound + h.bank_bound


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


def _take_unbound(h: Holding) -> Holding:
    """`h` less one unbound unit, from the bags first."""
    return replace(h, bags=h.bags - 1) if h.bags else replace(h, bank=h.bank - 1)


# On a Holdings row of an item the Scan dropped rows of (#156).
PRICE_MAY_BE_OFF = "Price may be off. Check the AH."


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
    are costed by its newest open Lots not tied to a Prediction (ADR-0007): open
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
    pricer: Callable[[int | None], float | None] | None = None,
    cheap: _Cheap | None = None,
) -> list[_VendorBuy | _FlipToSell]:
    """What's worth buying of an Item Key, from other players' (unit buyout, quantity)
    offers, cheapest first. `supply` is every unit on sale, the player's own included.

    Buy to Sell takes no more than sells within Days to Sell (#109) after
    the `held` unbound units, which take it first (#67), and posts just under the cheapest
    other player's Listing left once they're bought (`_post_at`), so they sell first. A
    cheap Listing that would undercut the resale is worth buying through, so every run of
    the cheapest offers is tried, and the one with the most profit whose every unit clears
    the Flip margin is bought (#62); the shorter runs that clear it are kept for when gold
    can't buy that one (ADR-0011). Each run counts only the Sale Events at or above its post
    price (#107), both for the minimum of Sale Events for a Flip (#57) and for what sells
    within Days to Sell (#109), so a lone ask far above every sale isn't
    taken at its word (#41). The post price never falls as a run grows, so neither does the
    room grow. The resale is never above what a merchant charges (#63). Anything else under
    the Vendor Price is bought to Vendor. Each unit bought costs the `effort` of buying it,
    and one bought to Sell the effort of posting it too (#73), and the deposits it's
    expected to lose waiting its turn in the `queue` after the `held` units (#78), at the
    Sell Rate at its post price.

    A `pricer` (`_Valuer.priced`) sets the post price instead, with no room limit and no
    minimum of Sale Events (#84). With the `cheap` Listings, a run counts the demand at its
    post price only since the ones it buys showed up (#132).
    """
    offers = sorted(offers)
    runs: list[_SellRun] = []
    prefix: Supply = []
    # What `_post_at` works out for each run, without rebuilding the supply per run (#105):
    # the player's own Listings don't change, and the cheapest offer left is this one if
    # it's only partly bought, else the cheapest one after it.
    own = _cheapest(without(supply, offers))
    after = _cheapest_from(offers)
    bought = 0
    for i, (unit, quantity) in enumerate(offers):
        if pricer is None:
            take, post_at = _sell_take(
                quantity,
                bought,
                _undercut(after[i + 1], own, config, merchant_cost),
                _undercut(unit, own, config, merchant_cost),
                lambda price: _room_at(
                    rate, price, held, config, config.days_to_sell_or_horizon_seconds, cheap=cheap
                ),
            )
        else:
            take, post_at = quantity, pricer(after[i + 1])
        if not take or post_at is None:
            break
        prefix = [*prefix, (unit, take)]
        bought += take
        demand = _demand_at(rate, post_at, cheap=cheap)
        at_price = _flip_queue(queue, demand, config)
        resale = post_at * (1 - cut)
        # Offers are cheapest first and the last unit waits longest, so if the dearest unit
        # clears the margin after its deposits, all do.
        lost = at_price.lost(held + bought - 1)
        if _resells(resale, unit, vendor_price, effort, lost, config):
            profit = sum((resale - 2 * effort - u) * n for u, n in prefix)
            profit -= at_price.lost_by(held, bought)
            # With a pricer and no Sell Rate at the price, there's nothing to wait by.
            per_hour = at_price.units_per_hour
            days = (held + bought) / (per_hour * 24) if per_hour else math.inf
            events = demand.sale_events if demand else 0
            runs.append(_SellRun(prefix, post_at, profit, days, events))
        if take < quantity:
            break  # the rest of this Listing is left, so no longer run buys past it
    buys: list[_VendorBuy | _FlipToSell] = []
    to_sell: Supply = []
    if runs:
        flip = _FlipToSell(item_key, tuple(runs), stack)
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
    beta: BetaSellRate | None = None,
    cheap: _Cheap | None = None,
) -> list[_HoldBuy]:
    """What's worth buying of an Item Key to Hold under a Prediction, from other players'
    (unit buyout, quantity) offers, cheapest first: the units whose Max Loss is small
    enough. `supply` is every unit on sale, and `held` the units the player could sell.

    A unit's Max Loss is its buyout less its exit without the Prediction. That's Sell, at
    the resale a Flip would get, for the units that would sell within the Sale Horizon if
    the Prediction were wrong, after the `held` ones, judged as strictly as a Flip: only
    the Sale Events at or above the resale's post price count (#107), and it's never
    above what a merchant charges (#63). Each is less the deposits it's expected to lose
    waiting its turn in the `queue` at that rate (#78). The rest can only be Vendored, or
    are worth nothing without a Vendor Price. Nothing is bought at or above the Merchant
    Cost after the `cut`, since no Sell fetches more than that (#91). Early in Live, the
    demand at the post price also counts the `beta` Sell Rate (#110, ADR-0024). With the
    `cheap` Listings, it counts only since the ones bought so far showed up, as a Flip's
    does (#132).
    """
    bought: Supply = []
    buys = []
    selling = True  # until a Listing is only partly taken: the rest of it stays up
    most = math.inf if merchant_cost is None else merchant_cost * (1 - cut)
    for unit, quantity in sorted(offers):
        if unit >= most:
            return buys
        queued = held + sum(n for _, n in bought)
        take, post_at = 0, None
        if selling:
            take, post_at = _sell_take(
                quantity,
                queued - held,
                _post_at(supply, offers, [*bought, (unit, quantity)], config, merchant_cost),
                _post_at(supply, offers, [*bought, (unit, quantity - 1)], config, merchant_cost),
                lambda price: _room_at(
                    rate, price, held, config, config.sale_horizon_seconds, beta, cheap
                ),
            )
        resale = post_at * (1 - cut) if take else 0
        beta_room = _beta_room(rate, beta, post_at, held, config, cheap) if take else None
        at_price = _flip_queue(queue, _demand_at(rate, post_at, beta, cheap), config)
        exits = [
            max(resale - at_price.lost(queued + i), vendor_price or 0) for i in range(take)
        ] + [vendor_price or 0] * (quantity - take)
        parts = [(len(list(same)), exit_value) for exit_value, same in groupby(exits)]
        for n, exit_value in parts:
            max_loss = unit - exit_value
            if max_loss > unit * config.prediction_max_loss_share:
                return buys
            buys.append(_HoldBuy(item_key, prediction, unit, n, max_loss, beta_room))
        bought.append((unit, take))
        selling = selling and take == quantity
    return buys


def _beta_room(
    rate: SellRate | None,
    beta: BetaSellRate | None,
    post_at: float | None,
    held: int,
    config: Config,
    cheap: _Cheap | None = None,
) -> BetaRoom | None:
    """The room at `post_at` a Prediction buy counts on, and how much of it the `beta`
    Sell Rate makes (#110); None without one. `cheap` as in `_demand_at`."""
    if beta is None or post_at is None:
        return None
    horizon = config.sale_horizon_seconds
    room = _room_at(rate, post_at, held, config, horizon, beta, cheap)
    without = _room_at(rate, post_at, held, config, horizon, cheap=cheap)
    return BetaRoom(post_at, room, room - without)


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
            beta_room=max(
                (b for b in (r.beta_room, buy.beta_room) if b is not None),
                key=lambda b: (b.from_beta > 0, b.room),
                default=None,
            ),
        )
    return list(rows.values())


def _sell_take(
    quantity: int,
    bought: int,
    post_if_all: float | None,
    post_if_part: float | None,
    room_at: Callable[[float | None], int],
) -> tuple[int, float | None]:
    """How many units of the next Listing a buy to Sell takes after `bought` units, and the
    price they're all posted at (#107). The whole Listing if the room at the price that
    leaves, `post_if_all`, has space for it. Else part of it, posted under what's left of
    it at `post_if_part`, which is never dearer and so never has less room."""
    if bought + quantity <= room_at(post_if_all):
        return quantity, post_if_all
    return max(0, min(quantity - 1, room_at(post_if_part) - bought)), post_if_part


def _demand_at(
    rate: SellRate | None,
    post_at: float | None,
    beta: BetaSellRate | None = None,
    cheap: _Cheap | None = None,
) -> SellRate | None:
    """The Sell Rate a unit bought to Sell counts on when posted at `post_at` (#107): only
    the Sale Events at or above it, and for a buy that takes the `cheap` Listings under
    it, only since the stretch of cheaper stock began (#132, #135), pooled with a
    Prediction buy's `beta` Sell Rate (#110). None without a Sell Rate or a price."""
    if post_at is None:
        return None
    demand = None if rate is None else rate.at_or_above(post_at)
    cutoff = None if cheap is None else cheap.since(post_at)
    if demand is not None and cutoff is not None:
        demand = demand.since_cheap(cutoff, cheap.latest)
    return demand if beta is None else beta.pooled(demand, post_at)


def _room_at(
    rate: SellRate | None,
    post_at: float | None,
    held: int,
    config: Config,
    horizon_seconds: int,
    beta: BetaSellRate | None = None,
    cheap: _Cheap | None = None,
) -> int:
    """Units bought at `post_at` that should sell within `horizon_seconds` after the
    `held` ones, from the demand at that price (`_demand_at`, `_flip_room`)."""
    demand = _demand_at(rate, post_at, beta, cheap)
    return max(0, _flip_room(demand, config, horizon_seconds) - held)


def _flip_queue(queue: _Queue, demand: SellRate | None, config: Config) -> _Queue:
    """`queue` moving at the `demand` Sell Rate under the Flip priors (#107)."""
    per_day = _units_per_day(
        demand, config.sell_rate_prior_hours_flips, config.sale_size_prior_events_flips
    )
    return replace(queue, units_per_hour=per_day / 24)


def _flip_room(rate: SellRate | None, config: Config, horizon_seconds: int) -> int:
    """Units bought to resell that should sell within `horizon_seconds`, judged under the
    Flip priors. That's Days to Sell (`Config.days_to_sell_or_horizon_seconds`, #109) for
    a unit bought to Sell, and the Sale Horizon for one bought to Hold. None unless the Sell Rate
    rests on the minimum of Sale Events for a Flip: one or two Disappearances can be one
    seller cancelling (#57)."""
    if rate is None or rate.sale_events < config.flip_min_sale_events:
        return 0
    return sellable_units(
        rate,
        config.sell_rate_prior_hours_flips,
        config.sale_size_prior_events_flips,
        horizon_seconds,
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


def _post_at(
    supply: Supply, others: Supply, bought: Supply, config: Config, cap: float | None = None
) -> float | None:
    """The price to post one unit at once `bought` is gone from other players' `others`
    (#62): just under the cheapest of them left, so it sells first, or `cap` if that's
    lower. The player's own Listings, the rest of `supply`, are matched rather than
    undercut. None if no Listing is left to price against."""
    return _undercut(
        cheapest_without(others, bought), cheapest_without(supply, others), config, cap
    )


def _undercut(
    other: int | None, own: int | None, config: Config, cap: float | None
) -> float | None:
    """`_post_at` from the cheapest `other` player's unit price left and the cheapest of
    the player's `own`, either None when there's none."""
    prices = [other - config.post_undercut_copper] if other is not None else []
    prices += [own] if own is not None else []
    if not prices:
        return None
    value = min(prices)
    return value if cap is None else min(value, cap)


def _cheapest(supply: Supply) -> int | None:
    """The cheapest unit price in a `without`-shaped supply, or None if it's empty."""
    return supply[0][0] if supply else None


def _cheapest_from(offers: Supply) -> list[int | None]:
    """For each index into `offers` (sorted, cheapest first), and one past the end, the
    cheapest unit price with a unit on offer from there on."""
    cheapest: list[int | None] = [None]
    for unit, quantity in reversed(offers):
        cheapest.append(unit if quantity > 0 else cheapest[-1])
    return cheapest[::-1]


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


def cheapest_without(supply: Supply, bought: Supply) -> int | None:
    """`_cheapest(without(supply, bought))` without building and sorting what's left:
    `_post_at` asks it hundreds of thousands of times a pass (#141)."""
    taken = Counter()
    for unit, quantity in bought:
        taken[unit] += quantity
    left = Counter()
    for unit, quantity in supply:
        left[unit] += quantity
    return min((unit for unit, quantity in left.items() if quantity > taken[unit]), default=None)


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
            plan.add(buy.chain, buy.parts)
            r = rows.get(recipe_id, replace(plan.row(), cost=0))
            selling = buy.selling + (r.made.selling if r.made else 0)
            made = CraftOutput(plan.crafts * plan.recipe.quantity_min, selling, buy.post_at)
            rows[recipe_id] = replace(
                plan.row(),
                cost=r.cost + buy.gold,
                buys=_merged(r.buys, buy.buys),
                # The outlet keeps a price even when no unit beats the Vendor Price.
                post_at=made.post_at if made.selling else None,
                made=made,
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
                sale_events=run.sale_events,
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
    disenchants: list[Row],
    gold: float,
    flip_rows: int,
    craft_rows: int,
    disenchant_rows: int,
) -> list[Row]:
    """The Shopping List (#86): each Item Key's Flip to Sell and Flip to Vendor, and each
    recipe's Flips to Craft, sized as if it were the only buy within `gold`, most
    profitable first. The Flips to Sell and to Vendor are cut to those in the top
    `flip_rows` by any of Profit, Per click, Per day (Flips to Sell only) or ROI (#98),
    and the Flips to Craft,
    apart, to the top `craft_rows` by Profit (#87), and the Flips to Disenchant likewise
    to `disenchant_rows` (#89). A Flip to Sell is priced on the run it buys (ADR-0011)."""
    flips = _flip_options(buys, gold)
    ranks = _best_ranks(flips)
    crafted = [row for recipe in crafts if recipe for row in _option([], recipe, gold)]
    crafted.sort(key=lambda r: -r.profit)
    disenchanted = sorted(disenchants, key=lambda r: -r.profit)
    # One list again, most profit first: Replay takes the options in that order.
    return sorted(
        [r for r, rank in zip(flips, ranks, strict=True) if rank <= flip_rows]
        + crafted[:craft_rows]
        + disenchanted[:disenchant_rows],
        key=lambda r: -r.profit,
    )


def _flip_options(buys: list[_VendorBuy | _FlipToSell], gold: float) -> list[Row]:
    """Each Item Key's Flip to Sell and Flip to Vendor as a Shopping List option (#86)."""
    groups: dict[object, list[_VendorBuy | _FlipToSell]] = {}
    for buy in buys:
        groups.setdefault((buy.item_key, isinstance(buy, _FlipToSell)), []).append(buy)
    return [row for group in groups.values() for row in _option(group, [], gold)]


def _best_ranks(flips: list[Row]) -> list[int]:
    """Each Flip's best place, from 1, by any of Profit, Per click, Per day (Flips to Sell
    only) or ROI (#98)."""
    best = [len(flips)] * len(flips)  # Profit ranks them all
    selling = [i for i, r in enumerate(flips) if r.action is Action.SELL]
    for measure, indices in (
        (_profit, range(len(flips))),
        (per_click, range(len(flips))),
        # Every Flip to Vendor ties at "now", so Per day ranks the Flips to Sell alone.
        (per_day, selling),
        (return_on_cost, range(len(flips))),
    ):
        # Ties go to the most profit.
        ranked = sorted(indices, key=lambda i: (-measure(flips[i]), -flips[i].profit))
        for place, i in enumerate(ranked, 1):
            best[i] = min(best[i], place)
    return best


def _profit(row: Row) -> float:
    return row.profit


def per_click(row: Row) -> float:
    """A Flip's Profit for each Listing bought and stack posted (#98)."""
    return row.profit / (row.listings + row.posts)


def per_day(row: Row) -> float:
    """A Flip's Profit for each day until its last unit sells, at least a day (#101): a
    one-off Flip that sells in an hour can't be made again all day. A Flip to Vendor sells
    now, before any Flip to Sell (#98)."""
    return math.inf if row.days is None else row.profit / max(row.days, 1)


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
