"""The Backtest (#167, ADR-0032): a policy trades a Market's past Scans in time order on
its own simulated gold, and is graded by the Sale Records that came after each buy.

A posted unit sells to a later Sale Record of its Item Key at or above its price, up to
the record's units, our cheapest units first (a buyer takes the cheapest, so our cheaper
unit would have gone instead). Only a record whose Listing was still up while our posting
was (at or after the Scan we posted in, and before its 24 h ran out) counts. A sold unit
brings its price after the cut.

A posting's unsold units exit as the Brain's Holdings advice would (#204): at the first
Scan at or after its 24 h runs out, each loses a Deposit, and unit i reposts at the
Holdings price then (its own without one) while that price after the cut, less the
Deposits it's expected to lose waiting its turn, beats the Vendor Price, up to what sells
within the Sale Horizon; the rest are vendored. Every policy exits this way. Between a
posting running out and that Scan the units aren't on the AH. All amounts are copper.
"""

import math
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from brain.config import Config
from brain.fair_value import FairValueCache
from brain.history import Market, character_markets, scan_times, supply_at, vendor_prices
from brain.observation import (
    Calibration,
    OwnPurchasesTaken,
    SaleRecord,
    grader_calibration,
    own_purchases_taken,
    sale_records,
    sell_rate_calibration,
)
from brain.predictions import Prediction
from brain.recommend import (
    Action,
    BuyUnder,
    HoldingsAdvice,
    MarketRecommendations,
    Row,
    auction_cut,
    deposit_of,
    holdings_advice,
    recommend_market,
    take_under,
    units_selling,
)
from brain.scan import item_id_of

POSTING_SECONDS = 24 * 3600
WEEK_SECONDS = 7 * 24 * 3600
START_GOLD = 400_000  # 40g

# Each policy is the Brain under its config, from the player's (#167).
POLICIES: dict[str, Callable[[Config], Config]] = {
    "brain": lambda c: c,
    # Every buy-side gate loosened: no cheap-stock cutoff, one Sale Event is enough, the
    # Holdings' Sell Rate priors for Flips too, and no margin or Minimum Profit needed.
    "relaxed": lambda c: replace(
        c,
        cheap_stock_cutoff=False,
        flip_min_sale_events=1,
        sell_rate_prior_hours_flips=c.sell_rate_prior_hours_holdings,
        sale_size_prior_events_flips=c.sale_size_prior_events_holdings,
        flip_min_margin_share=0.0,
        flip_min_margin_copper=0,
        row_min_profit_share=0.0,
        row_min_profit_copper=0,
        row_min_profit_per_click=0,
    ),
    # No risk caps (#170, ADR-0034): what they change is measured against it. The Minimum
    # Profit (#197) stays: it isn't a risk cap.
    "uncapped": lambda c: replace(c, risk_caps=False),
}

# The Buy Unders as standing orders (#173), with the price-moved test or without it.
BUY_UNDER_POLICIES: dict[str, bool] = {"buyunder": True, "buyunder_unchecked": False}

# A player flipping with Auctionator, the Dec 2 baseline (#196, ADR-0039).
AUCTIONATOR = "auctionator"
# Auctionator has no cap of its own; a careful player spreads the Stake over 5 Item Keys
# or more (ADR-0039's #196 note).
AUCTIONATOR_STAKE_SHARE = 0.2
# And no more than a stack: with no sale data it can't tell what sells, so it doesn't
# buy hundreds of anything (#196: 528 Copper Rods lost 75g in Deposits on Beta).
AUCTIONATOR_MAX_UNITS = 20


@dataclass(frozen=True)
class Buy:
    """What a policy buys at a Scan: the units it posts, the gold they cost, and any gold
    back at once from units vendored as bought (a Flip to Vendor posts none)."""

    item_key: str
    units: int
    cost: float
    post_at: float  # per unit, before the cut
    back: float = 0.0  # gold back at once, from units vendored as bought
    way: Action | None = None  # a Buy Under's way out, for its P&L by way (#173)


# (Scan time, gold, Item Keys with units still posted, what the units still posted cost)
# -> what it buys at that Scan.
BuyPolicy = Callable[[int, float, frozenset[str], float], Sequence[Buy]]


@dataclass(frozen=True)
class Terms:
    """What the Market charges and pays: its cut, a Deposit per unit posted for 24 h, the
    Vendor Price, other players' cheapest unit buyout of an Item Key in a Scan (None
    when they have none up), and the Brain's Holdings advice for an Item Key at a Scan."""

    cut: float
    deposit: Callable[[str], float]
    vendor: Callable[[str], int]
    cheapest_ask: Callable[[str, int], int | None]
    holdings: Callable[[str, int], HoldingsAdvice]


@dataclass
class Trade:
    """One Buy and what came of it."""

    item_key: str
    units: int
    cost: float
    price: float  # per unit, as posted (moved by a repost)
    posted_at: int  # when its current posting went up
    sold: float = 0  # in part when the grader believes a share of a record (#167)
    vendored: float = 0
    postings: int = 0  # that expired
    deposits: float = 0.0  # lost on them
    proceeds: float = 0.0
    # Its unsold units at their Vendor Price (`salvage`), or at other players' cheapest
    # ask then (`salvage_market`), less the Deposits they lost: when vendored, or as
    # marked at the end if still posted (not `closed`).
    salvage: float = 0.0
    salvage_market: float = 0.0
    closed: bool = False
    way: Action | None = None  # a Buy Under's way out (#173)

    @property
    def left(self) -> float:
        return self.units - self.sold - self.vendored

    def profit(self, market: bool = False) -> float:
        """Gold it made, at the vendor mark or the market mark."""
        salvage = self.salvage_market if market else self.salvage
        return self.proceeds + salvage - self.deposits - self.cost


@dataclass(frozen=True)
class Split:
    """The trades by how they went (#204): sold out (or done at once), some units
    vendored, and units still posted at the end."""

    sold_out: list[Trade]
    part_vendored: list[Trade]
    still_posted: list[Trade]


@dataclass
class Simulation:
    """One policy's run of the Backtest: its simulated gold and every Buy it made."""

    gold: float
    trades: list[Trade] = field(default_factory=list)
    # (gold, gold plus unsold units at cost) after each Scan's buys
    curve: list[tuple[float, float]] = field(default_factory=list)

    @property
    def gold_low(self) -> float:
        return min((gold for gold, _ in self.curve), default=self.gold)

    @property
    def max_drawdown(self) -> float:
        """The deepest fall of gold plus unsold units at cost from a peak before it, as a
        share of that peak."""
        peak, deepest = 0.0, 0.0
        for _, bankroll in self.curve:
            peak = max(peak, bankroll)
            if peak > 0:
                deepest = max(deepest, (peak - bankroll) / peak)
        return deepest

    def profit(self, market: bool = False) -> float:
        return sum(t.profit(market) for t in self.trades)

    def split(self) -> Split:
        still_posted = [t for t in self.trades if t.left]
        part_vendored = [t for t in self.trades if not t.left and t.vendored]
        sold_out = [t for t in self.trades if not t.left and not t.vendored]
        return Split(sold_out, part_vendored, still_posted)


def simulate(
    times: Sequence[int],
    policy: BuyPolicy,
    records: Sequence[SaleRecord],
    terms: Terms,
    start_gold: float,
    last_buy: int | None = None,
    grade_share: float = 1.0,
) -> Simulation:
    """`policy` trading the Scans at `times`, oldest first, graded by `records`, of whose
    units it believes `grade_share`. It buys nothing after `last_buy`, and never an Item
    Key it still has units posted in: the Scans don't show our simulated posts."""
    sim = Simulation(gold=start_gold)
    for previous, at in zip([None, *times], times, strict=False):
        if previous is not None:
            _fill(sim, [r for r in records if previous < r.seen_at <= at], terms, grade_share)
        _expire(sim, at, terms)
        if last_buy is None or at <= last_buy:
            _buy(sim, at, policy, terms)
        sim.curve.append((sim.gold, sim.gold + _tied_up(sim)))
    if times:
        _expire(sim, times[-1], terms, end=True)
    return sim


def _tied_up(sim: Simulation) -> float:
    """What the units still posted cost."""
    return sum(t.cost * t.left / t.units for t in sim.trades if t.units and not t.closed)


def _buy(sim: Simulation, at: int, policy: BuyPolicy, terms: Terms) -> None:
    posted = frozenset(t.item_key for t in sim.trades if not t.closed)
    for buy in policy(at, sim.gold, posted, _tied_up(sim)):
        if buy.item_key in posted:
            continue
        trade = Trade(
            buy.item_key, buy.units, buy.cost, buy.post_at, at, proceeds=buy.back, way=buy.way
        )
        trade.closed = not buy.units
        sim.gold += buy.back - buy.cost
        sim.trades.append(trade)


def _fill(sim: Simulation, records: Sequence[SaleRecord], terms: Terms, grade_share: float) -> None:
    """Sell posted units to `records`, oldest first, believing `grade_share` of each
    record's units (so a unit may sell in part)."""
    by_item: dict[str, list[Trade]] = defaultdict(list)
    for trade in sim.trades:
        if trade.closed:
            continue
        by_item[trade.item_key].append(trade)
    for r in records:
        units = r.units * grade_share
        for trade in sorted(by_item.get(r.item_key, []), key=lambda t: t.price):
            if units <= 0 or trade.price > r.unit_buyout:
                break
            if not trade.posted_at <= r.last_seen < trade.posted_at + POSTING_SECONDS:
                continue  # sold before our posting went up, or after it ran out
            if not trade.left:
                continue
            n = min(units, trade.left)
            got = n * trade.price * (1 - terms.cut)  # its Deposits went as its postings ran out
            trade.sold += n
            trade.proceeds += got
            sim.gold += got
            units -= n


def _expire(sim: Simulation, at: int, terms: Terms, end: bool = False) -> None:
    """Exit the units of each posting run out by the Scan at `at` as the Brain's Holdings
    advice would then (#204), and close the sold-out lots. At the `end`, mark what's still
    posted instead (left open)."""
    for trade in sim.trades:
        if trade.closed:
            continue
        if not trade.left:
            trade.closed = True
        elif end:
            vendor = trade.left * terms.vendor(trade.item_key)
            trade.salvage += vendor
            trade.salvage_market += trade.left * _market_mark(trade, at, terms)
            sim.gold += vendor
        elif at >= trade.posted_at + POSTING_SECONDS:
            _repost(sim, trade, at, terms)


def _repost(sim: Simulation, trade: Trade, at: int, terms: Terms) -> None:
    """Lose a Deposit on each unit of `trade`'s expired posting, then repost the units the
    Holdings advice at `at` keeps posting at its price (theirs without one) and vendor the
    rest."""
    lost = trade.left * terms.deposit(trade.item_key)
    trade.postings += 1
    trade.deposits += lost
    sim.gold -= lost
    advice = terms.holdings(trade.item_key, at)
    price = trade.price if advice.post_at is None else advice.post_at
    vendor = terms.vendor(trade.item_key)
    # As the Holdings split Sell from Vendor; `trade.left` may be part of a unit.
    selling = units_selling(
        price * (1 - terms.cut), min(trade.left, advice.room), advice.lost, vendor
    )
    keep = min(trade.left, selling)
    vendoring = trade.left - keep
    trade.salvage += vendoring * vendor
    trade.salvage_market += vendoring * _market_mark(trade, at, terms)
    trade.vendored += vendoring
    sim.gold += vendoring * vendor
    trade.price, trade.posted_at = price, at
    trade.closed = not trade.left


def _market_mark(trade: Trade, at: int, terms: Terms) -> float:
    """An unsold unit of `trade` at other players' cheapest ask at `at` less 1c, after the
    cut, capped at its price, and never under the Vendor Price."""
    vendor = terms.vendor(trade.item_key)
    ask = terms.cheapest_ask(trade.item_key, at)
    return vendor if ask is None else max(vendor, min(ask - 1, trade.price) * (1 - terms.cut))


@dataclass(frozen=True)
class MarketBacktest:
    """One Market's Backtest: each policy's run over its Scans, its runs at the grader's
    low and high bounds, the grader and Sell Rate checked on own Listings, and what own
    Purchases took out of Sell Rate."""

    market: Market
    scans: int
    runs: dict[str, Simulation]  # by policy name
    bounds: dict[str, tuple[Simulation, Simulation]]  # (low, high), by policy name
    grader_calibration: Calibration
    sell_rate_calibration: Calibration
    own_purchases: OwnPurchasesTaken


def backtest(
    conn: sqlite3.Connection,
    config: Config,
    predictions: Sequence[Prediction],
    since: int | None = None,
    until: int | None = None,
    policies: Sequence[str] = ("brain",),
    start_gold: float = START_GOLD,
    no_buys_in_last_seconds: int = WEEK_SECONDS,
) -> list[MarketBacktest]:
    """Each Market's `policies` (names in POLICIES or BUY_UNDER_POLICIES) trading its
    Scans in [since, until] from `start_gold`, buying nothing in the last
    `no_buys_in_last_seconds` of them, so every buy gets a week to sell. Flips to Disenchant
    are left out: their mats aren't simulated."""
    config = replace(config, grades_path=None)  # a Backtest never freezes a Grade
    result = []
    for market in character_markets(conn):
        times = [
            t
            for t in scan_times(conn, market)
            if (since is None or since <= t) and (until is None or t <= until)
        ]
        if not times:
            continue
        cache = FairValueCache()
        records = sale_records(conn, market, config, cache)
        terms = _terms(conn, config, market, cache)

        shares = (1.0, config.backtest_grade_low, config.backtest_grade_high)
        graded = {
            name: [
                simulate(
                    times,
                    _policy(conn, config, name, market, predictions, cache, terms),
                    records,
                    terms,
                    start_gold,
                    last_buy=times[-1] - no_buys_in_last_seconds,
                    grade_share=share,
                )
                for share in shares
            ]
            for name in policies
        }
        runs = {name: central for name, (central, _, _) in graded.items()}
        bounds = {name: (low, high) for name, (_, low, high) in graded.items()}
        calibration = grader_calibration(conn, market, config)
        sell_rate = sell_rate_calibration(conn, market, config, cache)
        own_purchases = own_purchases_taken(conn, market, config, cache)
        result.append(
            MarketBacktest(market, len(times), runs, bounds, calibration, sell_rate, own_purchases)
        )
    return result


def _terms(
    conn: sqlite3.Connection, config: Config, market: Market, cache: FairValueCache
) -> Terms:
    vendor = vendor_prices(conn, market.era)
    asks: dict[int, Mapping[str, list[tuple[int, int]]]] = {}

    def cheapest_ask(item_key: str, at: int) -> int | None:
        if at not in asks:
            asks.clear()  # only the latest Scan asked about is kept
            asks[at] = supply_at(conn, market, at, others_only=True)
        offers = asks[at].get(item_key)
        return min(unit for unit, _ in offers) if offers else None

    return Terms(
        cut=auction_cut(market, config),
        deposit=deposit_of(conn, config, market),
        vendor=lambda item_key: vendor.get(item_id_of(item_key), 0),
        cheapest_ask=cheapest_ask,
        holdings=holdings_advice(conn, config, market, cache),
    )


def _policy(
    conn: sqlite3.Connection,
    config: Config,
    name: str,
    market: Market,
    predictions: Sequence[Prediction],
    cache: FairValueCache,
    terms: Terms,
) -> BuyPolicy:
    if name == AUCTIONATOR:
        return _auctionator_policy(conn, market, terms)
    if name in BUY_UNDER_POLICIES:
        # Graded with the Sell way the Brain leaves off (#173).
        config = replace(config, buy_under_sell_way=True)
        checked = BUY_UNDER_POLICIES[name]
        return _buy_under_policy(conn, config, market, predictions, cache, terms, checked)
    return _brain_policy(conn, POLICIES[name](config), market, predictions, cache, terms)


def _buy_under_policy(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    predictions: Sequence[Prediction],
    cache: FairValueCache,
    terms: Terms,
    checked: bool,
) -> BuyPolicy:
    """The Buy Unders as standing orders (#173): at each Scan, the previous Scan's Sell and
    Vendor ways take other players' Listings up now (`take_under`, `checked` or not) while
    the gold lasts. A Sell way posts what it takes; a Vendor way vendors it at once. Craft
    and Disenchant ways are left out: their outputs and mats aren't simulated."""
    standing: list[BuyUnder] = []

    def policy(at: int, gold: float, posted: frozenset[str], tied_up: float) -> list[Buy]:
        offers = supply_at(conn, market, at, others_only=True)
        buys = []
        for b in standing:
            if b.item_key is None or b.item_key in posted:
                continue
            if b.way not in (Action.SELL, Action.VENDOR):
                continue
            taken = take_under(b, offers.get(b.item_key, []), config, gold, checked)
            if taken is None:
                continue
            if taken.post_at is None:
                back = taken.units * terms.vendor(b.item_key)
                buys.append(Buy(b.item_key, 0, taken.cost, 0, back=back, way=b.way))
            else:
                buys.append(Buy(b.item_key, taken.units, taken.cost, taken.post_at, way=b.way))
            gold -= buys[-1].cost - buys[-1].back
        cache.start_pass()
        m = recommend_market(
            conn,
            config,
            market,
            predictions,
            at,
            as_of=at,
            fair_value_cache=cache,
            paid=False,
            loot_alert=False,
        )
        standing[:] = m.buy_under
        return buys

    return policy


def _auctionator_policy(conn: sqlite3.Connection, market: Market, terms: Terms) -> BuyPolicy:
    """A player flipping with Auctionator (#196): Flips to Sell only, of the Listings at
    an Item Key's cheapest ask when posting 1c under its next-lowest ask still beats it
    after the cut and one Deposit (stricter than the spread alone: the cut is on the post).
    Up to a fifth of the Stake and a stack each, most profit first while the gold lasts, in whole
    Listings, smallest first: the last Item Key gets the ones the gold left still buys."""

    def policy(at: int, gold: float, posted: frozenset[str], tied_up: float) -> list[Buy]:
        cap = AUCTIONATOR_STAKE_SHARE * (gold + tied_up)
        options = []
        for item_key, offers in supply_at(conn, market, at, others_only=True).items():
            if item_key in posted:
                continue
            cheapest = min(unit for unit, _ in offers)
            above = [unit for unit, _ in offers if unit > cheapest]
            if not above:
                continue
            post_at = min(above) - 1
            margin = post_at * (1 - terms.cut) - terms.deposit(item_key) - cheapest
            if margin <= 0:
                continue
            listings = sorted(quantity for unit, quantity in offers if unit == cheapest)
            option = _AuctionatorOption(item_key, cheapest, post_at, margin, listings)
            if option.units(cap):
                options.append(option)
        buys = []
        for option in sorted(options, key=lambda o: -o.margin * o.units(cap)):
            units = option.units(min(cap, gold))
            if units:
                buys.append(Buy(option.item_key, units, units * option.ask, option.post_at))
                gold -= buys[-1].cost
        return buys

    return policy


@dataclass(frozen=True)
class _AuctionatorOption:
    """An Item Key's Listings at its cheapest `ask` (their quantities, smallest first), and
    the `margin` a unit makes posted at `post_at`."""

    item_key: str
    ask: int
    post_at: int
    margin: float
    listings: list[int]

    def units(self, spend: float) -> int:
        """The units of the Listings, smallest first, that `spend` buys whole, up to a
        stack."""
        units = 0
        for quantity in self.listings:
            if (units + quantity) * self.ask > spend or units + quantity > AUCTIONATOR_MAX_UNITS:
                break
            units += quantity
        return units


def _brain_policy(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    predictions: Sequence[Prediction],
    cache: FairValueCache,
    terms: Terms,
) -> BuyPolicy:
    """The Brain's Shopping List at each Scan, as of then, sized to the simulated gold
    and Stake (the gold plus the units still posted at cost, ADR-0034): the options a
    player would take (`options_taken`), while the gold and the room last."""

    def policy(at: int, gold: float, posted: frozenset[str], tied_up: float) -> list[Buy]:
        cache.start_pass()
        m = recommend_market(
            conn,
            config,
            market,
            predictions,
            at,
            as_of=at,
            buy_under=False,
            fair_value_cache=cache,
            paid=False,
            loot_alert=False,
            gold=int(gold),
            tied_up=tied_up,
        )
        m = replace(m, shopping_list=[r for r in m.shopping_list if r.disenchant is None])
        shopping, _ = options_taken(m, config.shopping_list_rows)
        buys = []
        for r in shopping:
            if r.cost is None or r.cost > gold or r.item_key in posted:
                continue
            vendor = terms.vendor(r.item_key)
            if r.action is Action.SELL:
                buys.append(Buy(r.item_key, r.quantity, r.cost, r.post_at))
            elif r.action is Action.VENDOR:
                buys.append(Buy(r.item_key, 0, r.cost, 0, back=r.quantity * vendor))
            elif r.action is Action.CRAFT and r.made is not None:
                rest = r.made.units - r.made.selling
                buys.append(
                    Buy(r.item_key, r.made.selling, r.cost, r.made.post_at or 0, back=rest * vendor)
                )
            else:
                continue
            gold -= buys[-1].cost - buys[-1].back
        return buys

    return policy


def options_taken(m: MarketRecommendations, flip_rows: int) -> tuple[list[Row], list[Row]]:
    """The Shopping List options and Prediction buys a player would take, since each option
    was sized as if the only buy (#86): most profit first while the gold (or the Budget)
    lasts, skipping any that buys, uses or makes an Item Key one already taken does (a
    Flip to Disenchant makes its expected mats, #89). Only the top `flip_rows` Flips to
    Sell and to Vendor by Profit are options, so the rows kept for Per click, Per day or
    ROI (#98) aren't taken. The room the risk caps leave (ADR-0034) runs out
    as the gold does. Risky rows are never taken (#194, ADR-0037): the player takes their
    risk, which their Flip Grades judge instead. The Prediction buys then get the gold
    left, in order: the room isn't theirs."""
    gold = m.spend
    room = math.inf if m.room is None else m.room
    shopping: list[Row] = []
    keys: set[str] = set()
    sized = [r for r in m.shopping_list if not r.risky]
    flips = [r for r in sized if r.action in (Action.SELL, Action.VENDOR)]
    top = {id(r) for r in flips[:flip_rows]}
    options = [r for r in sized if r.action not in (Action.SELL, Action.VENDOR) or id(r) in top]
    for r in options:
        touched = _touched(r)
        if r.cost is None or r.cost > min(gold, room) or touched & keys:
            continue
        shopping.append(r)
        keys |= touched
        gold -= r.cost
        room -= r.cost
    prediction_buys = []
    for r in m.prediction_buys:
        if r.cost is not None and r.cost <= gold:
            prediction_buys.append(r)
            gold -= r.cost
    return shopping, prediction_buys


def _touched(r: Row) -> set[str]:
    """The Item Keys a Shopping List option buys, uses or makes."""
    if r.disenchant is not None:
        return {*(b.item_key for b in r.disenchant.buys), *(m.item_key for m in r.mats)}
    return {r.item_key, *(b.item_key for b in r.buys), *(u.item_key for u in r.uses)}
