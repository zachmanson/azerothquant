from common175 import *
conn, config, market, preds, cache = setup()
def count(m): return len(m.shopping_list), sum(w.failed is None for w in m.why_not)
orig = R.dropped_at
for lab in ["10-07 21:33", "10-08 18:02", "10-09 21:49", "10-10 17:00", "10-10 17:20"]:
    t = find(conn, market, lab)
    base = count(run(conn, config, market, preds, cache, t))
    R.dropped_at = lambda *a: frozenset()
    nod = count(run(conn, config, market, preds, cache, t))
    R.dropped_at = orig
    print(f"H2 {lab}: rows/pass base {base} -> no dropped gate {nod}", flush=True)
t = find(conn, market, "10-05 18:17")
for asof in (t, t + 120):
    cache.start_pass()
    m = R.recommend_market(conn, config, market, preds, t, as_of=asof, fair_value_cache=cache,
                           why_not=True, buy_under=False, paid=False, loot_alert=False)
    print(f"H3 10-05 18:17 as_of {ts(asof)}: gold {m.gold} rows/pass {count(m)}", flush=True)
