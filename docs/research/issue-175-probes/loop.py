"""#175 loop: Shopping List rows + per-Item-Key first failed check at two Scans."""
import pickle, sys, time
from collections import Counter
from common175 import *
conn, config, market, preds, cache = setup()
labels = sys.argv[1:] or ["10-06 21:45", "10-07 21:33"]
out = {}
for lab in labels:
    t0 = time.monotonic()
    m = run(conn, config, market, preds, cache, find(conn, market, lab))
    kinds = Counter((r.action.value if r.action else None) for r in m.shopping_list)
    first = Counter("pass" if w.failed is None else w.failed.value for w in m.why_not)
    print(f"{lab}: rows {len(m.shopping_list)} {dict(kinds)} | why-not {dict(first)} [{time.monotonic()-t0:.0f}s]", flush=True)
    out[lab] = m
pickle.dump({k: (v.shopping_list, v.why_not) for k, v in out.items()}, open(WORK / "loop.pkl", "wb"))
