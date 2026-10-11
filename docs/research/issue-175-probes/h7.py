import common175
from pathlib import Path
common175.WORK = Path(common175.__file__).parent / "work2"
from collections import Counter
from common175 import *
from brain.history import scan_times
conn, config, market, preds, cache = setup()
T = scan_times(conn, market)
orig = R._Valuer.cheap
for lab in ["10-08 18:23", "10-09 21:49", "10-10 17:00", "10-10 17:20", "10-06 21:45"]:
    now = find(conn, market, lab)
    base = {w.item_key: w for w in run(conn, config, market, preds, cache, now).why_not}
    R._Valuer.cheap = lambda self, k: R._Cheap(())
    free = {w.item_key: w for w in run(conn, config, market, preds, cache, now).why_not}
    R._Valuer.cheap = orig
    lost = [k for k, w in free.items() if w.failed is None and base[k].failed is not None]
    ages = Counter()
    for k in lost:
        b = base[k]
        scans_back = T.index(now) - T.index(b.cheap_since) if b.cheap_since in T else None
        ages[(scans_back, round((now - b.cheap_since) / 3600, 1) if b.cheap_since else None, b.failed.value)] += 1
    print(f"{lab}: lost to cutoff {len(lost)}; (stretch began N Scans back, hours ago, check): {dict(ages)}", flush=True)
