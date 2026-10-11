import sys, common175
from pathlib import Path
common175.WORK = Path(common175.__file__).parent / "work2"
from common175 import *
R._Valuer.cheap = lambda self, k: R._Cheap(())
conn, config, market, preds, cache = setup()
for lab in ["10-04 19:05", "10-06 21:45", "10-07 21:33", "10-08 18:02", "10-08 18:23", "10-09 20:51", "10-09 21:49", "10-10 16:44", "10-10 17:00", "10-10 17:20", "10-10 17:38", "10-11 12:03"]:
    m = run(conn, config, market, preds, cache, find(conn, market, lab))
    w = m.why_not
    o = [x for x in w if x.post_at and x.ask <= 0.8 * x.post_at]
    print(f"nocheap {lab}: rows {len(m.shopping_list):2} pass {sum(x.failed is None for x in w):2} outliers se>=3 {sum(x.sale_events>=3 for x in o)}", flush=True)
