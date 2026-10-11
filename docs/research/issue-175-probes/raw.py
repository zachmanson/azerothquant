from common175 import *
from brain.history import supply_at
import inspect
conn, config, market, preds, cache = setup()
prev=None
for t in [t for t in scan_times(conn, market) if ts(t) >= "10-02"]:
    o = supply_at(conn, market, t, others_only=True)
    n = gap = 0
    for k, units in o.items():
        prices = sorted(u[0] for u in units)
        n += 1
        if len(prices) >= 2 and prices[0] <= 0.8 * prices[1]: gap += 1
    hours = (t - prev)/3600 if prev else 0
    print(f"{ts(t)} gap {hours:5.1f}h keys {n:5} cheapest<=80%next {gap:4}", flush=True)
    prev = t
