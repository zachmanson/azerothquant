"""Synthetic workload at the README's stated size (~58k rows/Scan), profiled stage by stage."""

import cProfile
import pstats
import random
import sys
import time
from pathlib import Path

from brain.config import Config, Era, Install
from brain.fair_value import FairValueCache
from brain.history import Market, import_scans, open_history
from brain.recommend import recommend_market
from brain.savedvariables import parse_savedvariables

N_SCANS = int(sys.argv[1]) if len(sys.argv) > 1 else 24
ROWS = 58_000
ITEMS = 7_000
rng = random.Random(1)
T0 = 1_790_000_000
C = Config(installs=(Install(path=Path("C:/x"), era=Era.BETA),))
M = Market("R", "Alliance", Era.BETA)

base = {i: rng.randint(50, 50_000) for i in range(ITEMS)}
stacky = {i: rng.random() < 0.4 for i in range(ITEMS)}


def new_row():
    i = rng.randrange(ITEMS)
    q = rng.choice((1, 5, 10, 20)) if stacky[i] else 1
    unit = int(base[i] * rng.uniform(0.7, 1.6))
    return {"itemString": f"item:{1000 + i}", "quantity": q, "buyout": q * unit, "timeLeft": 4}


book = [new_row() for _ in range(ROWS)]
scans = []
for k in range(N_SCANS):
    scans.append({"id": k, "requestedAt": T0 + k * 1200, "realm": "R", "character": "Me-R",
                  "faction": "Alliance", "droppedRows": 0, "listings": [dict(r) for r in book]})
    # ~3% leave (sales/cancels), ~3% arrive, ~5% tick down a bucket.
    book = [r for r in book if rng.random() > 0.03] + [new_row() for _ in range(ROWS * 3 // 100)]
    for r in book:
        if r["timeLeft"] > 2 and rng.random() < 0.05:
            r["timeLeft"] -= 1


def lua(v):
    if isinstance(v, dict):
        return "{" + ",".join(f'["{k}"]={lua(x)}' for k, x in v.items()) + "}"
    if isinstance(v, list):
        return "{" + ",".join(lua(x) for x in v) + "}"
    if isinstance(v, str):
        return f'"{v}"'
    return str(v).lower() if isinstance(v, bool) else str(v)


text = "AzerothQuantDB = " + lua({"scans": scans[:1]}) + "\n"
t = time.perf_counter()
parse_savedvariables(text)
print(f"parse one 58k-row Scan ({len(text) / 1e6:.1f} MB of Lua): {time.perf_counter() - t:.2f}s")

db = open_history(":memory:")
t = time.perf_counter()
for s in scans:
    import_scans(db, [s], Era.BETA, C)
print(f"import {N_SCANS} Scans: {time.perf_counter() - t:.2f}s "
      f"({(time.perf_counter() - t) / N_SCANS:.2f}s each)")
print("listing rows:", db.execute("SELECT COUNT(*) FROM listing").fetchone()[0])

now = T0 + (N_SCANS - 1) * 1200
cache = FairValueCache()
for label in ("recommend, cold cache", "recommend, warm cache (next pass)"):
    cache.start_pass()
    prof = cProfile.Profile()
    t = time.perf_counter()
    prof.enable()
    recommend_market(db, C, M, [], now, fair_value_cache=cache, paid=False)
    prof.disable()
    print(f"{label}: {time.perf_counter() - t:.2f}s")
    pstats.Stats(prof).sort_stats("cumulative").print_stats(r"brain[\\/]", 22)
