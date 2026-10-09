"""Probe 4: a walk-forward backtest over the 69 Scans.

Usage: p4_backtest.py <policy> <grader> [key=value ...]
  policy: brain | brain_wide | brain_relaxed | ev | ev_nosize
  grader: wide (default evidence) | strict (Brain-like, <= 1 h gaps) | loose (no 1.2x cap)

Each policy starts with 40g at the first Scan and trades on its own simulated gold. At every
Scan, in time order:
 1. Fills: each later sale-like record (probes/_work/sales.pkl) of an Item Key at unit price
    q fills up to its units of the policy's posted units priced <= q, cheapest first (a
    buyer takes the cheapest first, so our cheaper unit would have gone instead). Only
    records whose Listing was still up at or after the Scan we posted in count. A sold unit
    brings price x (1 - 5% cut), less a deposit for every 24 h posting it waited through.
 2. Expiry: units unsold 7 days after posting are relisted once, for 7 more days, at the
    lower of their price and 1c under the cheapest other ask then (if that still beats the
    Vendor Price); still unsold after that, they're dumped at their Vendor Price after
    losing a deposit per day posted ("conservative" mark). The "market" mark instead credits them at the cheapest
    other player's ask then, after the cut, capped at their post price (not reinvested;
    reported apart).
 3. Decide: the policy picks buys with the gold it has, never in an Item Key it still has
    units posted in (the real Scans don't show our simulated posts).
Units still posted at the end are marked both ways, and reported apart as "open".
Graded only on gold: the 5s "effort" per non-stacking unit is a policy input, not a cost.
Flips to Disenchant are left out of the Brain's options (their mats aren't simulated).
"""

import json
import math
import pickle
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass

from common import OUT, WORK, Clock, replace, setup, times

import brain.recommend as R
from brain.history import supply_at
from brain.replay import _taken
from brain.scan import item_id_of

policy = sys.argv[1]
grader = sys.argv[2] if len(sys.argv) > 2 else "wide"
opts = dict(a.split("=") for a in sys.argv[3:])
KAPPA = float(opts.get("kappa", 0.5))  # demand haircut for the EV policy (a guess)
HURDLE = float(opts.get("hurdle", 0.10))  # EV must be >= this share of the cost
ITEM_CAP = float(opts.get("item_cap", 0.10))  # most of the bankroll in one Item Key
DEPLOY_CAP = float(opts.get("deploy_cap", 0.60))  # most of the bankroll tied up in posts
LOSS_CAP = float(opts.get("loss_cap", 0.05))  # most one buy can lose if nothing sells
START = int(opts.get("start", 400000))  # 40g
TAG = opts.get("tag", "")
# No new buys after this Scan time (0: none), so every buy gets its week before the data ends.
LAST_BUY = int(opts.get("last_buy", 0))
# EV v2 (designed after seeing v1, so in-sample): sales and watched hours count less with
# age (half-life in hours, 0: off), and a falling market-wide price is projected forward.
HALF_LIFE_H = float(opts.get("hl", 0))
DRIFT = opts.get("drift", "0") == "1"
# relist=0: no markdown week; a lot unsold after 7 days is vendored then (an exit rule).
RELIST = opts.get("relist", "1") == "1"
# dts=N: the Brain runs with Days to Sell set to N days (the in-game setting, ADR-0020).
DTS = float(opts.get("dts", 0))
# Share of each sale-like record's units the grader believes (p6: ~60-75% of own "gone"
# Listings were really sold, the rest cancelled).
GRADE_SHARE = float(opts.get("grade_share", 1.0))

conn, config, market, predictions, cache = setup()
TS = times(conn, market)
H = 7 * 86400
POST = 24 * 3600
CUT = R.auction_cut(market, config)
clock = Clock()

with open(WORK / "sales.pkl", "rb") as f:
    RECORDS = pickle.load(f)


def grade_ok(r):
    item, price, units, last, seen, gap, kind, fvr = r
    if grader == "strict":
        return gap <= 1.0 and (fvr is None or fvr <= 1.2)
    if grader == "loose":
        return kind == "partial" or gap <= 12
    return (kind == "partial" or gap <= 12) and (fvr is None or fvr <= 1.2)


GRADE = [r for r in RECORDS if grade_ok(r)]
# What the EV policy may learn from: the same rules, gaps <= 12 h only (their hours are
# the exposure), never anything after the Scan it decides at.
LEARN = [r for r in RECORDS if r[5] <= 12 and (r[7] is None or r[7] <= 1.2)]
LEARN_T = [r[4] for r in LEARN]
GAPS = [(a, b) for a, b in zip(TS, TS[1:]) if b - a <= 12 * 3600]

vendor = R.vendor_prices(conn, market.era)
deposit = R.deposit_of(conn, config, market)


@dataclass
class Lot:
    item: str
    units: int
    price: float
    cost: float  # per unit
    t: int
    source: str
    sold: int = 0
    proceeds: float = 0.0
    salvage: float = 0.0
    salvage_market: float = 0.0
    closed: bool = False
    relisted: bool = False


class Sim:
    def __init__(self):
        self.gold = START
        self.lots: list[Lot] = []
        self.all: list[Lot] = []
        self.spent = 0.0
        self.vendored_now = 0.0
        self.peak = START
        self.curve = []

    def open_items(self):
        return {lot.item for lot in self.lots}

    def bankroll(self):
        return self.gold + sum(l.cost * (l.units - l.sold) for l in self.lots)

    def fill(self, t0, t1):
        lo = bisect_left(GRADE_T, t0 + 1)
        hi = bisect_left(GRADE_T, t1 + 1)
        by_item = defaultdict(list)
        for lot in self.lots:
            by_item[lot.item].append(lot)
        for r in GRADE[lo:hi]:
            item, q, units, last, seen = r[:5]
            units *= GRADE_SHARE
            lots = by_item.get(item)
            if not lots:
                continue
            for lot in sorted(lots, key=lambda l: l.price):
                if units <= 1e-9 or lot.price > q:
                    break
                if last < lot.t or lot.units == lot.sold:
                    continue
                n = min(units, lot.units - lot.sold)
                waits = max(0, math.ceil((seen - lot.t) / POST) - 1)
                got = n * (lot.price * (1 - CUT) - waits * deposit(item))
                lot.sold += n
                lot.proceeds += got
                self.gold += got
                units -= n

    def expire(self, t, final=False):
        keep = []
        for lot in self.lots:
            left = lot.units - lot.sold
            v = vendor.get(item_id_of(lot.item), 0)
            if left and not final and t - lot.t < (2 * H if lot.relisted else H):
                keep.append(lot)
                continue
            if left and not final and not lot.relisted and RELIST:
                # One markdown: relist for another week under the cheapest other ask.
                asks = others_at(t).get(lot.item)
                new = min(lot.price, min(u for u, _ in asks) - 1) if asks else lot.price
                if new * (1 - CUT) > v:
                    lot.price, lot.relisted = new, True
                    keep.append(lot)
                    continue
            lost = left * math.floor(min(t - lot.t, 2 * H) / POST) * deposit(lot.item)
            lot.salvage = left * v - lost
            asks = others_at(t).get(lot.item)
            mkt = min(min(u for u, _ in asks) - 1, lot.price) * (1 - CUT) if asks else v
            lot.salvage_market = left * max(v, mkt) - lost
            self.gold += lot.salvage
            lot.closed = not final
            if not left:
                lot.closed = True
        self.lots = keep

    def buy(self, item, units, cost_total, post_at, source):
        self.gold -= cost_total
        self.spent += cost_total
        lot = Lot(item, units, post_at, cost_total / units, now, source)
        self.lots.append(lot)
        self.all.append(lot)


GRADE_T = [r[4] for r in GRADE]
_others = {}


def others_at(t):
    if t not in _others:
        _others.clear()
        _others[t] = supply_at(conn, market, t, others_only=True)
    return _others[t]


# ---------- the Brain's own Shopping List as a policy ----------
_gold_box = [START]
R.pooled_gold = lambda *a, **k: int(_gold_box[0])
R.market_budget = lambda *a, **k: None
if DTS:
    R.market_days_to_sell = lambda *a, **k: round(DTS * 86400)
orig_cheap = R._Valuer.cheap


def brain_config():
    if policy == "brain_wide":
        return replace(config, observation_window_max_seconds=12 * 3600)
    if policy == "brain_relaxed":
        R._Valuer.cheap = lambda self, k: R._Cheap(())
        return replace(config, flip_min_sale_events=1, sell_rate_prior_hours_flips=3,
                       sale_size_prior_events_flips=1, flip_min_margin_share=0.0,
                       flip_min_margin_copper=0)
    return config


def brain_moves(sim, t):
    _gold_box[0] = sim.gold
    cache.start_pass()
    m = R.recommend_market(conn, brain_config(), market, predictions, t, as_of=t,
                           buy_under=False, fair_value_cache=cache, paid=False,
                           loot_alert=False)
    m = replace(m, shopping_list=[r for r in m.shopping_list if r.disenchant is None])
    shopping, _ = _taken(m, config.shopping_list_rows)
    open_items = sim.open_items()
    for r in shopping:
        if r.cost is None or r.cost > sim.gold or r.item_key in open_items:
            continue
        if r.action is R.Action.SELL:
            sim.buy(r.item_key, r.quantity, r.cost, r.post_at, "Flip to Sell")
        elif r.action is R.Action.VENDOR:
            sim.gold += r.quantity * vendor.get(item_id_of(r.item_key), 0) - r.cost
            sim.spent += r.cost
            sim.vendored_now += r.quantity * vendor.get(item_id_of(r.item_key), 0) - r.cost
        elif r.action is R.Action.CRAFT and r.made is not None:
            v = vendor.get(item_id_of(r.item_key), 0)
            rest = r.made.units - r.made.selling
            if r.made.selling:
                # The vendored rest's gold comes back at once: the lot carries the net cost.
                sim.buy(r.item_key, r.made.selling, r.cost - rest * v, r.made.post_at,
                        "Flip to Craft")
            else:
                sim.gold += rest * v - r.cost
                sim.spent += r.cost


# ---------- the expected-value policy ----------
def poisson_terms(mu):
    k_max = int(mu + 6 * math.sqrt(mu) + 12)
    p = math.exp(-mu)
    out = [p]
    for k in range(1, k_max + 1):
        p *= mu / k
        out.append(p)
    return out


def expected_sold(rate_ev, size, ahead, n, hours):
    """E[min(n, max(0, size*N - ahead))], N ~ Poisson(rate_ev * hours)."""
    mu = rate_ev * hours
    if mu <= 0:
        return 0.0
    if mu > 40:  # exp(-mu) underflows past ~745; past 40 the mean is close enough
        return min(n, max(0.0, size * mu - ahead))
    return sum(p * min(n, max(0.0, size * k - ahead)) for k, p in enumerate(poisson_terms(mu)))


def ev_moves(sim, t):
    since = t - config.sell_rate_range_seconds

    def w(at):
        return 0.5 ** ((t - at) / 3600 / HALF_LIFE_H) if HALF_LIFE_H else 1.0

    hours = sum((b - a) * w(b) for a, b in GAPS if since < b <= t) / 3600
    lo, hi = bisect_left(LEARN_T, since + 1), bisect_left(LEARN_T, t + 1)
    seen = defaultdict(list)
    for r in LEARN[lo:hi]:
        seen[r[0]].append((r[1], r[2], w(r[4])))
    fall = 1.0
    if DRIFT:
        back = [x for x in TS if x <= t - 72 * 3600]
        if back:
            a, b = cache.fair_values(conn, market, config, back[-1]), cache.fair_values(conn, market, config, t)
            ratios = sorted(b[k] / a[k] for k in set(a) & set(b) if a[k])
            if ratios:
                per_day = ratios[len(ratios) // 2] ** (86400 / (t - back[-1])) - 1
                fall = (1 + min(0.0, per_day)) ** 3.5  # half the week, falling at that rate
    others = others_at(t)
    valuer = R._valuer(conn, config, market, t, fair_value_cache=cache)[0]
    bank = sim.bankroll()
    brake = 0.5 if bank < 0.8 * sim.peak else 1.0
    item_cap, loss_cap = ITEM_CAP * bank * brake, LOSS_CAP * bank * brake
    if policy == "ev_nosize":
        item_cap = loss_cap = math.inf
    prior_h = config.sell_rate_prior_hours_flips
    cands = []
    for item, sales in seen.items():
        offers = sorted(others.get(item, []))
        if not offers or item in sim.open_items():
            continue
        sales.sort(reverse=True)  # dearest first
        prices = [-p for p, _, _ in sales]
        cum_units, cum_w, c, cw = [], [], 0.0, 0.0
        for _, u, wt in sales:
            c += u * wt
            cw += wt
            cum_units.append(c)
            cum_w.append(cw)
        v = vendor.get(item_id_of(item), 0)
        dep = deposit(item)
        effort = valuer.effort(item)
        best = None
        cost = n = 0
        for i, (unit, qty) in enumerate(offers[:12]):
            cost += unit * qty
            n += qty
            if cost > item_cap or cost > sim.gold:
                break
            rest = offers[i + 1:]
            levels = sorted({u for u, _ in rest})[:4]
            for j, level in enumerate(levels):
                post = level - config.post_undercut_copper
                if post <= unit:
                    continue
                ahead = sum(q for u, q in rest if u < post)
                net = post * fall * (1 - CUT) - effort
                if n * net - cost - effort * n < HURDLE * cost:
                    continue  # can't clear the hurdle even if every unit sells
                k = bisect_right(prices, -post)  # sales at >= post
                if not k:
                    continue
                units_at, events = cum_units[k - 1], cum_w[k - 1]
                rate = events / (hours + prior_h) * KAPPA
                size = units_at / events
                sold_by = [expected_sold(rate, size, ahead, n, d * 24) for d in range(1, 8)]
                sold = sold_by[-1]
                deposits = dep * sum(n - s for s in sold_by[:-1]) + dep * (n - sold)
                ev = sold * net + (n - sold) * v - deposits - cost - effort * n
                worst = cost + effort * n - n * v + 7 * dep * n
                if worst > loss_cap:
                    continue
                if ev >= HURDLE * cost and (best is None or ev > best[0]):
                    best = (ev, cost, n, post, worst)
        if best:
            cands.append((best[0] / best[1], item, *best))
    cands.sort(reverse=True)
    deployed = bank - sim.gold
    for _, item, ev, cost, n, post, worst in cands:
        if cost > sim.gold or deployed + cost > DEPLOY_CAP * bank:
            continue
        sim.buy(item, n, cost, post, "EV")
        deployed += cost


# ---------- the Buy Unders as standing orders ----------
_standing = []


def buyunder_moves(sim, t):
    _gold_box[0] = sim.gold
    others = others_at(t)
    open_items = sim.open_items()
    for b in _standing:
        if b.item_key is None or b.item_key in open_items or b.way not in (R.Action.SELL, R.Action.VENDOR):
            continue
        offers = sorted(others.get(b.item_key, []))
        take, cost, units = [], 0, 0
        cap = math.inf if b.units is None else b.units
        for unit, qty in offers:
            if unit > b.price or units >= cap:
                break
            q = int(min(qty, cap - units))
            if cost + unit * q > sim.gold:
                q = int((sim.gold - cost) // unit)
            if q <= 0:
                break
            take.append((unit, q))
            cost += unit * q
            units += q
        if not units:
            continue
        if b.way is R.Action.VENDOR:
            v = vendor.get(item_id_of(b.item_key), 0)
            sim.gold += units * v - cost
            sim.spent += cost
            sim.vendored_now += units * v - cost
            continue
        left = R.without(offers, take)
        post = R._undercut(left[0][0] if left else None, None, config, None)
        if post is None:
            continue
        sim.buy(b.item_key, units, cost, post, "Buy Under")
    cache.start_pass()
    m = R.recommend_market(conn, config, market, predictions, t, as_of=t, buy_under=True,
                           fair_value_cache=cache, paid=False, loot_alert=False)
    _standing[:] = m.buy_under


# ---------- run ----------
sim = Sim()
prev = TS[0] - 1
for now in TS:
    sim.fill(prev, now)
    sim.expire(now)
    sim.peak = max(sim.peak, sim.bankroll())
    if LAST_BUY and now > LAST_BUY:
        pass
    elif policy == "buyunder":
        buyunder_moves(sim, now)
    elif policy.startswith("brain"):
        brain_moves(sim, now)
    else:
        ev_moves(sim, now)
    R._Valuer.cheap = orig_cheap
    sim.curve.append((now, round(sim.gold), round(sim.bankroll())))
    clock.lap(f"{policy}/{grader} {now} gold {sim.gold/1e4:.2f}g lots {len(sim.lots)}")
    prev = now
sim.expire(TS[-1], final=True)

closed = [l for l in sim.all if l.closed]
opened = [l for l in sim.all if not l.closed]


def pnl(lots, market_mark=False):
    return sum(l.proceeds + (l.salvage_market if market_mark else l.salvage)
               - l.cost * l.units for l in lots)


full = [l for l in sim.all if l.t + H <= TS[-1]]
res = {
    "policy": policy, "grader": grader, "opts": opts,
    "start_gold": START, "end_gold_conservative": round(sim.gold),
    "buys": len(sim.all), "spent": round(sim.spent),
    "units_bought": sum(l.units for l in sim.all),
    "units_sold": sum(l.sold for l in sim.all),
    "pnl_closed": round(pnl(closed)), "pnl_closed_market": round(pnl(closed, True)),
    "pnl_open_conservative": round(pnl(opened)), "pnl_open_market": round(pnl(opened, True)),
    "pnl_all_conservative": round(pnl(sim.all)), "pnl_all_market": round(pnl(sim.all, True)),
    "pnl_full_horizon_cohort": round(pnl(full)),
    "pnl_full_horizon_cohort_market": round(pnl(full, True)),
    "full_horizon_buys": len(full),
    "vendor_flips_net": round(sim.vendored_now),
    "winners": sum(1 for l in sim.all if l.proceeds + l.salvage > l.cost * l.units),
    "losers": sum(1 for l in sim.all if l.proceeds + l.salvage < l.cost * l.units),
    "biggest_loss": round(min((l.proceeds + l.salvage - l.cost * l.units for l in sim.all),
                              default=0)),
    "biggest_win": round(max((l.proceeds + l.salvage - l.cost * l.units for l in sim.all),
                             default=0)),
    "curve": sim.curve,
    "trades": [l.__dict__ for l in sim.all],
}
name = f"p4_{policy}_{grader}{('_' + TAG) if TAG else ''}.json"
(OUT / name).write_text(json.dumps(res, indent=1))
print({k: v for k, v in res.items() if k not in ("curve", "trades")})
