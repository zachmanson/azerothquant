"""Probe 6: how often a "gone, can't have expired" Listing was really a sale, measured on
the player's own Listings, whose fate the mail tells (Sold / Cancelled / Expired).

Each own Listing that went missing is matched to the first unused auction mail with the
same item name and count (and, for a sale, the same stack price) read after it was last
seen. Then it's classified by the rules the Brain uses (expiry possible from the
time-left bucket, gap length) and compared to what the mail says.
Writes probes/out/p6_own_truth.txt.
"""

from collections import Counter

from common import OUT, setup, times

from brain.observation import disappearances

conn, config, market, predictions, cache = setup()
ts = times(conn, market)
seen = cache.listings(conn, market)
names = dict(conn.execute("SELECT id, item_name FROM listing WHERE own = 1"))
own = [x for x in seen if x.own]
ds = [d for d in disappearances(conn, market, config, own)]
mails = conn.execute(
    "SELECT id, kind, item_name, count, price, first_read_at FROM auction_mail"
    " WHERE kind IN ('sold','cancelled','expired') ORDER BY first_read_at").fetchall()
used = set()
by_listing = {(x.item_key, x.unit_buyout, x.last_seen, x.quantity): x for x in own}
rows = []
for d in sorted(ds, key=lambda d: d.last_seen):
    x = by_listing.get((d.item_key, d.unit_buyout, d.last_seen, d.quantity))
    name = None
    if x is not None:
        name = conn.execute(
            "SELECT item_name FROM listing WHERE own=1 AND item_key=? AND unit_buyout=?"
            " AND item_name IS NOT NULL LIMIT 1", (d.item_key, d.unit_buyout)).fetchone()
        name = name[0] if name else None
    match = None
    for mid, kind, mname, count, price, read in mails:
        if mid in used or mname != name or count != d.quantity or read < d.last_seen:
            continue
        if kind == "sold" and price != d.unit_buyout * d.quantity:
            continue
        match = (mid, kind)
        break
    if match:
        used.add(match[0])
    gap = (d.gone_at - d.last_seen) / 3600
    rows.append((d, gap, match[1] if match else "no mail matched"))

out = [f"Own Listings that went missing: {len(rows)}; matched to a mail: "
       f"{sum(r[2] != 'no mail matched' for r in rows)}"]
for label, keep in (
    ("Brain rule: gap <= 1 h, can't have expired", lambda d, g: g <= 1 and not d.expiry_possible),
    ("Wider rule: gap <= 12 h, can't have expired", lambda d, g: g <= 12 and not d.expiry_possible),
    ("Gap 1-12 h only, can't have expired", lambda d, g: 1 < g <= 12 and not d.expiry_possible),
    ("Expiry possible (any gap)", lambda d, g: d.expiry_possible),
):
    c = Counter(r[2] for r in rows if keep(r[0], r[1]))
    matched = c["sold"] + c["cancelled"] + c["expired"]
    prec = c["sold"] / matched if matched else float("nan")
    out.append(f"  {label}: {dict(c)}  -> sold share of matched {prec:.0%}")
(OUT / "p6_own_truth.txt").write_text("\n".join(out) + "\n")
print("\n".join(out))
