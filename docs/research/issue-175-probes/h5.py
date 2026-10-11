import sys, common175
from pathlib import Path
common175.WORK = Path(common175.__file__).parent / "work2"
from common175 import *
import brain.observation as O
if sys.argv[1] == "off":
    O.dropped_item_ids = lambda conn, market: {}
conn, config, market, preds, cache = setup()
for lab in ["10-06 21:45", "10-07 21:33", "10-08 18:02", "10-08 18:23", "10-09 20:51", "10-09 21:49", "10-10 16:44", "10-10 17:00", "10-10 17:20", "10-11 12:03"]:
    m = run(conn, config, market, preds, cache, find(conn, market, lab))
    w = m.why_not
    print(f"{sys.argv[1]} {lab}: rows {len(m.shopping_list):2} pass {sum(x.failed is None for x in w):2} SE-fails {sum(1 for x in w if x.failed and x.failed.value=='Sale Events')}", flush=True)
