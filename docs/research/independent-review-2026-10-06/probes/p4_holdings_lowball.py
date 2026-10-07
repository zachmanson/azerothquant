from pathlib import Path
from brain.config import Config, Era, Install
from brain.history import Holding
from brain.recommend import _Valuer
from brain.sell_rate import SellRate
C = Config(installs=(Install(path=Path("C:/x"), era=Era.BETA),))
T = 1_790_000_000
# 20 Sale Events at 1000c over 100 h of windows; held: 5 units; Vendor Price 250c.
rate = SellRate(units_per_day=4.8, sale_events=20, window_hours=100, reposts=0, coincidences=0,
                sale_units=20, typical_sale_size=1,
                sale_prices=tuple((1000, 1, T - i * 3600) for i in range(20)))
for book in ([(1000, 20)], [(300, 1), (1000, 20)]):
    v = _Valuer({"9": book}, {"9": book}, {}, {"9": rate}, {9: 250}, {}, 0.05,
                frozenset(), {}, C)
    rows = v.rows("9", Holding(bags=5))
    print("book", book, "->", [(r.action and r.action.value, r.quantity, r.price) for r in rows])
