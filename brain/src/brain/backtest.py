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
from brain.observation import SaleRecord, sale_records
from brain.predictions import Prediction
from brain.recommend import Action, auction_cut, deposit_of, recommend_market
from brain.replay import options_taken
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


# (Scan time, gold, Item Keys with units still posted) -> what it buys at that Scan.
BuyPolicy = Callable[[int, float, frozenset[str]], Sequence[Buy]]


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
    sold: int = 0
    proceeds: float = 0.0
    # Its unsold units at their Vendor Price (`salvage`), or at other players' cheapest
    # ask then (`salvage_market`), less the Deposits they lost: when vendored, or as
    # marked at the end if still posted (not `closed`).
    salvage: float = 0.0
    salvage_market: float = 0.0
    relisted: bool = False
    closed: bool = False

    @property
    def left(self) -> int:
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
) -> Simulation:
    """`policy` trading the Scans at `times`, oldest first, graded by `records`. It buys
    nothing after `last_buy`, and never an Item Key it still has units posted in: the
    Scans don't show our simulated posts."""
    sim = Simulation(gold=start_gold)
    for previous, at in zip([None, *times], times, strict=False):
        if previous is not None:
            _fill(sim, [r for r in records if previous < r.seen_at <= at], terms)
        _expire(sim, at, terms)
        if last_buy is None or at <= last_buy:
            _buy(sim, at, policy, terms)
    if times:
        _expire(sim, times[-1], terms, end=True)
    return sim


def _buy(sim: Simulation, at: int, policy: BuyPolicy, terms: Terms) -> None:
    posted = frozenset(t.item_key for t in sim.trades if not t.closed)
    for buy in policy(at, sim.gold, posted):
        if buy.item_key in posted:
            continue
        trade = Trade(buy.item_key, buy.units, buy.cost, buy.post_at, at, proceeds=buy.back)
        trade.closed = not buy.units
        sim.gold += buy.back - buy.cost
        sim.trades.append(trade)


def _fill(sim: Simulation, records: Sequence[SaleRecord], terms: Terms) -> None:
    """Sell posted units to `records`, oldest first."""
    by_item: dict[str, list[Trade]] = defaultdict(list)
    for trade in sim.trades:
        if trade.closed:
            continue
        by_item[trade.item_key].append(trade)
    for r in records:
        units = r.units
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
    """One Market's Backtest: each policy's run over its Scans."""

    market: Market
    scans: int
    runs: dict[str, Simulation]  # by policy name


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
        runs = {
            name: simulate(
                times,
                _brain_policy(conn, POLICIES[name](config), market, predictions, cache, terms),
                records,
                terms,
                start_gold,
                last_buy=times[-1] - no_buys_in_last_seconds,
            )
            for name in policies
        }
        result.append(MarketBacktest(market, len(times), runs))
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
    """The Brain's Shopping List at each Scan, as of then, sized to the simulated gold:
    the options a player would take (`options_taken`), while the gold lasts."""

    def policy(at: int, gold: float, posted: frozenset[str]) -> list[Buy]:
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
