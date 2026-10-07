"""One buyer takes ten 100c units and one 115c unit in a window: how much demand at >=114c?"""
from pathlib import Path
from brain.config import Config, Era, Install
from brain.history import Market, import_scans, open_history
from brain.sell_rate import sell_rates
T0, MIN = 1_790_000_000, 60
C = Config(installs=(Install(path=Path("C:/x"), era=Era.BETA),))
def scan(at, rows):
    return {"id": 1, "requestedAt": at, "realm": "R", "character": "Me-R", "faction": "Alliance",
            "droppedRows": 0, "listings": rows}
def row(unit, qty=1):
    return {"itemString": "item:2589", "quantity": qty, "buyout": qty * unit, "timeLeft": 4}
db = open_history(":memory:")
import_scans(db, [scan(T0, [row(100, 10), row(115, 1), row(300, 5)]),
                  scan(T0 + 20 * MIN, [row(300, 5)])], Era.BETA, C)
r = sell_rates(db, Market("R", "Alliance", Era.BETA), C, now=T0 + 20 * MIN)["2589"]
print("sale_prices", r.sale_prices)
print("units counted as demand at >=114c:", r.at_or_above(114).sale_units, "(true: 1)")
