from dataclasses import replace
from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.flips import CraftFlip, NotGradable, craft_flips, flip_record
from brain.grades_file import (
    FlipGrade,
    Named,
    NamedBuy,
    NamedCraft,
    craft_flip_name,
    freeze_named,
    freeze_shown,
    freeze_shown_crafts,
    load_frozen,
)
from brain.history import (
    Market,
    import_character_reads,
    import_mailbox_reads,
    import_scans,
    open_history,
)
from brain.lots import NamedSet

T0 = 1_790_000_000
MINUTE = 60
HOUR = 3600
REALM = "Classic Beta PvP"
MARKET = Market(realm=REALM, faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
LINEN_LINK = "|cffffffff|Hitem:2589::::::::20:1490:::::::::|h[Linen Cloth]|h|r"
BOLT = "item:2996::::::::20:1490"
LINEN_KEY, BOLT_KEY = "2589", "2996"
BOLT_RECIPE = 2963
TAILORING = 197

# As in test_flips: a 3 hour Sale Horizon, and no priors, so hourly Scans make a Sell Rate
# taken at its word.
CONFIG = replace(
    Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),)),
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


def scan(at, *rows):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "droppedRows": 0,
        "listings": list(rows),
        "vendorPrices": {},
    }


def row(item=LINEN, quantity=1, unit=100):
    return {"itemString": item, "quantity": quantity, "buyout": quantity * unit, "timeLeft": 4}


def bolt_market(*scans_after):
    """2 Linen at 100 and a Bolt at 1000 sell each hour from T0: at T0 + 1 h the Brain
    names a Flip to Craft of 3 Bolts, buying 6 Linen at up to 100."""
    return [
        scan(T0 + n * HOUR, row(quantity=20 - 2 * n), row(BOLT, quantity=6 - n, unit=1000))
        for n in range(3)
    ] + list(scans_after)


def recipe(output=2996, reagents=((2589, 2),), recipe_id=BOLT_RECIPE):
    """A Known Recipe as the Addon records it, with Basic reagents only."""
    return {
        "recipeID": recipe_id,
        "outputItemID": output,
        "quantityMin": 1,
        "quantityMax": 1,
        "bindType": 0,
        "reagents": [
            {"itemID": item_id, "quantity": n, "reagentType": 1} for item_id, n in reagents
        ],
    }


def character_read(at=T0, crafts=(), recipes=None):
    """Kash-Patel with 10000 copper and the Bolt recipe, and the `crafts` (recipe, at) it
    made since its last Read."""
    read = {
        "readAt": at,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 10_000,
        "bags": [],
        "vendorPrices": {2589: 10},
        "professions": {
            TAILORING: {
                "readAt": at,
                "professionID": TAILORING,
                "recipes": recipes or [recipe()],
            }
        },
        "professionList": [{"professionID": TAILORING}],
    }
    if crafts:
        read["crafts"] = [{"recipeID": r, "at": t, "quantity": 1} for r, t in crafts]
    return read


def mailbox_read(read_at, *mails):
    return {
        "readAt": read_at,
        "realm": REALM,
        "character": "Kash-Patel",
        "shownCount": len(mails),
        "totalCount": len(mails),
        "skippedMails": 0,
        "mails": list(mails),
    }


def won(at, count, unit, link=LINEN_LINK, name="Linen Cloth", read_after=12 * HOUR):
    """A Purchase that arrived at `at`, read `read_after` later."""
    mail = {
        "index": 1,
        "sender": "Alliance Auction House",
        "subject": f"Auction won: {name}",
        "money": 0,
        "daysLeft": 30 - read_after / 86400,
        "firstItemQuantity": count,
        "firstItemLink": link,
        "invoice": {"invoiceType": "buyer", "itemName": name, "bid": count * unit, "count": count},
    }
    return mailbox_read(at + read_after, mail)


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def load(db, scans, mailbox_reads=(), reads=(), first_read=None):
    import_scans(db, list(scans), Era.BETA, CONFIG)
    import_mailbox_reads(db, list(mailbox_reads), Era.BETA, CONFIG)
    import_character_reads(db, [first_read or character_read(), *reads], Era.BETA, CONFIG)


def freezing(tmp_path, config=CONFIG):
    return replace(config, grades_path=tmp_path / "grades.toml")


BOUGHT = T0 + HOUR + 10 * MINUTE


def test_a_reagent_purchase_at_or_under_its_most_to_pay_is_a_flip_to_craft_of_what_was_named(
    db, tmp_path
):
    load(db, bolt_market(), [won(BOUGHT, count=6, unit=100)])

    [flip] = craft_flips(db, freezing(tmp_path), MARKET, [], now=T0 + 2 * HOUR)

    assert (flip.recipe_id, flip.scan_at, flip.bought_at) == (BOLT_RECIPE, T0 + HOUR, BOUGHT)
    named = flip.named
    assert (named.item_key, named.character, named.units) == (BOLT_KEY, "Kash-Patel", 3)
    assert named.buys == (NamedBuy(LINEN_KEY, 6, 100.0),)
    assert named.post_at == 999
    assert named.profit == pytest.approx(3 * 999 * 0.95 - 6 * 100)
    assert flip.grade is None
    # Frozen the first time it's worked out.
    assert load_frozen(tmp_path / "grades.toml", MARKET).shown_crafts[T0 + HOUR] == (named,)


def test_a_reagent_purchase_over_its_most_to_pay_is_no_flip_to_craft(db):
    load(db, bolt_market(), [won(BOUGHT, count=6, unit=101)])

    assert craft_flips(db, CONFIG, MARKET, [], now=T0 + 2 * HOUR) == []


THREAD_LINK = "|cffffffff|Hitem:2320::::::::20:1490:::::::::|h[Coarse Thread]|h|r"


def test_a_purchase_of_a_reagent_the_row_buys_from_a_merchant_is_no_flip_to_craft(db):
    # Each Bolt takes a Coarse Thread too, from a merchant at 10.
    with_thread = character_read(recipes=[recipe(reagents=((2589, 2), (2320, 1)))])
    with_thread["merchantCosts"] = {2320: 10}
    thread = won(BOUGHT, count=3, unit=5, link=THREAD_LINK, name="Coarse Thread")
    load(db, bolt_market(), [thread], first_read=with_thread)

    assert craft_flips(db, CONFIG, MARKET, [], now=T0 + 2 * HOUR) == []
    # The same row's Linen would be.
    linen = won(BOUGHT, count=6, unit=100, read_after=13 * HOUR)
    import_mailbox_reads(db, [linen], Era.BETA, CONFIG)
    [flip] = craft_flips(db, CONFIG, MARKET, [], now=T0 + 2 * HOUR)
    assert [b.item_key for b in flip.named.buys] == [LINEN_KEY]


GRADED = BOUGHT + 3 * HOUR  # a Sale Horizon after the first Purchase
CRAFTED = BOUGHT + 20 * MINUTE


def sold(at, count, unit, name="Bolt of Linen Cloth"):
    """A Sold Outcome that arrived at `at`, read 12 hours later."""
    invoice = {"invoiceType": "seller", "itemName": name, "bid": count * unit, "count": count}
    mail = {
        "index": 1,
        "sender": "Alliance Auction House",
        "subject": f"Auction successful: {name}",
        "money": round(count * unit * 0.95),
        "daysLeft": 29.5,
        "invoice": invoice,
    }
    return mailbox_read(at + 12 * HOUR, mail)


def later_bolts(*at):
    """Scans after the matched one, a Bolt at 1000 and 2 Linen at 100 still selling each
    hour. The first shows the player's own Bolts posted at 999, which names them."""
    own = row(BOLT, quantity=3, unit=999) | {"own": True, "name": "Bolt of Linen Cloth"}
    return [
        scan(t, row(quantity=14 - 2 * n), row(BOLT, quantity=3 - n, unit=1000), *([own] * (n == 0)))
        for n, t in enumerate(at)
    ]


def crafted(*at, recipe_id=BOLT_RECIPE):
    """The Character Read that carried Bolt crafts at each of `at`."""
    return character_read(at=max(at) + MINUTE, crafts=[(recipe_id, t) for t in at])


def test_a_flip_to_craft_is_graded_on_its_output_sold_within_the_horizon_and_open_after_it(db):
    load(
        db,
        bolt_market(*later_bolts(T0 + 3 * HOUR, GRADED)),
        [won(BOUGHT, count=6, unit=100), sold(T0 + 3 * HOUR + 10 * MINUTE, count=1, unit=999)],
        [crafted(CRAFTED, CRAFTED + MINUTE, CRAFTED + 2 * MINUTE)],
    )

    [flip] = craft_flips(db, CONFIG, MARKET, [], now=GRADED)

    grade = flip.grade
    assert (grade.graded_at, grade.units, grade.cost) == (GRADED, 3, 600)
    assert (grade.sold_units, grade.open_units) == (1, 2)
    assert grade.proceeds == pytest.approx(999 * 0.95)
    # The 2 left post at 999 and sell within the next Sale Horizon, a Bolt going each hour.
    assert grade.open_value == pytest.approx(2 * 999 * 0.95)
    assert grade.crafted_after == 20 * MINUTE
    assert grade.listed_after == T0 + 3 * HOUR - BOUGHT
    assert flip.expected == pytest.approx(flip.named.profit)


BANDAGE_RECIPE = 3275  # Linen Bandage: 1 Linen Cloth each


def test_bought_units_crafted_by_another_recipe_make_no_output_of_the_flip(db):
    # 2 of the 6 Linen go into Bandages, the other 4 into 2 Bolts.
    bandage = recipe(output=1251, reagents=((2589, 1),), recipe_id=BANDAGE_RECIPE)
    both = crafted(CRAFTED, CRAFTED + MINUTE) | {
        "crafts": [
            {"recipeID": BANDAGE_RECIPE, "at": CRAFTED, "quantity": 1},
            {"recipeID": BANDAGE_RECIPE, "at": CRAFTED + MINUTE, "quantity": 1},
            {"recipeID": BOLT_RECIPE, "at": CRAFTED + 2 * MINUTE, "quantity": 1},
            {"recipeID": BOLT_RECIPE, "at": CRAFTED + 3 * MINUTE, "quantity": 1},
        ]
    }
    both["professions"][TAILORING]["recipes"].append(bandage)
    load(db, bolt_market(*later_bolts(T0 + 3 * HOUR, GRADED)), [won(BOUGHT, 6, 100)], [both])

    [flip] = craft_flips(db, CONFIG, MARKET, [], now=GRADED)

    assert (flip.grade.units, flip.grade.cost, flip.grade.crafted_after) == (2, 400, 22 * MINUTE)
    assert flip.expected == pytest.approx(flip.named.profit * 2 / 3)


def test_a_flip_to_craft_none_of_whose_units_its_recipe_crafted_by_the_horizon_is_not_gradable(db):
    load(
        db,
        bolt_market(*later_bolts(T0 + 3 * HOUR, GRADED)),
        [won(BOUGHT, count=6, unit=100)],
        [crafted(GRADED + MINUTE)],
    )

    [flip] = craft_flips(db, CONFIG, MARKET, [], now=GRADED + HOUR)

    assert (flip.grade, flip.not_gradable) == (None, NotGradable.NOT_CRAFTED)


def test_a_flip_to_craft_whose_craft_used_looted_reagents_is_not_gradable(db):
    # 5 Linen bought for 3 Bolts: the last Bolt takes the 5th and a looted one, so #44
    # opens no Lot for it.
    load(
        db,
        bolt_market(*later_bolts(T0 + 3 * HOUR, GRADED)),
        [won(BOUGHT, count=5, unit=100)],
        [crafted(CRAFTED, CRAFTED + MINUTE, CRAFTED + 2 * MINUTE)],
    )

    [flip] = craft_flips(db, CONFIG, MARKET, [], now=GRADED)

    assert (flip.grade, flip.not_gradable) == (None, NotGradable.UNCOSTED)


def test_a_craft_from_held_reagents_only_is_no_flip_to_craft(db):
    load(
        db,
        bolt_market(*later_bolts(T0 + 3 * HOUR, GRADED)),
        reads=[crafted(CRAFTED, CRAFTED + MINUTE, CRAFTED + 2 * MINUTE)],
    )

    assert craft_flips(db, CONFIG, MARKET, [], now=GRADED) == []


SHIRT_RECIPE, SHIRT_KEY = 2394, "2576"  # a Shirt takes 2 Bolts


def test_a_sub_craft_chain_grades_only_the_top_crafts_output(db, tmp_path):
    # What T0 + 1 h named, frozen: a Shirt, Sub-crafting its Bolts from 4 bought Linen.
    # 6 Linen bought make 3 Bolts, and 2 of them a Shirt. The 3rd Bolt is a leftover.
    config = freezing(tmp_path)
    shirt = NamedCraft(
        SHIRT_KEY,
        SHIRT_RECIPE,
        "Kash-Patel",
        1,
        (NamedBuy(LINEN_KEY, 4, 100.0),),
        2000.0,
        900.0,
        None,
        3 * HOUR,
    )
    freeze_shown_crafts(config.grades_path, MARKET, T0 + HOUR, 3 * HOUR, [shirt])
    freeze_named(config.grades_path, MARKET, T0 + HOUR, NamedSet({LINEN_KEY: 100.0}))
    chain = crafted(CRAFTED, CRAFTED + MINUTE, CRAFTED + 2 * MINUTE)
    chain["crafts"].append({"recipeID": SHIRT_RECIPE, "at": CRAFTED + 3 * MINUTE, "quantity": 1})
    chain["professions"][TAILORING]["recipes"].append(
        recipe(output=2576, reagents=((2996, 2),), recipe_id=SHIRT_RECIPE)
    )
    load(db, bolt_market(*later_bolts(T0 + 3 * HOUR, GRADED)), [won(BOUGHT, 6, 100)], [chain])

    [flip] = craft_flips(db, config, MARKET, [], now=GRADED)

    assert flip.named == shirt
    assert (flip.grade.units, flip.grade.cost, flip.grade.crafted_after) == (1, 400, 20 * MINUTE)


# Flip margins so high nothing is ever a Flip.
NO_FLIPS = replace(CONFIG, flip_min_margin_share=100.0)


def test_flip_to_craft_rows_are_frozen_and_read_back_instead_of_worked_out_again(db, tmp_path):
    load(db, bolt_market(), [won(BOUGHT, count=6, unit=100)])
    [flip] = craft_flips(db, freezing(tmp_path), MARKET, [], now=T0 + 2 * HOUR)

    assert craft_flips(db, freezing(tmp_path, NO_FLIPS), MARKET, [], now=T0 + 2 * HOUR) == [flip]


def frozen_before_crafts(tmp_path, shown=(), named=None):
    """A grades.toml from before #114: T0 + 1 h's Flip to Sell rows and what it named to
    buy (by default Linen at up to 100) are frozen, but not its Flip to Craft rows."""
    config = freezing(tmp_path)
    named = NamedSet({LINEN_KEY: 100.0}) if named is None else named
    freeze_shown(config.grades_path, MARKET, T0 + HOUR, 3 * HOUR, list(shown))
    freeze_named(config.grades_path, MARKET, T0 + HOUR, named)
    return config


def test_an_old_scan_is_worked_out_for_crafts_when_a_named_purchase_matched_no_flip_to_sell(
    db, tmp_path
):
    config = frozen_before_crafts(tmp_path)
    load(db, bolt_market(), [won(BOUGHT, count=6, unit=100)])

    [flip] = craft_flips(db, config, MARKET, [], now=T0 + 2 * HOUR)

    assert load_frozen(config.grades_path, MARKET).shown_crafts == {T0 + HOUR: (flip.named,)}


@pytest.mark.parametrize(
    "shown, named",
    [
        # For Use: the Scan named no Linen.
        ((), NamedSet()),
        # It matched a Flip to Sell row.
        ((Named(LINEN_KEY, 6, 100, 150.0, 200.0, None, 3 * HOUR),), NamedSet({LINEN_KEY: 100.0})),
    ],
)
def test_an_old_scan_isnt_worked_out_for_crafts_for_a_purchase_a_flip_to_craft_cant_explain(
    db, tmp_path, shown, named
):
    config = frozen_before_crafts(tmp_path, shown, named)
    load(db, bolt_market(), [won(BOUGHT, count=6, unit=100)])

    assert craft_flips(db, config, MARKET, [], now=T0 + 2 * HOUR) == []
    assert load_frozen(config.grades_path, MARKET).shown_crafts == {}


def test_a_grade_is_frozen_only_once_a_scan_and_a_mailbox_read_at_its_grading_moment_are_in(
    db, tmp_path
):
    # The Sold mail from within the horizon is only read after the Scan at its end.
    config = freezing(tmp_path)
    load(
        db,
        bolt_market(*later_bolts(T0 + 3 * HOUR, GRADED)),
        [won(BOUGHT, count=6, unit=100, read_after=10 * MINUTE)],
        [crafted(CRAFTED, CRAFTED + MINUTE, CRAFTED + 2 * MINUTE)],
    )
    [first] = craft_flips(db, config, MARKET, [], now=GRADED)
    assert load_frozen(config.grades_path, MARKET).craft_flips == {}
    import_mailbox_reads(db, [sold(T0 + 3 * HOUR, count=1, unit=999)], Era.BETA, CONFIG)

    [flip] = craft_flips(db, config, MARKET, [], now=GRADED)

    assert (first.grade.sold_units, flip.grade.sold_units) == (0, 1)
    frozen = load_frozen(config.grades_path, MARKET).craft_flips
    assert frozen == {craft_flip_name(BOLT_RECIPE, T0 + HOUR): flip.grade}


def graded_craft(units, named_units, profit, cost, sold_units, gross, open_value, post_at):
    named = NamedCraft(
        BOLT_KEY, BOLT_RECIPE, "Kash-Patel", named_units, (), post_at, profit, None, 3 * HOUR
    )
    grade = FlipGrade(
        GRADED,
        units,
        cost,
        sold_units,
        gross,
        gross * 0.95,
        open_value,
        (0.5,) * sold_units,
        None,
        0,
        60,
    )
    return CraftFlip(BOLT_RECIPE, T0 + HOUR, named, BOUGHT, grade)


def test_the_record_of_graded_flips_to_craft_takes_them_together():
    # 2 of a row's 4 Bolts crafted, expected 2 x 500: 1 sold at 900 and 1 open at 800. A
    # row that Vendors all it makes has no Post at, so no price to compare.
    partial = graded_craft(2, 4, 2000.0, 400, 1, 900.0, 800.0, post_at=1000.0)
    vendored = graded_craft(1, 1, 100.0, 50, 0, 0.0, 120.0, post_at=None)
    skipped = CraftFlip(BOLT_RECIPE, T0, partial.named, BOUGHT, not_gradable=NotGradable.UNCOSTED)

    record = flip_record([partial, vendored, skipped])

    assert (record.graded, record.paid_off) == (2, 2)
    realized = (900 * 0.95 + 800 - 400) + (120 - 50)
    assert record.realized_over_expected == pytest.approx(realized / (1000 + 100))
    assert record.price_over_post_at == pytest.approx(0.9)
    assert record.sold_within == pytest.approx(1 / 3)


def test_crafted_after_counts_only_crafts_that_used_the_flips_units(db, tmp_path):
    # A Shirt here takes a Bolt and 2 Linen. The Bolt is held: crafted at T0 + 20 min
    # from Linen bought earlier. Only the Shirt craft used the Flip's 2 Linen.
    config = freezing(tmp_path)
    shirt = NamedCraft(
        SHIRT_KEY,
        SHIRT_RECIPE,
        "Kash-Patel",
        1,
        (NamedBuy(LINEN_KEY, 2, 100.0),),
        2000.0,
        900.0,
        None,
        3 * HOUR,
    )
    freeze_shown(config.grades_path, MARKET, T0, 3 * HOUR, [])
    freeze_shown_crafts(config.grades_path, MARKET, T0, 3 * HOUR, [])
    for at in (T0, T0 + HOUR):
        freeze_named(config.grades_path, MARKET, at, NamedSet({LINEN_KEY: 100.0}))
    freeze_shown_crafts(config.grades_path, MARKET, T0 + HOUR, 3 * HOUR, [shirt])
    shirt_craft = character_read(at=CRAFTED + MINUTE, crafts=[(SHIRT_RECIPE, CRAFTED)])
    shirt_craft["professions"][TAILORING]["recipes"].append(
        recipe(output=2576, reagents=((2996, 1), (2589, 2)), recipe_id=SHIRT_RECIPE)
    )
    load(
        db,
        bolt_market(*later_bolts(T0 + 3 * HOUR, GRADED)),
        [won(T0 + 10 * MINUTE, 2, 100), won(BOUGHT, 2, 100)],
        [crafted(T0 + 20 * MINUTE), shirt_craft],
    )

    [flip] = craft_flips(db, config, MARKET, [], now=GRADED)

    assert (flip.grade.units, flip.grade.crafted_after) == (1, 20 * MINUTE)
