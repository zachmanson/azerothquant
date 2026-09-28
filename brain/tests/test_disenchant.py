from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.disenchant import ItemInfo, load_table
from brain.history import (
    Holding,
    Market,
    enchanting_skills,
    import_character_reads,
    import_scans,
    item_info,
    open_history,
)
from brain.predictions import Prediction
from brain.recommend import Action, exit_values, recommend

T0 = 1_790_000_000
REALM = "Classic Beta PvP"
MARKET = Market(realm=REALM, faction="Alliance", era=Era.BETA)
CONFIG = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))
ENCHANTING = 333

ARMOR, WEAPON = 4, 2
UNCOMMON, RARE, EPIC = 2, 3, 4
STRANGE_DUST, LESSER_MAGIC, GREATER_MAGIC, SMALL_GLIMMERING = 10940, 10938, 10939, 10978
NEXUS_CRYSTAL = 20725


@pytest.fixture(scope="module")
def table():
    return load_table()


def green(level, class_id=ARMOR, equip_loc="INVTYPE_CHEST", quality=UNCOMMON):
    return ItemInfo(item_level=level, quality=quality, class_id=class_id, equip_loc=equip_loc)


def test_a_green_armor_piece_resolves_to_its_item_level_band(table):
    # Band edges: 15 is the top of 5-15, 16 the bottom of 16-20.
    assert (table.group(1, green(15)).min_level, table.group(1, green(15)).max_level) == (5, 15)
    assert (table.group(1, green(16)).min_level, table.group(1, green(16)).max_level) == (16, 20)
    assert table.group(1, green(4)) is None  # below every band


def test_armor_yields_mostly_dust_and_weapons_mostly_essence(table):
    armor = table.group(1, green(18)).expected
    weapon = table.group(1, green(18, WEAPON, "INVTYPE_2HWEAPON")).expected

    # chance × mean quantity: 75% of 2-3 Strange Dust, 20% of 1-2 Greater Magic Essence,
    # 5% of one Small Glimmering Shard.
    assert armor == pytest.approx({STRANGE_DUST: 1.875, GREATER_MAGIC: 0.3, SMALL_GLIMMERING: 0.05})
    assert weapon == pytest.approx(
        {STRANGE_DUST: 0.5, GREATER_MAGIC: 1.125, SMALL_GLIMMERING: 0.05}
    )


def test_blues_and_purples_have_their_own_bands(table):
    assert table.group(1, green(60, quality=RARE)).expected == pytest.approx(
        {14344: 0.995, NEXUS_CRYSTAL: 0.005}
    )
    assert table.group(1, green(70, quality=EPIC)).expected == pytest.approx({NEXUS_CRYSTAL: 1.5})


def test_only_uncommon_to_epic_equippable_armor_and_weapons_disenchant(table):
    assert table.group(1, green(18, quality=1)) is None  # white
    assert table.group(1, green(18, class_id=0)) is None  # a consumable
    assert table.group(1, green(18, equip_loc="")) is None  # can't be equipped
    assert table.group(1, green(18, equip_loc="INVTYPE_BODY")) is None  # a shirt
    assert table.group(1, green(18, equip_loc="INVTYPE_TABARD")) is None
    # An enchanter's wand: a green weapon, but it can't be Disenchanted.
    assert table.group(11288, green(15, WEAPON, "INVTYPE_RANGEDRIGHT")) is None


@pytest.mark.parametrize(
    "level, skill",
    [(5, 1), (20, 1), (21, 25), (25, 25), (26, 50), (60, 200), (61, 225), (89, 225), (92, 300)],
)
def test_the_enchanting_skill_an_item_level_needs(table, level, skill):
    assert table.required_skill(level) == skill


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def scan(at, info):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "droppedRows": 0,
        "listings": [],
        "itemInfo": info,
    }


def info(level, quality=UNCOMMON, class_id=ARMOR, equip_loc="INVTYPE_CHEST"):
    return {"itemLevel": level, "quality": quality, "classID": class_id, "equipLoc": equip_loc}


def test_a_scans_item_info_is_imported_and_the_newest_wins(db):
    # From the Archive's JSON the keys arrive as strings.
    import_scans(db, [scan(T0 + 60, {"7": info(20)})], Era.BETA, CONFIG)
    import_scans(db, [scan(T0, {7: info(18), 8: info(30, class_id=WEAPON)})], Era.BETA, CONFIG)

    assert item_info(db, Era.BETA) == {
        7: ItemInfo(20, UNCOMMON, ARMOR, "INVTYPE_CHEST"),
        8: ItemInfo(30, UNCOMMON, WEAPON, "INVTYPE_CHEST"),
    }


def test_unreadable_item_info_is_skipped(db):
    report = import_scans(db, [scan(T0, {7: {"itemLevel": 20}, 8: info(30)})], Era.BETA, CONFIG)

    assert item_info(db, Era.BETA) == {8: ItemInfo(30, UNCOMMON, ARMOR, "INVTYPE_CHEST")}
    assert any("Item Info" in w for w in report.warnings)


def test_a_character_reads_item_info_is_imported_too(db):
    # A bound green never shows up in a Scan, only in the bags.
    r = read("Bob", T0, {})
    r["itemInfo"] = {9999: info(18)}
    import_character_reads(db, [r], Era.BETA, CONFIG)

    assert item_info(db, Era.BETA) == {9999: ItemInfo(18, UNCOMMON, ARMOR, "INVTYPE_CHEST")}


def read(character, at, professions):
    """A Character Read whose profession windows are {professionID: skillLevel}."""
    return {
        "readAt": at,
        "realm": REALM,
        "character": character,
        "faction": "Alliance",
        "money": 0,
        "bags": [],
        "professionList": [{"professionID": p} for p in professions],
        "professions": {
            p: {
                "readAt": at,
                "professionID": p,
                "skillLevel": skill,
                "maxSkillLevel": 300,
                "recipes": [],
            }
            for p, skill in professions.items()
        },
    }


def test_a_characters_enchanting_skill_is_from_its_latest_read_that_has_one(db):
    reads = [
        read("Bob", T0, {ENCHANTING: 90}),
        read("Bob", T0 + 60, {ENCHANTING: 95}),
        read("Bob", T0 + 120, {ENCHANTING: None}),
        read("Ann", T0, {197: 150}),  # Tailoring only
    ]
    # The latest Read has Enchanting but no window read, so no skill: the one before counts.
    reads[2].pop("professions")
    import_character_reads(db, reads, Era.BETA, CONFIG)

    assert enchanting_skills(db, MARKET) == {"Bob": 95}


def test_a_dropped_enchanting_has_no_skill(db):
    reads = [read("Bob", T0, {ENCHANTING: 90}), read("Bob", T0 + 60, {})]
    reads[1].pop("professions")
    import_character_reads(db, reads, Era.BETA, CONFIG)

    assert enchanting_skills(db, MARKET) == {}


# --- Disenchant in the Brain: Holdings and Best Exit Value ---

HOUR = 3600
GREEN = "9999"
GREEN_LINK = "|cff1eff00|Hitem:9999::::::::20:1490:::::::::|h[Green Chest]|h|r"
DUST = "item:10940::::::::20:1490"
# Default knobs, but a 3 hour Sale Horizon and no priors, as in test_recommend.
RECOMMEND_CONFIG = replace(
    CONFIG,
    sale_horizon_seconds=3 * HOUR,
    sell_rate_prior_hours_holdings=0,
    sell_rate_prior_hours_flips=0,
    sale_size_prior_events_holdings=0,
    sale_size_prior_events_flips=0,
    flip_min_sale_events=1,
)


def market_scans(green_level=18, dust_selling=False):
    """Two Scans an hour apart that tell the Brain what the green is. With
    `dust_selling`, 2 Strange Dust sell in that hour at 100: 6 in the 3 h horizon."""
    scans = []
    for n in range(2):
        s = scan(T0 + n * HOUR, {int(GREEN): info(green_level)})
        if dust_selling:
            s["listings"] = [
                {
                    "itemString": DUST,
                    "quantity": 20 - 2 * n,
                    "buyout": (20 - 2 * n) * 100,
                    "timeLeft": 4,
                }
            ]
        scans.append(s)
    return scans


def holder(count=1, enchanting=90, vendor_prices=None):
    """Bob's Read: `count` bound Green Chests, and Enchanting at `enchanting` (None: none)."""
    professions = {} if enchanting is None else {ENCHANTING: enchanting}
    r = read("Bob", T0, professions)
    r["bags"] = [{"bag": 0, "slot": 1, "link": GREEN_LINK, "count": count, "isBound": True}]
    r["vendorPrices"] = vendor_prices or {9999: 50, 10940: 100, 10939: 200, 10978: 400}
    return r


def holdings_of(db, scans, reads, predictions=()):
    import_scans(db, scans, Era.BETA, RECOMMEND_CONFIG)
    import_character_reads(db, reads, Era.BETA, RECOMMEND_CONFIG)
    [result] = recommend(db, RECOMMEND_CONFIG, predictions)
    return [(r.item_key, r.action, r.quantity, r.profit, r.character) for r in result.holdings]


def test_a_bound_green_worth_more_as_mats_is_disenchanted_by_a_character_who_can(db):
    # 1.875 Strange Dust, 0.3 Greater Magic Essence and 0.05 Small Glimmering Shard, at
    # their Vendor Prices (no market data), beat the green's own 50.
    assert holdings_of(db, market_scans(), [holder()]) == [
        (GREEN, Action.DISENCHANT, 1, pytest.approx(1.875 * 100 + 0.3 * 200 + 0.05 * 400), "Bob")
    ]


@pytest.mark.parametrize(
    "enchanting, level",
    [
        (None, 18),  # no Enchanting read
        (20, 22),  # item level 21-25 needs 25
    ],
)
def test_no_disenchant_way_without_the_enchanting_skill(db, enchanting, level):
    assert holdings_of(db, market_scans(level), [holder(enchanting=enchanting)]) == [
        (GREEN, Action.VENDOR, 1, 50, "")
    ]


def test_an_item_under_a_prediction_is_not_disenchanted(db):
    # Its bound units can't be Held either (ADR-0006), so they stay Vendored.
    written = date.fromtimestamp(T0) - timedelta(days=1)
    prediction = Prediction(
        "greens", "a reason", (GREEN,), "a patch", written, written + timedelta(days=30)
    )

    assert holdings_of(db, market_scans(), [holder()], [prediction]) == [
        (GREEN, Action.VENDOR, 1, 50, "")
    ]


def test_mats_are_valued_at_the_margin_so_disenchanting_stops_once_they_would_be_vendored(db):
    # 6 dust sell within the horizon at 99 less the cut, the rest go at a Vendor Price of
    # 10. Each Disenchant adds 1.875 dust on top of the ones before: the 4th would take
    # dust from 5.625 to 7.5, only 0.375 of it selling, and about 50 doesn't beat 100.
    prices = {9999: 100, 10940: 10}
    rows = holdings_of(db, market_scans(dust_selling=True), [holder(10, vendor_prices=prices)])

    assert [(key, action, n) for key, action, n, *_ in rows] == [
        (GREEN, Action.VENDOR, 7),  # most profit first
        (GREEN, Action.DISENCHANT, 3),
    ]


def test_best_exit_value_counts_the_disenchant_way(db):
    import_scans(db, market_scans(), Era.BETA, RECOMMEND_CONFIG)
    import_character_reads(db, [holder()], Era.BETA, RECOMMEND_CONFIG)

    values = exit_values(db, RECOMMEND_CONFIG, MARKET, {GREEN: Holding(bags=2)}, T0 + HOUR)

    assert values == {GREEN: pytest.approx(2 * (1.875 * 100 + 0.3 * 200 + 0.05 * 400))}
