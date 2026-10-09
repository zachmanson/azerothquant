"""Probe 5: why Flips to Craft and Flips to Disenchant are 0-2 rows.

(a) Latest Scan, every Known Recipe: the first Flip to Craft step the Brain would take,
    the output's post price, Sell room and Sale Events, and what stopped it.
(b) Latest Scan, every Disenchant source group with Listings: cheapest Listing, the
    expected mats' value for one Disenchant, the margin it needs, and what stopped it.
(c) Every Scan: how many Flips to Craft / Disenchant / Sell rows the Brain made, as is and
    with the Flip margin at 0 and the Sale Events minimum at 1 for these two tabs.
Writes probes/out/p5_craft_de.txt.
"""

import math
from collections import Counter

from common import OUT, Clock, replace, setup, times

import brain.recommend as R
from brain.scan import item_id_of

conn, config, market, predictions, cache = setup()
TS = times(conn, market)
now = TS[-1]
clock = Clock()
out = []


def say(s=""):
    print(s, flush=True)
    out.append(s)


def g(c):
    return "-" if c is None else f"{c/1e4:.2f}g"


craft_log, de_log = [], []
orig_ftc, orig_ftd = R._flips_to_craft, R._flip_to_disenchant


def ftc(plans, crafting, asks, merchant, valuer, outlet, under, gold, config_, plan):
    res = orig_ftc(plans, crafting, asks, merchant, valuer, outlet, under, gold, config_, plan)
    info = {"recipe": plan.recipe.recipe_id, "output": plan.output, "made": len(res)}
    if plan.recipe.bind_type is None:
        info["stop"] = "unknown bind type"
    else:
        sources = R._Sources(held=dict(crafting.held), crafted=dict(crafting.crafted),
                             asks=dict(asks), merchant=merchant, valuer=valuer, under=under,
                             plans=plans, spent=__import__("collections").Counter(crafting.spent),
                             config=config_)
        out_ = outlet(plan)
        step = R._flip_step(plan, sources, out_)
        rate = valuer.rates.get(plan.output)
        info.update(post_at=out_.post_at, room=out_.room, vendor=out_.vendor_price,
                    events=rate.sale_events if rate else 0,
                    events_at=(rate.at_or_above(out_.post_at).sale_events
                               if rate and out_.post_at else 0),
                    qty=plan.recipe.quantity_min)
        if step is None:
            info["stop"] = "no step (reagents can't be had, or nothing to buy)"
        else:
            need = max(step.gold * config_.flip_min_margin_share, config_.flip_min_margin_copper)
            info.update(gold=step.gold, profit=step.profit, need=need, selling=step.selling)
            if step.gold > gold:
                info["stop"] = "gold"
            elif step.profit < need:
                info["stop"] = ("margin, output Vendored (no Sell room)" if step.selling == 0
                                else "margin")
            else:
                info["stop"] = None
    craft_log.append(info)
    return res


def ftd(group, disenchanter, listed, valuer, sources, gold, config_):
    res = orig_ftd(group, disenchanter, listed, valuer, sources, gold, config_)
    unit, key = min(listed)
    expected = {str(m): q for m, q in group.expected.items()}
    net = R._mats_value(expected, {}, valuer, sources, config_)
    sell_part = 0.0
    for mat, q in expected.items():
        w = R._way_out(mat, valuer, config_, sources)
        sell_part += q * (w.value if w and w.way is R.Action.SELL else 0)
    need = max(unit * config_.flip_min_margin_share, config_.flip_min_margin_copper)
    de_log.append({"group": group.key, "listed": len(listed), "cheapest": unit,
                   "mats": net, "sell_part": sell_part,
                   "effort": config_.non_stacking_effort_copper,
                   "need": need, "made": res.quantity if res else 0})
    return res


R._flips_to_craft, R._flip_to_disenchant = ftc, ftd


def run(cfg, at):
    cache.start_pass()
    return R.recommend_market(conn, cfg, market, predictions, at, as_of=at, buy_under=False,
                              fair_value_cache=cache, paid=False, loot_alert=False)


m = run(config, now)
clock.lap("latest")
say(f"Latest Scan: {len(craft_log)} recipes known; Flips to Craft made: "
    f"{sum(1 for c in craft_log if c['made'])}")
stops = Counter(c.get("stop") or "made" for c in craft_log)
say("What stopped each recipe's first Flip to Craft step:")
for k, n in stops.most_common():
    say(f"  {n:>3}  {k}")
say("\n  output  qty  post_at  room  events(all/at post)  gold  profit  needs  stop")
for c in sorted(craft_log, key=lambda c: -(c.get("profit") or -1e9)):
    say(f"  {c['output']:>7} {c.get('qty','')!s:>3} {g(c.get('post_at')):>8} {c.get('room','')!s:>4}"
        f" {c.get('events',0):>4}/{c.get('events_at',0):<4} {g(c.get('gold')):>8}"
        f" {g(c.get('profit')):>8} {g(c.get('need')):>7}  {c.get('stop') or 'made'}")

say(f"\nDisenchant source groups with Listings whose best way out is Disenchant: {len(de_log)}")
for d in sorted(de_log, key=lambda d: d["cheapest"] - d["mats"]):
    say(f"  {d['group']!s:<28} listed {d['listed']:>3}  cheapest {g(d['cheapest']):>7}"
        f"  mats {g(d['mats']):>7} (by Sell {g(d['sell_part'])})  - effort {g(d['effort'])}"
        f"  margin needs {g(d['need'])}  bought {d['made']}")
skills = R.enchanting_skills(conn, market, None)
say(f"Enchanting skills: {skills}")

# (c) rows per Scan.
loose = replace(config, flip_min_margin_share=0.0, flip_min_margin_copper=0,
                flip_min_sale_events=1)
say("\nRows per Scan (Sell, Craft, Disenchant): as is | margin 0 + min 1 Sale Event")
per = []
for at in TS:
    row = []
    for cfg in (config, loose):
        craft_log.clear()
        de_log.clear()
        mm = run(cfg, at)
        c = Counter("Disenchant" if r.disenchant else r.action.value for r in mm.shopping_list)
        row.append((c["Sell"] + c["Vendor"], c["Craft"], c["Disenchant"]))
    per.append(row)
    say(f"  {at}  {row[0]}  |  {row[1]}")
clock.lap("per scan")
for i, name in enumerate(("as is", "loosened")):
    for j, kind in enumerate(("Sell/Vendor", "Craft", "Disenchant")):
        vals = [r[i][j] for r in per]
        say(f"{name:<9} {kind:<11} mean {sum(vals)/len(vals):.1f}  zero in "
            f"{sum(v == 0 for v in vals)}/{len(vals)} Scans  max {max(vals)}")
(OUT / "p5_craft_de.txt").write_text("\n".join(out) + "\n")
