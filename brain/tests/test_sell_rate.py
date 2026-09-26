from dataclasses import replace
from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.history import Market, import_scans, open_history
from brain.sell_rate import SellRate, sell_rates

T0 = 1_790_000_000
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR

# Default cap (1 h), default time-left buckets and the default 14-day range.
CONFIG = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))
MARKET = Market(realm="Classic Beta PvP", faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
LINEN_KEY = "2589"
SILK = "item:4306::::::::20:1490"
SILK_KEY = "4306"


def scan(at, *rows):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": "Classic Beta PvP",
        "character": "Kash-Patel",
        "faction": "Alliance",
        "droppedRows": 0,
        "listings": list(rows),
    }


def row(item=LINEN, quantity=1, unit=100, time_left=4):
    return {
        "itemString": item,
        "quantity": quantity,
        "buyout": quantity * unit,
        "timeLeft": time_left,
    }


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def run(db, *scans):
    import_scans(db, list(scans), Era.BETA, CONFIG)


def test_a_market_without_observation_windows_has_no_data(db):
    # Two Scans 3 h apart: Listings were seen, but the gap is too long to count.
    run(db, scan(T0, row(quantity=20)), scan(T0 + 3 * HOUR, row(quantity=15)))

    assert sell_rates(db, MARKET, CONFIG, now=T0 + 3 * HOUR) == {}


def test_an_item_key_with_windows_but_no_sales_sells_zero_a_day(db):
    run(db, scan(T0, row(), row(item=SILK)), scan(T0 + 30 * MINUTE, row(), row(item=SILK)))

    rates = sell_rates(db, MARKET, CONFIG, now=T0 + 30 * MINUTE)

    assert {key: rate.units_per_day for key, rate in rates.items()} == {LINEN_KEY: 0, SILK_KEY: 0}


def test_partial_sales_over_window_hours_scaled_to_a_day(db):
    run(
        db,
        scan(T0, row(quantity=20)),
        scan(T0 + 30 * MINUTE, row(quantity=15)),  # 5 sold
        scan(T0 + HOUR, row(quantity=12)),  # 3 sold: 8 units in 1 h of windows
    )

    rates = sell_rates(db, MARKET, CONFIG, now=T0 + HOUR)

    assert rates[LINEN_KEY].units_per_day == 8 * 24


def test_a_probable_sale_that_fails_the_price_check_does_not_count(db):
    # 12 units, so Fair Value is the cheapest 2: both at 100. The 110 is within 1.2x of it
    # and counts; the 200 is too dear to be a sale.
    run(
        db,
        scan(T0, row(quantity=10, unit=100), row(unit=110), row(unit=200)),
        scan(T0 + 30 * MINUTE, row(quantity=10, unit=100)),
    )

    rates = sell_rates(db, MARKET, CONFIG, now=T0 + 30 * MINUTE)

    assert rates[LINEN_KEY].units_per_day == 1 / 0.5 * 24


def test_each_sell_rate_carries_its_evidence(db):
    run(
        db,
        scan(
            T0,
            row(quantity=20),  # 5 sell: a Partial Sale
            row(unit=100),  # gone; the only new one like it is dearer: a coincidence and a sale
            row(item=SILK, unit=100),  # reposted at 90
        ),
        scan(T0 + 30 * MINUTE, row(quantity=15), row(unit=120), row(item=SILK, unit=90)),
    )

    rates = sell_rates(db, MARKET, CONFIG, now=T0 + 30 * MINUTE)

    assert rates[LINEN_KEY] == SellRate(
        units_per_day=6 / 0.5 * 24, sale_events=2, window_hours=0.5, reposts=0, coincidences=1
    )
    assert rates[SILK_KEY] == SellRate(
        units_per_day=0, sale_events=0, window_hours=0.5, reposts=1, coincidences=0
    )


@pytest.mark.parametrize(("ended_ago", "counted"), [(14 * DAY - 1, True), (14 * DAY, False)])
def test_only_windows_ending_in_the_last_14_days_count(db, ended_ago, counted):
    now = T0 + 30 * MINUTE + ended_ago
    run(db, scan(T0, row(quantity=20)), scan(T0 + 30 * MINUTE, row(quantity=15)))

    rates = sell_rates(db, MARKET, CONFIG, now=now)

    assert (LINEN_KEY in rates) == counted


def test_a_setting_for_the_range_changes_which_windows_count(db):
    config = replace(CONFIG, sell_rate_range_seconds=DAY)
    run(
        db,
        scan(T0, row(quantity=20)),
        scan(T0 + 30 * MINUTE, row(quantity=15)),  # 5 sold, 2 days before now
        scan(T0 + 2 * DAY),
        scan(T0 + 2 * DAY + 30 * MINUTE),  # nothing sold
    )

    rates = sell_rates(db, MARKET, config, now=T0 + 2 * DAY + 30 * MINUTE)

    assert rates[LINEN_KEY] == SellRate(
        units_per_day=0, sale_events=0, window_hours=0.5, reposts=0, coincidences=0
    )
