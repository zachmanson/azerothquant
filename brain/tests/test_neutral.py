"""Neutral-to-home Flips (#231): at a Neutral Auction House, a Shopping List of Listings
there worth carrying home, every exit valued at the home Market."""

from dataclasses import replace
from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.history import Market, import_character_reads, import_scans, open_history
from brain.recommend import Action, neutral_lists

T0 = 1_790_000_000
HOUR = 3600
REALM = "Classic Beta PvP"
HOME = Market(realm=REALM, faction="Alliance", era=Era.BETA)
NEUTRAL = Market(realm=REALM, faction="Neutral", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
LINEN_KEY = "2589"

# As in test_flips: a 3 hour Sale Horizon and no priors, so hourly Scans make a Sell Rate
# taken at its word, and the risk caps off, so a row is sized by the gold alone.
CONFIG = replace(
    Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),)),
    sale_horizon_seconds=3 * HOUR,
    sell_rate_prior_hours_holdings=0,
    sell_rate_prior_hours_flips=0,
    sale_size_prior_events_holdings=0,
    sale_size_prior_events_flips=0,
    flip_min_sale_events=1,
    risk_caps=False,
    row_min_profit_share=0.0,
    row_min_profit_copper=0,
    row_min_profit_per_click=0,
)


def scan(at, *rows, faction="Alliance"):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": faction,
        "droppedRows": 0,
        "listings": list(rows),
        "vendorPrices": {},
    }


BOLT = "item:2996::::::::20:1490"
BOLT_KEY = "2996"
TAILORING = 197


def row(quantity=1, unit=100, item=LINEN):
    return {"itemString": item, "quantity": quantity, "buyout": quantity * unit, "timeLeft": 4}


def character_read(money=10_000, faction="Alliance", character="Kash-Patel", recipes=(), bags=()):
    read = {
        "readAt": T0,
        "realm": REALM,
        "character": character,
        "faction": faction,
        "money": money,
        "bags": list(bags),
        "vendorPrices": {2589: 10},
    }
    if recipes:
        read["professions"] = {
            TAILORING: {"readAt": T0, "professionID": TAILORING, "recipes": list(recipes)}
        }
        read["professionList"] = [{"professionID": TAILORING}]
    return read


BOLT_RECIPE = {
    "recipeID": 2963,
    "outputItemID": 2996,
    "quantityMin": 1,
    "quantityMax": 1,
    "bindType": 0,
    "reagents": [{"itemID": 2589, "quantity": 2, "reagentType": 1}],
}


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def load(db, scans, reads=None):
    import_scans(db, list(scans), Era.BETA, CONFIG)
    import_character_reads(db, reads or [character_read()], Era.BETA, CONFIG)


def home_linen_market():
    """Home: 2 Linen at 1000 sell each hour from T0, so a Flip posts them at 999."""
    return [
        scan(T0, row(quantity=20, unit=1000)),
        scan(T0 + HOUR, row(quantity=18, unit=1000)),
        scan(T0 + 2 * HOUR, row(quantity=16, unit=1000)),
    ]


def test_a_neutral_listing_under_homes_price_is_bought_there_and_posted_under_homes_cheapest(db):
    load(db, [*home_linen_market(), scan(T0 + 2 * HOUR + 600, row(5, 200), faction="Neutral")])

    [neutral] = neutral_lists(db, CONFIG, [])

    assert (neutral.neutral, neutral.neutral_as_of) == (NEUTRAL, T0 + 2 * HOUR + 600)
    assert (neutral.home.market, neutral.home.as_of) == (HOME, T0 + 2 * HOUR)
    [flip] = neutral.home.shopping_list
    assert (flip.item_key, flip.action, flip.quantity, flip.cost) == (
        LINEN_KEY,
        Action.SELL,
        5,
        1000,
    )
    assert flip.post_at == 999


def test_dearer_neutral_listings_dont_set_the_post_price_and_the_home_cut_is_charged(db):
    """At home, the 200s bought would post under the 400s. At the Neutral house they're
    no rival: the post stays under home's cheapest, after home's 5% cut, not Neutral's."""
    neutral = scan(T0 + 2 * HOUR + 600, row(5, 200), row(3, 400), faction="Neutral")
    load(db, [*home_linen_market(), neutral])

    [flip] = neutral_lists(db, CONFIG, [])[0].home.shopping_list

    assert flip.post_at == 999
    # 2 an hour sell at 999 over the 3 hour Sale Horizon: 6 units, the 5 at 200 and one 400.
    assert (flip.quantity, flip.cost) == (6, 5 * 200 + 400)
    assert flip.profit == pytest.approx(6 * 999 * 0.95 - (5 * 200 + 400))


def test_each_faction_with_characters_gets_its_own_neutral_list_valued_at_its_own_home(db):
    """Horde's home Linen sells at 500, so it posts the Neutral 200s at 499."""
    horde_home = [
        scan(T0, row(quantity=20, unit=500), faction="Horde"),
        scan(T0 + HOUR, row(quantity=18, unit=500), faction="Horde"),
    ]
    reads = [character_read(), character_read(faction="Horde", character="Grob-Zug")]
    neutral = scan(T0 + 2 * HOUR + 600, row(5, 200), faction="Neutral")
    load(db, [*home_linen_market(), *horde_home, neutral], reads)

    lists = {n.home.market.faction: n.home for n in neutral_lists(db, CONFIG, [])}

    assert sorted(lists) == ["Alliance", "Horde"]
    assert lists["Alliance"].shopping_list[0].post_at == 999
    assert lists["Horde"].shopping_list[0].post_at == 499
    assert lists["Horde"].as_of == T0 + HOUR


def test_a_faction_without_a_neutral_scan_on_its_realm_gets_no_neutral_list(db):
    load(db, home_linen_market())

    assert neutral_lists(db, CONFIG, []) == []


def test_a_flip_to_craft_buys_its_reagents_at_the_neutral_house_and_sells_the_output_at_home(
    db,
):
    """Home has a Bolt selling at 1000 an hour and no Linen up: only the Neutral Linen
    makes a Flip to Craft."""
    home = [scan(T0 + n * HOUR, row(quantity=6 - n, unit=1000, item=BOLT)) for n in range(3)]
    neutral = scan(T0 + 2 * HOUR + 600, row(6, 100), faction="Neutral")
    load(db, [*home, neutral], [character_read(recipes=[BOLT_RECIPE])])

    [craft] = neutral_lists(db, CONFIG, [])[0].home.shopping_list

    assert (craft.item_key, craft.action, craft.post_at) == (BOLT_KEY, Action.CRAFT, 999)
    assert {(b.item_key, b.max_unit_price) for b in craft.buys} == {(LINEN_KEY, 100)}


LINEN_LINK = "|cffffffff|Hitem:2589::::::::20:1490:::::::::|h[Linen Cloth]|h|r"


def test_held_units_of_an_item_not_up_at_the_neutral_house_dont_stop_the_list(db):
    """Held Linen is valued at home, where it's up; the Neutral house has only Bolts."""
    held = {"bag": 0, "slot": 1, "link": LINEN_LINK, "count": 3, "isBound": False}
    neutral = scan(T0 + 2 * HOUR + 600, row(1, 50, item=BOLT), faction="Neutral")
    load(db, [*home_linen_market(), neutral], [character_read(bags=[held])])

    [n] = neutral_lists(db, CONFIG, [])

    assert n.home.holdings == []


BOLT_LINK = "|cffffffff|Hitem:2996::::::::20:1490:::::::::|h[Bolt of Linen Cloth]|h|r"
BAG = "item:4238::::::::20:1490"
BAG_RECIPE = {
    "recipeID": 3755,
    "outputItemID": 4238,
    "quantityMin": 1,
    "quantityMax": 1,
    "bindType": 0,
    "reagents": [{"itemID": 2996, "quantity": 2, "reagentType": 1}],
}


def test_held_reagents_not_up_at_the_neutral_house_are_valued_at_home(db):
    """A Flip to Craft values the held Bolts it uses at home, where they're up: the
    Neutral house has only Linen. It was a KeyError for every Neutral list on Live."""
    home = [
        scan(
            T0 + n * HOUR,
            row(quantity=6 - n, unit=5000, item=BAG),
            row(quantity=6 - n, unit=1000, item=BOLT),
        )
        for n in range(3)
    ]
    neutral = scan(T0 + 2 * HOUR + 600, row(6, 100), faction="Neutral")
    held = {"bag": 0, "slot": 1, "link": BOLT_LINK, "count": 2, "isBound": False}
    reads = [character_read(recipes=[BOLT_RECIPE, BAG_RECIPE], bags=[held])]
    load(db, [*home, neutral], reads)

    assert neutral_lists(db, CONFIG, [])[0].home.shopping_list


def test_held_reagents_a_neutral_flip_to_craft_uses_up_are_valued_at_homes_wait_price(db):
    """#234: home has a Bolt at 300 that a Flip to Sell would buy, so the held Bolt Waits
    to post at 999 behind it rather than dumping at 299. A Neutral Flip to Craft that uses
    it up for a Bag gives up what it would bring at home: 999 after the cut, not 299."""
    home = [
        scan(
            T0 + n * HOUR,
            row(quantity=6 - n, unit=5000, item=BAG),
            row(quantity=1, unit=300, item=BOLT),
            row(quantity=6 - n, unit=1000, item=BOLT),
        )
        for n in range(3)
    ]
    neutral = scan(T0 + 2 * HOUR + 600, row(6, 100), faction="Neutral")
    held = {"bag": 0, "slot": 1, "link": BOLT_LINK, "count": 1, "isBound": False}
    reads = [character_read(recipes=[BOLT_RECIPE, BAG_RECIPE], bags=[held])]
    load(db, [*home, neutral], reads)

    [craft] = neutral_lists(db, CONFIG, [])[0].home.shopping_list

    assert (craft.item_key, craft.quantity, craft.cost) == ("4238", 2, 600)
    # 2 Bags posted at 4999, less the 6 Linen and the held Bolt's 999 after home's cut.
    assert craft.profit == pytest.approx(2 * 4999 * 0.95 - 600 - 999 * 0.95)
