"""The Backtest (#167, ADR-0032): a policy trades a Market's past Scans in time order on
its own simulated gold, and is graded by the Sale Records that came after each buy.

A posted unit sells to a later Sale Record of its Item Key at or above its price, up to
the record's units, our cheapest units first (a buyer takes the cheapest, so our cheaper
unit would have gone instead). Only a record whose Listing was still up at or after the
Scan we posted in counts. A sold unit brings its price after the cut, less a Deposit for
every 24 h posting it waited through. A Buy's units unsold a week after it was posted is relisted
once, for another week, at the lower of its price and 1c under other players' cheapest
ask then, if that still beats the Vendor Price after the cut; unsold after that, it's
vendored after losing a Deposit for each day posted. All amounts are copper.
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
    SaleRecord,
    grader_calibration,
    sale_records,
    sell_rate_calibration,
)
from brain.predictions import Prediction
from brain.recommend import (
    Action,
    MarketRecommendations,
    Row,
    auction_cut,
    deposit_of,
    recommend_market,
)
from brain.scan import item_id_of

POSTING_SECONDS = 24 * 3600
WEEK_SECONDS = 7 * 24 * 3600
START_GOLD = 400_000  # 40g

# Each policy is the Brain under its config, from the player's (#167).
POLICIES: dict[str, Callable[[Config], Config]] = {
    "brain": lambda c: c,
    # Every buy-side gate loosened: no cheap-stock cutoff, one Sale Event is enough, the
    # Holdings' Sell Rate priors for Flips too, and no margin needed.
    "relaxed": lambda c: replace(
        c,
        cheap_stock_cutoff=False,
        flip_min_sale_events=1,
        sell_rate_prior_hours_flips=c.sell_rate_prior_hours_holdings,
        sale_size_prior_events_flips=c.sale_size_prior_events_holdings,
        flip_min_margin_share=0.0,
        flip_min_margin_copper=0,
    ),
    # No risk caps (#170, ADR-0034): what they change is measured against it.
    "uncapped": lambda c: replace(c, risk_caps=False),
}


@dataclass(frozen=True)
class Buy:
    """What a policy buys at a Scan: the units it posts, the gold they cost, and any gold
    back at once from units vendored as bought (a Flip to Vendor posts none)."""

    item_key: str
    units: int
    cost: float
    post_at: float  # per unit, before the cut
    back: float = 0.0  # gold back at once, from units vendored as bought


# (Scan time, gold, Item Keys with units still posted, what the units still posted cost)
# -> what it buys at that Scan.
BuyPolicy = Callable[[int, float, frozenset[str], float], Sequence[Buy]]


@dataclass(frozen=True)
class Terms:
    """What the Market charges and pays: its cut, a Deposit per unit posted for 24 h, the
    Vendor Price, and other players' cheapest unit buyout of an Item Key in a Scan (None
    when they have none up)."""

    cut: float
    deposit: Callable[[str], float]
    vendor: Callable[[str], int]
    cheapest_ask: Callable[[str, int], int | None]


@dataclass
class Trade:
    """One Buy and what came of it."""

    item_key: str
    units: int
    cost: float
    price: float  # per unit, as posted (lowered by a relist)
    posted_at: int
    sold: float = 0  # in part when the grader believes a share of a record (#167)
    proceeds: float = 0.0
    # Its unsold units at their Vendor Price (`salvage`), or at other players' cheapest
    # ask then (`salvage_market`), less the Deposits they lost: when vendored, or as
    # marked at the end if still posted (not `closed`).
    salvage: float = 0.0
    salvage_market: float = 0.0
    relisted: bool = False
    closed: bool = False

    @property
    def left(self) -> float:
        return self.units - self.sold

    def profit(self, market: bool = False) -> float:
        """Gold it made, at the vendor mark or the market mark."""
        return self.proceeds + (self.salvage_market if market else self.salvage) - self.cost


@dataclass(frozen=True)
class Split:
    """The trades by how they went: sold out without a relist (or done at once), sold
    or vendored after one, and the rest (vendored unsold after a week, or still posted
    at the end)."""

    sold_out_in_week_1: list[Trade]
    relisted: list[Trade]
    rest: list[Trade]


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
        week_1 = [t for t in self.trades if not t.left and not t.relisted]
        relisted = [t for t in self.trades if t.relisted]
        rest = [t for t in self.trades if t.left and not t.relisted]
        return Split(week_1, relisted, rest)


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
        trade = Trade(buy.item_key, buy.units, buy.cost, buy.post_at, at, proceeds=buy.back)
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
            if r.last_seen < trade.posted_at or trade.sold == trade.units:
                continue
            n = min(units, trade.units - trade.sold)
            waits = max(0, math.ceil((r.seen_at - trade.posted_at) / POSTING_SECONDS) - 1)
            got = n * (trade.price * (1 - terms.cut) - waits * terms.deposit(trade.item_key))
            trade.sold += n
            trade.proceeds += got
            sim.gold += got
            units -= n


def _expire(sim: Simulation, at: int, terms: Terms, end: bool = False) -> None:
    """Relist or vendor the posted units whose week ran out by the Scan at `at`, and close the
    sold-out ones. At the `end`, mark what's still posted instead (left open)."""
    for trade in sim.trades:
        if trade.closed:
            continue
        age = at - trade.posted_at
        if trade.left and not end and age < (2 if trade.relisted else 1) * WEEK_SECONDS:
            continue
        vendor = terms.vendor(trade.item_key)
        ask = terms.cheapest_ask(trade.item_key, at)
        if trade.left and not end and not trade.relisted:
            price = trade.price if ask is None else min(trade.price, ask - 1)
            if price * (1 - terms.cut) > vendor:
                trade.price, trade.relisted = price, True
                continue
        lost = math.floor(min(age, 2 * WEEK_SECONDS) / POSTING_SECONDS) * terms.deposit(
            trade.item_key
        )
        market = vendor if ask is None else min(ask - 1, trade.price) * (1 - terms.cut)
        trade.salvage = trade.left * (vendor - lost)
        trade.salvage_market = trade.left * (max(vendor, market) - lost)
        sim.gold += trade.salvage
        trade.closed = not end or not trade.left


@dataclass(frozen=True)
class MarketBacktest:
    """One Market's Backtest: each policy's run over its Scans, its runs at the grader's
    low and high bounds, and the grader and Sell Rate checked on own Listings."""

    market: Market
    scans: int
    runs: dict[str, Simulation]  # by policy name
    bounds: dict[str, tuple[Simulation, Simulation]]  # (low, high), by policy name
    grader_calibration: Calibration
    sell_rate_calibration: Calibration


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
    """Each Market's `policies` (names in POLICIES) trading its Scans in [since, until]
    from `start_gold`, buying nothing in the last `no_buys_in_last_seconds` of them, so
    every buy gets its week. Flips to Disenchant are left out: their mats aren't
    simulated."""
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
        terms = _terms(conn, config, market)

        shares = (1.0, config.backtest_grade_low, config.backtest_grade_high)
        graded = {
            name: [
                simulate(
                    times,
                    _brain_policy(conn, POLICIES[name](config), market, predictions, cache, terms),
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
        result.append(MarketBacktest(market, len(times), runs, bounds, calibration, sell_rate))
    return result


def _terms(conn: sqlite3.Connection, config: Config, market: Market) -> Terms:
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
    )


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
