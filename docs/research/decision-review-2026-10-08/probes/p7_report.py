"""Probe 7: the backtest results (probes/out/p4_*.json) side by side.
Writes probes/out/p7_backtest_table.txt and p7_backtest_table.md.
"""

import json

from common import OUT


def g(c):
    return f"{c / 1e4:+.2f}g"


rows = []
for path in sorted(OUT.glob("p4_*.json")):
    r = json.loads(path.read_text())
    curve = [b for _, _, b in r["curve"]]
    peak, dd = curve[0], 0
    for b in curve:
        peak = max(peak, b)
        dd = max(dd, (peak - b) / peak)
    trades = r["trades"]
    closed = [t for t in trades if t["closed"]]
    pnl_closed = [t["proceeds"] + t["salvage"] - t["cost"] * t["units"] for t in closed]
    sold_share = r["units_sold"] / r["units_bought"] if r["units_bought"] else 0
    rows.append((path.stem[3:], r, dd, sold_share, pnl_closed))

head = ("| run | total P&L (vendor mark) | total P&L (market mark) | buys | units sold / bought | P&L all (vendor mark) | P&L all (market mark) "
        "| closed P&L | open P&L (vendor / market) | won / lost | worst trade | best trade "
        "| max drawdown | Vendor flips |")
lines = [head, "|" + "---|" * 14]
for name, r, dd, share, pc in rows:
    lines.append(
        f"| {name} | {g(r['pnl_all_conservative'] + r['vendor_flips_net'])} "
        f"| {g(r['pnl_all_market'] + r['vendor_flips_net'])} | {r['buys']} | {r['units_sold']:.0f} / {r['units_bought']} ({share:.0%}) "
        f"| {g(r['pnl_all_conservative'])} | {g(r['pnl_all_market'])} | {g(r['pnl_closed'])} "
        f"| {g(r['pnl_open_conservative'])} / {g(r['pnl_open_market'])} "
        f"| {r['winners']} / {r['losers']} | {g(r['biggest_loss'])} | {g(r['biggest_win'])} "
        f"| {dd:.0%} | {g(r['vendor_flips_net'])} |")
text = "\n".join(lines) + "\n"
(OUT / "p7_backtest_table.md").write_text(text)
print(text)
