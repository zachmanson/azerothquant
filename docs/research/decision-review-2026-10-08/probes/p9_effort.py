"""Probe 9: the 5s "effort" per non-stacking unit (#73) as a gate, on the latest Scan.

Flips to Disenchant and gear Flips to Sell pay it per unit bought (and posted). Re-runs the
Shopping List with it at 500c (as is), 200c, 100c and 0c, with nothing else changed.
Writes probes/out/p9_effort.txt.
"""

from collections import Counter

from common import OUT, replace, setup, times

import brain.recommend as R

conn, config, market, predictions, cache = setup()
now = times(conn, market)[-1]
out = []
for effort in (500, 200, 100, 0):
    cache.start_pass()
    m = R.recommend_market(conn, replace(config, non_stacking_effort_copper=effort), market,
                           predictions, now, fair_value_cache=cache, buy_under=False,
                           paid=False, loot_alert=False)
    c, p, cost = Counter(), Counter(), Counter()
    for r in m.shopping_list:
        k = "Disenchant" if r.disenchant else r.action.value
        c[k] += 1
        p[k] += r.profit or 0
        cost[k] += r.cost or 0
    line = f"effort {effort:>3}c: " + ", ".join(
        f"{k} {c[k]} rows (profit {p[k]/1e4:.2f}g on {cost[k]/1e4:.2f}g)" for k in sorted(c))
    print(line, flush=True)
    out.append(line)
(OUT / "p9_effort.txt").write_text("\n".join(out) + "\n")
