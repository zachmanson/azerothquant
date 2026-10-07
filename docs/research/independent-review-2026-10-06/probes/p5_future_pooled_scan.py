from pathlib import Path
from brain.config import Config, Era, Install
from brain.history import import_pooled_scans, import_scans, open_history, scan_times, Market
T0 = 1_790_000_000
C = Config(installs=(Install(path=Path("C:/x"), era=Era.BETA),))
def scan(at, char=True):
    s = {"id": 1, "requestedAt": at, "realm": "R", "faction": "Alliance", "droppedRows": 0,
         "listings": [{"itemString": "item:2589", "quantity": 1, "buyout": 100, "timeLeft": 4}]}
    if char: s["character"] = "Me-R"
    return s
db = open_history(":memory:")
import_scans(db, [scan(T0)], Era.BETA, C)
# A pooled body whose requestedAt is 30 days ahead (header said "now"; the Brain never compares).
import_pooled_scans(db, [("p1", scan(T0 + 30 * 86400, char=False))], Era.BETA, C)
r = import_scans(db, [scan(T0 + 1800)], Era.BETA, C)
print("own Scan 30 min later: imported", r.scans_imported, "waiting for rebuild", r.scans_waiting_for_rebuild)
print("Market scan times:", scan_times(db, Market("R", "Alliance", Era.BETA)))
