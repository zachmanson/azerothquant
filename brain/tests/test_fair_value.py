from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.fair_value import fair_value, fair_values
from brain.history import Market, import_scans, open_history

# Default slice (cheapest 15% of units) and outlier cut (under half the slice's median).
CONFIG = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))
MARKET = Market(realm="Classic Beta PvP", faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
LINEN_KEY = "2589"
SILK = "item:4306::::::::20:1490"
SILK_KEY = "4306"
T0 = 1_790_000_000
MINUTE = 60


def scan(at, *rows, faction="Alliance"):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": "Classic Beta PvP",
        "character": "Kash-Patel",
        "faction": faction,
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


# --- Fair Value of a supply ---


def test_a_one_listing_market_is_worth_that_listings_price():
    assert fair_value([(250, 20)], CONFIG) == 250


def test_fair_value_averages_the_cheapest_15_percent_of_units_splitting_a_listing():
    # 40 units, so the slice is the cheapest 6: all 3 at 300 and 3 of the 30 at 500.
    supply = [(2000, 7), (500, 30), (300, 3)]

    assert fair_value(supply, CONFIG) == 400


def test_a_single_cheap_outlier_is_a_flip_not_the_price():
    # 20 units, so the slice is 3: the 1 copper and two at 100. The median is 100, and
    # the 1 copper is under half of it.
    supply = [(1, 1), (100, 12), (120, 7)]

    assert fair_value(supply, CONFIG) == 100


def test_fair_value_rises_once_the_cheap_units_are_bought():
    # A Flip buying the 4 at 100 leaves only the 16 at 200 (#23).
    assert fair_value([(100, 4), (200, 16)], CONFIG) == 100
    assert fair_value([(200, 16)], CONFIG) == 200


def test_a_supply_with_nothing_left_has_no_fair_value():
    assert fair_value([], CONFIG) is None
    assert fair_value([(100, 0)], CONFIG) is None


# --- Fair Value per Item Key in a Market ---


def test_fair_value_per_item_key_comes_from_the_latest_scan_only(db):
    run(
        db,
        scan(T0, row(unit=50), row(item=SILK, unit=900)),
        scan(
            T0 + 20 * MINUTE,
            row(quantity=10, unit=120),
            row(quantity=10, unit=150),
            row(item=SILK, quantity=5, unit=400),
        ),
        scan(T0 + 30 * MINUTE, row(unit=1), faction="Horde"),
    )

    # Linen: 20 units, so the slice is the cheapest 3, all at 120.
    assert fair_values(db, MARKET, CONFIG) == {LINEN_KEY: 120, SILK_KEY: 400}


def test_a_cheap_outlier_and_a_one_listing_item_in_a_scan(db):
    run(
        db,
        scan(
            T0,
            row(unit=1),  # a Flip, not the price
            row(quantity=12, unit=100),
            row(quantity=7, unit=120),
            row(item=SILK, quantity=4, unit=700),  # the only silk
        ),
    )

    assert fair_values(db, MARKET, CONFIG) == {LINEN_KEY: 100, SILK_KEY: 700}
