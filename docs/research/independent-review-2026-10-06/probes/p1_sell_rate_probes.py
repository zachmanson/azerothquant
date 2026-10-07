"""Probes of the Brain's estimators, against the real code (no mocks)."""

from pathlib import Path

from brain.config import Config, Era, Install
from brain.history import Market, import_scans, open_history
from brain.sell_rate import sell_rates

T0 = 1_790_000_000
MIN = 60
CONFIG = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))
MARKET = Market(realm="R", faction="Alliance", era=Era.BETA)
LINEN = "item:2589"


def scan(at, rows, dropped=0):
    return {"id": 1, "requestedAt": at, "realm": "R", "character": "Me-R",
            "faction": "Alliance", "droppedRows": dropped, "listings": rows}


def row(unit, qty=1, tl=4, item=LINEN):
    return {"itemString": item, "quantity": qty, "buyout": qty * unit, "timeLeft": tl}


def rate(scans, now):
    db = open_history(":memory:")
    import_scans(db, scans, Era.BETA, CONFIG)
    return sell_rates(db, MARKET, CONFIG, now=now).get("2589")


book = [row(100 + i) for i in range(10)]  # ten 1-unit listings, 100c..109c, nothing sells

print("P1 incomplete own Scan (client hadn't loaded the item):")
r = rate([scan(T0, book), scan(T0 + 20 * MIN, [], dropped=10), scan(T0 + 40 * MIN, book)],
         T0 + 40 * MIN)
print(f"   true sales 0 -> sale_events={r.sale_events}, units={r.sale_units}, "
      f"units/day={r.units_per_day:.0f}")

print("P2 the player buys 3 cheapest listings for a Flip (own Purchase):")
r = rate([scan(T0, book), scan(T0 + 20 * MIN, book[3:])], T0 + 20 * MIN)
print(f"   market sales 0 -> sale_events={r.sale_events}, units={r.sale_units}, "
      f"units/day={r.units_per_day:.0f}")

# P3 (sweep priced at its dearest unit) is in p3_sweep_dearest.py

print("P4 a seller cancels (no repost) - not distinguishable from a sale:")
r = rate([scan(T0, book), scan(T0 + 20 * MIN, book[:9])], T0 + 20 * MIN)
print(f"   sale_events={r.sale_events}")

print("P5 2h postings: bucket-2 listings disappearing over a 30+ min gap never count:")
two_h = [row(100 + i, tl=2) for i in range(5)]
r = rate([scan(T0, two_h), scan(T0 + 35 * MIN, two_h[2:])], T0 + 35 * MIN)
print(f"   true sales 2 -> sale_events={r.sale_events if r else None}")

print("P6 identical-price listings from two sellers: a whole 20-stack sells and someone"
      " posts 5 at the same price within the window:")
r = rate([scan(T0, [row(100, 20)]), scan(T0 + 20 * MIN, [row(100, 5)])], T0 + 20 * MIN)
print(f"   true: 20 units sold -> units={r.sale_units}")

print("P7 Sell Rate scales watched hours to a day: 2h watched at peak with 4 sales")
peak = [scan(T0 + k * 20 * MIN, book[k:]) for k in range(7)]
r = rate(peak, T0 + 120 * MIN)
print(f"   window_hours={r.window_hours}, units/day={r.units_per_day:.0f} "
      "(assumes the peak rate holds all 24 h)")
