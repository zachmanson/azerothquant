import math
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

import brain.recommend as recommend_module
from brain.config import Config, Era, Install
from brain.disenchant import ItemInfo, load_table
from brain.history import (
    Holding,
    Market,
    enchanting_skills,
    import_character_reads,
    import_scans,
    item_info,
    known_recipes,
    open_history,
)
from brain.lots import start_of
from brain.predictions import Prediction
from brain.recommend import (
    Action,
    BuyUnder,
    ListingBuy,
    MatYield,
    _nothing_held,
    _plans,
    _valuer,
    _way_out,
    exit_values,
    grades,
    recommend,
)

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


def test_live_falls_back_to_betas_item_info_until_it_has_its_own(db):
    # Without item info a fresh Live Brain can't tell what a green disenchants into.
    import_scans(db, [scan(T0, {7: info(18), 8: info(30)})], Era.BETA, CONFIG)
    import_scans(db, [scan(T0, {7: info(20)})], Era.LIVE, CONFIG)

    assert item_info(db, Era.LIVE) == {
        7: ItemInfo(20, UNCOMMON, ARMOR, "INVTYPE_CHEST"),
        8: ItemInfo(30, UNCOMMON, ARMOR, "INVTYPE_CHEST"),
    }


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
    risk_caps=False,  # sized by the gold alone, as written (ADR-0034)
    row_min_profit_share=0.0,  # no Minimum Profit (#197), as written
    row_min_profit_copper=0,
    row_min_profit_per_click=0,
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


def test_an_enchanting_skill_raised_later_does_not_gate_best_exit_value_before(db):
    # Item level 22 needs 25: Bob has 20 at the moment and trains to 90 after it.
    import_scans(db, market_scans(22), Era.BETA, RECOMMEND_CONFIG)
    trained = read("Bob", T0 + 2 * HOUR, {ENCHANTING: 90})
    import_character_reads(db, [holder(enchanting=20), trained], Era.BETA, RECOMMEND_CONFIG)

    values = exit_values(db, RECOMMEND_CONFIG, MARKET, {GREEN: Holding(bags=2)}, T0 + HOUR)

    assert values == {GREEN: 2 * 50}


OTHER = "9998"  # another green armor piece of the Green Chest's band
DUST_KEY = "10940"
# Dust Vendors for 10, so past the 6 that sell in the horizon it's worth little.
MARGINAL_PRICES = {9999: 100, 9998: 100, 10940: 10, 10939: 200, 10978: 400}


def two_greens(db):
    """Bob, an enchanter, holds 2 unbound Green Chests and 2 of the other green, with
    Strange Dust selling 6 in the horizon."""
    r = read("Bob", T0, {ENCHANTING: 90})
    r["bags"] = [
        {"bag": 0, "slot": 1, "link": GREEN_LINK, "count": 2, "isBound": False},
        {"bag": 0, "slot": 2, "link": other_green(9998), "count": 2, "isBound": False},
    ]
    r["vendorPrices"] = MARGINAL_PRICES
    r["itemInfo"] = {9998: info(18, equip_loc="INVTYPE_LEGS")}
    import_scans(db, market_scans(dust_selling=True), Era.BETA, RECOMMEND_CONFIG)
    import_character_reads(db, [r], Era.BETA, RECOMMEND_CONFIG)
    return {GREEN: Holding(bags=2), OTHER: Holding(bags=2)}


def test_greens_that_yield_the_same_mat_share_its_sale_slots_in_best_exit_value(db):
    held = two_greens(db)

    joint = exit_values(db, RECOMMEND_CONFIG, MARKET, held, T0 + HOUR)
    alone = [
        exit_values(db, RECOMMEND_CONFIG, MARKET, {key: h}, T0 + HOUR)[key]
        for key, h in held.items()
    ]

    # 4 Disenchants expect 7.5 dust, but only 6 sell: each green alone expects 3.75.
    assert sum(joint.values()) < sum(alone)
    [result] = recommend(db, RECOMMEND_CONFIG)
    assert sum(joint.values()) == pytest.approx(sum(r.profit for r in result.holdings))


def test_a_grades_open_units_share_their_mats_sale_slots_too(db):
    held = two_greens(db)
    written = date.fromtimestamp(T0 + HOUR) + timedelta(days=1)
    p = Prediction(
        "greens",
        "a reason",
        (GREEN, OTHER),
        "a patch",
        written,
        written + timedelta(days=30),
        happened=written + timedelta(days=1),
    )
    graded_at = start_of(written + timedelta(days=1)) + RECOMMEND_CONFIG.sale_horizon_seconds

    [grade] = grades(db, RECOMMEND_CONFIG, MARKET, [p], graded_at)

    joint = exit_values(db, RECOMMEND_CONFIG, MARKET, held, graded_at)
    assert grade.open_value == pytest.approx(sum(joint.values()))


def test_held_mats_lower_the_best_exit_value_of_a_green_that_yields_them(db):
    import_scans(db, market_scans(dust_selling=True), Era.BETA, RECOMMEND_CONFIG)
    import_character_reads(
        db, [holder(count=0, vendor_prices=MARGINAL_PRICES)], Era.BETA, RECOMMEND_CONFIG
    )

    def value(held):
        return exit_values(db, RECOMMEND_CONFIG, MARKET, held, T0 + HOUR)[GREEN]

    # 6 held dust take every sale slot, so the green's dust would only Vendor.
    with_dust = value({GREEN: Holding(bags=1), DUST_KEY: Holding(bags=6)})
    assert with_dust < value({GREEN: Holding(bags=1)})


@pytest.mark.parametrize(
    "bound, value",
    [
        ({GREEN: {"Bob": 1}}, 1.875 * 100 + 0.3 * 200 + 0.05 * 400),
        ({GREEN: {"Ann": 1}}, 50),  # Ann can't Disenchant it, and can't mail it to Bob
        ({}, 50),  # no holder given
    ],
)
def test_a_bound_units_best_exit_value_disenchants_it_only_for_a_holder_who_can(db, bound, value):
    import_scans(db, market_scans(), Era.BETA, RECOMMEND_CONFIG)
    import_character_reads(db, [holder(count=0)], Era.BETA, RECOMMEND_CONFIG)

    held = {GREEN: Holding(bags_bound=1)}
    values = exit_values(db, RECOMMEND_CONFIG, MARKET, held, T0 + HOUR, bound)

    assert values == {GREEN: pytest.approx(value)}


def ann(count=1, enchanting=None, bound=True):
    """Ann's Read: `count` Green Chests, and Enchanting at `enchanting` (None: none)."""
    professions = {} if enchanting is None else {ENCHANTING: enchanting}
    r = read("Ann", T0, professions)
    r["bags"] = [{"bag": 0, "slot": 1, "link": GREEN_LINK, "count": count, "isBound": bound}]
    return r


def test_a_bound_green_held_by_a_character_who_cant_disenchant_it_takes_its_next_best_action(
    db,
):
    # Bob can Disenchant it, but a bound unit can't be mailed to him.
    assert holdings_of(db, market_scans(), [ann(), holder(count=0)]) == [
        (GREEN, Action.VENDOR, 1, 50, "")
    ]


def test_a_bound_green_is_disenchanted_by_the_character_who_holds_it(db):
    # Ann can Disenchant too, and comes first by name, but can't be mailed Bob's unit.
    rows = holdings_of(db, market_scans(), [ann(count=0, enchanting=90), holder()])

    assert [(key, action, n, who) for key, action, n, _, who in rows] == [
        (GREEN, Action.DISENCHANT, 1, "Bob")
    ]


def test_unbound_greens_held_by_a_character_who_cant_disenchant_are_mailed_to_one_who_can(db):
    rows = holdings_of(db, market_scans(), [ann(count=2, bound=False), holder(count=0)])

    assert [(key, action, n, who) for key, action, n, _, who in rows] == [
        (GREEN, Action.DISENCHANT, 2, "Bob")
    ]


# --- Buy Under with the Disenchant way (#88) ---

GREEN_ITEM = "item:9999::::::::20:1490"
# A green at 50, and its mats dear enough to beat the 5s effort of buying a green.
MAT_PRICES = {9999: 50, 10940: 1000, 10939: 2000, 10978: 4000}
# 1.875 Strange Dust, 0.3 Greater Magic Essence, 0.05 Small Glimmering Shard.
GREEN_MATS = (
    MatYield("10940", 1.875),
    MatYield("10939", 0.3),
    MatYield("10978", 0.05),
)


def green_listed(*units, level=18):
    """One Scan with Green Chests, one at each of `units`, by other players."""
    s = scan(T0, {int(GREEN): info(level)})
    s["listings"] = [
        {"itemString": GREEN_ITEM, "quantity": 1, "buyout": unit, "timeLeft": 4} for unit in units
    ]
    return [s]


def enchanter(enchanting=90, vendor_prices=None, recipes=()):
    """Bob's Read: Enchanting at `enchanting`, with `recipes` known in it."""
    r = read("Bob", T0, {ENCHANTING: enchanting})
    r["vendorPrices"] = vendor_prices or MAT_PRICES
    r["professions"][ENCHANTING]["recipes"] = list(recipes)
    return r


def buy_unders_of(db, scans, reads):
    import_scans(db, scans, Era.BETA, RECOMMEND_CONFIG)
    import_character_reads(db, reads, Era.BETA, RECOMMEND_CONFIG)
    [result] = recommend(db, RECOMMEND_CONFIG)
    return result.buy_under


def test_an_item_buys_under_its_expected_mats_when_a_character_can_disenchant_it(db):
    # The mats at their Vendor Prices: 1875 + 600 + 200 = 2675, less the 5s effort of
    # buying a green (they don't stack): B = 2175 / 1.2. The mats Vendor: no limit.
    buys = buy_unders_of(db, green_listed(1000), [enchanter()])

    [green] = [b for b in buys if b.item_key == GREEN]
    assert replace(green, mats=()) == BuyUnder(
        GREEN,
        1812,
        Action.DISENCHANT,
        units=None,
        seen=1,
        window_days=7,
        listed_now=True,
        disenchanter="Bob",
    )
    assert mats_of(green) == GREEN_MATS


def mats_of(buy):
    """A Buy Under's mats, with the expected quantities rounded off the float noise."""
    return tuple(MatYield(m.item_key, round(m.quantity, 6)) for m in buy.mats)


def test_a_mat_that_feeds_a_craft_brings_the_crafts_credit_to_the_disenchant_way(db):
    # 2 Greater Magic Essence make a wand that Vendors for 1g: 5000 per Essence beats its
    # own 2000. 1875 + 0.3 x 5000 + 200 = 3575, less the 500 effort: B = 3075 / 1.2.
    wand = {
        "recipeID": 1,
        "outputItemID": 7777,
        "quantityMin": 1,
        "quantityMax": 1,
        "bindType": 0,
        "reagents": [{"itemID": GREATER_MAGIC, "quantity": 2, "reagentType": 1}],
    }
    reads = [enchanter(vendor_prices=MAT_PRICES | {7777: 10000}, recipes=[wand])]

    buys = buy_unders_of(db, green_listed(1000), reads)

    # Its group's Buy Under gets the same credit.
    assert [(b.price, b.units) for b in buys if b.way is Action.DISENCHANT] == [
        (2562, None),
        (2562, None),
    ]


def test_a_disenchant_way_is_good_for_as_many_disenchants_as_its_most_limited_mat_has_room_for(
    db,
):
    # 6 Strange Dust sell within the horizon, which beats their Vendor Price of 10: room
    # for 6 / 1.875 = 3 Disenchants. The Essence and the Shard Vendor, with no limit.
    scans = market_scans(dust_selling=True)
    for s in scans:
        s["listings"].append(
            {"itemString": GREEN_ITEM, "quantity": 1, "buyout": 300, "timeLeft": 4}
        )
    reads = [enchanter(vendor_prices=MAT_PRICES | {10940: 10})]

    buys = buy_unders_of(db, scans, reads)

    # The item's and its group's alike.
    assert [(b.way, b.units) for b in buys if b.way is Action.DISENCHANT] == [
        (Action.DISENCHANT, 3),
        (Action.DISENCHANT, 3),
    ]


def other_green(item_id, name="Other Green"):
    return f"|cff1eff00|Hitem:{item_id}::::::::20:1490:::::::::|h[{name}]|h|r"


def group_scans(other_unit=1500):
    """Three Scans an hour apart, each with one green by another player: the Green Chest
    at 1000, then another green armor piece of the same band at `other_unit`, then a green
    shirt, which can't be Disenchanted, at 500."""
    infos = {
        int(GREEN): info(18),
        9998: info(20, equip_loc="INVTYPE_LEGS"),
        9997: info(18, equip_loc="INVTYPE_BODY"),
    }
    items = [
        (GREEN_ITEM, 1000),
        ("item:9998::::::::20:1490", other_unit),
        ("item:9997::::::::20:1490", 500),
    ]
    scans = []
    for n, (item, unit) in enumerate(items):
        s = scan(T0 + n * HOUR, infos)
        s["id"] = n + 1
        s["listings"] = [{"itemString": item, "quantity": 1, "buyout": unit, "timeLeft": 4}]
        scans.append(s)
    return scans


def test_a_disenchant_source_group_buys_under_its_expected_mats_seen_across_its_items(db):
    # The same 1812 as the Green Chest's (armor, item level 16-20). Its Listing and the
    # other piece's count as two Scans; the shirt's is in no group.
    table = load_table()
    buys = buy_unders_of(db, group_scans(), [enchanter()])

    [group] = [b for b in buys if b.group is not None]
    assert replace(group, mats=()) == BuyUnder(
        None,
        1812,
        Action.DISENCHANT,
        units=None,
        seen=2,
        window_days=7,
        listed_now=False,
        disenchanter="Bob",
        group=table.group(int(GREEN), green(18)),
    )
    assert mats_of(group) == GREEN_MATS


@pytest.mark.parametrize(
    "enchanting, level",
    [
        (None, 18),  # no Enchanting read
        (24, 25),  # item level 21-25 needs 25
    ],
)
def test_no_group_buys_under_without_a_character_who_can_disenchant_its_items(
    db, enchanting, level
):
    reader = enchanter(enchanting) if enchanting else read("Bob", T0, {})
    reader["vendorPrices"] = MAT_PRICES

    buys = buy_unders_of(db, green_listed(1000, level=level), [reader])

    assert [b for b in buys if b.way is Action.DISENCHANT] == []


def test_a_group_listing_over_its_buy_under_isnt_a_sighting(db):
    buys = buy_unders_of(db, group_scans(other_unit=1813), [enchanter()])

    assert [(b.price, b.seen) for b in buys if b.group is not None] == [(1812, 1)]


# --- Flip to Disenchant (#89) ---

OTHER_ITEM = "item:9998::::::::20:1490"
# Dust sells 6 in the horizon, else Vendors for 10. The Essence and the Shard Vendor dear.
FLIP_PRICES = MAT_PRICES | {10940: 10, 9998: 50}
# 0.3 x 2000 + 0.05 x 4000 = 800 for the Essence and the Shard, and 1.875 dust at
# 99 less the 5% cut while it sells, less the 5s effort of buying a green.
SOLD_DUST_NET = 800 + 1.875 * 99 * 0.95 - 500


def flip_scans(*listings):
    """Dust selling 6 in the horizon (`market_scans`), and in the latest Scan other
    players' greens of the armor 16-20 group: (item string, unit buyout) each."""
    scans = market_scans(dust_selling=True)
    for s in scans:
        s["itemInfo"][9998] = info(20, equip_loc="INVTYPE_LEGS")
    scans[-1]["listings"] += [
        {"itemString": item, "quantity": 1, "buyout": unit, "timeLeft": 4}
        for item, unit in listings
    ]
    return scans


def flips_to_disenchant(db, scans, reads, config=RECOMMEND_CONFIG):
    """The Flips to Disenchant, with 1g to spend unless the first Read has gold."""
    reads[0]["money"] = reads[0]["money"] or 10000
    import_scans(db, scans, Era.BETA, config)
    import_character_reads(db, reads, Era.BETA, config)
    [result] = recommend(db, config)
    return [r for r in result.shopping_list if r.disenchant is not None]


def test_a_flip_to_disenchant_buys_a_groups_cheapest_listings_while_the_mats_room_lasts(db):
    # The first 3 Disenchants' dust all sells (5.625 of 6), so each nets SOLD_DUST_NET and
    # clears the margin up to 376. The 4th's dust mostly Vendors: 0.375 x 94.05 + 1.5 x 10
    # + 800 - 500 = 350.27, which only clears up to 250, so the 320 Listing stops it.
    listed = [(GREEN_ITEM, 300), (OTHER_ITEM, 150), (GREEN_ITEM, 100), (OTHER_ITEM, 320)]

    [row] = flips_to_disenchant(db, flip_scans(*listed), [enchanter(vendor_prices=FLIP_PRICES)])

    assert row.disenchant.buys == (
        ListingBuy(GREEN, 100),
        ListingBuy(OTHER, 150),
        ListingBuy(GREEN, 300),
    )
    assert (row.action, row.character, row.quantity, row.listings, row.cost) == (
        Action.DISENCHANT,
        "Bob",
        3,
        3,
        550,
    )
    assert row.profit == pytest.approx(3 * SOLD_DUST_NET - 550)
    assert mats_of(row) == tuple(MatYield(m.item_key, round(3 * m.quantity, 6)) for m in GREEN_MATS)


CHEAP_GREENS = [(GREEN_ITEM, 100), (OTHER_ITEM, 150), (GREEN_ITEM, 300)]


def test_a_listing_whose_item_has_a_better_way_out_than_disenchant_isnt_bought(db):
    # The other piece Vendors for 20s, more than its mats bring: that's a Flip to Vendor.
    reads = [enchanter(vendor_prices=FLIP_PRICES | {9998: 2000})]

    [row] = flips_to_disenchant(db, flip_scans(*CHEAP_GREENS), reads)

    assert row.disenchant.buys == (ListingBuy(GREEN, 100), ListingBuy(GREEN, 300))


DUST_LINK = "|cffffffff|Hitem:10940::::::::20:1490:::::::::|h[Strange Dust]|h|r"


def test_held_mats_take_the_mats_room_first(db):
    # 6 held dust take every sale slot, so each Disenchant's dust Vendors: 800 + 18.75
    # - 500 = 318.75, which clears up to 218.
    reader = enchanter(vendor_prices=FLIP_PRICES)
    reader["bags"] = [{"bag": 0, "slot": 1, "link": DUST_LINK, "count": 6, "isBound": False}]

    [row] = flips_to_disenchant(db, flip_scans(*CHEAP_GREENS), [reader])

    assert row.disenchant.buys == (ListingBuy(GREEN, 100), ListingBuy(OTHER, 150))
    assert row.profit == pytest.approx(2 * 318.75 - 250)


def test_no_flip_to_disenchant_without_a_character_who_can_disenchant(db):
    reader = read("Bob", T0, {})
    reader["vendorPrices"] = FLIP_PRICES

    assert flips_to_disenchant(db, flip_scans(*CHEAP_GREENS), [reader]) == []


def test_a_flip_to_disenchant_leaves_out_items_the_latest_scan_dropped_rows_of(db):
    # #156: the Scan's ladder of Green Chests is partial, so the cheapest it saw may not
    # be the cheapest up. The other pieces' 150 and 320 are the first two Disenchants.
    listed = [(GREEN_ITEM, 300), (OTHER_ITEM, 150), (GREEN_ITEM, 100), (OTHER_ITEM, 320)]
    scans = flip_scans(*listed)
    scans[-1] |= {"droppedRows": 5, "droppedItemIDs": [int(GREEN)]}

    [row] = flips_to_disenchant(db, scans, [enchanter(vendor_prices=FLIP_PRICES)])

    assert row.disenchant.buys == (ListingBuy(OTHER, 150), ListingBuy(OTHER, 320))


def test_the_budget_cuts_a_flip_to_disenchant(db):
    reader = enchanter(vendor_prices=FLIP_PRICES)
    reader["budget"] = 299

    [row] = flips_to_disenchant(db, flip_scans(*CHEAP_GREENS), [reader])

    assert row.disenchant.buys == (ListingBuy(GREEN, 100), ListingBuy(OTHER, 150))


def test_a_flip_to_disenchant_stops_at_the_first_listing_that_breaks_a_risk_cap(db):
    # #170, ADR-0034: 2.99% of the 1g Stake leaves 2s 99c of room, as the Budget above.
    config = replace(RECOMMEND_CONFIG, risk_caps=True, flip_tied_up_share=0.0299)

    [row] = flips_to_disenchant(
        db, flip_scans(*CHEAP_GREENS), [enchanter(vendor_prices=FLIP_PRICES)], config
    )

    assert row.disenchant.buys == (ListingBuy(GREEN, 100), ListingBuy(OTHER, 150))
    assert (row.quantity, row.capped, row.capped_by) == (2, 3, "room")


def test_a_mat_that_feeds_a_craft_brings_the_crafts_credit_to_a_flip_to_disenchant(db):
    # 2 Greater Magic Essence make a wand that Vendors for 1g: 5000 per Essence, so one
    # Disenchant nets 1.875 x 94.05 + 0.3 x 5000 + 200 - 500, which clears a 700 Listing.
    wand = {
        "recipeID": 1,
        "outputItemID": 7777,
        "quantityMin": 1,
        "quantityMax": 1,
        "bindType": 0,
        "reagents": [{"itemID": GREATER_MAGIC, "quantity": 2, "reagentType": 1}],
    }
    reads = [enchanter(vendor_prices=FLIP_PRICES | {7777: 10000}, recipes=[wand])]

    [row] = flips_to_disenchant(db, flip_scans((GREEN_ITEM, 700)), reads)

    assert row.profit == pytest.approx(1.875 * 99 * 0.95 + 0.3 * 5000 + 200 - 500 - 700)


WEAPON_ITEM = "item:9996::::::::20:1490"


def test_flips_to_disenchant_are_cut_to_the_most_profitable(db):
    # A green weapon's group is apart from the armor's. It yields mostly Essence, which
    # Vendors dear here, so its one Listing makes more than the armor's three.
    scans = flip_scans(*CHEAP_GREENS, (WEAPON_ITEM, 300))
    for s in scans:
        s["itemInfo"][9996] = info(18, class_id=WEAPON, equip_loc="INVTYPE_WEAPON")
    config = replace(RECOMMEND_CONFIG, disenchant_list_rows=1)

    both = flips_to_disenchant(db, scans, [enchanter(vendor_prices=FLIP_PRICES)])
    assert [r.disenchant.group.kind for r in both] == ["weapon", "armor"]
    [kept] = recommend(db, config)[0].shopping_list

    assert kept == both[0]


def test_a_flip_to_disenchant_under_the_minimum_profit_is_left_off(db):
    # #197: as above, a Minimum Profit just over the armor's Profit leaves only the weapon.
    scans = flip_scans(*CHEAP_GREENS, (WEAPON_ITEM, 300))
    for s in scans:
        s["itemInfo"][9996] = info(18, class_id=WEAPON, equip_loc="INVTYPE_WEAPON")

    weapon, armor = flips_to_disenchant(db, scans, [enchanter(vendor_prices=FLIP_PRICES)])
    config = replace(RECOMMEND_CONFIG, row_min_profit_copper=math.floor(armor.profit) + 1)

    assert recommend(db, config)[0].shopping_list == [weapon]


def test_a_way_out_asked_again_in_a_pass_is_the_one_worked_out_afresh(db, monkeypatch):
    # #141: a Valuer remembers its ways out for the pass. The Greater Magic Essence's
    # is a Craft (the wand), the green's a Disenchant, and the Dust's is limited by the
    # 6 that sell in the horizon: each asked over and over, with and without Sources,
    # in both orders, on one Valuer, is what it is with nothing remembered.
    wand = {
        "recipeID": 1,
        "outputItemID": 7777,
        "quantityMin": 1,
        "quantityMax": 1,
        "bindType": 0,
        "reagents": [{"itemID": GREATER_MAGIC, "quantity": 2, "reagentType": 1}],
    }
    scans = market_scans(dust_selling=True)
    for s in scans:
        s["listings"].append(
            {"itemString": GREEN_ITEM, "quantity": 1, "buyout": 300, "timeLeft": 4}
        )
    prices = MAT_PRICES | {10940: 10, 7777: 10000}
    import_scans(db, scans, Era.BETA, RECOMMEND_CONFIG)
    import_character_reads(db, [enchanter(vendor_prices=prices, recipes=[wand])], Era.BETA, CONFIG)
    now, config = T0 + HOUR, RECOMMEND_CONFIG
    valuer, _ = _valuer(db, config, MARKET, now)
    plans = _plans(known_recipes(db, MARKET), now)
    keys = [GREEN, DUST_KEY, "10939", "10978", "7777"]

    sources = _nothing_held(valuer, plans, config)
    ahead = valuer.after({}, {**valuer.held, DUST_KEY: 3})

    # Nothing remembered: every way out, the nested Craft and Disenchant ones too, is
    # worked out afresh.
    with monkeypatch.context() as m:
        m.setattr(
            "brain.recommend._way_out",
            lambda key, v, c, s=None: recommend_module._best_way_out(key, v, c, s),
        )
        expected = {
            (key, s): recommend_module._way_out(key, valuer, config, sources if s else None)
            for key in keys
            for s in (True, False)
        }
        expected_ahead = recommend_module._way_out(DUST_KEY, ahead, config, sources)
    assert {expected[GREEN, True].way, expected["10939", True].way} == {
        Action.DISENCHANT,
        Action.CRAFT,
    }
    assert expected[DUST_KEY, True].units is not None

    asked = [(key, s) for s in (True, False, True) for key in [*keys, *reversed(keys)]]
    for key, s in asked:
        assert _way_out(key, valuer, config, sources if s else None) == expected[key, s]
    # One with 3 Dust held ahead has 3 fewer units of room: it doesn't share the answers.
    assert expected_ahead.units == expected[DUST_KEY, True].units - 3
    assert _way_out(DUST_KEY, ahead, config, sources) == expected_ahead


def test_beta_never_falls_back_to_lives_item_info(db):
    import_scans(db, [scan(T0, {7: info(20)})], Era.LIVE, CONFIG)

    assert item_info(db, Era.BETA) == {}
