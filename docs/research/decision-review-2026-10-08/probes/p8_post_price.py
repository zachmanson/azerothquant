"""Probe 8: where in the book real sales happen, for the post-price question.

For every sale-like record (p3, gaps <= 12 h, <= 1.2x Fair Value, plus Partial Sales), its
unit price over the cheapest other player's ask of that Item Key in the Scan it was last
seen in, and how many cheaper units were up then (all of which a cheapest-first buyer
would have had to take first). Weighted by units.
Writes probes/out/p8_post_price.txt.
"""

import pickle
from collections import Counter, defaultdict

from common import OUT, WORK, setup, times

from brain.history import supply_at

conn, config, market, predictions, cache = setup()
with open(WORK / "sales.pkl", "rb") as f:
    records = [r for r in pickle.load(f)
               if (r[6] == "partial" or r[5] <= 12) and (r[7] is None or r[7] <= 1.2)]
by_scan = defaultdict(list)
for r in records:
    by_scan[r[3]].append(r)
ratio = Counter()
levels = Counter()
for at, rs in sorted(by_scan.items()):
    book = supply_at(conn, market, at, others_only=True)
    for item, price, units, *_ in rs:
        asks = sorted(book.get(item, []))
        if not asks:
            continue
        low = asks[0][0]
        x = price / low
        band = ("at the cheapest" if x <= 1.0 else "<=5% above" if x <= 1.05
                else "5-20% above" if x <= 1.2 else ">20% above")
        ratio[band] += units
        n_levels = len({u for u, _ in asks if u < price})
        levels["0 cheaper price levels" if n_levels == 0 else
               "1" if n_levels == 1 else "2-3" if n_levels <= 3 else "4+"] += units
total = sum(ratio.values())
out = [f"Units sold (sale-like records): {total}"]
out.append("Price over the cheapest other ask then up:")
for k in ["at the cheapest", "<=5% above", "5-20% above", ">20% above"]:
    out.append(f"  {k:<16} {ratio[k]:>8}  {ratio[k]/total:.0%}")
out.append("Distinct cheaper price levels a buyer went through first:")
for k in ["0 cheaper price levels", "1", "2-3", "4+"]:
    out.append(f"  {k:<22} {levels[k]:>8}  {levels[k]/total:.0%}")
(OUT / "p8_post_price.txt").write_text("\n".join(out) + "\n")
print("\n".join(out))
