import functools, sys, time
from dataclasses import replace
sys.argv = ["x", "12"]
src = open(r"bench.py").read()
exec(src.split("text = ")[0])
import brain.matching as matching, brain.replay as replay, brain.recommend as rec
orig = matching._match_group
matching._match_group = lambda ps, cs, cm: ([(ps[0], cs[0])] if cm(ps[0], cs[0]) else []) if len(ps) == len(cs) == 1 else orig(ps, cs, cm)
db = open_history(":memory:")
for s in scans: import_scans(db, [s], Era.BETA, C)
replay.character_markets = rec.character_markets = lambda conn: {M: []}
cfg = replace(C, sale_horizon_seconds=3600)
since, until = T0 + 6 * 1200, T0 + 8 * 1200
t = time.perf_counter(); r1 = replay.replay(db, cfg, [], since, until); a = time.perf_counter() - t
shared = FairValueCache()
replay.recommend_market = functools.partial(replay.recommend_market, fair_value_cache=shared)
t = time.perf_counter(); r2 = replay.replay(db, cfg, [], since, until); b = time.perf_counter() - t
print(f"C replay of {r1[0].scans} Scans x {len(r1[0].graded)} policies: {a:.1f}s -> {b:.1f}s "
      f"with one shared cache; same grades: {r1[0].graded == r2[0].graded}")
# D. packed rows: one string per Scan, "itemString,qty,buyout,timeLeft;..."
packed = ";".join(f'{r["itemString"]},{r["quantity"]},{r["buyout"]},{r["timeLeft"]}' for r in scans[0]["listings"])
t = time.perf_counter()
rows = [x.split(",") for x in packed.split(";")]
rows = [{"itemString": a, "quantity": int(b), "buyout": int(c), "timeLeft": int(d)} for a, b, c, d in rows]
print(f"D split a packed 58k-row Scan string: {time.perf_counter() - t:.2f}s ({len(packed)/1e6:.1f} MB)")
