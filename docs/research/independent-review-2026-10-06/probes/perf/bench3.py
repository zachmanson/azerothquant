import functools, re, sys, time
from dataclasses import replace
sys.argv = ["x", "12"]
src = open(r"bench.py").read()
exec(src.split("text = ")[0])
import brain.matching as matching, brain.savedvariables as sv, brain.replay as replay, brain.recommend as rec

# --- A. matching fast path: a 1x1 group needs no flow graph ---
orig_group = matching._match_group
def fast_group(ps, cs, can_match):
    if len(ps) == 1 and len(cs) == 1:
        return [(ps[0], cs[0])] if can_match(ps[0], cs[0]) else []
    return orig_group(ps, cs, can_match)
def import_all(label):
    db = open_history(":memory:"); t = time.perf_counter()
    for s in scans: import_scans(db, [s], Era.BETA, C)
    dt = time.perf_counter() - t
    rows = db.execute("SELECT item_key, unit_buyout, quantity, first_seen_scan_id, last_seen_scan_id FROM listing ORDER BY 1,2,3,4,5").fetchall()
    ps = db.execute("SELECT COUNT(*), SUM(units_sold) FROM partial_sale").fetchone()
    print(f"A {label}: import {len(scans)} Scans {dt:.1f}s; listings={len(rows)} partial={ps}")
    return db, rows
db, base_rows = import_all("as is")
matching._match_group = fast_group
_, fast_rows = import_all("1x1 fast path")
print("   same history:", base_rows == fast_rows)
matching._match_group = orig_group

# --- B. parser: string fast path + whitespace regex ---
text = "AzerothQuantDB = " + lua({"scans": scans[:1]}) + "\n"
t = time.perf_counter(); ref = parse_savedvariables(text); a = time.perf_counter() - t
_PLAIN = re.compile(r'"([^"\\n]*)"')
_WS = re.compile(r"\s*")
orig_string, orig_skip = sv._Parser._string, sv._Parser._skip_space
def string(self):
    m = _PLAIN.match(self.text, self.pos)
    if m: self.pos = m.end(); return m.group(1)
    return orig_string(self)
def skip(self):
    self.pos = _WS.match(self.text, self.pos).end()
    if self.text.startswith("--", self.pos): orig_skip(self)
sv._Parser._string, sv._Parser._skip_space = string, skip
t = time.perf_counter(); new = parse_savedvariables(text); b = time.perf_counter() - t
print(f"B parse one Scan: {a:.2f}s -> {b:.2f}s, same result: {ref == new}")

# --- C. replay with and without one shared FairValueCache ---
replay.character_markets = rec.character_markets = lambda conn: {M: []}
cfg = replace(C, sale_horizon_seconds=2 * 3600)
since, until = T0 + 6 * 1200, T0 + 8 * 1200   # 3 Scans replayed
t = time.perf_counter(); r1 = replay.replay(db, cfg, [], since, until); a = time.perf_counter() - t
shared = FairValueCache()
orig_rm = replay.recommend_market
replay.recommend_market = functools.partial(orig_rm, fair_value_cache=shared)
t = time.perf_counter(); r2 = replay.replay(db, cfg, [], since, until); b = time.perf_counter() - t
print(f"C replay of {r1[0].scans} Scans: {a:.1f}s -> {b:.1f}s with one shared cache; "
      f"same grades: {r1[0].graded == r2[0].graded}")
