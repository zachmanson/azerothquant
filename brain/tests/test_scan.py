import pytest

from brain.scan import ItemKey, ItemStringError, Scan, ScanRow, unit_buyout


def test_item_key_ignores_the_scanning_characters_level_and_spec():
    # 20:1490 are the level and spec of whoever ran the Scan, not part of the Listing.
    level_20_scan = ItemKey.from_item_string("item:9768::::::::20:1490::1:1:12743")
    level_60_scan = ItemKey.from_item_string("item:9768::::::::60:71::1:1:12743")

    assert level_20_scan == level_60_scan == ItemKey(item_id=9768, bonus_ids=(12743,))


def test_item_key_without_a_suffix_bonus_id():
    assert ItemKey.from_item_string("item:2589") == ItemKey(item_id=2589, bonus_ids=())
    assert ItemKey.from_item_string("item:2589::::::::20:1490") == ItemKey(2589, ())


def test_random_suffixes_are_different_item_keys():
    monkey = ItemKey.from_item_string("item:9768::::::::20:1490::1:1:12743")
    eagle = ItemKey.from_item_string("item:9768::::::::20:1490::1:1:12750")

    assert monkey != eagle


def test_bonus_id_order_does_not_matter():
    a = ItemKey.from_item_string("item:9768::::::::20:1490::1:2:12743:500")
    b = ItemKey.from_item_string("item:9768::::::::20:1490::1:2:500:12743")

    assert a == b
    assert str(a) == "9768:500:12743"


def test_item_key_ignores_modifiers_after_the_bonus_ids():
    key = ItemKey.from_item_string("item:9768::::::::20:1490::1:1:12743:1:9:20")

    assert key == ItemKey(9768, (12743,))


def test_item_key_string_round_trip():
    assert str(ItemKey(2589, ())) == "2589"
    assert str(ItemKey(9768, (12743,))) == "9768:12743"


@pytest.mark.parametrize(
    "item_string",
    [
        "",
        "item:",
        "hitem:9768",
        "item:abc",
        "item:9768::::::::20:1490::1:2:12743",  # says 2 bonus IDs, has 1
        "item:9768::::::77",  # legacy suffix field is expected to be empty
    ],
)
def test_rejects_item_strings_it_does_not_understand(item_string):
    with pytest.raises(ItemStringError):
        ItemKey.from_item_string(item_string)


def test_unit_buyout_divides_the_whole_auction_buyout():
    assert unit_buyout(buyout=1940, quantity=20) == 97
    assert unit_buyout(buyout=500, quantity=1) == 500


def test_unit_buyout_that_is_not_whole_copper_is_flagged_not_rounded():
    assert unit_buyout(buyout=1941, quantity=20) is None


# --- Scan.from_saved ---


def saved_scan(**fields):
    return {
        "requestedAt": 1_790_000_000,
        "realm": "Classic Beta PvP",
        "faction": "Alliance",
        "character": "Kash-Patel",
        "droppedRows": 0,
        **fields,
    }


def test_reads_packed_rows_and_own_rows_together():
    # #144: everyone else's rows come as one string, the player's own as tables.
    scan = Scan.from_saved(
        saved_scan(
            listings=[
                {
                    "itemString": "item:2589::::::::20:1490",
                    "quantity": 5,
                    "buyout": 500,
                    "timeLeft": 4,
                    "own": True,
                    "name": "Linen Cloth",
                }
            ],
            packedListings="item:2589::::::::20:1490,20,1940,4;item:9768::::::::20:1490::1:1:12743,1,5000,2",
        )
    )

    assert set(scan.rows) == {
        ScanRow("2589", 100, own=True, quantity=5, time_left=4, item_name="Linen Cloth"),
        ScanRow("2589", 97, own=False, quantity=20, time_left=4),
        ScanRow("9768:12743", 5000, own=False, quantity=1, time_left=2),
    }


def test_packed_rows_it_cannot_read_or_price_exactly_are_counted_not_kept():
    scan = Scan.from_saved(
        saved_scan(
            packedListings=(
                "item:2589,3,10,4;"  # 10 / 3 isn't whole copper
                "item:2589,nil,100,4;"  # a field the Addon couldn't fill
                "item:2589,1,100;"  # too few fields
                "item:2589,+1,100,4;"  # int() would take it; the Addon never writes it
                "item:2589,1,100,4"
            )
        )
    )

    assert scan.rows == (ScanRow("2589", 100, own=False, quantity=1, time_left=4),)
    assert scan.inexact_rows == 1
    assert scan.unreadable_rows == 3


def test_an_empty_packed_string_is_no_rows():
    assert Scan.from_saved(saved_scan(packedListings="")).rows == ()
