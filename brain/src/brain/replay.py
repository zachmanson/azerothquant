"""The replay (#80, ADR-0015): at each past Scan of a Market, the Brain and two baselines
choose what to do with the same Holdings and gold, and each is graded by what the Market
did next.

A policy's grade at one Scan is the gold its moves bring within the Sale Horizon after
it, plus what it's left holding at the end of that horizon at its Best Exit Value, less
what the same Holdings would have been worth held untouched until then: the value its
moves add. A posted unit sells when a later Sale Event of its Item Key reached its price
(a buyer takes the cheapest units first, so the policy's cheapest posts go first), up to
that Sale Event's units, and loses a Deposit each time its posting expires first. All
amounts are copper.
"""

import math
import sqlite3
import statistics
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from brain.config import Config
from brain.fair_value import Supply
from brain.history import (
    Holding,
    KnownRecipe,
    Market,
    character_markets,
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
from brain.lots import happened_at, link_sales, lots
from brain.mailbox import MailKind
from brain.observation import SaleEvent, sell_rate_evidence
from brain.predictions import Prediction
from brain.recommend import (
    BOUND_ON_CRAFT,
    Action,
    MarketRecommendations,
    Row,
    auction_cut,
    cheapest,
    deposit_of,
    exit_values,
    item_id_of,
    market_holdings,
    recommend_market,
    without,
)


class Policy(StrEnum):
    BRAIN = "Brain"
    AUCTIONATOR = "Auctionator"
    TSM = "TSM"
    # Ablations: the Brain with one feature switched off.
    BRAIN_WITHOUT_SUB_CRAFTS = "Brain without Sub-crafts"
    BRAIN_WITHOUT_FLIPS_TO_CRAFT = "Brain without Flips to Craft"
    BRAIN_WITHOUT_DEPOSITS = "Brain without Deposits"


# Each Brain run's config, from the full Brain's.
_BRAINS: dict[Policy, Callable[[Config], Config]] = {
    Policy.BRAIN: lambda c: c,
    Policy.BRAIN_WITHOUT_SUB_CRAFTS: lambda c: replace(c, craft_chain_depth=1),
    Policy.BRAIN_WITHOUT_FLIPS_TO_CRAFT: lambda c: replace(c, flips_to_craft=False),
    Policy.BRAIN_WITHOUT_DEPOSITS: lambda c: replace(c, deposits=False),
}


@dataclass(frozen=True)
class MarketReplay:
    """One Market's replay: each policy's value added, summed over the Scans graded."""

    market: Market
    scans: int  # the Scans graded: ones with a whole Sale Horizon of Scans after them
    graded: dict[Policy, float] = field(default_factory=dict)  # value added, summed
    # The confirmation: what the player's own Sold Outcomes in the range brought after
    # the cut, less what the Lot units they closed cost.
    realized_profit: float = 0.0

    def over(self, baseline: Policy) -> float | None:
        """How much more value the Brain added than `baseline`, as a share of the
        baseline's; None when the baseline added none."""
        base = self.graded[baseline]
        return (self.graded[Policy.BRAIN] - base) / abs(base) if base else None


@dataclass(frozen=True)
class _Post:
    item_key: str
    units: int
    price: float  # per unit, before the cut


@dataclass
class _Moves:
    """What a policy does at one Scan: the gold it spends and gets from vendors, what it
    posts, and the units it holds on to, which are valued at the end of the horizon."""

    spent: float = 0.0
    vendored: float = 0.0
    posts: list[_Post] = field(default_factory=list)
    kept: Counter[str] = field(default_factory=Counter)


# The emulated TSM's DBMarket (ADR-0015), after TSM's published AuctionDB Market Value:
# per Scan, the mean of the cheapest units, at least the cheapest 15% and then more up to
# 30% while each is under 120% of the one before, leaving out units more than 1.5
# standard deviations from that set's mean. A day's value is the mean of its Scans', and
# DBMarket weights the last 14 days' values by 14 for the latest down to 1 for the
# oldest. The day weights are our own choice: TSM's aren't published exactly.
_DB_DAYS = 14
_DB_LEAST_SHARE, _DB_MOST_SHARE = 0.15, 0.30
_DB_STEP = 1.2
_DB_OUTLIER_DEVIATIONS = 1.5
_TSM_FLOOR_SHARE = 0.8


def db_market(
    conn: sqlite3.Connection,
    market: Market,
    at: int,
    cache: dict[int, dict[str, float]] | None = None,
) -> dict[str, float]:
    """The emulated TSM's DBMarket of every Item Key, from the Market's Scans in the 14
    days up to `at`, every Listing counted, own ones included. A day is 24 h back from
    `at`, not a calendar day. `cache` keeps each Scan's values by its time, for a caller
    asking again at later Scans."""
    cache = {} if cache is None else cache
    by_day: dict[str, dict[int, list[float]]] = {}
    for t in scan_times(conn, market):
        day = (at - t) // 86400
        if not 0 <= day < _DB_DAYS:
            continue
        if t not in cache:
            values = {k: _scan_market_value(s) for k, s in supply_at(conn, market, t).items()}
            cache[t] = {k: v for k, v in values.items() if v is not None}
        for item_key, value in cache[t].items():
            by_day.setdefault(item_key, {}).setdefault(day, []).append(value)
    return {
        item_key: sum((_DB_DAYS - d) * statistics.mean(v) for d, v in days.items())
        / sum(_DB_DAYS - d for d in days)
        for item_key, days in by_day.items()
    }


def _scan_market_value(supply: Supply) -> float | None:
    """One Scan's market value of an Item Key (see above); None with no units."""
    prices = sorted(unit for unit, n in supply for _ in range(n))
    if not prices:
        return None
    least = math.ceil(len(prices) * _DB_LEAST_SHARE)
    most = max(least, math.floor(len(prices) * _DB_MOST_SHARE))
    cheap = prices[:least]
    for price in prices[least:most]:
        if price >= cheap[-1] * _DB_STEP:
            break
        cheap.append(price)
    mean, deviation = statistics.mean(cheap), statistics.pstdev(cheap)
    kept = [p for p in cheap if abs(p - mean) <= _DB_OUTLIER_DEVIATIONS * deviation]
    return statistics.mean(kept)


def db_min_buyout(conn: sqlite3.Connection, market: Market, at: int) -> dict[str, int]:
    """The emulated TSM's DBMinBuyout of every Item Key: its cheapest unit in the Scan
    requested at `at`."""
    return {
        item_key: min(unit for unit, _ in supply)
        for item_key, supply in supply_at(conn, market, at).items()
    }


def replay(
    conn: sqlite3.Connection,
    config: Config,
    predictions: Sequence[Prediction],
    since: int,
    until: int,
) -> list[MarketReplay]:
    """Each Market's policies graded at its Scans requested in [since, until] that have a
    whole Sale Horizon of Scans after them."""
    config = replace(config, grades_path=None)  # a replay never freezes a Grade
    horizon = config.sale_horizon_seconds
    result = []
    for market, characters in character_markets(conn).items():
        times = scan_times(conn, market)
        if not times:
            continue
        replayed = [t for t in times if since <= t <= until and t + horizon <= times[-1]]
        events = sell_rate_evidence(conn, market, config, since + 1, until + horizon + 1)
        deposit = deposit_of(conn, config, market)
        vendor = vendor_prices(conn, market.era)
        cut = auction_cut(market, config)
        recipes = known_recipes(conn, market)
        merchant = {str(i): cost for i, cost in merchant_costs(conn, market).items()}
        scan_values: dict[int, dict[str, float]] = {}
        graded: Counter[Policy] = Counter()
        for t in replayed:
            later = [e for e in events.sale_events if t < e.seen_at <= t + horizon]
            held = market_holdings(conn, market, characters, as_of=t)
            untouched = sum(exit_values(conn, config, market, held, t + horizon).values())
            others = supply_at(conn, market, t, others_only=True)
            gold = pooled_gold(conn, market.era, market.realm, market.faction, t)
            moves = {
                policy: _brain(
                    recommend_market(conn, run(config), market, predictions, t, as_of=t), vendor
                )
                for policy, run in _BRAINS.items()
            } | {
                Policy.AUCTIONATOR: _auctionator(held, others, vendor, gold, deposit, cut),
                Policy.TSM: _tsm(
                    held,
                    others,
                    vendor,
                    recipes,
                    merchant,
                    db_market(conn, market, t, scan_values),
                    db_min_buyout(conn, market, t),
                    gold,
                ),
            }
            for policy, m in moves.items():
                value = _grade(conn, config, market, m, later, deposit, cut, t)
                graded[policy] += value - untouched
        realized = _realized(conn, market, since, until, cut)
        result.append(MarketReplay(market, len(replayed), dict(graded), realized))
    return result


def _realized(
    conn: sqlite3.Connection, market: Market, since: int, until: int, cut: float
) -> float:
    """Realized profit from the Sold Outcomes in [since, until]: each one's price after
    the cut, less the cost of the Lot units it closed. Units without a Lot (looted,
    crafted) cost nothing, and an Unlinked Outcome closes none (ADR-0007)."""
    bought = purchases(conn, market)
    linked = link_sales(outcomes(conn, market), listings(conn, market), bought)
    proceeds = sum(
        o.price * (1 - cut)
        for o in linked
        if o.kind is MailKind.SOLD and since <= happened_at(o) <= until
    )
    cost = sum(
        sale.units * lot.cost / lot.units
        for lot in lots(bought, linked)
        for sale in lot.sales
        if since <= sale.sold_at <= until
    )
    return proceeds - cost


def _brain(m: MarketRecommendations, vendor: Mapping[int, int]) -> _Moves:
    """The Brain's Recommendations as moves: Sell rows posted, Vendor rows vendored (for
    nothing without a Vendor Price), no-data and Hold units held on to, and the Shopping
    List options and Prediction buys the player would take (`_taken`). A Flip to Craft's
    output is posted and vendored as it was valued; a Craft Action's is in the Holdings
    rows. Held units a taken Flip to Craft uses come off the least profitable Holdings
    rows of their Item Key."""
    moves = _Moves()
    shopping, prediction_buys = _taken(m)
    used: Counter[str] = Counter()
    for r in shopping:
        for use in r.uses:
            used[use.item_key] += use.quantity
    for r in reversed(m.holdings):
        taken = min(used[r.item_key], r.quantity)
        used[r.item_key] -= taken
        quantity = r.quantity - taken
        if r.action is Action.SELL:
            moves.posts.append(_Post(r.item_key, quantity, r.price))
        elif r.action is Action.VENDOR:
            moves.vendored += quantity * (r.price or 0)
        elif r.action in (None, Action.HOLD):
            moves.kept[r.item_key] += quantity
        elif r.action is Action.CRAFT:
            moves.spent += r.merchant_gold
    for r in shopping:
        moves.spent += r.cost
        if r.action is Action.SELL:
            moves.posts.append(_Post(r.item_key, r.quantity, r.post_at))
        elif r.action is Action.VENDOR:
            moves.vendored += r.quantity * vendor[item_id_of(r.item_key)]
        elif r.action is Action.CRAFT and r.made is not None:
            if r.made.selling:
                moves.posts.append(_Post(r.item_key, r.made.selling, r.made.post_at))
            vendor_price = vendor.get(item_id_of(r.item_key), 0)
            moves.vendored += (r.made.units - r.made.selling) * vendor_price
    for r in prediction_buys:
        moves.spent += r.cost
        moves.kept[r.item_key] += r.quantity
    return moves


def _taken(m: MarketRecommendations) -> tuple[list[Row], list[Row]]:
    """The Shopping List options and Prediction buys a player would take, since each option
    was sized as if the only buy (#86): most profit first while the gold (or the Budget)
    lasts, skipping any that buys, uses or makes an Item Key one already taken does. The
    Prediction buys then get what's left, in order."""
    gold = m.gold if m.budget is None else min(m.gold, m.budget)
    shopping: list[Row] = []
    keys: set[str] = set()
    for r in m.shopping_list:
        touched = {r.item_key, *(b.item_key for b in r.buys), *(u.item_key for u in r.uses)}
        if r.cost is None or r.cost > gold or touched & keys:
            continue
        shopping.append(r)
        keys |= touched
        gold -= r.cost
    prediction_buys = []
    for r in m.prediction_buys:
        if r.cost is not None and r.cost <= gold:
            prediction_buys.append(r)
            gold -= r.cost
    return shopping, prediction_buys


def _exit(
    moves: _Moves, item_key: str, h: Holding, price: float | None, vendor_price: int | None
) -> None:
    """A baseline's way out for held units: bound ones Vendored, the rest posted at
    `price`, or without one Vendored, or held on to without a Vendor Price either."""
    unbound = h.bags + h.bank
    moves.vendored += (h.bags_bound + h.bank_bound) * (vendor_price or 0)
    if price is not None:
        moves.posts.append(_Post(item_key, unbound, price))
    elif vendor_price is not None:
        moves.vendored += unbound * vendor_price
    else:
        moves.kept[item_key] += unbound


def _auctionator(
    held: Mapping[str, Holding],
    others: Mapping[str, Supply],
    vendor: Mapping[int, int],
    gold: int,
    deposit: Callable[[str], float],
    cut: float,
) -> _Moves:
    """Auctionator's way, roughly its buy and sell lists. Flip to Sell only: all the units
    at the cheapest ask, when it sits under the next-lowest by more than the cut and the
    Deposit, reposted 1c under that next one, most profit per gold first while the gold
    lasts. Then every held unit posted 1c under the cheapest other player's Listing left,
    or Vendored when that pays more or there's no Listing. Bound units are Vendored, and
    units with neither are held on to."""
    moves = _Moves()
    asks = {item_key: sorted(supply) for item_key, supply in others.items()}
    flips = []
    for item_key, supply in asks.items():
        prices = sorted({unit for unit, _ in supply})
        if len(prices) < 2:
            continue
        low, next_low = prices[:2]
        if next_low - low <= next_low * cut + deposit(item_key):
            continue
        units = sum(n for unit, n in supply if unit == low)
        profit = units * ((next_low - 1) * (1 - cut) - low)
        flips.append((profit / (low * units), item_key, low, units, next_low - 1))
    for _, item_key, low, units, post in sorted(flips, reverse=True):
        if low * units > gold:
            continue
        gold -= low * units
        moves.spent += low * units
        moves.posts.append(_Post(item_key, units, post))
        asks[item_key] = [(unit, n) for unit, n in asks[item_key] if unit != low]
    for item_key, h in held.items():
        vendor_price = vendor.get(item_id_of(item_key))
        post = asks[item_key][0][0] - 1 if asks.get(item_key) else None
        pays = post is not None and post * (1 - cut) > (vendor_price or 0)
        _exit(moves, item_key, h, post if pays else None, vendor_price)
    return moves


def _tsm(
    held: Mapping[str, Holding],
    others: Mapping[str, Supply],
    vendor: Mapping[int, int],
    recipes: Sequence[KnownRecipe],
    merchant: Mapping[str, float],
    market_value: Mapping[str, float],
    min_buyout: Mapping[str, int],
    gold: int,
) -> _Moves:
    """The emulated TSM's way, a typical default operation. Crafts first (`_tsm_crafts`),
    then every held unit, crafted ones included, posted 1c under the cheapest other
    player's Listing while that's between the floor, 80% of DBMarket (or the Vendor
    Price, if more), and the normal price, DBMarket (or the Vendor Price, if more), else
    at the normal price. Units without a DBMarket are Vendored, or held on to without a
    Vendor Price, and so are bound ones."""
    moves = _Moves()
    held = _tsm_crafts(held, others, recipes, merchant, market_value, min_buyout, gold, moves)
    for item_key, h in held.items():
        vendor_price = vendor.get(item_id_of(item_key))
        price = _tsm_price(market_value.get(item_key), others.get(item_key), vendor_price)
        _exit(moves, item_key, h, price, vendor_price)
    return moves


def _tsm_crafts(
    held: Mapping[str, Holding],
    others: Mapping[str, Supply],
    recipes: Sequence[KnownRecipe],
    merchant: Mapping[str, float],
    market_value: Mapping[str, float],
    min_buyout: Mapping[str, int],
    gold: float,
    moves: _Moves,
) -> dict[str, Holding]:
    """The Holdings once the emulated TSM's crafts are made, their gold counted into
    `moves`. One level deep: a Known Recipe whose output's DBMarket beats its reagents'
    DBMinBuyout (a merchant's cost where one sells it) is crafted again and again, from
    held unbound reagents first, then a merchant, then the cheapest other players' asks,
    while one more craft's reagents, held ones at their DBMinBuyout, still cost less than
    its output's DBMarket and the gold lasts. No Sell Rate and no inventory limit. Outputs
    that bind or whose bind type is unknown, and recipes with a cooldown, are left out."""
    units = {item_key: h.bags + h.bank for item_key, h in held.items()}
    asks = {item_key: sorted(supply) for item_key, supply in others.items()}
    made: Counter[str] = Counter()
    by_id = {r.recipe_id: r for r in recipes}
    for recipe in (by_id[i] for i in sorted(by_id)):
        output = str(recipe.output_item_id)
        worth = market_value.get(output)
        if recipe.bind_type is None or recipe.bind_type in BOUND_ON_CRAFT:
            continue
        if recipe.cooldown is not None or worth is None:
            continue
        needs = Counter()
        for reagent in recipe.reagents:
            needs[str(reagent.item_id)] += reagent.quantity
        priced = {key: merchant.get(key, min_buyout.get(key)) for key in needs}
        if any(p is None for p in priced.values()):
            continue
        worth *= recipe.quantity_min
        if worth <= sum(n * priced[key] for key, n in needs.items()):
            continue
        while True:
            craft = _tsm_craft(needs, units, asks, merchant, priced)
            if craft is None or craft[1] >= worth or craft[0] > gold:
                break
            spend, _, taken, bought = craft
            gold -= spend
            moves.spent += spend
            for key, n in taken.items():
                units[key] -= n
            for key, supply in bought.items():
                asks[key] = without(asks[key], supply)
            made[output] += recipe.quantity_min
    result = {}
    for item_key in sorted({*held, *made}):
        h = held.get(item_key, Holding())
        unbound = h.bags + h.bank
        used = unbound - units.get(item_key, 0)
        result[item_key] = Holding(
            bags=unbound - used + made[item_key],
            bags_bound=h.bags_bound + h.bank_bound,
        )
    return result


def _tsm_craft(
    needs: Mapping[str, int],
    units: Mapping[str, int],
    asks: Mapping[str, Supply],
    merchant: Mapping[str, float],
    priced: Mapping[str, float],
) -> tuple[float, float, Counter[str], dict[str, Supply]] | None:
    """One more craft's reagents: the gold it spends, what it costs with held reagents at
    `priced`, the held units it takes and the asks it buys; None if they can't be had."""
    spend, cost = 0.0, 0.0
    taken: Counter[str] = Counter()
    bought: dict[str, Supply] = {}
    for key, n in needs.items():
        take = min(n, units.get(key, 0))
        if take:
            taken[key] = take
        cost += take * priced[key]
        short = n - take
        if not short:
            continue
        if key in merchant:
            spend += short * merchant[key]
            continue
        asked = cheapest(asks.get(key, []), short)
        if asked is None:
            return None
        bought[key] = asked
        spend += sum(unit * k for unit, k in asked)
    return spend, cost + spend, taken, bought


def _tsm_price(
    market_value: float | None, asks: Supply | None, vendor_price: int | None
) -> float | None:
    """The emulated TSM's price to post at; None without a DBMarket. It never posts above
    the normal price, even when the cheapest Listing is dearer."""
    if market_value is None:
        return None
    normal = max(market_value, vendor_price or 0)
    floor = max(_TSM_FLOOR_SHARE * market_value, vendor_price or 0)
    undercut = min(unit for unit, _ in asks) - 1 if asks else None
    return undercut if undercut is not None and floor <= undercut < normal else normal


def _grade(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    moves: _Moves,
    later: list[SaleEvent],
    deposit: Callable[[str], float],
    cut: float,
    at: int,
) -> float:
    """What `moves` made at the Scan requested `at` bring by the end of the Sale Horizon,
    and what's still held then is worth. An unsold post has lost a Deposit per posting
    expired by then; its Best Exit Value from then on charges only the ones after."""
    posting = config.post_duration_hours * 3600
    horizon = config.sale_horizon_seconds
    value = moves.vendored - moves.spent
    kept = Counter(moves.kept)
    for item_key in sorted({p.item_key for p in moves.posts}):
        waiting = sorted(
            ([p.price, p.units] for p in moves.posts if p.item_key == item_key),
            key=lambda post: post[0],
        )
        for event in (e for e in later if e.item_key == item_key):
            room = event.units
            for post in waiting:
                if not room or post[0] > event.unit_buyout:
                    break
                sold = min(room, post[1])
                # Sold before the Scan that saw it: a posting ending right then hadn't.
                expiries = math.ceil((event.seen_at - at) / posting) - 1
                value += sold * (post[0] * (1 - cut) - expiries * deposit(item_key))
                post[1] -= sold
                room -= sold
            waiting = [post for post in waiting if post[1]]
        unsold = sum(units for _, units in waiting)
        value -= unsold * math.floor(horizon / posting) * deposit(item_key)
        kept[item_key] += unsold
    held = {item_key: Holding(bags=units) for item_key, units in kept.items() if units}
    return value + sum(exit_values(conn, config, market, held, at + horizon).values())
