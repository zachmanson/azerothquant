"""Probe 2: how much sale evidence the history has, and what the Sale Event rules drop.

For every other player's Listing that went missing between two Scans: was the gap an
Observation Window (<= 60 min), could it have expired, did a Repost explain it, and was it
priced over 1.2x Fair Value (the Probable Sale cap). Also Observation Window hours by day.
Writes probes/out/p2_evidence.txt.
"""

from collections import Counter, defaultdict
from datetime import datetime

from common import OUT, Clock, setup, times

from brain.observation import (
    _pair_reposts,
    disappearances,
    observation_windows,
    sell_rate_evidence,
)

conn, config, market, predictions, cache = setup()
ts = times(conn, market)
now = ts[-1]
clock = Clock()
out = []


def say(s=""):
    print(s, flush=True)
    out.append(s)


wins = observation_windows(conn, market, config)
by_day = defaultdict(float)
for w in wins:
    by_day[datetime.fromtimestamp(w.end).strftime("%m-%d")] += (w.end - w.start) / 3600
total_span = (ts[-1] - ts[0]) / 3600
say(f"Scans: {len(ts)} over {total_span:.0f} h ({total_span/24:.1f} days)")
say(f"Observation Windows (gap <= 60 min): {len(wins)}, {sum(by_day.values()):.1f} h in all")
say("  by day: " + ", ".join(f"{d} {h:.1f}h" for d, h in sorted(by_day.items())))
gaps = [b - a for a, b in zip(ts, ts[1:])]
say(f"  gaps > 60 min: {sum(g > 3600 for g in gaps)}, covering "
    f"{sum(g for g in gaps if g > 3600)/3600:.0f} h unobserved")

seen = cache.listings(conn, market)
ds = [d for d in disappearances(conn, market, config, seen) if not d.own]
clock.lap("disappearances")
c = Counter()
for d in ds:
    c["in window" if d.in_window else "long gap"] += 1
    c[("in window" if d.in_window else "long gap",
       "expiry possible" if d.expiry_possible else "can't have expired")] += 1
say(f"\nOther players' Listings gone between two Scans: {len(ds)}")
for k, n in sorted(c.items(), key=str):
    say(f"  {k}: {n}")

# Sale Events as the Brain counts them, over the whole history.
ev = sell_rate_evidence(conn, market, config, ts[0], now + 1, seen, fair_value_cache=cache)
clock.lap("evidence default")
say(f"\nSale Events (whole history, default rules): {len(ev.sale_events)} over "
    f"{ev.window_hours:.1f} h, Item Keys {len({e.item_key for e in ev.sale_events})}; "
    f"reposts {len(ev.reposts)}")
loose = config.__class__(**{**config.__dict__, "probable_sale_max_fair_value_multiple": 1e9})
ev2 = sell_rate_evidence(conn, market, loose, ts[0], now + 1, seen, fair_value_cache=cache)
clock.lap("evidence no FV cap")
say(f"Sale Events with no 1.2x Fair Value cap: {len(ev2.sale_events)} "
    f"(+{len(ev2.sale_events) - len(ev.sale_events)}), units "
    f"{sum(e.units for e in ev2.sale_events)} vs {sum(e.units for e in ev.sale_events)}")
# Price of each Sale Event relative to the cheapest other ask in the Scan before it.
fv = {}
above = Counter()
for e in ev2.sale_events:
    prev = max(t for t in ts if t < e.seen_at)
    if prev not in fv:
        fv[prev] = cache.fair_values(conn, market, config, prev)
    v = fv[prev].get(e.item_key)
    if v:
        r = e.unit_buyout / v
        above["<=1.0x" if r <= 1 else "1.0-1.2x" if r <= 1.2 else "1.2-1.5x" if r <= 1.5
              else "1.5-2x" if r <= 2 else ">2x"] += 1
say("Dearest unit of each Sale Event (no cap) vs Fair Value of the Scan before: "
    + ", ".join(f"{k} {above[k]}" for k in ["<=1.0x", "1.0-1.2x", "1.2-1.5x", "1.5-2x", ">2x"]))

# Long-gap disappearances that can't have expired: sale-like evidence never counted.
long_sale_like = [d for d in ds if not d.in_window and not d.expiry_possible]
say(f"\nLong-gap disappearances that can't have expired (not reposts checked): "
    f"{len(long_sale_like)} Listings, {sum(d.quantity for d in long_sale_like)} units")

# The last 14 days, as the Sell Rate sees it.
since = now - config.sell_rate_range_seconds + 1
ev14 = sell_rate_evidence(conn, market, config, since, now + 1, seen, fair_value_cache=cache)
per_key = Counter(e.item_key for e in ev14.sale_events)
say(f"\nSell Rate range (14 d): {ev14.window_hours:.1f} h watched, "
    f"{len(ev14.sale_events)} Sale Events, {len(per_key)} Item Keys; "
    f">=3 events: {sum(n >= 3 for n in per_key.values())}, "
    f">=5: {sum(n >= 5 for n in per_key.values())}, >=10: {sum(n >= 10 for n in per_key.values())}")
last7 = [e for e in ev14.sale_events if e.seen_at > now - 7 * 86400]
say(f"  of them in the last 7 days: {len(last7)} Sale Events "
    f"({sum((w.end - w.start) for w in ev14.windows if w.end > now - 7*86400)/3600:.1f} h watched)")
(OUT / "p2_evidence.txt").write_text("\n".join(out) + "\n")
