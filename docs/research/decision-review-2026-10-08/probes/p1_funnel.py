"""Probe 1: which gates remove the Flip to Sell candidates on the latest Scan.

(a) The Brain's own why-not verdicts (first failed Check, #108) for every Item Key with
    other players' Listings, plus each Check tested on its own (not just the first fail).
(b) The Shopping List re-run with one gate relaxed at a time, then all at once, in one
    process so the Fair Values are worked out once.
Writes probes/out/p1_*.json and prints a summary (saved as probes/out/p1_funnel.txt).
"""

from collections import Counter

from common import Clock, dump, replace, setup, times

import brain.recommend as R

conn, config, market, predictions, cache = setup()
now = times(conn, market)[-1]
clock = Clock()
lines = []


def say(s=""):
    print(s, flush=True)
    lines.append(s)


def run(cfg, why_not=False, buy_under=False):
    cache.start_pass()
    return R.recommend_market(
        conn, cfg, market, predictions, now, fair_value_cache=cache, why_not=why_not,
        buy_under=buy_under, paid=False, loot_alert=False,
    )


def summary(m):
    c = Counter()
    profit = Counter()
    for r in m.shopping_list:
        kind = "Disenchant" if r.disenchant else r.action.value
        c[kind] += 1
        profit[kind] += r.profit or 0
    return {k: (c[k], round(profit[k])) for k in sorted(c)}


base = run(config, why_not=True, buy_under=True)
clock.lap("baseline (cold)")
say(f"Scan {now}, gold {base.gold}, spend {base.spend}, window hours {base.window_hours:.1f}")
say(f"Shopping List baseline: {summary(base)}  ({len(base.shopping_list)} rows)")
say(f"Buy Unders: {len(base.buy_under)}  listed now: {sum(b.listed_now for b in base.buy_under)}")

w = base.why_not
first = Counter("made the list" if x.failed is None else x.failed.value for x in w)
say(f"\nItem Keys with other players' Listings: {len(w)}")
say("First failed Check (the Brain's own order):")
for k, n in first.most_common():
    say(f"  {k:<16} {n}")

# Each check on its own.
no_price = sum(x.post_at is None for x in w)
se = [x for x in w if x.sale_events < x.min_sale_events]
se0 = [x for x in w if x.sale_events == 0]
room = [x for x in w if x.room < x.held + x.needs]
margin = [x for x in w if x.clear_at is None or x.clear_at < x.ask]
cut = [x for x in w if x.cheap_since is not None]
needs_wall = [x for x in w if x.needs > 1]
say("\nEach Check alone (an Item Key can fail several):")
say(f"  no price to post at (nothing else listed): {no_price}")
say(f"  Sale Events at/above post price < {config.flip_min_sale_events}: {len(se)}"
    f"  (of which 0 Sale Events: {len(se0)})")
say(f"  room < held + needs:                     {len(room)}")
say(f"  margin: cheapest ask above clear-at price: {len(margin)}")
say(f"  demand cut to 'since cheap stock went up':  {len(cut)}")
say(f"  clearing run is a wall (needs > 1 unit):  {len(needs_wall)}")
both = [x for x in w if x.clear_at is not None and x.clear_at >= x.ask]
say(f"  cheapest ask clears margin at its way-out value: {len(both)}")
say("  ...of those, failing Sale Events: "
    f"{sum(x.sale_events < x.min_sale_events for x in both)}, failing room: "
    f"{sum(x.room < x.held + x.needs for x in both)}")

# Sale Events at all, regardless of price.
rates = R._valuer(conn, config, market, now, fair_value_cache=cache)[0].rates
any_sales = sum(1 for x in w if rates.get(x.item_key) and rates[x.item_key].sale_events)
three = sum(1 for x in w if rates.get(x.item_key) and rates[x.item_key].sale_events >= 3)
say(f"\nItem Keys on sale with any Sale Event in 14 days: {any_sales}; with >=3: {three}")
dump("p1_why_not.json", w)

# (b) one gate relaxed at a time.
orig_dropped, orig_cheap = R.dropped_at, R._Valuer.cheap


def no_dropped(on):
    R.dropped_at = (lambda *a: frozenset()) if on else orig_dropped


def no_cheap(on):
    R._Valuer.cheap = (lambda self, k: R._Cheap(())) if on else orig_cheap


variants = {
    "min Sale Events 3 -> 1": dict(flip_min_sale_events=1),
    "no cheap-stock cutoff": "cheap",
    "Flip priors -> Holdings priors (3 h, 1 event)": dict(
        sell_rate_prior_hours_flips=3, sale_size_prior_events_flips=1),
    "margin 10%/1s -> 0%/0c": dict(flip_min_margin_share=0.0, flip_min_margin_copper=0),
    "margin 10%/1s -> 5%/0c": dict(flip_min_margin_share=0.05, flip_min_margin_copper=0),
    "deposits off": dict(deposits=False),
    "dropped rows ignored": "dropped",
    "undercut 1c -> 0c (match)": dict(post_undercut_copper=0),
    "ALL of the above (margin 0)": "all",
}
results = {"baseline": summary(base)}
say("\nShopping List with one gate relaxed (kind: rows, expected profit in copper):")
say(f"  {'baseline':<46} {summary(base)}")
for name, v in variants.items():
    cfg = config
    if v == "cheap":
        no_cheap(True)
    elif v == "dropped":
        no_dropped(True)
    elif v == "all":
        no_cheap(True)
        no_dropped(True)
        cfg = replace(config, flip_min_sale_events=1, sell_rate_prior_hours_flips=3,
                      sale_size_prior_events_flips=1, flip_min_margin_share=0.0,
                      flip_min_margin_copper=0, deposits=False)
    else:
        cfg = replace(config, **v)
    m = run(cfg)
    no_cheap(False)
    no_dropped(False)
    results[name] = summary(m)
    say(f"  {name:<46} {results[name]}")
    clock.lap(name)
    if v == "all":
        dump("p1_all_relaxed_rows.json", m.shopping_list)

dump("p1_variants.json", results)
dump("p1_baseline_rows.json", base.shopping_list)
dump("p1_buy_unders.json", base.buy_under)
(dump("p1_funnel.txt", "") .write_text("\n".join(lines) + "\n"))
