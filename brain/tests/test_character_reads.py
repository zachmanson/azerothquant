import dataclasses
from pathlib import Path

import pytest

from brain.archive import Archive
from brain.config import Config, Era, Install
from brain.history import (
    Holding,
    KnownRecipe,
    Market,
    Reagent,
    holdings,
    import_character_reads,
    known_recipes,
    merchant_costs,
    open_history,
    pooled_gold,
)

T0 = 1_790_000_000
REALM = "Classic Beta PvP"
LINEN = "|cffffffff|Hitem:2589::::::::20:1490:::::::::|h[Linen Cloth]|h|r"
# A random-suffix item: its Item Key includes the bonus ID.
MONKEY = (
    "|cff1eff00|Hitem:9768::::::::20:1490::1:1:12743::::::|h[Scouting Trousers of the Monkey]|h|r"
)
HEARTHSTONE = "|cffffffff|Hitem:6948::::::::20:1490:::::::::|h[Hearthstone]|h|r"
CONFIG = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))


def item(link=LINEN, count=1, bound=False, bag=0, slot=1):
    return {"bag": bag, "slot": slot, "link": link, "count": count, "isBound": bound}


def character_read(
    at=T0,
    character="Kash-Patel",
    realm=REALM,
    faction="Alliance",
    money=0,
    bags=(),
    bank=None,
    professions=None,
    profession_list=None,
    merchant_costs=None,
):
    read = {
        "readAt": at,
        "realm": realm,
        "character": character,
        "faction": faction,
        "money": money,
        "bags": list(bags),
    }
    if bank is not None:
        bank_at, items = bank
        read |= {"bankReadAt": bank_at, "bank": list(items)}
    if professions is not None:
        read["professions"] = {p["professionID"]: p for p in professions}
    if profession_list is not None:
        read["professionList"] = [
            {"professionID": pid, "professionName": f"Profession {pid}"} for pid in profession_list
        ]
    if merchant_costs is not None:
        read["merchantCosts"] = merchant_costs
    return read


TAILORING = 197
BASIC, OPTIONAL = 1, 0  # Enum.CraftingReagentType; #29 checks what Forever gives


def recipe(recipe_id=2963, output=2996, reagents=((2589, 2),), **fields):
    """A Known Recipe as KnownRecipes.build shapes it; reagents are Basic unless typed."""
    return {
        "recipeID": recipe_id,
        "name": f"Recipe {recipe_id}",
        "recipeType": 1,
        "outputItemID": output,
        "link": f"|cffffffff|Henchant:{recipe_id}|h[Recipe {recipe_id}]|h|r",
        "quantityMin": 1,
        "quantityMax": 1,
        "bindType": 0,
        "reagents": [
            {"itemID": r[0], "quantity": r[1], "reagentType": r[2] if len(r) > 2 else BASIC}
            for r in reagents
        ],
    } | fields


def profession(recipes, at=T0 - 30, profession_id=TAILORING):
    return {
        "readAt": at,
        "professionID": profession_id,
        "professionName": f"Profession {profession_id}",
        "skillLevel": 75,
        "maxSkillLevel": 150,
        "recipes": list(recipes),
    }


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def archived_config(tmp_path):
    return dataclasses.replace(CONFIG, archive_dir=tmp_path / "archive")


# --- Archive then import ---


def test_every_character_read_is_archived_verbatim_and_imported(db, tmp_path):
    config = archived_config(tmp_path)
    first = character_read(T0, money=100, bags=[item(), {"bag": 0, "slot": 2, "odd": True}])
    second = character_read(T0 + 60, money=200, bank=(T0 + 30, [item(count=5)]))

    report = import_character_reads(db, [second, first], Era.BETA, config)

    assert report.character_reads_imported == 2
    archived = sorted(Archive(config.archive_dir).character_reads(), key=lambda r: r[1]["readAt"])
    assert archived == [(Era.BETA, first), (Era.BETA, second)]


def test_known_recipes_and_merchant_costs_are_archived_verbatim(db, tmp_path):
    # Kept raw so `brain rebuild` can re-parse them (ADR-0005, #18 amendment). Keyed by
    # professionID and itemID, so JSON gives string keys.
    config = archived_config(tmp_path)
    recipe = {
        "recipeID": 2963,
        "name": "Bolt of Linen Cloth",
        "recipeType": 1,
        "outputItemID": 2996,
        "quantityMin": 1,
        "quantityMax": 1,
        "bindType": 0,
        "reagents": [{"itemID": 2589, "quantity": 2, "reagentType": 1}],
    }
    # Per unit, so a stack of 3 for 10 copper costs a fraction of a copper each.
    merchant_costs = {2320: 10, 2604: 10 / 3}
    tailoring = {"readAt": T0 - 30, "professionID": 197, "professionName": "Tailoring"}
    profession_list = [{"professionID": 197, "professionName": "Tailoring"}]
    plain = character_read(T0, money=100, bags=[item(count=3)])
    with_recipes = plain | {
        "professions": {197: tailoring | {"recipes": [recipe]}},
        "professionList": profession_list,
        "merchantCosts": merchant_costs,
    }
    plain_db = open_history(":memory:")
    import_character_reads(plain_db, [plain], Era.BETA, CONFIG)

    report = import_character_reads(db, [with_recipes], Era.BETA, config)

    assert report.character_reads_imported == 1
    assert report.warnings == []
    assert holdings(db, Era.BETA, REALM, "Kash-Patel") == holdings(
        plain_db, Era.BETA, REALM, "Kash-Patel"
    )
    assert pooled_gold(db, Era.BETA, REALM, "Alliance") == 100
    [(_, archived)] = Archive(config.archive_dir).character_reads()
    assert archived["professions"] == {"197": tailoring | {"recipes": [recipe]}}
    assert archived["professionList"] == profession_list
    assert archived["merchantCosts"] == {"2320": 10, "2604": 10 / 3}
    plain_db.close()


def test_reimporting_the_same_character_read_changes_nothing(db, tmp_path):
    config = archived_config(tmp_path)
    import_character_reads(db, [character_read()], Era.BETA, config)

    report = import_character_reads(db, [character_read()], Era.BETA, config)

    assert report.character_reads_imported == 0
    assert report.character_reads_already_imported == 1
    assert len(list(Archive(config.archive_dir).character_reads())) == 1


def test_a_character_read_that_cant_be_named_is_skipped_and_not_archived(db, tmp_path):
    # Without realm, character and readAt it has no identity or file name, so it stays in
    # SavedVariables where it can at least be looked at.
    config = archived_config(tmp_path)
    no_time = character_read()
    del no_time["readAt"]

    report = import_character_reads(
        db,
        [no_time, character_read(character=None), character_read(at=True), "junk"],
        Era.BETA,
        config,
    )

    assert report.character_reads_unreadable == 4
    assert len(report.warnings) == 4
    assert list(Archive(config.archive_dir).character_reads()) == []


def run(db, *reads, era=Era.BETA):
    return import_character_reads(db, list(reads), era, CONFIG)


# --- Pooled gold ---


def test_gold_is_each_characters_latest_read_summed_over_one_realm_and_faction(db):
    run(
        db,
        character_read(T0, "Kash-Patel", money=100),
        character_read(T0 + 60, "Kash-Patel", money=250),  # latest wins, whatever the order
        character_read(T0 + 30, "Kash-Patel", money=999),
        character_read(T0, "Alt-Patel", money=40),
        character_read(T0, "Horde-Patel", faction="Horde", money=7000),
        character_read(T0, "Kash-Patel", realm="Quel'Thalas", money=8000),
    )
    run(db, character_read(T0, "Kash-Patel", money=5), era=Era.LIVE)

    assert pooled_gold(db, Era.BETA, REALM, "Alliance") == 290
    assert pooled_gold(db, Era.BETA, REALM, "Horde") == 7000
    assert pooled_gold(db, Era.BETA, "Quel'Thalas", "Alliance") == 8000
    assert pooled_gold(db, Era.LIVE, REALM, "Alliance") == 5
    assert pooled_gold(db, Era.LIVE, REALM, "Horde") == 0


def test_a_character_counts_toward_the_faction_of_its_latest_read(db):
    # After a faction change, the old faction's pool no longer has this Character's gold.
    run(
        db,
        character_read(T0, "Kash-Patel", faction="Alliance", money=100),
        character_read(T0 + 60, "Kash-Patel", faction="Horde", money=300),
    )

    assert pooled_gold(db, Era.BETA, REALM, "Alliance") == 0
    assert pooled_gold(db, Era.BETA, REALM, "Horde") == 300


# --- Holdings ---


def test_holdings_are_the_latest_reads_bags_by_item_key_split_by_bound(db):
    run(
        db,
        character_read(T0, bags=[item(LINEN, count=99)]),
        character_read(
            T0 + 60,
            bags=[
                item(LINEN, count=20, slot=1),
                item(LINEN, count=7, slot=2),
                item(MONKEY, count=1, slot=3),
                item(HEARTHSTONE, count=1, bound=True, slot=4),
            ],
        ),
    )

    assert holdings(db, Era.BETA, REALM, "Kash-Patel") == {
        "2589": Holding(bags=27),
        "9768:12743": Holding(bags=1),
        "6948": Holding(bags_bound=1),
    }


def test_a_character_with_no_reads_holds_nothing(db):
    run(db, character_read(character="Alt-Patel", bags=[item()]))

    assert holdings(db, Era.BETA, REALM, "Kash-Patel") == {}
    assert holdings(db, Era.LIVE, REALM, "Alt-Patel") == {}


def test_an_item_the_brain_cant_read_is_counted_and_the_rest_held(db):
    # Say a battle pet cage or a keystone: not an item: link. It stays in the Archive.
    pet = "|cff0070dd|Hbattlepet:39:1:3:152:13:10:0x0|h[Mechanical Squirrel]|h|r"
    report = run(
        db,
        character_read(bags=[item(pet), {"bag": 0, "slot": 2}, item(LINEN, count=3, slot=3)]),
    )

    assert report.character_reads_imported == 1
    assert report.character_items_unreadable == 2
    assert len(report.warnings) == 2
    assert holdings(db, Era.BETA, REALM, "Kash-Patel") == {"2589": Holding(bags=3)}


def test_the_bank_comes_from_the_latest_read_that_has_one(db):
    run(
        db,
        character_read(T0, bank=(T0 - 30, [item(LINEN, count=500, bag=-1)])),
        character_read(
            T0 + 60,
            bags=[item(LINEN, count=2)],
            bank=(T0 + 50, [item(LINEN, count=40, bag=-1), item(HEARTHSTONE, bound=True, bag=5)]),
        ),
        # Bank not opened in the latest session: its bank is left out, not empty.
        character_read(T0 + 120, bags=[item(LINEN, count=5)]),
    )

    assert holdings(db, Era.BETA, REALM, "Kash-Patel") == {
        "2589": Holding(bags=5, bank=40),
        "6948": Holding(bank_bound=1),
    }


def test_holdings_as_of_a_moment_come_from_the_reads_up_to_then(db):
    run(
        db,
        character_read(T0, bags=[item(LINEN, count=3)], bank=(T0, [item(LINEN, count=40, bag=-1)])),
        character_read(T0 + 60, bags=[item(LINEN, count=9)]),
        character_read(
            T0 + 120, bags=[item(LINEN, count=1)], bank=(T0 + 120, [item(LINEN, count=2, bag=-1)])
        ),
    )

    assert holdings(db, Era.BETA, REALM, "Kash-Patel", as_of=T0 + 60) == {
        "2589": Holding(bags=9, bank=40)
    }
    assert holdings(db, Era.BETA, REALM, "Kash-Patel", as_of=T0 - 1) == {}


def test_a_bank_read_empty_is_empty(db):
    run(
        db,
        character_read(T0, bank=(T0, [item(LINEN, count=40, bag=-1)])),
        character_read(T0 + 60, bank=(T0 + 50, [])),
    )

    assert holdings(db, Era.BETA, REALM, "Kash-Patel") == {}


def test_a_read_with_unreadable_gold_or_faction_adds_nothing_to_the_pool(db):
    report = run(
        db,
        character_read(T0, "Kash-Patel", money=100),
        character_read(T0 + 60, "Kash-Patel", money="lots", bags=[item()]),
        character_read(T0, "Alt-Patel", faction=None, money=40),
    )

    assert report.character_reads_imported == 3
    assert len(report.warnings) == 2
    assert pooled_gold(db, Era.BETA, REALM, "Alliance") == 0
    # Its bags are still the Character's Holdings.
    assert holdings(db, Era.BETA, REALM, "Kash-Patel") == {"2589": Holding(bags=1)}


# --- Known Recipes ---

ALLIANCE = Market(REALM, "Alliance", Era.BETA)


def test_a_known_recipe_keeps_its_output_quantity_cooldown_and_basic_reagents(db):
    run(
        db,
        character_read(
            T0,
            professions=[
                profession(
                    [
                        recipe(
                            2963,
                            output=2996,
                            reagents=[(2589, 2), (2321, 1), (7068, 1, OPTIONAL)],
                            quantityMin=1,
                            quantityMax=3,
                            bindType=1,
                            cooldown=3600,
                        )
                    ],
                    at=T0 - 30,
                )
            ],
            profession_list=[TAILORING],
        ),
    )

    assert known_recipes(db, ALLIANCE) == [
        KnownRecipe(
            character="Kash-Patel",
            profession_id=TAILORING,
            recipe_id=2963,
            output_item_id=2996,
            quantity_min=1,
            quantity_max=3,
            bind_type=1,
            cooldown=3600,
            read_at=T0 - 30,
            reagents=(Reagent(2589, 2), Reagent(2321, 1)),
        )
    ]


def test_a_recipe_that_makes_no_item_is_not_a_known_recipe(db):
    # Most enchants: GetRecipeSchematic gives no outputItemID, so the Addon leaves it out.
    enchant = recipe(7418, output=None, reagents=[(10940, 1)])
    del enchant["outputItemID"]
    run(
        db,
        character_read(
            professions=[profession([enchant, recipe(7421, output=6218)], profession_id=333)],
            profession_list=[333],
        ),
    )

    assert [r.recipe_id for r in known_recipes(db, ALLIANCE)] == [7421]


def test_each_professions_recipes_come_from_the_latest_read_that_has_it(db):
    cooking = 185
    both = [TAILORING, cooking]
    run(
        db,
        character_read(
            T0,
            professions=[
                profession([recipe(2963, output=2996)], at=T0 - 10),
                profession([recipe(2538, output=2679)], at=T0 - 10, profession_id=cooking),
            ],
            profession_list=both,
        ),
        # Learned one more Tailoring recipe; Cooking's window wasn't opened.
        character_read(
            T0 + 60,
            professions=[
                profession([recipe(2963, output=2996), recipe(2964, output=2997)], at=T0 + 50)
            ],
            profession_list=both,
        ),
        # Neither window opened.
        character_read(T0 + 120, profession_list=both),
    )

    assert [(r.profession_id, r.recipe_id, r.read_at) for r in known_recipes(db, ALLIANCE)] == [
        (cooking, 2538, T0 - 10),
        (TAILORING, 2963, T0 + 50),
        (TAILORING, 2964, T0 + 50),
    ]


def test_a_dropped_professions_recipes_are_not_current(db):
    mining = 186
    run(
        db,
        character_read(
            T0,
            professions=[profession([recipe(2963, output=2996)], at=T0 - 10)],
            profession_list=[TAILORING, mining],
        ),
        # Unlearned Tailoring. Its recipes are still on the older Read.
        character_read(T0 + 60, profession_list=[mining]),
    )

    assert known_recipes(db, ALLIANCE) == []


def test_a_read_that_cant_say_which_professions_defers_to_the_one_before(db):
    run(
        db,
        character_read(T0, profession_list=[]),
        character_read(T0 + 60, profession_list=[TAILORING]),
        # professionList left out: the client couldn't say, which isn't "none".
        character_read(T0 + 120, professions=[profession([recipe(2963, output=2996)])]),
    )

    assert [r.recipe_id for r in known_recipes(db, ALLIANCE)] == [2963]


def test_known_recipes_are_those_of_the_characters_in_the_market(db):
    def reads(character, realm=REALM, faction="Alliance", recipe_id=2963):
        return character_read(
            T0,
            character,
            realm=realm,
            faction=faction,
            professions=[profession([recipe(recipe_id, output=2996)])],
            profession_list=[TAILORING],
        )

    run(
        db,
        reads("Kash-Patel", recipe_id=1),
        reads("Alt-Patel", recipe_id=2),
        reads("Horde-Patel", faction="Horde", recipe_id=3),
        reads("Kash-Patel", realm="Quel'Thalas", recipe_id=4),
        # Changed faction since: counts where its latest Read puts it.
        reads("Turn-Patel", faction="Horde", recipe_id=5),
        character_read(T0 + 60, "Turn-Patel", profession_list=[TAILORING]),
    )
    run(db, reads("Kash-Patel", recipe_id=6), era=Era.LIVE)

    assert [(r.character, r.recipe_id) for r in known_recipes(db, ALLIANCE)] == [
        ("Alt-Patel", 2),
        ("Kash-Patel", 1),
        ("Turn-Patel", 5),
    ]


def test_a_profession_read_with_no_time_of_its_own_is_as_of_its_character_read(db):
    tailoring = profession([recipe(2963, output=2996, cooldown=600)])
    del tailoring["readAt"]
    run(db, character_read(T0, professions=[tailoring], profession_list=[TAILORING]))

    [known] = known_recipes(db, ALLIANCE)
    assert (known.cooldown, known.read_at) == (600, T0)


def test_a_recipe_the_brain_cant_read_is_skipped_with_a_warning(db):
    # No schematic: the Addon leaves reagents out, which is unknown, not "none".
    no_schematic = recipe(1)
    del no_schematic["reagents"]
    report = run(
        db,
        character_read(
            bags=[item(count=3)],
            professions=[
                profession(
                    [
                        no_schematic,
                        recipe(2, quantityMin=None),
                        recipe(3, reagents=[("thread", 1)]),
                        recipe(5) | {"reagents": ["junk"]},
                        "junk",
                        recipe(4, output=2996),
                    ]
                )
            ],
            profession_list=[TAILORING],
        ),
    )

    assert report.character_reads_imported == 1
    assert len(report.warnings) == 5
    assert [r.recipe_id for r in known_recipes(db, ALLIANCE)] == [4]
    assert holdings(db, Era.BETA, REALM, "Kash-Patel") == {"2589": Holding(bags=3)}


# --- Merchant Costs ---

THREAD, VIAL = 2320, 3371


def test_merchant_costs_are_the_lowest_of_each_characters_latest_price(db):
    run(
        db,
        # Kash-Patel's Thread got dearer (lost a reputation discount): its old price is gone.
        character_read(T0, "Kash-Patel", merchant_costs={THREAD: 8, VIAL: 20}),
        character_read(T0 + 60, "Kash-Patel", merchant_costs={THREAD: 10}),
        # No merchant visited: its latest prices are still the ones above.
        character_read(T0 + 120, "Kash-Patel"),
        # Per unit, so a stack of 3 for 10 copper is a fraction each.
        character_read(T0, "Alt-Patel", merchant_costs={THREAD: 12, VIAL: 10 / 3}),
        character_read(T0, "Horde-Patel", faction="Horde", merchant_costs={THREAD: 1}),
        character_read(T0, "Far-Patel", realm="Quel'Thalas", merchant_costs={THREAD: 1}),
    )
    run(db, character_read(T0, "Kash-Patel", merchant_costs={THREAD: 1}), era=Era.LIVE)

    assert merchant_costs(db, ALLIANCE) == {THREAD: 10, VIAL: 10 / 3}
