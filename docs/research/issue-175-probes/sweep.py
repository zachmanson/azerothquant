import pickle, time
from collections import Counter
from common175 import *
conn, config, market, preds, cache = setup()
ts_all = [t for t in scan_times(conn, market) if ts(t) >= "10-02"]
res = {}
prev = None
for t in ts_all:
    m = run(conn, config, market, preds, cache, t)
    w = m.why_not
    fs = sum(1 for r in m.shopping_list if r.action and r.action.value == "Sell")
    passing = sum(x.failed is None for x in w)
    clear = sum(1 for x in w if x.clear_at is not None and x.clear_at >= x.ask)
    clear_se = sum(1 for x in w if x.clear_at is not None and x.clear_at >= x.ask and x.sale_events >= x.min_sale_events)
    gap = (t - prev) / 3600 if prev else 0
    print(f"{ts(t)} gap {gap:5.1f}h rows {len(m.shopping_list):2} sell {fs:2} pass {passing:2} keys {len(w):5} askUnderClear {clear:3} +se {clear_se:3} fails {dict(Counter(x.failed.value for x in w if x.failed))}", flush=True)
    res[t] = w
    prev = t
pickle.dump(res, open(WORK / "sweep.pkl", "wb"))
