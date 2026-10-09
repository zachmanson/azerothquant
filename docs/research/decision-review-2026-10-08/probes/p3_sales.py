"""Probe 3: a table of every sale-like event in the history, over every gap between Scans,
for the backtest's grader and for the EV policy's demand estimates.

A record is (item_key, unit price, units, last_seen, seen_at, gap_hours, kind, fv_ratio):
- kind "partial": a Partial Sale (a stack that shrank), unambiguous in any gap. The Brain
  only counts the ones at the end of an Observation Window (<= 60 min gap).
- kind "gone": another player's Listing that went missing, whose time-left bucket rules
  out expiry over the gap, and no Repost explains (the Brain's own rules, ADR-0004, but
  in any gap, not only <= 60 min).
Items either Scan dropped rows of are left out, as the Brain does (#150).
fv_ratio is the price over the Fair Value of the Scan it was last seen in (the Brain caps
Probable Sales at 1.2x).
Writes probes/_work/sales.pkl and probes/out/p3_sales.txt.
"""

import pickle
from collections import Counter, defaultdict

from common import OUT, WORK, Clock, setup, times

from brain.history import dropped_item_ids, partial_sales
from brain.observation import _disappearance, _pair_reposts
from brain.scan import item_id_of

conn, config, market, predictions, cache = setup()
ts = times(conn, market)
nxt = dict(zip(ts, ts[1:]))
clock = Clock()
seen = cache.listings(conn, market)
dropped = dropped_item_ids(conn, market)


def left_out(a, b):
    return dropped.get(a, frozenset()) | dropped.get(b, frozenset())


fv = {}


def fair(at, key):
    if at not in fv:
        fv[at] = cache.fair_values(conn, market, config, at)
    return fv[at].get(key)


new_by_first = defaultdict(list)
cands = defaultdict(list)
for x in seen:
    new_by_first[x.first_seen].append(x)
    if x.own:
        continue
    gone = nxt.get(x.last_seen)
    if gone is None or item_id_of(x.item_key) in left_out(x.last_seen, gone):
        continue
    d = _disappearance(x, gone, config)
    if not d.expiry_possible:
        cands[gone].append(d)
clock.lap("candidates")

records = []
reposts = 0
for gone, ds in cands.items():
    pairing = _pair_reposts(ds, new_by_first.get(gone, []))
    reposts += len(pairing.reposts)
    for d in pairing.sales:
        v = fair(d.last_seen, d.item_key)
        records.append((d.item_key, d.unit_buyout, d.quantity, d.last_seen, gone,
                        (gone - d.last_seen) / 3600, "gone", d.unit_buyout / v if v else None))
clock.lap("gone")
prev = {b: a for a, b in nxt.items()}
for p in partial_sales(conn, market):
    if p.own or p.seen_at not in prev:
        continue
    a = prev[p.seen_at]
    if item_id_of(p.item_key) in left_out(a, p.seen_at):
        continue
    v = fair(a, p.item_key)
    records.append((p.item_key, p.unit_buyout, p.units_sold, a, p.seen_at, (p.seen_at - a) / 3600,
                    "partial", p.unit_buyout / v if v else None))
clock.lap("partial")
records.sort(key=lambda r: r[4])
with open(WORK / "sales.pkl", "wb") as f:
    pickle.dump(records, f)

out = []
c = Counter()
u = Counter()
for r in records:
    band = "<=1h" if r[5] <= 1 else "1-12h" if r[5] <= 12 else ">12h"
    c[(r[6], band)] += 1
    u[(r[6], band)] += r[2]
out.append(f"Sale-like records: {len(records)} ({sum(r[2] for r in records)} units); "
           f"reposts paired off: {reposts}")
for k in sorted(c):
    out.append(f"  {k[0]:<8} gap {k[1]:<6} {c[k]:>7} records {u[k]:>8} units")
capped = [r for r in records if r[7] is not None and r[7] > 1.2]
out.append(f"  priced over 1.2x Fair Value (the Brain's Probable Sale cap): {len(capped)}")
(OUT / "p3_sales.txt").write_text("\n".join(out) + "\n")
print("\n".join(out))
