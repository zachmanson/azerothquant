import pytest

from brain.scan import ItemKey, ItemStringError, unit_buyout


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
