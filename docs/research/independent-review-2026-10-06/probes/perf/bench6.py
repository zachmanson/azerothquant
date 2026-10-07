import sys, time, statistics
sys.argv = ["x", "24"]
src = open(r"bench.py").read()
exec(src.split("text = ")[0])
import brain.matching as matching
from brain.history import supply_at
orig = matching._match_group
matching._match_group = lambda ps, cs, cm: ([(ps[0], cs[0])] if cm(ps[0], cs[0]) else []) if len(ps) == len(cs) == 1 else orig(ps, cs, cm)
db = open_history(":memory:")
for s in scans: import_scans(db, [s], Era.BETA, C)
at = T0 + 23 * 1200
t = time.perf_counter(); a = supply_at(db, M, at); base = time.perf_counter() - t
db.executescript("""
ALTER TABLE listing ADD COLUMN first_at INTEGER; ALTER TABLE listing ADD COLUMN last_at INTEGER;
UPDATE listing SET first_at = (SELECT requested_at FROM scan WHERE id = first_seen_scan_id),
                   last_at = (SELECT requested_at FROM scan WHERE id = last_seen_scan_id);
CREATE INDEX listing_alive ON listing (market_id, last_at, first_at);
CREATE INDEX partial_sale_by_listing ON partial_sale (listing_id);
""")
q = ("SELECT l.item_key, l.unit_buyout, l.quantity + COALESCE((SELECT SUM(p.units_sold) FROM partial_sale p"
     " JOIN scan ps ON ps.id = p.scan_id WHERE p.listing_id = l.id AND ps.requested_at > ?), 0)"
     " FROM listing l WHERE l.market_id = 1 AND l.last_at >= ? AND l.first_at <= ? ORDER BY l.id")
t = time.perf_counter(); rows = db.execute(q, (at, at, at)).fetchall(); new = time.perf_counter() - t
b = {}
for k, u, n in rows: b.setdefault(k, []).append((u, n))
print(f"supply_at(latest Scan) over {db.execute('select count(*) from listing').fetchone()[0]} listings: "
      f"{base*1000:.0f} ms -> {new*1000:.0f} ms with first/last times on listing + index; same: {a == b}")
# statistics.mean/pstdev vs plain arithmetic (db_market's per-Scan values)
xs = [float(i % 997) for i in range(30)]
t = time.perf_counter()
for _ in range(20000): statistics.mean(xs); statistics.pstdev(xs)
s1 = time.perf_counter() - t
t = time.perf_counter()
for _ in range(20000):
    m = sum(xs) / len(xs); (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5
s2 = time.perf_counter() - t
print(f"statistics.mean+pstdev x20k: {s1:.2f}s -> plain arithmetic {s2:.2f}s")
