from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.history import import_character_reads, import_scans, open_history, vendor_prices

T0 = 1_790_000_000
REALM = "Classic Beta PvP"
CONFIG = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))


def scan(at, prices, faction="Alliance"):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": faction,
        "droppedRows": 0,
        "listings": [],
        "vendorPrices": prices,
    }


def character_read(at, prices):
    return {
        "readAt": at,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 0,
        "bags": [],
        "vendorPrices": prices,
    }


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def test_a_scans_vendor_prices_are_imported_by_item_id(db):
    # 0 is kept as it is: a vendor won't buy the item.
    import_scans(db, [scan(T0, {2589: 10, 6948: 0})], Era.BETA, CONFIG)

    assert vendor_prices(db, Era.BETA) == {2589: 10, 6948: 0}


def test_a_character_reads_vendor_prices_are_imported_too(db):
    # Grey junk and soulbound drops never show up on the Auction House, only in bags.
    import_character_reads(db, [character_read(T0, {3300: 25})], Era.BETA, CONFIG)

    assert vendor_prices(db, Era.BETA) == {3300: 25}


def test_the_newest_vendor_price_wins_whatever_order_they_were_imported_in(db):
    # `brain rebuild` imports every Scan before any Character Read, so import order
    # isn't the order they were seen in.
    import_character_reads(db, [character_read(T0 + 60, {2589: 12, 3300: 25})], Era.BETA, CONFIG)
    import_scans(db, [scan(T0, {2589: 10, 6948: 0})], Era.BETA, CONFIG)
    import_character_reads(db, [character_read(T0 - 60, {6948: 5})], Era.BETA, CONFIG)

    assert vendor_prices(db, Era.BETA) == {2589: 12, 3300: 25, 6948: 0}


def test_an_entry_the_brain_cant_read_is_skipped_with_a_warning_and_the_rest_kept(db):
    prices = {2589: 10, "junk": 5, 6948: "lots", 3300: -1, 2592: True}

    report = import_scans(db, [scan(T0, prices)], Era.BETA, CONFIG)

    assert report.scans_imported == 1
    assert vendor_prices(db, Era.BETA) == {2589: 10}
    assert len(report.warnings) == 1


def test_each_era_keeps_its_own_vendor_prices(db):
    # Forever changed some prices from Classic; Live may yet change them from Beta.
    import_scans(db, [scan(T0, {2589: 10})], Era.BETA, CONFIG)
    import_scans(db, [scan(T0 - 60, {2589: 13})], Era.LIVE, CONFIG)

    assert vendor_prices(db, Era.BETA) == {2589: 10}
    assert vendor_prices(db, Era.LIVE) == {2589: 13}
