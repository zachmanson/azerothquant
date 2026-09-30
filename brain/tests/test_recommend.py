import math
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.history import (
    Market,
    import_character_reads,
    import_mailbox_reads,
    import_scans,
    open_history,
)
from brain.lots import Held, start_of
from brain.predictions import Prediction
from brain.recommend import (
    Action,
    BetaRoom,
    Blocked,
    BlockReason,
    BuyUnder,
    ChainNode,
    CharacterHolding,
    Check,
    Grade,
    NodeKind,
    ReagentBuy,
    ReagentUse,
    Row,
    SubCraft,
    _Caps,
    _HoldBuy,
    _spend_on_predictions,
    grades,
    held_at_writing,
    per_day,
    recommend,
    recommend_market,
    sellable_units,
)
from brain.sell_rate import SellRate

T0 = 1_790_000_000
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR
REALM = "Classic Beta PvP"
MARKET = Market(realm=REALM, faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
LINEN_LINK = "|cffffffff|Hitem:2589::::::::20:1490:::::::::|h[Linen Cloth]|h|r"
LINEN_KEY = "2589"
ORE = "item:2770::::::::20:1490"
ORE_KEY = "2770"
GOLD = 100 * 100 * 100  # copper
TAILORING = 197

# Default knobs (5% faction cut, 20% and 1 silver Flip margin), except a Sale Horizon of
# 3 hours, so a Sell Rate from a single short Observation Window is small enough to cap,
# and no Sell Rate Prior, Sale Size Prior or minimum of Sale Events for a Flip, so these
# tests take the raw rate at its word.
DEFAULTS = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))
CONFIG = replace(
    DEFAULTS,
    sale_horizon_seconds=3 * HOUR,
    sell_rate_prior_hours_holdings=0,
    sell_rate_prior_hours_flips=0,
    sale_size_prior_events_holdings=0,
    sale_size_prior_events_flips=0,
    flip_min_sale_events=1,
)


def scan(at, *rows, vendor_prices=None, faction="Alliance"):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": faction,
        "droppedRows": 0,
        "listings": list(rows),
        "vendorPrices": vendor_prices or {},
    }


def row(item=LINEN, quantity=1, unit=100, time_left=4, own=False):
    listing = {
        "itemString": item,
        "quantity": quantity,
        "buyout": quantity * unit,
        "timeLeft": time_left,
    }
    if own:
        listing["own"] = True
    return listing


def item(link=LINEN_LINK, count=1, bound=False):
    return {"bag": 0, "slot": 1, "link": link, "count": count, "isBound": bound}


def character_read(
    *bags,
    character="Kash-Patel",
    faction="Alliance",
    money=0,
    vendor_prices=None,
    at=T0,
    recipes=None,
    merchant_costs=None,
    professions=(TAILORING,),
    bank=None,
    budget=None,
    days_to_sell=None,
):
    read = {
        "readAt": at,
        "realm": REALM,
        "character": character,
        "faction": faction,
        "money": money,
        "bags": list(bags),
        "vendorPrices": vendor_prices or {},
    }
    if recipes is not None:
        # The same recipes in each profession's window, as some of Forever's are.
        read["professions"] = {
            p: {"readAt": at, "professionID": p, "recipes": list(recipes)} for p in professions
        }
        read["professionList"] = [{"professionID": p} for p in professions]
    if merchant_costs is not None:
        read["merchantCosts"] = merchant_costs
    if bank is not None:
        read |= {"bankReadAt": at, "bank": list(bank)}
    if budget is not None:
        read["budget"] = budget
    if days_to_sell is not None:
        read["daysToSell"] = days_to_sell
    return read


BOLT = "item:2996::::::::20:1490"
BOLT_KEY = "2996"
BOLT_LINK = "|cffffffff|Hitem:2996::::::::20:1490:::::::::|h[Bolt of Linen Cloth]|h|r"
THREAD_KEY = "2320"


def recipe(recipe_id=2963, output=2996, reagents=((2589, 2),), quantity=1, bind_type=0, **fields):
    """A Known Recipe as the Addon records it, with Basic reagents only."""
    return {
        "recipeID": recipe_id,
        "outputItemID": output,
        "quantityMin": quantity,
        "quantityMax": quantity,
        "bindType": bind_type,
        "reagents": [
            {"itemID": item_id, "quantity": n, "reagentType": 1} for item_id, n in reagents
        ],
    } | fields


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def other_db():
    """A second History, for a run beside the one in `db` (#67)."""
    conn = open_history(":memory:")
    yield conn
    conn.close()


def run(db, scans=(), reads=(), config=CONFIG, predictions=(), mailbox_reads=()):
    import_scans(db, list(scans), Era.BETA, config)
    import_mailbox_reads(db, list(mailbox_reads), Era.BETA, config)
    import_character_reads(db, list(reads), Era.BETA, config)
    return {r.market: r for r in recommend(db, config, list(predictions))}


def selling_two_linen_an_hour(*latest_rows, unit=100, sale_events=1):
    """Scans an hour apart in which 2 Linen sold each hour, as `sale_events` Sale Events:
    48 a day, so 6 in the 3 h horizon. Fair Value in the latest Scan is `unit`, before
    any `latest_rows` are added to it."""
    return [
        scan(T0 + n * HOUR, row(quantity=20 - 2 * n, unit=unit)) for n in range(sale_events)
    ] + [scan(T0 + sale_events * HOUR, row(quantity=20 - 2 * sale_events, unit=unit), *latest_rows)]


# --- Holdings: Vendor vs Sell ---


def test_units_that_sell_within_the_horizon_are_sold_and_the_rest_vendored(db):
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), vendor_prices={2589: 10})],
    )

    assert result[MARKET].holdings == [
        # #64: posted 1 copper under the cheapest other Listing, the 100s, like a Flip.
        Row(
            LINEN_KEY,
            Action.SELL,
            6,
            price=99,
            profit=pytest.approx(6 * 99 * 0.95),
            margin=pytest.approx(99 * 0.95 - 10),
            sale_events=1,
        ),
        Row(LINEN_KEY, Action.VENDOR, 4, price=10, profit=40),
    ]


def test_held_units_are_never_sold_above_what_a_merchant_charges(db):
    # #63: Fair Value is 100, but a merchant sells Linen for 80.
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), vendor_prices={2589: 10}, merchant_costs={2589: 80})],
    )

    assert result[MARKET].holdings == [
        Row(LINEN_KEY, Action.SELL, 6, price=80, profit=6 * 76, margin=66, sale_events=1),
        Row(LINEN_KEY, Action.VENDOR, 4, price=10, profit=40),
    ]


def test_held_units_match_an_own_listing_under_the_cheapest_other_one(db):
    # #64: the player already has one up at 90, under the 100s, so held units match it.
    # Fair Value would be (90 + 100 + 100) / 3.
    result = run(
        db,
        selling_two_linen_an_hour(row(unit=90, own=True)),
        [character_read(item(count=2), vendor_prices={2589: 10})],
    )

    [sell] = result[MARKET].holdings
    assert (sell.action, sell.quantity, sell.price) == (Action.SELL, 2, 90)
    assert sell.profit == pytest.approx(2 * 90 * 0.95)


def test_held_units_are_never_sold_above_the_dearest_sale(db):
    # #64, as for Flips (#41): a lone 845 is all that's on sale, but the only sale was at
    # 100. Fair Value would be 845.
    result = run(
        db,
        [
            scan(T0, row(unit=100), row(unit=845)),
            scan(T0 + HOUR, row(unit=845)),
        ],
        [character_read(item(), vendor_prices={2589: 10})],
    )

    [sell] = result[MARKET].holdings
    assert (sell.action, sell.price) == (Action.SELL, 100)
    assert sell.profit == pytest.approx(100 * 0.95)


def test_held_units_are_valued_with_nothing_on_the_shopping_list_bought(db):
    # #86: the two 700s are a Flip to Sell, posted at 999 under the 1000s once bought. But
    # the Shopping List's options are alternatives, so held units undercut the 700s still
    # there (#64), not what's left if the Flip is bought (ADR-0010, superseded).
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=2, unit=700), unit=1000),
        [character_read(item(count=3), money=GOLD, vendor_prices={2589: 10})],
    )

    [sell] = result[MARKET].holdings
    assert (sell.action, sell.quantity, sell.price) == (Action.SELL, 3, 699)
    [flip] = result[MARKET].shopping_list
    assert (flip.quantity, flip.post_at) == (2, 999)


def test_a_flip_the_gold_cant_buy_whole_buys_the_best_run_that_fits(db):
    # #68, ADR-0011: all 5 would post under the 3g wall, but the gold buys only the 3 at
    # 1g, which still clear the margin under the 1g 50s. The Flip posts at 1g 49s 99c.
    result = run(
        db,
        selling_two_linen_an_hour(
            row(quantity=3, unit=10000), row(quantity=2, unit=15000), unit=30000
        ),
        [character_read(item(), money=30000, vendor_prices={2589: 10})],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.quantity, flip.post_at) == (3, 14999)
    assert flip.profit == pytest.approx(3 * (14999 * 0.95 - 10000))


def test_a_flip_with_no_run_the_gold_covers_that_clears_the_margin_is_skipped(db):
    # #68, ADR-0011: all 5 clear the margin under the 3g wall, but the gold buys only the
    # 3 at 1g, and posted under the 1g 10s they'd make 4s 49c each, short of the 20%.
    result = run(
        db,
        selling_two_linen_an_hour(
            row(quantity=3, unit=10000), row(quantity=2, unit=11000), unit=30000
        ),
        [character_read(item(), money=30000, vendor_prices={2589: 10})],
    )

    assert result[MARKET].shopping_list == []


def test_a_flip_to_sell_is_ranked_whole_so_one_the_gold_cant_finish_leaves_it_to_others(db):
    # #70: each 1g Linen makes 1.85 per gold if all 5 are bought and posted under the 3g
    # wall, but the 3g the player has buys only the 3 at 1g, which clear no margin under
    # the 1g 10s. Ranked whole, Linen is skipped and the Ore (0.9 per gold) gets the gold.
    result = run(
        db,
        [
            scan(T0, row(quantity=20, unit=30000), row(ORE, quantity=20, unit=1000)),
            scan(
                T0 + HOUR,
                row(quantity=18, unit=30000),
                row(quantity=3, unit=10000),
                row(quantity=2, unit=11000),
                row(ORE, quantity=18, unit=1000),
                row(ORE, quantity=1, unit=500),
            ),
        ],
        [character_read(money=30000, vendor_prices={2589: 10})],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.item_key, flip.action, flip.quantity, flip.post_at) == (
        ORE_KEY,
        Action.SELL,
        1,
        999,
    )
    assert flip.profit == pytest.approx(999 * 0.95 - 500)


def test_everything_is_vendored_when_a_vendor_pays_more_than_a_sale_brings_in(db):
    # Fair Value 100 less the 5% cut is 95.
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), vendor_prices={2589: 96})],
    )

    assert result[MARKET].holdings == [Row(LINEN_KEY, Action.VENDOR, 10, price=96, profit=960)]


@pytest.mark.parametrize(
    "scans",
    [
        # Too far apart to be an Observation Window: no Sell Rate at all.
        [scan(T0, row(quantity=20)), scan(T0 + 3 * HOUR, row(quantity=18))],
        # A window, but nothing sold in it: too thin to call the item unsellable.
        [scan(T0, row(quantity=20)), scan(T0 + HOUR, row(quantity=20))],
        # Sold before, but none left to price it by.
        [scan(T0, row(quantity=2)), scan(T0 + HOUR, row(quantity=1)), scan(T0 + 2 * HOUR)],
    ],
    ids=["no windows", "no sales", "no fair value"],
)
def test_without_sell_rate_evidence_or_a_fair_value_there_is_no_data_not_a_sell(db, scans):
    result = run(db, scans, [character_read(item(count=10), vendor_prices={2589: 10})])

    assert result[MARKET].holdings == [Row(LINEN_KEY, None, 10, note="no data")]


def test_bound_units_are_always_vendored(db):
    bound = "|cff1eff00|Hitem:5000::::::::20:1490:::::::::|h[Bound Boots]|h|r"
    result = run(
        db,
        selling_two_linen_an_hour(),
        [
            character_read(
                item(count=4),
                item(count=3, bound=True),
                item(bound, bound=True),
                vendor_prices={2589: 10, 5000: 250},
            )
        ],
    )

    assert result[MARKET].holdings == [
        Row(
            LINEN_KEY,
            Action.SELL,
            4,
            price=99,
            profit=pytest.approx(4 * 99 * 0.95),
            margin=pytest.approx(99 * 0.95 - 10),
            sale_events=1,
        ),
        Row("5000", Action.VENDOR, 1, price=250, profit=250),
        Row(LINEN_KEY, Action.VENDOR, 3, price=10, profit=30),
    ]


def test_an_item_with_no_vendor_price_is_shown_as_such(db):
    # Selling is the only exit whose value is known, so what sells is still Sold.
    result = run(db, selling_two_linen_an_hour(), [character_read(item(count=10))])

    assert result[MARKET].holdings == [
        Row(
            LINEN_KEY,
            Action.SELL,
            6,
            price=99,
            profit=pytest.approx(6 * 99 * 0.95),
            sale_events=1,
        ),
        Row(LINEN_KEY, Action.VENDOR, 4, note="no Vendor Price"),
    ]


def test_holdings_are_pooled_across_the_characters_in_a_market(db):
    # The horizon caps what the Market can take, not what each Character can sell.
    result = run(
        db,
        selling_two_linen_an_hour(),
        [
            character_read(item(count=5), vendor_prices={2589: 10}),
            character_read(item(count=5), character="Alt-One"),
            # The other faction trades in another Market, which hasn't been Scanned.
            character_read(item(count=50), character="Horde-Alt", faction="Horde"),
        ],
    )

    assert list(result) == [MARKET]
    assert result[MARKET].holdings == [
        Row(
            LINEN_KEY,
            Action.SELL,
            6,
            price=99,
            profit=pytest.approx(6 * 99 * 0.95),
            margin=pytest.approx(99 * 0.95 - 10),
            sale_events=1,
        ),
        Row(LINEN_KEY, Action.VENDOR, 4, price=10, profit=40),
    ]


def test_the_market_says_which_characters_hold_each_item_key(db):
    # Kash-Patel's bank is from an older Read: the latest one never opened it.
    result = run(
        db,
        selling_two_linen_an_hour(),
        [
            character_read(bank=[item(count=30)], at=T0 - DAY),
            character_read(item(count=12), item(count=5, bound=True), at=T0),
            character_read(item(ORE_LINK, count=3), item(count=4), character="Alt-One"),
            character_read(item(count=50), character="Horde-Alt", faction="Horde"),
        ],
    )

    assert result[MARKET].held == {
        LINEN_KEY: [
            CharacterHolding("Alt-One", bags=4),
            CharacterHolding("Kash-Patel", bags=17, bank=30, bound=5),
        ],
        ORE_KEY: [CharacterHolding("Alt-One", bags=3)],
    }


# --- Sibling suffixes (#58, ADR-0022) ---

MONKEY = "item:9768::::::::20:1490::1:1:12743"
MONKEY_KEY = "9768:12743"
MONKEY_LINK = (
    "|cff1eff00|Hitem:9768::::::::20:1490::1:1:12743::::::|h[Scouting Trousers of the Monkey]|h|r"
)
EAGLE = "item:9768::::::::20:1490::1:1:12750"
EAGLE_KEY = "9768:12750"


def test_a_held_suffix_sells_on_its_siblings_sale_events(db):
    # The Monkey has never sold, but an Eagle sold at 500, at or above the Monkey's post
    # price of 399. It counts at half a Sale Event: 0.5 units an hour, 1 in the 3 h horizon.
    result = run(
        db,
        [
            scan(T0, row(MONKEY, unit=400), row(EAGLE, unit=500)),
            scan(T0 + HOUR, row(MONKEY, unit=400)),
        ],
        [character_read(item(MONKEY_LINK, count=3), vendor_prices={9768: 10})],
    )

    assert result[MARKET].holdings == [
        Row(
            MONKEY_KEY,
            Action.SELL,
            1,
            price=399,
            profit=pytest.approx(399 * 0.95),
            margin=pytest.approx(399 * 0.95 - 10),
            sale_events=0,
            sibling_sales=1,
        ),
        Row(MONKEY_KEY, Action.VENDOR, 2, price=10, profit=20),
    ]


def test_sibling_sale_events_below_the_post_price_are_left_out(db):
    # The Monkey sold once at 450 and posts at 399. The Eagle sold at 300, under that:
    # buyers of a cheap Eagle say nothing about a Monkey at 399. 1 unit an hour, 3 in 3 h.
    result = run(
        db,
        [
            scan(T0, row(MONKEY, unit=400), row(MONKEY, unit=450), row(EAGLE, unit=300)),
            scan(T0 + HOUR, row(MONKEY, unit=400)),
        ],
        [character_read(item(MONKEY_LINK, count=5), vendor_prices={9768: 10})],
    )

    [sell, vendor] = result[MARKET].holdings
    assert (sell.action, sell.quantity, sell.price, sell.sibling_sales) == (
        Action.SELL,
        3,
        399,
        None,
    )
    assert (vendor.action, vendor.quantity) == (Action.VENDOR, 2)


def test_held_units_are_never_sold_above_the_dearest_own_or_sibling_sale(db):
    # #41's cap: the Monkey's own sale was at 100, but an Eagle sold at 500, so the Monkey
    # posts at 399, under the 400, and not at 100.
    result = run(
        db,
        [
            scan(T0, row(MONKEY, unit=400), row(MONKEY, unit=100), row(EAGLE, unit=500)),
            scan(T0 + HOUR, row(MONKEY, unit=400)),
        ],
        [character_read(item(MONKEY_LINK), vendor_prices={9768: 10})],
    )

    [sell] = result[MARKET].holdings
    assert (sell.action, sell.price, sell.sale_events, sell.sibling_sales) == (
        Action.SELL,
        399,
        1,
        1,
    )


def test_no_suffix_pool_weight_leaves_held_units_to_their_own_sale_events(db):
    result = run(
        db,
        [
            scan(T0, row(MONKEY, unit=400), row(EAGLE, unit=500)),
            scan(T0 + HOUR, row(MONKEY, unit=400)),
        ],
        [character_read(item(MONKEY_LINK, count=3), vendor_prices={9768: 10})],
        config=replace(CONFIG, suffix_pool_weight=0),
    )

    assert result[MARKET].holdings == [Row(MONKEY_KEY, None, 3, note="no data")]


def test_a_held_suffix_borrows_no_price_or_fair_value_from_its_siblings(db):
    # No Monkey is on sale to price against or take a Fair Value from, only Eagles, so
    # the Eagle's sale doesn't make the Monkey sellable.
    result = run(
        db,
        [
            scan(T0, row(EAGLE, unit=500), row(EAGLE, unit=450)),
            scan(T0 + HOUR, row(EAGLE, unit=450)),
        ],
        [character_read(item(MONKEY_LINK, count=3), vendor_prices={9768: 10})],
    )

    assert result[MARKET].holdings == [Row(MONKEY_KEY, None, 3, note="no data")]


def test_flips_and_buy_under_keep_their_own_item_keys_sale_events(db):
    # The held Monkeys Sell on the Eagle's sale, but a Monkey on sale at 50 isn't a Flip
    # to Sell, nor worth a Sell Buy Under: the Monkey itself has never sold.
    result = run(
        db,
        [
            scan(T0, row(MONKEY, unit=400), row(MONKEY, unit=50), row(EAGLE, unit=500)),
            scan(T0 + HOUR, row(MONKEY, unit=400), row(MONKEY, unit=50)),
        ],
        [character_read(item(MONKEY_LINK, count=3), vendor_prices={9768: 10}, money=GOLD)],
    )

    market = result[MARKET]
    assert [(r.action, r.sibling_sales) for r in market.holdings] == [
        (Action.SELL, 1),
        (Action.VENDOR, None),
    ]
    assert market.shopping_list == []
    assert [b for b in market.buy_under if b.way is Action.SELL] == []


# --- Shopping List: Flips ---


def test_listings_under_the_vendor_price_are_bought_to_vendor(db):
    result = run(
        db,
        [scan(T0, row(ORE, quantity=3, unit=5), row(ORE, unit=6), row(ORE, unit=10))],
        [character_read(money=GOLD, vendor_prices={2770: 10})],
    )

    # Any quantity: a vendor takes them all. The price is the most to pay per unit.
    assert result[MARKET].shopping_list == [
        Row(ORE_KEY, Action.VENDOR, 4, price=6, profit=3 * 5 + 4, cost=3 * 5 + 6)
    ]


def test_resale_is_priced_without_the_units_being_bought(db):
    # 20 Linen: Fair Value averages the cheapest 3, (700 + 700 + 1000) / 3 = 800. Resold at
    # that, the 700s clear only 60 after the cut, under the 1 silver minimum. But once
    # they're bought the cheapest Listing left is 1000, so they're posted at 999.
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=2, unit=700), unit=1000),
        [character_read(money=GOLD)],
    )

    assert result[MARKET].shopping_list == [
        Row(
            LINEN_KEY,
            Action.SELL,
            2,
            price=700,
            profit=pytest.approx(2 * (999 * 0.95 - 700)),
            post_at=999,
            sale_events=1,
            cost=1400,
        )
    ]


def test_a_flip_to_sell_posts_just_under_the_cheapest_listing_left(db):
    # #62: 3 at 1g and a wall at 1g 95s. Once the 3 are bought, the 1g 95s is the cheapest
    # Listing left, so they're posted 1 copper under it to sell first.
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=3, unit=10000), unit=19500),
        [character_read(money=GOLD)],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.quantity, flip.price, flip.post_at) == (3, 10000, 19499)
    assert flip.profit == pytest.approx(3 * (19499 * 0.95 - 10000))


def test_a_flip_to_sell_buys_through_a_listing_that_would_undercut_it(db):
    # #62: posted under the 1g 05s, the 1g units would lose money, so a buy loop that
    # stopped there would buy nothing. Buying the 1g 05s too leaves the 1g 95s wall, and
    # all 4 are posted under it.
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=3, unit=10000), row(unit=10500), unit=19500),
        [character_read(money=GOLD)],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.quantity, flip.price, flip.post_at) == (4, 10500, 19499)
    assert flip.profit == pytest.approx(3 * (19499 * 0.95 - 10000) + 19499 * 0.95 - 10500)


def test_a_flip_to_sell_matches_an_own_listing_under_the_cheapest_other_one(db):
    # The player already has one up at 900, under the 1000s: the 700s match it rather than
    # undercut the player's own Listing.
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=2, unit=700), row(unit=900, own=True), unit=1000),
        [character_read(money=GOLD)],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.quantity, flip.post_at) == (2, 900)
    assert flip.profit == pytest.approx(2 * (900 * 0.95 - 700))


@pytest.mark.parametrize(
    ("fair", "unit", "bought"),
    [
        # Posted at 999, resale 949.05: 158.05 over 791 is under 20% of it; 159.05 over
        # 790 isn't.
        (1000, 790, True),
        (1000, 791, False),
        # Posted at 399, resale 379.05: 100.05 over 279 clears 1 silver; 99.05 over 280
        # doesn't.
        (400, 279, True),
        (400, 280, False),
    ],
)
def test_a_flip_to_sell_must_clear_20_percent_and_1_silver(db, fair, unit, bought):
    result = run(
        db, selling_two_linen_an_hour(row(unit=unit), unit=fair), [character_read(money=GOLD)]
    )

    assert bool(result[MARKET].shopping_list) == bought


@pytest.mark.parametrize(("sale_events", "action"), [(2, Action.VENDOR), (3, Action.SELL)])
def test_a_flip_to_sell_needs_the_minimum_of_sale_events_or_is_vendored(db, sale_events, action):
    # #57: two Sale Events can be one seller cancelling, so the 500 isn't resold at 950.
    # A vendor still pays 600 for it.
    result = run(
        db,
        selling_two_linen_an_hour(row(unit=500), unit=1000, sale_events=sale_events),
        [character_read(money=GOLD, vendor_prices={2589: 600})],
        config=replace(CONFIG, flip_min_sale_events=3),
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.price) == (action, 500)


def test_a_flip_to_sell_buys_no_more_than_sells_within_the_horizon(db):
    # 6 sell within the horizon, so the 700s aren't bought and the 500s are posted under them.
    result = run(
        db,
        [
            scan(T0, row(quantity=200, unit=1000)),
            scan(
                T0 + HOUR,
                row(quantity=198, unit=1000),
                row(quantity=6, unit=500),
                row(quantity=4, unit=700),
            ),
        ],
        [character_read(money=GOLD)],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity, flip.price) == (Action.SELL, 6, 500)


def test_held_units_that_fill_the_horizon_leave_no_flip_to_sell(db):
    # #67: 6 sell within the horizon and 6 are held, so the cheap 500s aren't bought.
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=6, unit=500), unit=1000),
        [character_read(item(count=6), money=GOLD)],
    )

    assert result[MARKET].shopping_list == []


def test_a_flip_to_sell_buys_only_the_room_held_units_leave(db):
    # #67: 6 sell within the horizon and 2 are held, so only the 500s are bought, not the
    # 700s too. Posted at 699 they still clear the margin.
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=4, unit=500), row(quantity=2, unit=700), unit=1000),
        [character_read(item(count=2), money=GOLD)],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity, flip.price, flip.post_at) == (Action.SELL, 4, 500, 699)


def test_bound_held_units_leave_the_room_to_flips(db):
    # #67: bound units can't be sold, so all 6 of the 500s are bought.
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=6, unit=500), unit=1000),
        [character_read(item(count=6, bound=True), money=GOLD)],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity) == (Action.SELL, 6)


def test_a_flip_to_sell_is_never_resold_above_the_dearest_sale(db):
    # #41: a lone 845 is all that's left once the 300 is bought, but the only sale was at
    # 100. Resold at 100 less the cut, the 300 is a loss.
    result = run(
        db,
        [
            scan(T0, row(unit=100), row(unit=845)),
            scan(T0 + HOUR, row(unit=845), row(unit=300)),
        ],
        [character_read(money=GOLD)],
    )

    assert result[MARKET].shopping_list == []


def test_a_flip_to_sell_keeps_its_resale_when_a_sale_was_dearer(db):
    # A sale at 1100, above the 999 they're posted at once the 700s are bought. The 700s
    # come up after a gap too long to be an Observation Window, so they don't make the
    # 1100 too dear to be a sale (#74).
    result = run(
        db,
        [
            scan(T0, row(quantity=20, unit=1000), row(unit=1100)),
            scan(T0 + HOUR, row(quantity=20, unit=1000)),
            scan(T0 + 3 * HOUR, row(quantity=20, unit=1000), row(quantity=2, unit=700)),
        ],
        [character_read(money=GOLD)],
    )

    assert result[MARKET].shopping_list == [
        Row(
            LINEN_KEY,
            Action.SELL,
            2,
            price=700,
            profit=pytest.approx(2 * (999 * 0.95 - 700)),
            post_at=999,
            sale_events=1,
            cost=1400,
        )
    ]


def test_a_flip_to_sell_is_never_posted_above_what_a_merchant_charges(db):
    # #63: the 1g 95s wall would be undercut to 1g 94s 99c, but a merchant sells Linen for
    # 1g 50s, so no one pays more on the Auction House.
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=3, unit=10000), unit=19500),
        [character_read(money=GOLD, merchant_costs={2589: 15000})],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.quantity, flip.price, flip.post_at) == (3, 10000, 15000)
    assert flip.profit == pytest.approx(3 * (15000 * 0.95 - 10000))


def test_a_flip_to_sell_still_undercuts_a_listing_under_the_merchant_cost(db):
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=3, unit=10000), unit=19500),
        [character_read(money=GOLD, merchant_costs={2589: 25000})],
    )

    [flip] = result[MARKET].shopping_list
    assert flip.post_at == 19499


# --- Demand at the post price (#107) ---


def three_sales_at_600_then_one_at_2500(*latest_rows):
    """Scans an hour apart: 2 of the 600s sell in each of the first three hours, then 1
    of the 2500s in the fourth. 7 units over 4 h, so 5 sell in the 3 h horizon."""
    return [
        scan(T0 + n * HOUR, row(quantity=8 - 2 * n, unit=600), row(quantity=3, unit=2500))
        for n in range(4)
    ] + [scan(T0 + 4 * HOUR, row(quantity=2, unit=600), row(quantity=2, unit=2500), *latest_rows)]


def test_a_flip_to_sell_counts_only_the_sale_events_at_or_above_its_post_price(db):
    # Buying the 600s through would post at 2499, but only the one 2500 sold that high,
    # short of the 3 Sale Events a Flip needs. Posted at 599, just the 300s have all 4.
    result = run(
        db,
        three_sales_at_600_then_one_at_2500(row(quantity=2, unit=300)),
        [character_read(money=GOLD)],
        config=replace(CONFIG, flip_min_sale_events=3),
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity, flip.price, flip.post_at) == (Action.SELL, 2, 300, 599)


def test_a_flip_to_sells_room_and_wait_come_from_the_sale_events_at_its_post_price(db):
    # 2 of the 1000s sell every other hour, 6 in 6 h, and 8 of the 400s besides: 14 units,
    # so 7 would sell in the 3 h horizon. At or above 999, only the 1000s count: 3 do.
    # So the 700 isn't bought too, and the 3 cheap ones post under it, waiting 3 h.
    thousands = [20, 18, 18, 16, 16, 14]
    four_hundreds = [row(quantity=q, unit=400) for q in (12, 12, 8, 8)] + [
        row(quantity=4, unit=400, time_left=1)  # gone next Scan, maybe expired: no sale
    ]
    scans = [
        scan(T0 + n * HOUR, row(quantity=q, unit=1000), *four_hundreds[n : n + 1])
        for n, q in enumerate(thousands)
    ]
    scans.append(
        scan(
            T0 + 6 * HOUR,
            row(quantity=14, unit=1000),
            *[row(unit=u) for u in (300, 310, 320, 700)],
        )
    )

    result = run(db, scans, [character_read(money=GOLD)])

    [flip] = result[MARKET].shopping_list
    assert (flip.quantity, flip.post_at, flip.sale_events) == (3, 699, 3)
    assert flip.days == pytest.approx(3 / 24)


@pytest.mark.parametrize(("min_sale_events", "flipped"), [(3, True), (4, False)])
def test_sale_events_at_exactly_the_post_price_count_toward_the_minimum(
    db, min_sale_events, flipped
):
    # With no undercut the 500 posts at 1000, just what the 3 Sale Events sold at.
    result = run(
        db,
        selling_two_linen_an_hour(row(unit=500), unit=1000, sale_events=3),
        [character_read(money=GOLD)],
        config=replace(CONFIG, flip_min_sale_events=min_sale_events, post_undercut_copper=0),
    )

    assert [(r.action, r.post_at) for r in result[MARKET].shopping_list] == (
        [(Action.SELL, 1000)] if flipped else []
    )


def test_no_flip_to_sell_posts_where_only_two_sale_events_ever_sold(db):
    # #107, shaped like Hulking Gauntlets on beta: 8 Sale Events from 21s to 2g 99s, 11 up
    # at 68s 73c and a wall at 2g 49s. Bought out, they'd post at 2g 48s 99c, where only
    # the two 2g 99s sold: short of the 3 a Flip needs, though a day holds all 11. Each
    # sale's stack is gone the Scan after, maybe expired.
    sales = [(2100, 1), (8000, 2), (8000, 1), (29900, 1), (29900, 1), (18000, 1), (8800, 1)]
    sales.append((3000, 1))
    wall = row(quantity=3, unit=24900)

    def stacks(n):
        """The stack that sells in the window ending at Scan n, and the one sold before."""
        up = [row(quantity=sales[n][1] + 1, unit=sales[n][0])] if n < len(sales) else []
        sold = [row(unit=sales[n - 1][0], time_left=1)] if n else []
        return up + sold

    scans = [scan(T0 + n * HOUR, wall, *stacks(n)) for n in range(len(sales) + 1)]
    scans.append(scan(T0 + (len(sales) + 1) * HOUR, wall, row(quantity=11, unit=6873)))

    result = run(
        db,
        scans,
        [character_read(money=GOLD)],
        config=replace(CONFIG, flip_min_sale_events=3, sale_horizon_seconds=DAY),
    )

    assert [r for r in result[MARKET].shopping_list if r.action is Action.SELL] == []


def test_own_listings_are_never_bought(db):
    result = run(
        db,
        [scan(T0, row(ORE, unit=5, own=True))],
        [character_read(money=GOLD, vendor_prices={2770: 10})],
    )

    assert result[MARKET].shopping_list == []


def test_a_unit_a_vendor_pays_more_for_than_it_resells_for_is_bought_to_vendor(db):
    # Resale of the 700 would be 950 after the cut, but a vendor pays 960.
    result = run(
        db,
        selling_two_linen_an_hour(row(unit=700), unit=1000),
        [character_read(money=GOLD, vendor_prices={2589: 960})],
    )

    assert result[MARKET].shopping_list == [
        Row(LINEN_KEY, Action.VENDOR, 1, price=700, profit=260, cost=700)
    ]


def test_each_option_is_sized_on_its_own_and_ranked_by_profit(db):
    # #86: 40 copper between them. All the Ore (2 x 5 profit) costs 40 and all the Tin
    # (3 x 5 profit) 15, 55 together: each is shown whole, as if the only buy, and the
    # player picks. Most profit first, not most profit per gold.
    tin = "item:2771::::::::20:1490"
    result = run(
        db,
        [scan(T0, row(ORE, quantity=2, unit=20), row(tin, quantity=3, unit=5))],
        [
            character_read(money=25, vendor_prices={2770: 25, 2771: 10}),
            character_read(money=15, character="Alt-One"),
        ],
    )

    assert result[MARKET].shopping_list == [
        Row("2771", Action.VENDOR, 3, price=5, profit=15, cost=15),
        Row(ORE_KEY, Action.VENDOR, 2, price=20, profit=10, cost=40),
    ]


def test_an_option_the_gold_cant_buy_whole_buys_what_fits(db):
    # #86: 35 copper buys 1 of the 2 Ore, even though the Tin would fit beside it.
    tin = "item:2771::::::::20:1490"
    result = run(
        db,
        [scan(T0, row(ORE, quantity=2, unit=20), row(tin, quantity=3, unit=5))],
        [character_read(money=35, vendor_prices={2770: 25, 2771: 10})],
    )

    assert result[MARKET].shopping_list == [
        Row("2771", Action.VENDOR, 3, price=5, profit=15, cost=15),
        Row(ORE_KEY, Action.VENDOR, 1, price=20, profit=5, cost=20),
    ]


def test_the_shopping_list_shows_only_the_most_profitable_options(db):
    # #86: config shopping_list_rows cuts the list after the top options by profit.
    tin = "item:2771::::::::20:1490"
    result = run(
        db,
        [scan(T0, row(ORE, quantity=2, unit=20), row(tin, quantity=3, unit=5))],
        [character_read(money=GOLD, vendor_prices={2770: 25, 2771: 10})],
        config=replace(CONFIG, shopping_list_rows=1),
    )

    assert [r.item_key for r in result[MARKET].shopping_list] == ["2771"]


def test_a_budget_caps_what_each_option_spends(db):
    # #86: the latest Character Read in the Market carries the Budget the player set: 20
    # copper of the 1g held. Each option spends no more than it.
    tin = "item:2771::::::::20:1490"
    result = run(
        db,
        [scan(T0, row(ORE, quantity=2, unit=20), row(tin, quantity=3, unit=5))],
        [
            character_read(money=GOLD, vendor_prices={2770: 25, 2771: 10}, budget=100),
            character_read(money=GOLD, character="Alt-One", at=T0 + 1, budget=20),
        ],
    )

    assert result[MARKET].budget == 20
    assert result[MARKET].shopping_list == [
        Row("2771", Action.VENDOR, 3, price=5, profit=15, cost=15),
        Row(ORE_KEY, Action.VENDOR, 1, price=20, profit=5, cost=20),
    ]


def test_no_budget_in_the_latest_character_read_means_all_the_gold(db):
    result = run(
        db,
        [scan(T0, row(ORE, quantity=2, unit=20))],
        [
            character_read(money=GOLD, vendor_prices={2770: 25}, budget=20),
            character_read(money=GOLD, character="Alt-One", at=T0 + 1),
        ],
    )

    assert result[MARKET].budget is None
    [ore] = result[MARKET].shopping_list
    assert ore.quantity == 2


def test_holdings_are_ranked_by_expected_profit_with_unknowns_last(db):
    ore = "|cffffffff|Hitem:2770::::::::20:1490:::::::::|h[Copper Ore]|h|r"
    bound = "|cff1eff00|Hitem:3300::::::::20:1490:::::::::|h[Bound Ring]|h|r"
    fish = "|cffffffff|Hitem:6303::::::::20:1490:::::::::|h[Raw Slitherskin Mackerel]|h|r"
    result = run(
        db,
        selling_two_linen_an_hour(),
        [
            character_read(
                item(fish),
                item(ore),
                item(count=2),
                item(bound, count=3, bound=True),
                vendor_prices={2589: 10, 3300: 100},
            )
        ],
    )

    assert [(r.item_key, r.action, r.profit) for r in result[MARKET].holdings] == [
        ("3300", Action.VENDOR, 300),
        (LINEN_KEY, Action.SELL, pytest.approx(2 * 99 * 0.95)),
        ("2770", None, None),
        ("6303", None, None),
    ]


# --- Days to Sell (#109, ADR-0020) ---


@pytest.mark.parametrize(
    ("days_to_sell", "bought"), [(None, 7 * 48 - 2), (1, 48 - 2), (30, 7 * 48 - 2)]
)
def test_days_to_sell_caps_a_flip_to_sell_at_what_sells_in_it_after_the_held_units(
    db, days_to_sell, bought
):
    # 48 Linen sell a day. With a 7-day Sale Horizon a Flip to Sell buys a week of them
    # less the 2 held, the 200s and 400s; Days to Sell of 1 buys a day's, the 200s only.
    # One over the Sale Horizon is the Sale Horizon.
    ladder = (row(quantity=46, unit=200), row(quantity=288, unit=400))
    result = run(
        db,
        selling_two_linen_an_hour(*ladder, unit=1000),
        [character_read(item(count=2), money=GOLD, days_to_sell=days_to_sell)],
        config=replace(CONFIG, sale_horizon_seconds=7 * DAY),
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity) == (Action.SELL, bought)


def test_days_to_sell_leaves_the_held_units_on_the_sale_horizon(db, other_db):
    # 6 of the 10 held Linen sell within the 3 h Sale Horizon, the rest Vendor, whatever
    # Days to Sell says: it only caps buys (ADR-0020).
    def holdings(conn, days_to_sell):
        reads = [
            character_read(item(count=10), vendor_prices={2589: 10}, days_to_sell=days_to_sell)
        ]
        return run(conn, selling_two_linen_an_hour(), reads)[MARKET].holdings

    assert holdings(db, 1 / 24) == holdings(other_db, None)
    assert [(r.action, r.quantity) for r in holdings(other_db, None)] == [
        (Action.SELL, 6),
        (Action.VENDOR, 4),
    ]


def test_days_to_sell_caps_a_flip_to_crafts_sell_room(db):
    # 6 Bolts sell within the 3 h Sale Horizon, but only 3 in Days to Sell of 1.5 h. Past
    # it they'd Vendor, and they have no Vendor Price.
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(), money=GOLD, recipes=[recipe()], days_to_sell=1.5 / 24)],
    )

    [craft] = result[MARKET].shopping_list
    assert (craft.action, craft.quantity) == (Action.CRAFT, 3)


def test_days_to_sell_caps_a_buy_unders_sell_units(db):
    # 7 Linen sell an hour and 5 are held: 16 in the 3 h Sale Horizon, 2 in 1 h.
    result = run(
        db,
        linen_sold_under_1000(),
        [character_read(item(count=5), days_to_sell=1 / 24)],
    )

    assert [(b.way, b.units) for b in result[MARKET].buy_under] == [(Action.SELL, 2)]


# --- Per click, Per day and ROI (#98) ---


def test_a_flip_to_sell_counts_every_listing_it_buys_even_at_the_same_price(db):
    # Two 700s and a 750, each its own Listing: 3 Listings to click through.
    result = run(
        db,
        selling_two_linen_an_hour(row(unit=700), row(unit=700), row(unit=750), unit=1000),
        [character_read(money=GOLD)],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity, flip.listings) == (Action.SELL, 3, 3)


def test_a_flip_to_vendor_counts_every_listing_it_buys_even_at_the_same_price(db):
    # Three Ore Listings at 5, one of them a stack of 2: 3 Listings for 4 units.
    result = run(
        db,
        [scan(T0, row(ORE, unit=5), row(ORE, quantity=2, unit=5), row(ORE, unit=5))],
        [character_read(money=GOLD, vendor_prices={2770: 10})],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity, flip.listings) == (Action.VENDOR, 4, 3)


def test_a_flip_to_sell_posts_its_units_in_stacks_of_the_usual_sale_event_size(db):
    # Linen sells 2 at a time, so 5 bought are posted as 3 stacks: 2, 2 and 1.
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=5, unit=500), unit=1000),
        [character_read(money=GOLD)],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity, flip.posts) == (Action.SELL, 5, 3)


def test_a_flip_to_vendor_posts_nothing(db):
    result = run(
        db,
        [scan(T0, row(ORE, quantity=2, unit=5))],
        [character_read(money=GOLD, vendor_prices={2770: 10})],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.posts) == (Action.VENDOR, 0)


def test_a_flip_to_sell_waits_for_its_last_unit_behind_the_held_ones(db):
    # 48 Linen sell a day. The 2 held go first, then the 4 bought: the last sells in
    # 6 / 48 of a day.
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=4, unit=500), unit=1000),
        [character_read(item(count=2), money=GOLD)],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity) == (Action.SELL, 4)
    assert flip.days == pytest.approx(6 / 48)


def test_a_flip_to_vendor_has_no_wait(db):
    result = run(
        db,
        [scan(T0, row(ORE, quantity=2, unit=5))],
        [character_read(money=GOLD, vendor_prices={2770: 10})],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.days) == (Action.VENDOR, None)


def test_a_flip_to_sell_that_sells_within_a_day_makes_its_profit_per_day():
    # #101: a one-off Flip whose unit sells in 3 h can't be repeated all day.
    flip = Row(LINEN_KEY, Action.SELL, 1, profit=371, days=0.125)

    assert per_day(flip) == 371


def test_a_flip_to_sell_slower_than_a_day_splits_its_profit_over_its_days():
    # 900 over 2.5 days.
    flip = Row(LINEN_KEY, Action.SELL, 5, profit=900, days=2.5)

    assert per_day(flip) == 360


def test_a_flip_to_vendor_makes_its_profit_now():
    flip = Row(ORE_KEY, Action.VENDOR, 4, profit=20)

    assert per_day(flip) == math.inf


def test_an_option_in_the_top_rows_only_by_profit_per_click_is_kept(db):
    # shopping_list_rows = 1. The Ore makes the most profit (10 x 5 over 5 Listings, 10
    # a click), and its ROI (50 on 50) beats the Tin's (12 on 18). But the Tin's one
    # Listing makes 12 a click, so it's kept too. Both sell now. Most profit first.
    tin = "item:2771::::::::20:1490"
    result = run(
        db,
        [scan(T0, *[row(ORE, quantity=2, unit=5)] * 5, row(tin, quantity=3, unit=6))],
        [character_read(money=GOLD, vendor_prices={2770: 10, 2771: 10})],
        config=replace(CONFIG, shopping_list_rows=1),
    )

    assert [(r.item_key, r.profit) for r in result[MARKET].shopping_list] == [
        (ORE_KEY, 50),
        ("2771", 12),
    ]


def test_a_flip_to_vendor_never_takes_a_top_per_day_row(db):
    # shopping_list_rows = 1. The Linen Flip to Sell beats the Ore on Profit, Per click
    # and ROI. The Ore, vendored now, would top Per day, but Per day ranks only Flips to
    # Sell: every Flip to Vendor ties there, and they'd crowd the Flips to Sell out.
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=5, unit=500), unit=1000)[:-1]
        + [
            scan(
                T0 + HOUR,
                row(quantity=18, unit=1000),
                row(quantity=5, unit=500),
                *[row(ORE, quantity=2, unit=9)] * 3,
            )
        ],
        [character_read(money=GOLD, vendor_prices={2770: 10})],
        config=replace(CONFIG, shopping_list_rows=1),
    )

    assert [(r.item_key, r.action) for r in result[MARKET].shopping_list] == [
        (LINEN_KEY, Action.SELL),
    ]


def test_a_one_off_fast_flip_doesnt_beat_a_bigger_flip_that_sells_within_a_day(db):
    # shopping_list_rows = 1. 10 Tin sell an hour, 2 Linen. The one Tin bought sells in
    # minutes, the 5 Linen in 2.5 h: both within a day, so Per day is their Profit (#101),
    # and the Linen wins it as it wins Profit, Per click and ROI. Unfloored, the Tin's few
    # coppers over a few minutes would top Per day.
    tin = "item:2771::::::::20:1490"
    result = run(
        db,
        [
            scan(T0, row(quantity=20, unit=1000), row(tin, quantity=20, unit=1000)),
            scan(
                T0 + HOUR,
                row(quantity=18, unit=1000),
                row(quantity=5, unit=500),
                row(tin, quantity=10, unit=1000),
                row(tin, unit=780),
            ),
        ],
        [character_read(money=GOLD)],
        config=replace(CONFIG, shopping_list_rows=1),
    )

    assert [(r.item_key, r.action) for r in result[MARKET].shopping_list] == [
        (LINEN_KEY, Action.SELL),
    ]


# --- Non-stacking effort (#73) ---

BELT = "item:6539::::::::20:1490"
BELT_KEY = "6539"


def selling_two_an_hour(item, *latest_rows, stacks):
    """2 of `item` sell in an hour at 1000 each, out of 10 listed one at a time or, if it
    `stacks`, as one stack of 10: 6 sell within the 3 h horizon. `latest_rows` come 2 h
    later, beside the 8 left, after a gap too long for an Observation Window."""

    def wall(n):
        return [row(item, quantity=n, unit=1000)] if stacks else [row(item, unit=1000)] * n

    return [
        scan(T0, *wall(10)),
        scan(T0 + HOUR, *wall(8)),
        scan(T0 + 3 * HOUR, *wall(8), *latest_rows),
    ]


@pytest.mark.parametrize(("stacks", "flipped"), [(True, True), (False, False)])
def test_a_flip_to_sell_of_units_that_dont_stack_pays_to_buy_and_post_each(db, stacks, flipped):
    # 3 bought at 600 and posted at 999 make 349.05 each after the cut, well over the Flip
    # margin. But units that never stack cost 5s to buy and 5s to post each, a loss.
    result = run(
        db,
        selling_two_an_hour(BELT, *[row(BELT, unit=600)] * 3, stacks=stacks),
        [character_read(money=GOLD)],
    )

    flip = Row(
        BELT_KEY,
        Action.SELL,
        3,
        price=600,
        profit=pytest.approx(3 * (999 * 0.95 - 600)),
        post_at=999,
        sale_events=1,
        cost=1800,
    )
    assert result[MARKET].shopping_list == ([flip] if flipped else [])


@pytest.mark.parametrize(("vendor_price", "bought"), [(1100, False), (1101, True)])
def test_a_unit_that_doesnt_stack_is_bought_to_vendor_only_if_it_pays_for_the_buy(
    db, vendor_price, bought
):
    # Vendoring isn't a Listing, so only the buy costs 5s.
    result = run(
        db,
        [scan(T0, row(BELT, unit=600))],
        [character_read(money=GOLD, vendor_prices={6539: vendor_price})],
    )

    vendor = Row(BELT_KEY, Action.VENDOR, 1, price=600, profit=1, cost=600)
    assert result[MARKET].shopping_list == ([vendor] if bought else [])


@pytest.mark.parametrize(("stacks", "effort"), [(True, 0), (False, 500)])
def test_a_flip_to_craft_pays_to_post_each_output_that_doesnt_stack(db, stacks, effort):
    # 6 Belts sell within the horizon, posted at 999 for 949.05 after the cut, each made
    # from 2 Linen bought at 100. Each Belt that doesn't stack costs 5s to post.
    linen = row(quantity=20, unit=100)
    result = run(
        db,
        selling_two_an_hour(BELT, linen, stacks=stacks),
        [character_read(money=GOLD, recipes=[recipe(output=6539)])],
    )

    [craft] = result[MARKET].shopping_list
    assert (craft.item_key, craft.action, craft.quantity) == (BELT_KEY, Action.CRAFT, 6)
    assert craft.profit == pytest.approx(6 * (949.05 - effort - 200))


@pytest.mark.parametrize(("stacks", "effort"), [(True, 0), (False, 500)])
def test_a_flip_to_craft_pays_to_buy_each_reagent_that_doesnt_stack(db, stacks, effort):
    # 6 Bolts, each from a Belt bought at 100. Each Belt that doesn't stack costs 5s to buy.
    scans = linen_and_bolts_selling()
    scans[1]["listings"] += [row(BELT, quantity=6, unit=100)] if stacks else [row(BELT)] * 6
    result = run(db, scans, [character_read(money=GOLD, recipes=[recipe(reagents=((6539, 1),))])])

    [craft] = result[MARKET].shopping_list
    assert (craft.item_key, craft.action, craft.quantity) == (BOLT_KEY, Action.CRAFT, 6)
    assert craft.profit == pytest.approx(6 * (949.05 - effort - 100))


# --- Deposits (#78) ---

# Posted for an hour at a time, so with 2 Linen selling an hour, units 0-1 of the queue
# sell in their first posting, 2-3 lose one deposit first, and 4-5 lose two.
HOURLY_POSTS = replace(CONFIG, post_duration_hours=1)


@pytest.mark.parametrize(("hours", "lost"), [(3, 0), (1, 2 * 6 + 2 * 12)])
def test_held_units_down_the_queue_lose_a_deposit_per_expiry_before_they_sell(db, hours, lost):
    # With no Sold invoice, each posting of Linen costs 60% of its 10 Vendor Price: 6.
    # Posted for 3 hours, all 6 sell in their first posting and lose nothing.
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), vendor_prices={2589: 10})],
        config=replace(CONFIG, post_duration_hours=hours),
    )

    sell, _ = result[MARKET].holdings
    assert (sell.action, sell.quantity) == (Action.SELL, 6)
    assert sell.profit == pytest.approx(6 * 99 * 0.95 - lost)


def linen_sold_for_deposits(*deposits):
    """A Mailbox Read with a Linen Purchase, which links the name Linen Cloth to its Item
    Key, and a Sold Outcome per (count, deposit), each arriving an hour after the last."""
    buy = won(T0, 1, 50)["mails"][0]
    sales = [
        sold_mail("Linen Cloth")
        | {
            "daysLeft": 29 + n / 24,
            "invoice": {
                "invoiceType": "seller",
                "itemName": "Linen Cloth",
                "bid": 500,
                "count": count,
                "deposit": deposit,
            },
        }
        for n, (count, deposit) in enumerate(deposits)
    ]
    return mailbox_read(T0, buy) | {"mails": [buy, *sales], "shownCount": 1 + len(sales)}


def test_the_deposit_is_learned_from_the_latest_sold_invoice(db):
    # The latest sale of Linen paid 20 to post 2: 10 a unit, not the 6 (60% of the 10
    # Vendor Price) nor the 50 a unit of the earlier one. Posted hourly, units 3-4 of the
    # queue lose one and 5-6 lose two.
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), vendor_prices={2589: 10})],
        config=HOURLY_POSTS,
        mailbox_reads=[linen_sold_for_deposits((1, 50), (2, 20))],
    )

    sell = next(r for r in result[MARKET].holdings if r.action is Action.SELL)
    assert sell.quantity == 6
    assert sell.profit == pytest.approx(6 * 99 * 0.95 - (2 * 10 + 2 * 20))


@pytest.mark.parametrize("vendor_prices", [None, {2589: 0}])
def test_an_item_key_with_no_vendor_price_or_sold_invoice_pays_no_deposit(db, vendor_prices):
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), vendor_prices=vendor_prices)],
        config=HOURLY_POSTS,
    )

    sell = next(r for r in result[MARKET].holdings if r.action is Action.SELL)
    assert (sell.quantity, sell.profit) == (6, pytest.approx(6 * 99 * 0.95))


def test_a_held_unit_whose_deposits_eat_its_edge_over_vendor_goes_to_vendor(db):
    # Posted at 99 for 94.05 after the cut, Linen beats its 90 Vendor Price. But each
    # posting costs 54 (60% of 90), so from the third unit of the queue on, losing one
    # first leaves 40.05: those are Vendored, and the first two still Sell.
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), vendor_prices={2589: 90})],
        config=HOURLY_POSTS,
    )

    assert result[MARKET].holdings == [
        Row(LINEN_KEY, Action.VENDOR, 8, price=90, profit=720),
        Row(
            LINEN_KEY,
            Action.SELL,
            2,
            price=99,
            profit=pytest.approx(2 * 99 * 0.95),
            margin=pytest.approx(99 * 0.95 - 90),
            sale_events=1,
        ),
    ]


@pytest.mark.parametrize(("hours", "held", "lost"), [(3, 0, 0), (1, 0, 180), (1, 2, None)])
def test_a_flip_to_sell_must_clear_the_margin_after_its_last_units_deposits(db, hours, held, lost):
    # Posted at 999 for 949.05, 3 Linen at 600 clear the 20% margin by 349.05 each. Each
    # posting costs 180 (60% of 300). Posted hourly, the third unit of the queue loses one
    # first and still clears. Behind 2 held units, the last is fifth and loses two: a loss.
    bags = [item(count=held)] if held else []
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=3, unit=600), unit=1000),
        [character_read(*bags, money=GOLD, vendor_prices={2589: 300})],
        config=replace(CONFIG, post_duration_hours=hours),
    )

    flip = Row(
        LINEN_KEY,
        Action.SELL,
        3,
        price=600,
        profit=pytest.approx(3 * (949.05 - 600) - (lost or 0)),
        post_at=999,
        sale_events=1,
        cost=1800,
    )
    assert result[MARKET].shopping_list == ([] if lost is None else [flip])


# --- The Sell Rate Prior (#25) ---


def one_sale_in_18_minutes(*latest_rows):
    """One Linen sold in a single 18-minute Observation Window: a raw Sell Rate of 80 a
    day, from 0.3 h of watching. A deep Market at 1000, so resale stays well clear. One
    Sale Event is under the Flip minimum (#57), so tests that Flip on it lower that."""
    return [
        scan(T0, row(quantity=200, unit=1000)),
        scan(T0 + 18 * MINUTE, row(quantity=199, unit=1000), *latest_rows),
    ]


def test_a_flip_buys_only_what_the_discounted_sell_rate_says_will_sell(db):
    # As if 24 more hours had been watched with no sales: 1 / 24.3 h * 24 * 7 days = 6.9,
    # not the raw 80 a day * 7 = 560.
    config = replace(DEFAULTS, sell_rate_prior_hours_flips=24, flip_min_sale_events=1)
    result = run(
        db,
        one_sale_in_18_minutes(row(quantity=6, unit=500), row(quantity=4, unit=700)),
        [character_read(money=GOLD)],
        config=config,
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity, flip.price) == (Action.SELL, 6, 500)


def test_holdings_are_discounted_less_than_flips(db, other_db):
    # The default Sell Rate Prior for Holdings, 3 h: 1 / 3.3 h * 24 * 7 days = 50.9 of the 100
    # held are Sold. Flips get the default 24: 1 / 24.3 h * 24 * 7 = 6.9, so 6 bought. Held
    # units take the room before Flips (#67), so the Flips are judged with none held.
    config = replace(DEFAULTS, flip_min_sale_events=1)
    scans = one_sale_in_18_minutes(row(quantity=6, unit=500), row(quantity=4, unit=700))
    holding = run(
        db, scans, [character_read(item(count=100), vendor_prices={2589: 10})], config=config
    )
    flipping = run(other_db, scans, [character_read(money=GOLD)], config=config)

    sell, vendor = holding[MARKET].holdings
    assert (sell.action, sell.quantity) == (Action.SELL, 50)
    assert (vendor.action, vendor.quantity) == (Action.VENDOR, 50)
    [flip] = flipping[MARKET].shopping_list
    assert (flip.action, flip.quantity) == (Action.SELL, 6)


def test_the_market_shows_how_many_hours_of_observation_window_its_sell_rate_rests_on(db):
    result = run(db, one_sale_in_18_minutes(), [character_read()])

    assert result[MARKET].window_hours == pytest.approx(0.3)


def test_a_market_without_observation_windows_rests_on_none(db):
    result = run(db, [scan(T0, row())], [character_read()])

    assert result[MARKET].window_hours == 0


def test_without_a_sell_rate_prior_the_raw_rate_is_taken_at_its_word(db):
    # The raw 80 a day * 7 days = 560 units of room: all 100 held are Sold, and all 10
    # cheap units are bought.
    config = replace(
        DEFAULTS,
        sell_rate_prior_hours_holdings=0,
        sell_rate_prior_hours_flips=0,
        sale_size_prior_events_holdings=0,
        sale_size_prior_events_flips=0,
        flip_min_sale_events=1,
    )
    result = run(
        db,
        one_sale_in_18_minutes(row(quantity=10, unit=500)),
        [character_read(item(count=100), money=GOLD, vendor_prices={2589: 10})],
        config=config,
    )

    [sell] = result[MARKET].holdings
    assert (sell.action, sell.quantity) == (Action.SELL, 100)
    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity) == (Action.SELL, 10)


# --- The Sale Size Prior (#24) ---


def sold_in_10_hours(events, units, typical_sale_size=2):
    """A Sell Rate from `events` Sale Events of `units` in total over 10 h of windows."""
    return SellRate(
        units_per_day=units / 10 * 24,
        sale_events=events,
        window_hours=10,
        reposts=0,
        coincidences=0,
        sale_units=units,
        typical_sale_size=typical_sale_size,
    )


def test_one_big_sale_event_is_shrunk_toward_the_typical_size():
    # (20 + 5 * 2) / (1 + 5) = 5 units a Sale Event, at 1 / 10 h * 24 = 2.4 events a day:
    # 12 a day, not the raw 48.
    rate = sold_in_10_hours(events=1, units=20)

    assert sellable_units(rate, prior_hours=0, prior_events=5, horizon_seconds=DAY) == 12
    assert sellable_units(rate, prior_hours=0, prior_events=0, horizon_seconds=DAY) == 48


def test_the_sale_size_prior_fades_as_sale_events_build_up():
    # 30 Sale Events averaging 5 units: (150 + 5 * 2) / (30 + 5) = 4.57, near the Item
    # Key's own 5. At 30 / 10 h * 24 = 72 events a day that's 329, against the raw 360.
    rate = sold_in_10_hours(events=30, units=150)

    assert sellable_units(rate, prior_hours=0, prior_events=5, horizon_seconds=DAY) == 329


def one_buyer_takes_a_20_stack(*latest_rows):
    """A buyer takes a whole 20-stack of Linen in one 30-minute Observation Window: raw,
    960 a day, 120 in the 3 h horizon. Linen is usually listed 2 at a time, so the typical
    Sale Event is 2 units. A deep Market at 1000. `latest_rows` come up after a gap too
    long to be an Observation Window, so they don't price the 20-stack out (#74)."""
    stacks_of_2 = [row(quantity=2, unit=1000) for _ in range(50)]
    return [
        scan(T0, row(quantity=20, unit=1000), *stacks_of_2),
        scan(T0 + 30 * MINUTE, *stacks_of_2),
        scan(T0 + 3 * HOUR, *stacks_of_2, *latest_rows),
    ]


def test_holdings_and_flips_shrink_the_sale_event_size_by_their_own_prior(db, other_db):
    # Holdings, 1 Sale Event: (20 + 1 * 2) / 2 = 11 units, at 48 events a day = 66 in 3 h.
    # Flips, 5: (20 + 5 * 2) / 6 = 5 units, 30 in 3 h. Held units take the room before
    # Flips (#67), so the Flips are judged with none held.
    config = replace(CONFIG, sale_size_prior_events_holdings=1, sale_size_prior_events_flips=5)
    scans = one_buyer_takes_a_20_stack(row(quantity=30, unit=500), row(quantity=10, unit=700))
    holding = run(
        db, scans, [character_read(item(count=100), vendor_prices={2589: 10})], config=config
    )
    flipping = run(other_db, scans, [character_read(money=GOLD)], config=config)

    sell, vendor = holding[MARKET].holdings
    assert (sell.action, sell.quantity) == (Action.SELL, 66)
    assert (vendor.action, vendor.quantity) == (Action.VENDOR, 34)
    [flip] = flipping[MARKET].shopping_list
    assert (flip.action, flip.quantity, flip.price) == (Action.SELL, 30, 500)


# --- Craft (#31, ADR-0008) ---


def linen_and_bolts_selling(linen=100, bolt=1000, sale_events=1):
    """Linen and Bolts of Linen Cloth each selling 2 an hour, as `sale_events` Sale Events
    of each an hour apart: 6 of each sell within the 3 h horizon, at Fair Values of `linen`
    and `bolt`."""
    return [
        scan(
            T0 + n * HOUR,
            row(quantity=20 - 2 * n, unit=linen),
            row(BOLT, quantity=20 - 2 * n, unit=bolt),
        )
        for n in range(sale_events + 1)
    ]


def test_held_reagents_are_crafted_when_the_output_is_worth_more(db):
    # Posted 1 copper under the walls (#64), two Linen would Sell for 94.05 each after the
    # cut; the Bolt they make Sells for 949.05.
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(count=2), vendor_prices={2589: 10}, recipes=[recipe()])],
    )

    assert result[MARKET].holdings == [
        Row(
            BOLT_KEY,
            Action.SELL,
            1,
            price=999,
            profit=pytest.approx(949.05),
            sale_events=1,
            note="incl. 1 crafted",
        ),
        Row(
            BOLT_KEY,
            Action.CRAFT,
            1,
            profit=pytest.approx(949.05 - 2 * 94.05),
            note="on Kash-Patel: uses 2 of 2589",
            character="Kash-Patel",
            uses=(ReagentUse(LINEN_KEY, 2),),
        ),
    ]


def test_a_recipe_learned_after_a_moment_is_not_crafted_as_of_it(db):
    reads = [
        character_read(item(count=2), vendor_prices={2589: 10}, recipes=[]),
        character_read(item(count=2), at=T0 + 2 * HOUR, recipes=[recipe()]),
    ]
    run(db, linen_and_bolts_selling(), reads)

    then = recommend_market(db, CONFIG, MARKET, [], T0 + HOUR, as_of=T0 + HOUR)

    assert [(r.item_key, r.action) for r in then.holdings] == [(LINEN_KEY, Action.SELL)]


def test_crafting_stops_once_more_output_would_not_sell_within_the_horizon(db):
    # 20 Linen: 6 would Sell and 14 be Vendored at 10, so the first crafts use Linen worth
    # 20 a craft. The first 6 Bolts Sell for 949.05; a 7th would only Vendor for 15.
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(count=20), vendor_prices={2589: 10, 2996: 15}, recipes=[recipe()])],
    )

    assert result[MARKET].holdings == [
        Row(
            BOLT_KEY,
            Action.SELL,
            6,
            price=999,
            profit=pytest.approx(6 * 949.05),
            margin=pytest.approx(949.05 - 15),
            sale_events=1,
            note="incl. 6 crafted",
        ),
        Row(
            BOLT_KEY,
            Action.CRAFT,
            6,
            profit=pytest.approx(6 * (949.05 - 20)),
            note="on Kash-Patel: uses 12 of 2589",
            character="Kash-Patel",
            uses=(ReagentUse(LINEN_KEY, 12),),
        ),
        Row(
            LINEN_KEY,
            Action.SELL,
            6,
            price=99,
            profit=pytest.approx(6 * 99 * 0.95),
            margin=pytest.approx(99 * 0.95 - 10),
            sale_events=1,
        ),
        Row(LINEN_KEY, Action.VENDOR, 2, price=10, profit=20),
    ]


def test_recipes_competing_for_a_reagent_make_the_better_craft_first(db):
    # 4 Linen, each worth 94.05. A Linen Bag (2 Linen) Sells for 474.05, a Bolt for 949.05,
    # so the Linen all goes to Bolts, though the Bag's recipe comes first.
    bag = "item:5762::::::::20:1490"
    result = run(
        db,
        [
            scan(T0, *linen_and_bolts_selling()[0]["listings"], row(bag, quantity=20, unit=500)),
            scan(
                T0 + HOUR,
                *linen_and_bolts_selling()[1]["listings"],
                row(bag, quantity=18, unit=500),
            ),
        ],
        [
            character_read(
                item(count=4),
                recipes=[recipe(2000, output=5762), recipe(2963, output=2996)],
            )
        ],
    )

    [craft] = [r for r in result[MARKET].holdings if r.action is Action.CRAFT]
    assert craft == Row(
        BOLT_KEY,
        Action.CRAFT,
        2,
        profit=pytest.approx(2 * (949.05 - 2 * 94.05)),
        note="on Kash-Patel: uses 4 of 2589",
        character="Kash-Patel",
        uses=(ReagentUse(LINEN_KEY, 4),),
    )


def test_a_reagent_without_market_data_blocks_the_recipe(db):
    # Valuing the Ore at its Vendor Price would understate what crafting it away costs.
    ore = "|cffffffff|Hitem:2770::::::::20:1490:::::::::|h[Copper Ore]|h|r"
    result = run(
        db,
        linen_and_bolts_selling(),
        [
            character_read(
                item(ore, count=2),
                vendor_prices={2770: 5},
                recipes=[recipe(3000, reagents=[(2770, 2)])],
            )
        ],
    )

    assert result[MARKET].holdings == [
        Row(ORE_KEY, None, 2, note="no data"),
        Row(
            BOLT_KEY,
            Action.CRAFT,
            0,
            note="on Kash-Patel: no data for 2770",
            character="Kash-Patel",
            blocked=Blocked(BlockReason.NO_DATA, ORE_KEY),
        ),
    ]


@pytest.mark.parametrize(
    "item_key", [LINEN_KEY, BOLT_KEY], ids=["reagent under it", "output under it"]
)
def test_nothing_is_crafted_from_or_into_a_predictions_item_keys(db, item_key):
    # Its reagents are Held, never crafted away. Crafting into one would Hold units that
    # don't exist yet, at a cost no Lot could back.
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(count=2), money=GOLD, recipes=[recipe()])],
        predictions=[prediction(item_key)],
    )

    assert [r.action for r in result[MARKET].holdings] == [
        Action.HOLD if item_key == LINEN_KEY else Action.SELL
    ]


def test_an_output_whose_bind_type_is_unknown_blocks_the_recipe(db):
    # The client hadn't cached the Bolt, so whether it can go on the AH isn't known.
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(count=2), recipes=[recipe(bind_type=None)])],
    )

    assert result[MARKET].holdings == [
        Row(
            LINEN_KEY,
            Action.SELL,
            2,
            price=99,
            profit=pytest.approx(2 * 99 * 0.95),
            sale_events=1,
        ),
        Row(
            BOLT_KEY,
            Action.CRAFT,
            0,
            note="on Kash-Patel: unknown bind type",
            character="Kash-Patel",
            blocked=Blocked(BlockReason.UNKNOWN_BIND_TYPE),
        ),
    ]


def test_a_bind_on_pickup_output_is_only_worth_its_vendor_price(db):
    # Bolts Sell for 949.05, but these would be bound: a vendor pays 300, still more than
    # the 188.10 the Linen would bring.
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(count=2), vendor_prices={2996: 300}, recipes=[recipe(bind_type=1)])],
    )

    assert result[MARKET].holdings == [
        Row(BOLT_KEY, Action.VENDOR, 1, price=300, profit=300, note="incl. 1 crafted"),
        Row(
            BOLT_KEY,
            Action.CRAFT,
            1,
            profit=pytest.approx(300 - 2 * 94.05),
            note="on Kash-Patel: uses 2 of 2589",
            character="Kash-Patel",
            uses=(ReagentUse(LINEN_KEY, 2),),
        ),
    ]


def test_a_recipe_still_on_cooldown_as_of_its_read_is_blocked(db):
    # Read at T0 with 3 hours left; the latest Scan is only an hour on.
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(count=2), recipes=[recipe(cooldown=3 * HOUR)])],
    )

    until = datetime.fromtimestamp(T0 + 3 * HOUR).strftime("%Y-%m-%d %H:%M")
    [craft] = [r for r in result[MARKET].holdings if r.action is Action.CRAFT]
    assert craft == Row(
        BOLT_KEY,
        Action.CRAFT,
        0,
        note=f"on Kash-Patel: on cooldown until {until}",
        character="Kash-Patel",
    )


def test_a_cooldown_recipe_crafts_once_per_character_whose_cooldown_has_passed(db):
    # Enough Linen for 5 Bolts, but only Alt-One and Zed-Alt are off cooldown.
    ready = recipe(cooldown=30 * MINUTE)
    result = run(
        db,
        linen_and_bolts_selling(),
        [
            character_read(
                item(count=10),
                vendor_prices={2589: 10},
                recipes=[recipe(cooldown=3 * HOUR)],
            ),
            character_read(character="Alt-One", recipes=[ready]),
            character_read(character="Zed-Alt", recipes=[ready]),
        ],
    )

    [craft] = [r for r in result[MARKET].holdings if r.action is Action.CRAFT]
    assert craft == Row(
        BOLT_KEY,
        Action.CRAFT,
        2,
        profit=pytest.approx(2 * (949.05 - 20)),
        note="on Alt-One: uses 4 of 2589",
        character="Alt-One",
        uses=(ReagentUse(LINEN_KEY, 4),),
    )


def test_a_cooldown_recipe_in_several_professions_is_still_once_per_character(db):
    result = run(
        db,
        linen_and_bolts_selling(),
        [
            character_read(
                item(count=10),
                recipes=[recipe(cooldown=30 * MINUTE)],
                professions=(TAILORING, 185, 356),
            )
        ],
    )

    [craft] = [r for r in result[MARKET].holdings if r.action is Action.CRAFT]
    assert craft.quantity == 1


def test_bound_reagents_are_used_and_before_ones_that_would_sell(db):
    # Pooled across Characters. The 2 bound Linen would only Vendor for 10 each, so the
    # first Bolt loses 20 of Linen and the second the 188.10 the other 2 would Sell for.
    result = run(
        db,
        linen_and_bolts_selling(),
        [
            character_read(item(count=2), vendor_prices={2589: 10}, recipes=[recipe()]),
            character_read(item(count=2, bound=True), character="Alt-One"),
        ],
    )

    [craft] = [r for r in result[MARKET].holdings if r.action is Action.CRAFT]
    assert craft.quantity == 2
    assert craft.profit == pytest.approx((949.05 - 20) + (949.05 - 2 * 94.05))
    assert not [r for r in result[MARKET].holdings if r.item_key == LINEN_KEY]


def test_an_output_without_market_data_counts_at_its_vendor_price(db):
    shirt = 2576  # never seen on the Auction House
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(count=2), vendor_prices={shirt: 300}, recipes=[recipe(output=shirt)])],
    )

    assert result[MARKET].holdings == [
        Row(
            "2576",
            Action.CRAFT,
            1,
            profit=pytest.approx(300 - 2 * 94.05),
            note="on Kash-Patel: uses 2 of 2589",
            character="Kash-Patel",
            uses=(ReagentUse(LINEN_KEY, 2),),
        ),
        Row("2576", None, 1, note="no data, incl. 1 crafted"),
    ]


THREAD_LINK = "|cffffffff|Hitem:2320::::::::20:1490:::::::::|h[Coarse Thread]|h|r"
LINEN_AND_THREAD = [(2589, 2), (2320, 1)]


def test_merchant_reagents_cost_their_merchant_cost_and_missing_ones_are_bought(db):
    # 4 Linen and 1 Coarse Thread for two Bolts: the second Thread is bought. Thread has no
    # market data, but could be bought back for its 10, so that's what each one costs.
    result = run(
        db,
        linen_and_bolts_selling(),
        [
            character_read(
                item(count=4),
                item(THREAD_LINK),
                recipes=[recipe(reagents=LINEN_AND_THREAD)],
                merchant_costs={2320: 10},
            )
        ],
    )

    assert result[MARKET].holdings == [
        Row(
            BOLT_KEY,
            Action.SELL,
            2,
            price=999,
            profit=pytest.approx(2 * 949.05),
            sale_events=1,
            note="incl. 2 crafted",
        ),
        Row(
            BOLT_KEY,
            Action.CRAFT,
            2,
            profit=pytest.approx(2 * (949.05 - 2 * 94.05 - 10)),
            note="on Kash-Patel: uses 4 of 2589, 2 of 2320 (buy 1)",
            character="Kash-Patel",
            uses=(ReagentUse(LINEN_KEY, 4), ReagentUse("2320", 1)),
        ),
    ]


def test_a_missing_reagent_no_merchant_sells_means_no_craft(db):
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(count=2), recipes=[recipe(reagents=LINEN_AND_THREAD)])],
    )

    assert result[MARKET].holdings == [
        Row(
            LINEN_KEY,
            Action.SELL,
            2,
            price=99,
            profit=pytest.approx(2 * 99 * 0.95),
            sale_events=1,
        )
    ]


def test_a_craft_uses_at_least_one_held_reagent(db):
    # Bolts from Thread alone would vendor for more than the Thread costs: bought Thread
    # could be crafted forever. Only the one held is.
    result = run(
        db,
        linen_and_bolts_selling(),
        [
            character_read(
                item(THREAD_LINK),
                vendor_prices={2996: 15},
                recipes=[recipe(reagents=[(2320, 1)])],
                merchant_costs={2320: 10},
            )
        ],
    )

    [craft] = [r for r in result[MARKET].holdings if r.action is Action.CRAFT]
    assert craft.quantity == 1
    assert craft.profit == pytest.approx(949.05 - 10)


@pytest.mark.parametrize(("min_gain", "crafts"), [(929, 6), (930, 0)])
def test_a_craft_must_gain_more_than_the_minimum(db, min_gain, crafts):
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(count=20), vendor_prices={2589: 10, 2996: 15}, recipes=[recipe()])],
        config=replace(CONFIG, craft_min_gain=min_gain),
    )

    made = [r.quantity for r in result[MARKET].holdings if r.action is Action.CRAFT]
    assert sum(made) == crafts


# --- Flip to Craft (#32, ADR-0009) ---


def test_a_flip_to_craft_buys_only_the_reagents_held_ones_dont_cover(db):
    # 1 Linen held, worth the 94.05 it Sells for. The first Bolt buys 1 Linen at 100, the
    # next 5 buy 2 each, until the 6 Bolts that sell within the horizon, posted at 999
    # for 949.05 after the cut.
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(), money=GOLD, recipes=[recipe()])],
    )

    assert result[MARKET].shopping_list == [
        Row(
            BOLT_KEY,
            Action.CRAFT,
            6,
            profit=pytest.approx((949.05 - 94.05 - 100) + 5 * (949.05 - 200)),
            cost=11 * 100,
            note="on Kash-Patel: uses 12 of 2589 (buy 11)",
            buys=(ReagentBuy(LINEN_KEY, 11, 100),),
            character="Kash-Patel",
            uses=(ReagentUse(LINEN_KEY, 1),),
        )
    ]


def test_a_held_reagent_a_flip_to_craft_would_use_keeps_its_holdings_row(db):
    # #86 (was #69): 3 Linen held. The Craft Action uses 2 and the Flip to Craft would
    # use the 3rd (buying 9), but it's only an option, so the 3rd is still up for Sell.
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(count=3), money=GOLD, recipes=[recipe()])],
    )

    [craft] = result[MARKET].shopping_list
    assert (craft.quantity, craft.uses) == (5, (ReagentUse(LINEN_KEY, 1),))
    assert [(r.item_key, r.action, r.quantity) for r in result[MARKET].holdings] == [
        (BOLT_KEY, Action.SELL, 1),
        (BOLT_KEY, Action.CRAFT, 1),
        (LINEN_KEY, Action.SELL, 1),
    ]


def test_a_flip_to_crafts_output_is_never_resold_above_what_a_merchant_charges(db):
    # #63: as above, but a merchant sells Bolts for 500, so they resell for 475.
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(), money=GOLD, recipes=[recipe()], merchant_costs={2996: 500})],
    )

    [craft] = result[MARKET].shopping_list
    assert (craft.action, craft.quantity) == (Action.CRAFT, 6)
    assert craft.profit == pytest.approx((475 - 94.05 - 100) + 5 * (475 - 200))


def test_a_flip_to_crafts_reagents_cost_what_walking_up_the_asks_costs(db):
    # A Linen at 60 and one at 80 go into the first Bolt; every later one pays 100 a Linen.
    # Neither is a plain Flip: posted under the next Listing up, neither clears 1 silver.
    scans = linen_and_bolts_selling()
    scans[1]["listings"] += [row(unit=60), row(unit=80)]
    result = run(db, scans, [character_read(money=GOLD, recipes=[recipe()])])

    [craft] = result[MARKET].shopping_list
    assert (craft.quantity, craft.cost) == (6, 140 + 10 * 100)
    assert craft.profit == pytest.approx(6 * 949.05 - 1140)
    assert craft.buys == (ReagentBuy(LINEN_KEY, 12, 100),)


def test_a_flip_to_craft_buys_the_cheapest_asks_even_where_a_plain_flip_would(db):
    # #86: the 2 Linen at 10 are a Flip to Sell, resold at 299 under the 300s. The Bolts
    # are another option, so they buy the 10s too, then 10 at 300.
    scans = linen_and_bolts_selling(linen=300)
    scans[1]["listings"].append(row(quantity=2, unit=10))
    result = run(db, scans, [character_read(money=GOLD, recipes=[recipe()])])

    [craft, flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity, flip.post_at) == (Action.SELL, 2, 299)
    assert (craft.action, craft.cost) == (Action.CRAFT, 2 * 10 + 10 * 300)


def test_a_flip_to_sell_posts_as_if_no_flip_to_craft_bought_of_it(db):
    # #86 (was #68): the Bolts would buy all 12 Linen at 250, but they're an option, so the
    # 2 at 10 post under the 250s.
    scans = linen_and_bolts_selling(linen=300)
    scans[1]["listings"] += [row(quantity=12, unit=250), row(quantity=2, unit=10)]
    result = run(db, scans, [character_read(money=GOLD, recipes=[recipe()])])

    [craft, flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity, flip.post_at) == (Action.SELL, 2, 249)
    assert craft.buys == (ReagentBuy(LINEN_KEY, 12, 250),)


def test_a_flip_to_crafts_sell_room_is_net_of_held_output_only(db):
    # 6 Bolts sell within the horizon and 2 are held, so 4 crafted ones Sell, posted under
    # the Bolt at 500 that's a Flip to Sell: that's another option, not bought (#86). A
    # 5th would Vendor for 15, less than its 2 Linen cost.
    scans = linen_and_bolts_selling()
    scans[1]["listings"].append(row(BOLT, unit=500))
    result = run(
        db,
        scans,
        [
            character_read(
                item(BOLT_LINK, count=2),
                money=GOLD,
                vendor_prices={2996: 15},
                recipes=[recipe()],
            )
        ],
    )

    [craft, flip] = result[MARKET].shopping_list
    assert (flip.item_key, flip.action, flip.quantity) == (BOLT_KEY, Action.SELL, 1)
    assert (craft.action, craft.quantity) == (Action.CRAFT, 4)
    assert craft.profit == pytest.approx(4 * 499 * 0.95 - 4 * 200)


def test_crafted_output_takes_the_sale_horizon_before_a_flip_to_sell(db):
    # #67: 12 held Linen craft the 6 Bolts that sell within the horizon, so the cheap
    # Bolt isn't bought to Sell.
    scans = linen_and_bolts_selling()
    scans[1]["listings"].append(row(BOLT, unit=500))
    result = run(db, scans, [character_read(item(count=12), money=GOLD, recipes=[recipe()])])

    craft = next(r for r in result[MARKET].holdings if r.action is Action.CRAFT)
    assert (craft.item_key, craft.quantity) == (BOLT_KEY, 6)
    assert result[MARKET].shopping_list == []


@pytest.mark.parametrize(("hours", "lost"), [(3, 0), (1, 2 * 150 + 2 * 300)])
def test_a_flip_to_crafts_output_loses_deposits_down_the_queue(db, hours, lost):
    # #78: 6 Bolts sell within the horizon, posted at 999 for 949.05 each, from 2 Linen
    # at 100. Each posting costs 150 (60% of the 250 Vendor Price): posted hourly, Bolts
    # 3-4 lose one first and 5-6 lose two, still clearing the margin and beating Vendor.
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(money=GOLD, vendor_prices={2996: 250}, recipes=[recipe()])],
        config=replace(CONFIG, post_duration_hours=hours),
    )

    [craft] = result[MARKET].shopping_list
    assert (craft.item_key, craft.action, craft.quantity) == (BOLT_KEY, Action.CRAFT, 6)
    assert craft.profit == pytest.approx(6 * (949.05 - 200) - lost)


@pytest.mark.parametrize(("bolt", "crafts"), [(1000, 6), (400, 6), (300, 0)])
def test_a_flip_to_craft_must_clear_the_flip_margin_on_its_gold(db, bolt, crafts):
    # 2 Linen at 100 a Bolt: 200 of gold needs 1 silver back. A Bolt at 400 Sells for 380
    # (180 profit), one at 300 for 285 (85).
    result = run(
        db,
        linen_and_bolts_selling(bolt=bolt),
        [character_read(money=GOLD, recipes=[recipe()])],
    )

    made = [r.quantity for r in result[MARKET].shopping_list if r.action is Action.CRAFT]
    assert sum(made) == crafts


@pytest.mark.parametrize(("sale_events", "crafts"), [(2, 0), (3, 6)])
def test_a_flip_to_crafts_output_sells_only_on_the_minimum_of_sale_events(db, sale_events, crafts):
    # #57: on 2 Sale Events a Bolt has no Sell room, and without a Vendor Price it's worth
    # nothing, so no Linen is bought for it.
    result = run(
        db,
        linen_and_bolts_selling(sale_events=sale_events),
        [character_read(money=GOLD, recipes=[recipe()])],
        config=replace(CONFIG, flip_min_sale_events=3),
    )

    made = [r.quantity for r in result[MARKET].shopping_list if r.action is Action.CRAFT]
    assert sum(made) == crafts


def test_a_flip_to_crafts_output_counts_only_the_sale_events_at_or_above_its_post_price(db):
    # #107: the Bolts sold at 500, but that stack is gone, maybe expired, and the output
    # would post at 999 under the 1000s. Nothing sold that high, so no Linen is bought.
    scans = [
        scan(
            T0 + n * HOUR,
            row(quantity=20 - 2 * n, unit=100),
            row(BOLT, quantity=20 - 2 * n, unit=500, time_left=4 if n < 3 else 1),
            row(BOLT, quantity=5, unit=1000),
        )
        for n in range(4)
    ]
    scans.append(scan(T0 + 4 * HOUR, row(quantity=12, unit=100), row(BOLT, quantity=5, unit=1000)))

    result = run(db, scans, [character_read(money=GOLD, recipes=[recipe()])])

    assert [r for r in result[MARKET].shopping_list if r.action is Action.CRAFT] == []


def test_flips_to_craft_plain_flips_and_prediction_buys_each_get_all_the_gold(db):
    # #86: 15 copper. A Bolt from 2 Linen at 5 (10 copper) and all 3 Ore to Vendor (15)
    # are both shown, and so is the Tin to Hold under its Prediction.
    tin = "item:2771::::::::20:1490"
    scans = linen_and_bolts_selling()
    scans[1]["listings"] += [row(quantity=2, unit=5), row(ORE, quantity=3, unit=5)]
    scans[1]["listings"].append(row(tin, unit=1))
    result = run(
        db,
        scans,
        [character_read(money=15, vendor_prices={2770: 6, 2771: 1}, recipes=[recipe()])],
        predictions=[prediction("2771")],
    )

    assert [(r.item_key, r.action, r.quantity) for r in result[MARKET].shopping_list] == [
        (BOLT_KEY, Action.CRAFT, 1),
        (ORE_KEY, Action.VENDOR, 3),
    ]
    assert [(r.item_key, r.quantity) for r in result[MARKET].prediction_buys] == [("2771", 1)]


def test_flips_to_craft_are_cut_apart_from_flips_to_sell_and_to_vendor(db):
    # #87: shopping_list_rows cuts the Tin and Ore to the Tin alone, and the Bolt, under
    # craft_list_rows, is still shown. One list, most profit first.
    tin = "item:2771::::::::20:1490"
    scans = linen_and_bolts_selling()
    scans[1]["listings"] += [row(quantity=2, unit=5), row(ORE, quantity=3, unit=5)]
    scans[1]["listings"].append(row(tin, quantity=3, unit=1))
    result = run(
        db,
        scans,
        [character_read(money=GOLD, vendor_prices={2770: 6, 2771: 3}, recipes=[recipe()])],
        config=replace(CONFIG, shopping_list_rows=1),
    )

    assert [(r.item_key, r.action, r.quantity) for r in result[MARKET].shopping_list] == [
        (BOLT_KEY, Action.CRAFT, 6),
        ("2771", Action.VENDOR, 3),
    ]


def test_craft_list_rows_cuts_the_flips_to_craft(db):
    # #87: two recipes make Bolts, from 2 Linen or from 3. Only the better one is shown.
    result = run(
        db,
        linen_and_bolts_selling(),
        [
            character_read(
                money=GOLD, recipes=[recipe(), recipe(recipe_id=2964, reagents=((2589, 3),))]
            )
        ],
        config=replace(CONFIG, craft_list_rows=1),
    )

    [craft] = result[MARKET].shopping_list
    assert craft.buys == (ReagentBuy(LINEN_KEY, 12, 100),)


def test_a_flip_to_craft_from_merchant_reagents_alone_is_bounded_by_gold(db):
    # A Bolt from 1 Thread at 10 Vendors for 125. With 1 silver of gold, only 10 crafts.
    result = run(
        db,
        linen_and_bolts_selling(),
        [
            character_read(
                money=100,
                vendor_prices={2996: 125},
                recipes=[recipe(reagents=[(2320, 1)])],
                merchant_costs={2320: 10},
            )
        ],
    )

    assert result[MARKET].shopping_list == [
        Row(
            BOLT_KEY,
            Action.CRAFT,
            10,
            profit=pytest.approx(6 * (949.05 - 10) + 4 * (125 - 10)),
            cost=100,
            note="on Kash-Patel: uses 10 of 2320 (buy 10)",
            character="Kash-Patel",
            buys=(ReagentBuy(THREAD_KEY, 10, 10, merchant=True),),
        )
    ]


def test_a_held_merchant_reagent_is_used_before_one_is_bought(db):
    # The Thread held goes into the first Bolt; the other 5 buy theirs from a merchant.
    result = run(
        db,
        linen_and_bolts_selling(),
        [
            character_read(
                item(THREAD_LINK),
                money=GOLD,
                recipes=[recipe(reagents=LINEN_AND_THREAD)],
                merchant_costs={2320: 10},
            )
        ],
    )

    [craft] = result[MARKET].shopping_list
    assert (craft.quantity, craft.cost) == (6, 6 * 200 + 5 * 10)
    assert craft.buys == (
        ReagentBuy(LINEN_KEY, 12, 100),
        ReagentBuy(THREAD_KEY, 5, 10, merchant=True),
    )


def test_held_reagents_a_flip_to_craft_would_use_all_keep_their_holdings_row(db):
    # #86 (was #69): 20 Thread held; the 6 Bolts would use 6, but they're only an option.
    result = run(
        db,
        linen_and_bolts_selling(),
        [
            character_read(
                item(THREAD_LINK, count=20),
                money=GOLD,
                recipes=[recipe(reagents=LINEN_AND_THREAD)],
                merchant_costs={2320: 10},
            )
        ],
    )

    [craft] = result[MARKET].shopping_list
    assert craft.uses == (ReagentUse(THREAD_KEY, 6),)
    assert result[MARKET].holdings == [Row(THREAD_KEY, None, 20, note="no data")]


@pytest.mark.parametrize(
    "item_key", [LINEN_KEY, BOLT_KEY], ids=["reagent under it", "output under it"]
)
def test_nothing_is_flipped_to_craft_from_or_into_a_predictions_item_keys(db, item_key):
    # Buying them would be a Prediction buy.
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(money=GOLD, recipes=[recipe()])],
        predictions=[prediction(item_key)],
    )

    assert result[MARKET].shopping_list == []


def test_a_reagent_without_market_data_is_bought_but_never_taken_from_held(db):
    # Ore has asks but no sales. The 2 held can't be valued, so both Bolts buy theirs.
    ore = "|cffffffff|Hitem:2770::::::::20:1490:::::::::|h[Copper Ore]|h|r"
    scans = linen_and_bolts_selling()
    scans[1]["listings"].append(row(ORE, quantity=4, unit=100))
    result = run(
        db,
        scans,
        [character_read(item(ore, count=2), money=GOLD, recipes=[recipe(reagents=[(2770, 2)])])],
    )

    [craft] = result[MARKET].shopping_list
    assert (craft.quantity, craft.note) == (2, "on Kash-Patel: uses 4 of 2770 (buy 4)")


def test_a_recipe_on_cooldown_or_with_unknown_bind_type_is_not_flipped_to_craft(db):
    result = run(
        db,
        linen_and_bolts_selling(),
        [
            character_read(
                money=GOLD,
                recipes=[recipe(cooldown=3 * HOUR), recipe(2964, bind_type=None)],
            )
        ],
    )

    assert result[MARKET].shopping_list == []


def test_a_cooldown_recipe_flips_to_craft_only_what_held_crafts_left_of_its_limit(db):
    # Two Characters are off cooldown. One Bolt is crafted from the 2 Linen held.
    ready = recipe(cooldown=30 * MINUTE)
    result = run(
        db,
        linen_and_bolts_selling(),
        [
            character_read(item(count=2), money=GOLD, recipes=[ready]),
            character_read(character="Alt-One", recipes=[ready]),
        ],
    )

    [craft] = result[MARKET].shopping_list
    assert craft.quantity == 1


# --- Sub-crafts (#33, ADR-0014) ---

ORE_LINK = "|cffffffff|Hitem:2770::::::::20:1490:::::::::|h[Copper Ore]|h|r"
BAR = "item:2840::::::::20:1490"
BAR_KEY = "2840"
SMELT = recipe(2657, output=2840, reagents=[(2770, 1)])
BOLT_FROM_BARS = recipe(2963, output=2996, reagents=[(2840, 2)])


def selling(*prices, sale_events=1):
    """Each (item string, unit) selling 2 an hour, as `sale_events` Sale Events an hour
    apart: 6 of each sell within the 3 h horizon, at a Fair Value of `unit`."""
    return [
        scan(T0 + n * HOUR, *(row(it, quantity=20 - 2 * n, unit=unit) for it, unit in prices))
        for n in range(sale_events + 1)
    ]


def test_a_chain_whose_first_step_loses_money_alone_is_crafted(db):
    # Ore Sells for 94.05 after the cut and a Bar only for 46.55, so smelting alone loses.
    # Two Bars make a Bolt that Sells for 949.05.
    result = run(
        db,
        selling((ORE, 100), (BAR, 50), (BOLT, 1000)),
        [character_read(item(ORE_LINK, count=2), recipes=[SMELT, BOLT_FROM_BARS])],
    )

    assert result[MARKET].holdings == [
        Row(
            BOLT_KEY,
            Action.SELL,
            1,
            price=999,
            profit=pytest.approx(949.05),
            sale_events=1,
            note="incl. 1 crafted",
        ),
        Row(
            BOLT_KEY,
            Action.CRAFT,
            1,
            profit=pytest.approx(949.05 - 2 * 94.05),
            note="on Kash-Patel: uses 2 of 2770, via 2 of 2840 on Kash-Patel",
            character="Kash-Patel",
            uses=(ReagentUse(ORE_KEY, 2),),
            via=(SubCraft(BAR_KEY, 2, "Kash-Patel"),),
        ),
    ]


BAR_LINK = "|cffffffff|Hitem:2840::::::::20:1490:::::::::|h[Copper Bar]|h|r"


def test_a_sub_craft_never_uses_an_item_key_already_on_its_path(db):
    # A made-up recipe turns 1 Bar into 2 Ore. Smelting one of them back into a Bar
    # would leave an Ore over for nothing, every time: Bar -> Ore -> Bar is refused.
    # Turning the Bar into Ore to Sell loses (949.05 for 2 x 94.05).
    unsmelt = recipe(9999, output=2770, reagents=[(2840, 1)], quantity=2)
    result = run(
        db,
        selling((ORE, 100), (BAR, 1000)),
        [character_read(item(BAR_LINK), recipes=[SMELT, unsmelt])],
    )

    assert [r for r in result[MARKET].holdings if r.action is Action.CRAFT] == []


BAG = "item:5762::::::::20:1490"
BAG_FROM_BOLT = recipe(2000, output=5762, reagents=[(2996, 1)])


@pytest.mark.parametrize(("depth", "crafts"), [(3, 1), (2, 0)])
def test_a_chain_is_at_most_craft_chain_depth_crafts_deep(db, depth, crafts):
    # Ore -> Bar -> Bolt -> Bag is 3 crafts deep. Only the Bag pays for the 2 Ore.
    result = run(
        db,
        selling((ORE, 100), (BAR, 50), (BOLT, 150), (BAG, 1000)),
        [character_read(item(ORE_LINK, count=2), recipes=[SMELT, BOLT_FROM_BARS, BAG_FROM_BOLT])],
        config=replace(CONFIG, craft_chain_depth=depth),
    )

    made = [r for r in result[MARKET].holdings if r.action is Action.CRAFT]
    assert [(r.item_key, r.quantity) for r in made] == ([("5762", 1)] if crafts else [])
    if crafts:
        assert made[0].via == (
            SubCraft(BAR_KEY, 2, "Kash-Patel"),
            SubCraft(BOLT_KEY, 1, "Kash-Patel"),
        )
        assert made[0].note == (
            "on Kash-Patel: uses 2 of 2770, via 2 of 2840 on Kash-Patel, 1 of 2996 on Kash-Patel"
        )


def test_a_reagent_without_market_data_is_sub_crafted_but_its_held_units_are_not_used(db):
    # Bars were never seen on the Auction House, so the 2 held can't be valued and stay
    # put. Smelting 2 Ore into Bars for the Bolt doesn't need a Bar's value.
    result = run(
        db,
        selling((ORE, 100), (BOLT, 1000)),
        [
            character_read(
                item(ORE_LINK, count=2),
                item(BAR_LINK, count=2),
                recipes=[SMELT, BOLT_FROM_BARS],
            )
        ],
    )

    holdings = result[MARKET].holdings
    [craft] = [r for r in holdings if r.action is Action.CRAFT]
    assert craft.via == (SubCraft(BAR_KEY, 2, "Kash-Patel"),)
    assert craft.uses == (ReagentUse(ORE_KEY, 2),)
    assert craft.profit == pytest.approx(949.05 - 2 * 94.05)
    assert Row(BAR_KEY, None, 2, note="no data") in holdings


def test_a_cooldown_sub_recipes_limit_is_shared_by_every_chain(db):
    # Smelting is ready on one Character, so once. Bars have no market data, so a Bolt
    # (from 1 Bar) can only come through smelting: one Bolt from the 4 Ore held, and no
    # Flip to Craft buying Ore to smelt more.
    result = run(
        db,
        selling((ORE, 100), (BOLT, 1000)),
        [
            character_read(
                item(ORE_LINK, count=4),
                money=GOLD,
                recipes=[
                    recipe(2657, output=2840, reagents=[(2770, 1)], cooldown=30 * MINUTE),
                    recipe(2963, output=2996, reagents=[(2840, 1)]),
                ],
            )
        ],
    )

    [craft] = [r for r in result[MARKET].holdings if r.action is Action.CRAFT]
    assert (craft.quantity, craft.via) == (1, (SubCraft(BAR_KEY, 1, "Kash-Patel"),))
    assert [r for r in result[MARKET].shopping_list if r.action is Action.CRAFT] == []


SMELT_TWO = recipe(2657, output=2840, reagents=[(2770, 1)], quantity=2)
BOLT_FROM_BAR = recipe(2963, output=2996, reagents=[(2840, 1)])


def test_a_sub_crafts_leftover_joins_the_crafted_holdings(db):
    # A smelt makes 2 Bars and the Bolt needs 1: the other Sells for 46.55, which the
    # craft's gain counts.
    result = run(
        db,
        selling((ORE, 100), (BAR, 50), (BOLT, 1000)),
        [character_read(item(ORE_LINK), recipes=[SMELT_TWO, BOLT_FROM_BAR])],
    )

    holdings = result[MARKET].holdings
    [craft] = [r for r in holdings if r.action is Action.CRAFT]
    assert craft.profit == pytest.approx(949.05 - 94.05 + 46.55)
    assert (
        Row(
            BAR_KEY,
            Action.SELL,
            1,
            price=49,
            profit=pytest.approx(46.55),
            sale_events=1,
            note="incl. 1 crafted",
        )
        in holdings
    )


def test_a_flip_to_crafts_sub_craft_leftovers_are_no_holdings(db):
    # Bars have no market data, so each Bolt smelts 1 Ore bought at 100 and leaves a Bar.
    # Those Bars are only made if the option is taken, so they're no Holdings (#86).
    result = run(
        db,
        selling((ORE, 100), (BOLT, 1000)),
        [character_read(money=GOLD, recipes=[SMELT_TWO, BOLT_FROM_BAR])],
    )

    [craft] = result[MARKET].shopping_list
    assert (craft.quantity, craft.via) == (6, (SubCraft(BAR_KEY, 6, "Kash-Patel"),))
    assert craft.buys == (ReagentBuy(ORE_KEY, 6, 100),)
    assert result[MARKET].holdings == []


@pytest.mark.parametrize(
    ("bar", "buys", "via"),
    [
        (300, ReagentBuy(ORE_KEY, 12, 100), (SubCraft(BAR_KEY, 12, "Kash-Patel"),)),
        (90, ReagentBuy(BAR_KEY, 12, 90), ()),
    ],
    ids=["ore is cheaper", "bars are cheaper"],
)
def test_a_flip_to_craft_buys_whichever_of_the_reagent_or_its_sub_craft_costs_less(
    db, bar, buys, via
):
    result = run(
        db,
        selling((ORE, 100), (BAR, bar), (BOLT, 1000)),
        [character_read(money=GOLD, recipes=[SMELT, BOLT_FROM_BARS])],
    )

    [craft] = [r for r in result[MARKET].shopping_list if r.item_key == BOLT_KEY]
    assert (craft.quantity, craft.buys, craft.via) == (6, (buys,), via)


@pytest.mark.parametrize(
    ("smelt", "config"),
    [
        (SMELT, replace(CONFIG, craft_chain_depth=1)),
        (recipe(2657, output=2840, reagents=[(2770, 1)], cooldown=3 * HOUR), CONFIG),
    ],
    ids=["no chains", "smelt on cooldown"],
)
def test_a_reagent_without_market_data_that_cant_be_sub_crafted_blocks_the_recipe(
    db, smelt, config
):
    result = run(
        db,
        selling((ORE, 100), (BOLT, 1000)),
        [character_read(item(BAR_LINK, count=2), recipes=[smelt, BOLT_FROM_BARS])],
        config=config,
    )

    [craft] = [r for r in result[MARKET].holdings if r.item_key == BOLT_KEY]
    assert craft.blocked == Blocked(BlockReason.NO_DATA, BAR_KEY)


# --- Craft Chain (#77) ---


def contributions(nodes):
    """The gold of every node but a Craft, which only sums its sources: these add up to
    the row's Profit."""
    return sum(
        (0 if n.kind is NodeKind.CRAFT else n.gold) + contributions(n.children) for n in nodes
    )


def test_a_craft_actions_chain_is_its_exit_over_the_craft_over_the_held_reagents(db):
    # As in test_held_reagents_are_crafted_when_the_output_is_worth_more.
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(count=2), vendor_prices={2589: 10}, recipes=[recipe()])],
    )

    [craft] = [r for r in result[MARKET].holdings if r.action is Action.CRAFT]
    use = ChainNode(NodeKind.USE, LINEN_KEY, 2, pytest.approx(-2 * 94.05))
    top = ChainNode(
        NodeKind.CRAFT,
        BOLT_KEY,
        1,
        pytest.approx(-2 * 94.05),
        (use,),
        crafts=1,
        character="Kash-Patel",
    )
    assert craft.chain == (
        ChainNode(
            NodeKind.SELL,
            BOLT_KEY,
            1,
            pytest.approx(949.05),
            (top,),
            post_at=999,
            cut=pytest.approx(999 * 0.05),
            deposit=pytest.approx(0),
            effort=0,
        ),
    )
    assert contributions(craft.chain) == pytest.approx(craft.profit)


def test_a_flip_to_crafts_chain_uses_the_held_reagents_and_buys_the_rest(db):
    # As in test_a_flip_to_craft_buys_only_the_reagents_held_ones_dont_cover.
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(), money=GOLD, recipes=[recipe()])],
    )

    [craft] = result[MARKET].shopping_list
    [sell] = craft.chain
    assert (sell.kind, sell.quantity, sell.post_at) == (NodeKind.SELL, 6, 999)
    assert sell.gold == pytest.approx(6 * 949.05)
    [top] = sell.children
    assert (top.kind, top.quantity, top.crafts) == (NodeKind.CRAFT, 6, 6)
    assert [(n.kind, n.item_key, n.quantity, n.max_unit_price) for n in top.children] == [
        (NodeKind.USE, LINEN_KEY, 1, None),
        (NodeKind.BUY, LINEN_KEY, 11, 100),
    ]
    assert [n.gold for n in top.children] == [pytest.approx(-94.05), -1100]
    assert contributions(craft.chain) == pytest.approx(craft.profit)


def test_a_craft_whose_output_outruns_the_sale_horizon_exits_by_sell_and_vendor(db):
    # A made-up recipe makes 10 Bolts from 2 Linen: 6 Sell within the horizon, 4 Vendor.
    result = run(
        db,
        linen_and_bolts_selling(),
        [
            character_read(
                item(count=2),
                vendor_prices={2589: 10, 2996: 15},
                recipes=[recipe(quantity=10)],
            )
        ],
    )

    [craft] = [r for r in result[MARKET].holdings if r.action is Action.CRAFT]
    sell, vendor = craft.chain
    assert (sell.kind, sell.quantity, sell.children) == (NodeKind.SELL, 6, ())
    assert sell.gold == pytest.approx(6 * 949.05)
    assert (vendor.kind, vendor.quantity, vendor.gold) == (NodeKind.VENDOR, 4, 60)
    [top] = vendor.children
    assert (top.kind, top.quantity, top.crafts) == (NodeKind.CRAFT, 10, 1)
    assert contributions(craft.chain) == pytest.approx(craft.profit)


def test_a_sub_craft_is_a_craft_node_over_its_own_sources_and_leftover(db):
    # As in test_a_sub_crafts_leftover_joins_the_crafted_holdings: the smelt makes 2 Bars
    # from the held Ore, 1 goes into the Bolt and the other Sells for 46.55.
    result = run(
        db,
        selling((ORE, 100), (BAR, 50), (BOLT, 1000)),
        [character_read(item(ORE_LINK), recipes=[SMELT_TWO, BOLT_FROM_BAR])],
    )

    [craft] = [r for r in result[MARKET].holdings if r.action is Action.CRAFT]
    [sell] = craft.chain
    [top] = sell.children
    [smelt] = top.children
    assert (smelt.kind, smelt.item_key, smelt.quantity, smelt.crafts, smelt.character) == (
        NodeKind.CRAFT,
        BAR_KEY,
        2,
        1,
        "Kash-Patel",
    )
    assert [(n.kind, n.item_key, n.quantity) for n in smelt.children] == [
        (NodeKind.USE, ORE_KEY, 1),
        (NodeKind.LEFTOVER, BAR_KEY, 1),
    ]
    assert [n.gold for n in smelt.children] == [pytest.approx(-94.05), pytest.approx(46.55)]
    assert smelt.gold == top.gold == pytest.approx(-94.05 + 46.55)
    assert contributions(craft.chain) == pytest.approx(craft.profit)


def test_a_merchant_reagents_held_and_bought_units_are_a_use_and_a_merchant_node(db):
    # As in test_merchant_reagents_cost_their_merchant_cost_and_missing_ones_are_bought.
    result = run(
        db,
        linen_and_bolts_selling(),
        [
            character_read(
                item(count=4),
                item(THREAD_LINK),
                recipes=[recipe(reagents=LINEN_AND_THREAD)],
                merchant_costs={2320: 10},
            )
        ],
    )

    [craft] = [r for r in result[MARKET].holdings if r.action is Action.CRAFT]
    [top] = craft.chain[0].children
    assert [(n.kind, n.item_key, n.quantity, n.gold) for n in top.children] == [
        (NodeKind.USE, LINEN_KEY, 4, pytest.approx(-4 * 94.05)),
        (NodeKind.USE, THREAD_KEY, 1, -10),
        (NodeKind.MERCHANT, THREAD_KEY, 1, -10),
    ]
    assert contributions(craft.chain) == pytest.approx(craft.profit)


def test_a_blocked_crafts_chain_is_one_craft_with_the_blocking_reagent_marked(db):
    # As in test_a_reagent_without_market_data_that_cant_be_sub_crafted_blocks_the_recipe.
    result = run(
        db,
        selling((ORE, 100), (BOLT, 1000)),
        [character_read(item(BAR_LINK, count=2), recipes=[BOLT_FROM_BARS])],
    )

    [craft] = [r for r in result[MARKET].holdings if r.item_key == BOLT_KEY]
    blocked = Blocked(BlockReason.NO_DATA, BAR_KEY)
    assert craft.chain == (
        ChainNode(
            NodeKind.CRAFT,
            BOLT_KEY,
            1,
            None,
            (ChainNode(NodeKind.USE, BAR_KEY, 2, None, blocked=blocked),),
            crafts=1,
            character="Kash-Patel",
        ),
    )


def test_a_craft_of_unknown_bind_type_is_blocked_on_its_craft_node(db):
    result = run(
        db,
        linen_and_bolts_selling(),
        [character_read(item(count=2), recipes=[recipe(bind_type=None)])],
    )

    [craft] = [r for r in result[MARKET].holdings if r.action is Action.CRAFT]
    [top] = craft.chain
    assert (top.kind, top.crafts, top.blocked) == (
        NodeKind.CRAFT,
        1,
        Blocked(BlockReason.UNKNOWN_BIND_TYPE),
    )
    [use] = top.children
    assert (use.kind, use.quantity, use.gold) == (NodeKind.USE, 2, pytest.approx(-2 * 94.05))
    assert top.gold == use.gold


# --- Predictions (#26) ---

TODAY = date.fromtimestamp(T0)


def prediction(*item_keys, name="Linen spike", written=TODAY, lapse=None, happened=None):
    return Prediction(
        name=name,
        reason="Tailoring quests",
        item_keys=item_keys,
        catalyst="Phase 2",
        written=written,
        lapse=lapse or written + timedelta(weeks=8),
        happened=happened,
    )


def test_held_units_of_a_predictions_item_keys_are_held_under_it(db):
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), money=GOLD, vendor_prices={2589: 10})],
        predictions=[prediction(LINEN_KEY)],
    )

    # The gold they tie up is what letting them go would bring today: 6 Sold at 94.05 after
    # the cut and 4 Vendored at 10.
    assert result[MARKET].holdings == [
        Row(
            LINEN_KEY,
            Action.HOLD,
            10,
            cost=pytest.approx(6 * 94.05 + 4 * 10),
            prediction="Linen spike",
        )
    ]


@pytest.mark.parametrize(
    ("ended", "prediction_"),
    [
        (False, prediction(LINEN_KEY, lapse=TODAY)),  # its last day
        (True, prediction(LINEN_KEY, written=TODAY - timedelta(weeks=9))),  # Lapsed
        (True, prediction(LINEN_KEY, happened=TODAY)),
        (False, prediction(LINEN_KEY, happened=TODAY + timedelta(days=1))),
    ],
    ids=["lapses today", "lapsed", "catalyst happened", "catalyst still to come"],
)
def test_a_prediction_ends_when_its_catalyst_happens_or_it_lapses(db, ended, prediction_):
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), money=GOLD, vendor_prices={2589: 10})],
        predictions=[prediction_],
    )

    # Once it ends, the units go to their best Action without it.
    actions = [r.action for r in result[MARKET].holdings]
    assert actions == ([Action.SELL, Action.VENDOR] if ended else [Action.HOLD])


def test_units_held_since_a_prediction_was_written_tie_up_their_written_day_cost(db):
    # Written the day after the first Scans, when the 10 Linen held would have brought 604
    # (6 Sold at 94.05 and 4 Vendored at 10). Linen has since gone to 500, so letting them
    # go today would bring 2884.30, but they tie up the 604. 15% of 41s fits 604, not 2884.
    written = date.fromtimestamp(T0 + HOUR) + timedelta(days=1)
    later = T0 + 3 * DAY
    result = run(
        db,
        [
            *selling_two_linen_an_hour(),
            scan(later, row(quantity=20, unit=500)),
            scan(later + HOUR, row(quantity=18, unit=500)),
        ],
        [character_read(item(count=10), money=4100, vendor_prices={2589: 10})],
        predictions=[prediction(LINEN_KEY, written=written)],
    )

    assert result[MARKET].holdings == [
        Row(LINEN_KEY, Action.HOLD, 10, cost=604, prediction="Linen spike")
    ]


def test_held_units_over_the_cap_go_to_their_best_action_cheapest_exit_held_first(db):
    # 15% of 16s is 2s 40c. The 4 unbound units a vendor would take (10 each) fit first,
    # then 2 of the 6 that would Sell (94.05 each): 2s 28c. Bound units can't be sold after
    # the Catalyst either, so they're never Held.
    result = run(
        db,
        selling_two_linen_an_hour(),
        [
            character_read(
                item(count=10), item(count=3, bound=True), money=1600, vendor_prices={2589: 10}
            )
        ],
        predictions=[prediction(LINEN_KEY)],
    )

    assert result[MARKET].holdings == [
        Row(
            LINEN_KEY,
            Action.SELL,
            4,
            price=99,
            profit=pytest.approx(4 * 99 * 0.95),
            margin=pytest.approx(99 * 0.95 - 10),
            sale_events=1,
        ),
        Row(LINEN_KEY, Action.VENDOR, 3, price=10, profit=30),
        Row(
            LINEN_KEY,
            Action.HOLD,
            6,
            cost=pytest.approx(4 * 10 + 2 * 94.05),
            prediction="Linen spike",
        ),
    ]


def test_a_prediction_buys_only_units_whose_max_loss_is_at_most_10_percent_of_cost(db):
    # No Sell Rate, so a unit's exit without the Prediction is the 95 a vendor pays. At 100
    # it could lose 5 and at 105, 10, both within 10%; at 120 it could lose 25.
    result = run(
        db,
        [scan(T0, row(quantity=5, unit=100), row(quantity=5, unit=105), row(quantity=5, unit=120))],
        [character_read(money=GOLD, vendor_prices={2589: 95})],
        predictions=[prediction(LINEN_KEY)],
    )

    assert result[MARKET].prediction_buys == [
        Row(
            LINEN_KEY,
            Action.HOLD,
            10,
            price=105,
            cost=5 * 100 + 5 * 105,
            max_loss=5 * 5 + 5 * 10,
            prediction="Linen spike",
        )
    ]
    assert result[MARKET].prediction_cost == 1025


def test_under_a_prediction_its_item_keys_are_bought_to_hold_not_flipped(db):
    # 6 sell within the horizon. Without the Prediction the two 700s are a Flip posted at
    # 999 for 949.05 (the Max Loss is negative), and 4 of the 1000s would resell the same,
    # losing 50.95 each. Beyond the horizon there's no exit, so nothing more is bought.
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=2, unit=700), unit=1000),
        [character_read(money=GOLD)],
        predictions=[prediction(LINEN_KEY)],
    )

    assert result[MARKET].shopping_list == []
    assert result[MARKET].prediction_buys == [
        Row(
            LINEN_KEY,
            Action.HOLD,
            6,
            price=1000,
            cost=2 * 700 + 4 * 1000,
            max_loss=pytest.approx(2 * -249.05 + 4 * 50.95),
            prediction="Linen spike",
        )
    ]


@pytest.mark.parametrize(("hours", "bought"), [(3, 6), (1, 2)])
def test_a_buys_exit_is_a_resale_less_the_deposits_it_would_lose(db, hours, bought):
    # #78: as above, but each posting costs 60 (60% of a 100 Vendor Price). Posted
    # hourly, the first 1000 would be third in the queue and lose one first: its Max Loss
    # of 110.95 is more than 10% of it.
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=2, unit=700), unit=1000),
        [character_read(money=GOLD, vendor_prices={2589: 100})],
        predictions=[prediction(LINEN_KEY)],
        config=replace(CONFIG, post_duration_hours=hours),
    )

    [buy] = result[MARKET].prediction_buys
    assert buy.quantity == bought
    assert buy.max_loss == pytest.approx(2 * -249.05 + (bought - 2) * 50.95)


def test_a_buys_exit_is_never_a_resale_above_what_a_merchant_charges(db):
    # #63: as above, but a merchant sells Linen for 800, so a resale brings in 760. The
    # 700s gain 60 each; a 1000 would lose 240, more than 10% of it.
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=2, unit=700), unit=1000),
        [character_read(money=GOLD, merchant_costs={2589: 800})],
        predictions=[prediction(LINEN_KEY)],
    )

    [buy] = result[MARKET].prediction_buys
    assert (buy.quantity, buy.cost) == (2, 1400)
    assert buy.max_loss == pytest.approx(2 * -60)


def test_a_prediction_buys_only_below_the_merchant_cost_after_the_cut(db):
    # #91: a merchant sells Linen for 100, so no Sell fetches more than 95. A vendor pays
    # 95, so every unit's Max Loss is within 10%, but only the 94s are under the 95.
    result = run(
        db,
        [scan(T0, row(quantity=5, unit=94), row(quantity=5, unit=95), row(quantity=5, unit=96))],
        [character_read(money=GOLD, vendor_prices={2589: 95}, merchant_costs={2589: 100})],
        predictions=[prediction(LINEN_KEY)],
    )

    [buy] = result[MARKET].prediction_buys
    assert (buy.quantity, buy.cost) == (5, 5 * 94)


def test_held_units_take_the_sale_horizon_first_when_pricing_a_buys_exit(db):
    # 6 sell within the horizon, and the 4 held would go first if the Prediction is wrong,
    # so only 2 of the 100s could be resold, posted at 99 under the rest for 94.05.
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=4), money=GOLD)],
        predictions=[prediction(LINEN_KEY)],
    )

    [buy] = result[MARKET].prediction_buys
    assert buy.quantity == 2
    assert buy.max_loss == pytest.approx(2 * 5.95)


@pytest.mark.parametrize(("sale_events", "bought"), [(2, 0), (3, 6)])
def test_a_buys_exit_is_sell_only_on_the_minimum_of_sale_events(db, sale_events, bought):
    # #57: on 3 Sale Events 6 of the 100s could be resold at 95, losing 5 each. On 2 there
    # is no Sell, and without a Vendor Price each could lose all 100.
    result = run(
        db,
        selling_two_linen_an_hour(sale_events=sale_events),
        [character_read(money=GOLD)],
        config=replace(CONFIG, flip_min_sale_events=3),
        predictions=[prediction(LINEN_KEY)],
    )

    assert sum(r.quantity for r in result[MARKET].prediction_buys) == bought


def test_a_prediction_buys_max_loss_counts_only_the_sale_events_at_or_above_the_resale(db):
    # #107: the Linen sold at 500, but that stack is gone, maybe expired, and resold under
    # the 1000s it would post at 999. Nothing sold that high, so without the Prediction a
    # 700 only Vendors for 650, losing 50. The 1000s would lose 350, too much to buy.
    scans = [
        scan(
            T0 + n * HOUR,
            row(quantity=20 - 2 * n, unit=500, time_left=4 if n < 3 else 1),
            row(quantity=5, unit=1000),
        )
        for n in range(4)
    ]
    scans.append(scan(T0 + 4 * HOUR, row(quantity=5, unit=1000), row(quantity=2, unit=700)))

    result = run(
        db,
        scans,
        [character_read(money=GOLD, vendor_prices={2589: 650})],
        predictions=[prediction(LINEN_KEY)],
    )

    assert result[MARKET].prediction_buys == [
        Row(
            LINEN_KEY,
            Action.HOLD,
            2,
            price=700,
            cost=2 * 700,
            max_loss=2 * 50,
            prediction="Linen spike",
        )
    ]


def test_held_units_count_toward_a_predictions_cap_before_it_buys(db):
    # 15% of 1g is 15s. The 3 Ore held would Vendor for 1s each today, so 12s is left for
    # Linen at 1s, which can lose 5c each against the 95c a vendor pays.
    ore = "|cffffffff|Hitem:2770::::::::20:1490:::::::::|h[Copper Ore]|h|r"
    result = run(
        db,
        [scan(T0, row(quantity=20, unit=100))],
        [character_read(item(ore, count=3), money=10000, vendor_prices={2589: 95, 2770: 100})],
        predictions=[prediction(LINEN_KEY, ORE_KEY)],
    )

    assert result[MARKET].holdings == [
        Row(ORE_KEY, Action.HOLD, 3, cost=300, prediction="Linen spike")
    ]
    assert result[MARKET].prediction_buys == [
        Row(
            LINEN_KEY,
            Action.HOLD,
            12,
            price=100,
            cost=1200,
            max_loss=12 * 5,
            prediction="Linen spike",
        )
    ]


def test_prediction_buys_go_lowest_max_loss_first_within_the_total_cap(db):
    # A total cap of 20% of 1g: 20s across both Predictions, each capped at 15s. Ore can
    # lose 2% of its cost and Linen 5%, so Ore fills its 15s first and Linen gets the 5s
    # left.
    result = run(
        db,
        [scan(T0, row(quantity=20, unit=100), row(ORE, quantity=20, unit=100))],
        [character_read(money=10000, vendor_prices={2589: 95, 2770: 98})],
        config=replace(CONFIG, predictions_cap_share=0.2),
        predictions=[prediction(LINEN_KEY), prediction(ORE_KEY, name="Ore spike")],
    )

    assert result[MARKET].prediction_buys == [
        Row(ORE_KEY, Action.HOLD, 15, price=100, cost=1500, max_loss=30, prediction="Ore spike"),
        Row(LINEN_KEY, Action.HOLD, 5, price=100, cost=500, max_loss=25, prediction="Linen spike"),
    ]


@pytest.mark.parametrize(("budget", "units"), [(None, 7), (100, 5)])
def test_prediction_buys_get_the_budget_whatever_the_shopping_list_shows(db, budget, units):
    # #86: of 10s, the Ore Flip to Vendor would take 9s, but it's an option. The
    # Prediction's cap is 1s 50c, so 7 Linen at 20c, or 5 within a 1s Budget.
    result = run(
        db,
        [scan(T0, row(ORE, quantity=9, unit=100), row(quantity=20, unit=20))],
        [character_read(money=1000, vendor_prices={2589: 19, 2770: 200}, budget=budget)],
        predictions=[prediction(LINEN_KEY)],
    )

    [buy] = result[MARKET].prediction_buys
    assert (buy.quantity, buy.cost) == (units, units * 20)


# --- Unlinked Sold Outcomes (#27) ---


def sold_mail(name, price=500):
    return {
        "index": 1,
        "sender": "Alliance Auction House",
        "subject": f"Auction successful: {name}",
        "money": price,
        "daysLeft": 29.5,
        "invoice": {"invoiceType": "seller", "itemName": name, "bid": price, "count": 1},
    }


def test_the_market_counts_sold_outcomes_that_cant_be_linked_to_an_item_key(db):
    named = row(own=True) | {"name": "Linen Cloth"}
    mails = [sold_mail("Linen Cloth"), sold_mail("Tigerseye")]
    mailbox_read = {
        "readAt": T0 + HOUR,
        "realm": REALM,
        "character": "Kash-Patel",
        "shownCount": 2,
        "totalCount": 2,
        "skippedMails": 0,
        "mails": mails,
    }
    markets = run(db, [scan(T0, named)], [character_read()], mailbox_reads=[mailbox_read])
    assert markets[MARKET].unlinked_sales == 1


# --- Prediction-held Lots (#27) ---


def test_units_held_when_a_prediction_is_written_are_costed_at_that_days_best_exit(db):
    # Written the day after these Scans and Read; later ones must not count.
    written = date.fromtimestamp(T0 + HOUR) + timedelta(days=1)
    later = T0 + 3 * DAY
    run(
        db,
        [
            *selling_two_linen_an_hour(),
            scan(later, row(quantity=20, unit=500)),
            scan(later + HOUR, row(quantity=18, unit=500)),
        ],
        [
            character_read(item(count=10), vendor_prices={2589: 10}),
            character_read(item(count=30), at=later),
        ],
    )

    # As in the Hold test: 6 Sold at 94.05 after the cut and 4 Vendored at 10, 604.30.
    assert held_at_writing(db, CONFIG, MARKET, [prediction(LINEN_KEY, written=written)]) == [
        Held("Linen spike", LINEN_KEY, units=10, cost=604)
    ]


def test_a_best_exit_is_valued_with_nothing_on_that_scans_shopping_list_bought(db):
    # #86: on the written day the two 700s were a Flip to Sell, but as held units are now,
    # the 4 are posted under the 700s at 699, 664.05 after the cut, not under the 1000s.
    # The later Scans at 500 must not count.
    written = date.fromtimestamp(T0 + HOUR) + timedelta(days=1)
    later = T0 + 3 * DAY
    run(
        db,
        [
            *selling_two_linen_an_hour(row(quantity=2, unit=700), unit=1000),
            scan(later, row(quantity=20, unit=500)),
            scan(later + HOUR, row(quantity=18, unit=500)),
        ],
        [character_read(item(count=4), money=GOLD, vendor_prices={2589: 10})],
    )

    assert held_at_writing(db, CONFIG, MARKET, [prediction(LINEN_KEY, written=written)]) == [
        Held("Linen spike", LINEN_KEY, units=4, cost=2656)  # 4 * 664.05
    ]


def test_a_best_exit_is_never_a_sale_above_what_a_merchant_charges(db):
    # #63: Fair Value is 100, but a merchant sells Linen for 80, so 6 Sell at 76.
    run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), vendor_prices={2589: 10}, merchant_costs={2589: 80})],
    )

    written = date.fromtimestamp(T0 + HOUR) + timedelta(days=1)
    assert held_at_writing(db, CONFIG, MARKET, [prediction(LINEN_KEY, written=written)]) == [
        Held("Linen spike", LINEN_KEY, units=10, cost=6 * 76 + 4 * 10)
    ]


# --- Frozen in grades.toml (#66) ---


def freezing(tmp_path):
    return replace(CONFIG, grades_path=tmp_path / "grades.toml")


def worth_nothing(*args):
    return 0.0


def valued_at_nothing(conn, config, market, held, at, bound=None):
    return dict.fromkeys(held, 0.0)


def test_a_held_at_writing_cost_is_frozen_once_its_day_has_passed(db, tmp_path, monkeypatch):
    # The same held units as the first held-at-writing test (604). Later, the pricing
    # changes, and the cost recorded then must stand.
    written = date.fromtimestamp(T0 + HOUR) + timedelta(days=1)
    later = T0 + 3 * DAY
    run(
        db,
        [*selling_two_linen_an_hour(), scan(later, row(quantity=20, unit=500))],
        [character_read(item(count=10), vendor_prices={2589: 10})],
    )
    config = freezing(tmp_path)
    p = prediction(LINEN_KEY, written=written)
    assert held_at_writing(db, config, MARKET, [p]) == [Held("Linen spike", LINEN_KEY, 10, 604)]

    monkeypatch.setattr("brain.recommend._exit_value", worth_nothing)

    assert held_at_writing(db, config, MARKET, [p]) == [Held("Linen spike", LINEN_KEY, 10, 604)]


def test_a_held_at_writing_cost_is_not_frozen_before_a_scan_after_its_day(
    db, tmp_path, monkeypatch
):
    # Written the day after the last Scan: a Scan or a Read from its day may still come.
    run(db, selling_two_linen_an_hour(), [character_read(item(count=10), vendor_prices={2589: 10})])
    config = freezing(tmp_path)
    p = prediction(LINEN_KEY, written=date.fromtimestamp(T0 + HOUR) + timedelta(days=1))
    held_at_writing(db, config, MARKET, [p])

    monkeypatch.setattr("brain.recommend._exit_value", worth_nothing)

    assert held_at_writing(db, config, MARKET, [p]) == [Held("Linen spike", LINEN_KEY, 10, 0)]


def test_a_grade_is_frozen_once_worked_out(db, tmp_path, monkeypatch):
    written = TODAY + timedelta(days=1)
    p = prediction(LINEN_KEY, written=written, happened=written + timedelta(days=1))
    now = start_of(written + timedelta(days=2)) + 3 * HOUR
    run(
        db,
        [*selling_two_linen_an_hour(), scan(now, row(quantity=20))],
        [character_read(item(count=10), vendor_prices={2589: 10})],
    )
    config = freezing(tmp_path)
    [grade] = grades(db, config, MARKET, [p], now)
    assert grade.open_value > 0

    monkeypatch.setattr("brain.recommend.exit_values", valued_at_nothing)

    assert grades(db, config, MARKET, [p], now + DAY) == [grade]


def test_a_frozen_grade_outlives_the_history_it_was_worked_out_from(db, other_db, tmp_path):
    # grades.toml is kept apart from the history, which `brain rebuild` recreates (ADR-0005).
    written = TODAY + timedelta(days=1)
    p = prediction(LINEN_KEY, written=written, happened=written + timedelta(days=1))
    now = start_of(written + timedelta(days=2)) + 3 * HOUR
    run(
        db,
        [*selling_two_linen_an_hour(), scan(now, row(quantity=20))],
        [character_read(item(count=10), vendor_prices={2589: 10})],
    )
    config = freezing(tmp_path)
    [grade] = grades(db, config, MARKET, [p], now)
    assert grade.cost > 0

    assert grades(other_db, config, MARKET, [p], now) == [grade]


def test_a_grade_is_not_frozen_before_a_scan_at_its_grading_moment(db, tmp_path, monkeypatch):
    # A Scan or a Read from before the grading moment may still come.
    run(db, selling_two_linen_an_hour(), [character_read(item(count=10), vendor_prices={2589: 10})])
    config = freezing(tmp_path)
    written = TODAY + timedelta(days=1)
    p = prediction(LINEN_KEY, written=written, happened=written + timedelta(days=1))
    now = start_of(written + timedelta(days=2)) + 3 * HOUR
    grades(db, config, MARKET, [p], now)

    monkeypatch.setattr("brain.recommend.exit_values", valued_at_nothing)

    [grade] = grades(db, config, MARKET, [p], now)
    assert grade.open_value == 0


# --- Grading (#27) ---


def mailbox_read(read_at, mail):
    return {
        "readAt": read_at,
        "realm": REALM,
        "character": "Kash-Patel",
        "shownCount": 1,
        "totalCount": 1,
        "skippedMails": 0,
        "mails": [mail],
    }


def linen_sold(read_at, count, price):
    """A Mailbox Read with one Sold Outcome of Linen that arrived 12 hours before it. Its
    money is the price after the cut plus a refunded deposit, which grading must not use."""
    invoice = {"invoiceType": "seller", "itemName": "Linen Cloth", "bid": price, "count": count}
    mail = sold_mail("Linen Cloth", round(price * 0.95) + 60) | {"invoice": invoice}
    return mailbox_read(read_at, mail)


def test_a_prediction_is_graded_on_its_sales_and_its_open_units_best_exit_at_the_moment(db):
    # Written the day after these Scans with 10 Linen held (6 Sold at 94.05, 4 Vendored at
    # 10: 604), its Catalyst happens the next day. 2 sell at 300 while it stands. At the
    # grading moment, 3 hours on, the 8 left are worth what they were then: 6 Sold at 94.05
    # and 2 Vendored at 10. The Scans after the grading moment must not count.
    named = row(own=True) | {"name": "Linen Cloth"}
    written = date.fromtimestamp(T0 + HOUR) + timedelta(days=1)
    ended = start_of(written + timedelta(days=1))
    later = ended + DAY
    run(
        db,
        [
            scan(T0, row(quantity=20), named),
            scan(T0 + HOUR, row(quantity=18), named),
            scan(later, row(quantity=20, unit=500)),
            scan(later + HOUR, row(quantity=18, unit=500)),
        ],
        [character_read(item(count=10), vendor_prices={2589: 10})],
        mailbox_reads=[linen_sold(start_of(written) + 18 * HOUR, count=2, price=600)],
    )
    p = prediction(LINEN_KEY, written=written, happened=written + timedelta(days=1))

    assert grades(db, CONFIG, MARKET, [p], now=later + HOUR) == [
        Grade(
            "Linen spike",
            graded_at=ended + 3 * HOUR,
            proceeds=2 * 300 * 0.95,
            open_value=pytest.approx(6 * 94.05 + 2 * 10),
            cost=604,
        )
    ]


@pytest.mark.parametrize(
    ("prediction_", "graded"),
    [
        (prediction(LINEN_KEY, happened=TODAY + timedelta(days=1)), True),
        (prediction(LINEN_KEY, lapse=TODAY), True),  # it lasts through its lapse day
        (prediction(LINEN_KEY), False),
    ],
    ids=["catalyst happened", "lapsed", "still standing"],
)
def test_a_prediction_is_graded_once_a_sale_horizon_has_passed_since_it_ended(
    db, prediction_, graded
):
    run(db, selling_two_linen_an_hour(), [character_read()])
    tomorrow = start_of(TODAY + timedelta(days=1))

    assert grades(db, CONFIG, MARKET, [prediction_], now=tomorrow + 3 * HOUR - 1) == []
    result = grades(db, CONFIG, MARKET, [prediction_], now=tomorrow + 3 * HOUR)
    assert [g.graded_at for g in result] == ([tomorrow + 3 * HOUR] if graded else [])


ORE_LINK = "|cffffffff|Hitem:2770::::::::20:1490:::::::::|h[Copper Ore]|h|r"


def ore_won(read_at, count, price):
    """A Mailbox Read with one Purchase of Ore that arrived 12 hours before it."""
    mail = {
        "index": 1,
        "sender": "Alliance Auction House",
        "subject": "Auction won: Copper Ore",
        "money": 0,
        "daysLeft": 29.5,
        "firstItemQuantity": count,
        "firstItemLink": ORE_LINK,
        "invoice": {"invoiceType": "buyer", "itemName": "Copper Ore", "bid": price, "count": count},
    }
    return mailbox_read(read_at, mail)


def graded_ore_prediction(price):
    """Ended five days ago, after 10 Ore were bought under it for `price` in all, which a
    vendor now takes for 10c each."""
    written = TODAY - timedelta(days=10)
    return prediction(
        ORE_KEY, name="Ore spike", written=written, happened=TODAY - timedelta(days=5)
    ), ore_won(start_of(written) + 18 * HOUR, count=10, price=price)


def test_caps_are_halved_while_the_pooled_return_of_graded_predictions_is_negative(db):
    # As in the cap test, but 7.5% of 16s is 1s 20c: only the 4 units a vendor would take.
    ore, bought = graded_ore_prediction(price=1000)  # -90%
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), money=1600, vendor_prices={2589: 10, 2770: 10})],
        predictions=[prediction(LINEN_KEY), ore],
        mailbox_reads=[bought],
    )

    assert result[MARKET].pooled_return == pytest.approx(-0.9)
    [hold] = [r for r in result[MARKET].holdings if r.action is Action.HOLD]
    assert (hold.quantity, hold.cost) == (4, 40)


def test_there_is_no_brake_unless_the_pooled_return_is_below_zero(db):
    ore, bought = graded_ore_prediction(price=100)  # broke even
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), money=1600, vendor_prices={2589: 10, 2770: 10})],
        predictions=[prediction(LINEN_KEY), ore],
        mailbox_reads=[bought],
    )

    assert result[MARKET].pooled_return == 0
    [hold] = [r for r in result[MARKET].holdings if r.action is Action.HOLD]
    assert hold.quantity == 6


def test_units_bought_under_a_prediction_tie_up_their_price_and_the_rest_todays_exit(db):
    # 10 Ore bought under it for 10s, and 2 more come from elsewhere (looted, say), which
    # have no Lot: those tie up what a vendor pays today.
    written = TODAY - timedelta(days=2)
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(ORE_LINK, count=12), money=GOLD, vendor_prices={2770: 10})],
        predictions=[prediction(ORE_KEY, name="Ore spike", written=written)],
        mailbox_reads=[ore_won(start_of(written) + 18 * HOUR, count=10, price=1000)],
    )

    assert result[MARKET].holdings == [
        Row(ORE_KEY, Action.HOLD, 12, cost=1000 + 2 * 10, prediction="Ore spike")
    ]


def test_with_nothing_graded_there_is_no_pooled_return(db):
    result = run(db, selling_two_linen_an_hour(), [character_read()], predictions=[prediction()])
    assert (result[MARKET].grades, result[MARKET].pooled_return) == ([], None)


# --- Holdings ROI (#50) ---


def won(read_at, count, price, link=LINEN_LINK, name="Linen Cloth"):
    """A Mailbox Read with one Purchase that arrived 12 hours before it."""
    mail = {
        "index": 1,
        "sender": "Alliance Auction House",
        "subject": f"Auction won: {name}",
        "money": 0,
        "daysLeft": 29.5,
        "firstItemQuantity": count,
        "firstItemLink": link,
        "invoice": {"invoiceType": "buyer", "itemName": name, "bid": price, "count": count},
    }
    return mailbox_read(read_at, mail)


def test_held_units_bought_on_the_auction_house_show_roi_after_the_cut(db):
    # 10 Linen bought for 50c each. 6 Sell at 99 (94.05 after the cut), 4 Vendor at 10.
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), vendor_prices={2589: 10})],
        mailbox_reads=[won(T0, count=10, price=500)],
    )

    sell, vendor = result[MARKET].holdings
    assert (sell.action, sell.paid, sell.paid_units) == (Action.SELL, 50, 10)
    assert sell.roi == pytest.approx(0.881)
    assert (vendor.action, vendor.paid, vendor.paid_units) == (Action.VENDOR, 50, 10)
    assert vendor.roi == pytest.approx(-0.8)


def test_held_units_are_costed_by_the_newest_lots_first(db):
    # 8 bought at 20c, then 5 at 80c, and 10 held: the 5 at 80c and 5 of the 20c ones. The
    # other 3 are taken to be gone without a Sold Outcome.
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), vendor_prices={2589: 10})],
        mailbox_reads=[
            won(T0 - DAY, count=8, price=160),
            won(T0, count=5, price=400),
        ],
    )

    assert {(r.paid, r.paid_units) for r in result[MARKET].holdings} == {(50, 10)}


def test_held_units_without_a_lot_are_left_out_of_paid(db):
    # Only 4 of the 10 were bought; the rest were looted, say.
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), vendor_prices={2589: 10})],
        mailbox_reads=[won(T0, count=4, price=200)],
    )

    assert {(r.paid, r.paid_units) for r in result[MARKET].holdings} == {(50, 4)}


def test_units_bought_under_a_prediction_are_left_out_of_paid(db):
    # 4 bought at 10s under a Prediction that has since ended, then 3 at 50c.
    written = TODAY - timedelta(days=10)
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), vendor_prices={2589: 10})],
        predictions=[prediction(LINEN_KEY, written=written, happened=TODAY - timedelta(days=5))],
        mailbox_reads=[
            won(start_of(written) + 18 * HOUR, count=4, price=4000),
            won(T0, count=3, price=150),
        ],
    )

    assert {(r.paid, r.paid_units) for r in result[MARKET].holdings} == {(50, 3)}


def test_craft_rows_get_no_roi(db):
    # A Bolt bought for 5s: the Bolt Sell row has its Paid, the Craft row none.
    result = run(
        db,
        linen_and_bolts_selling(),
        [
            character_read(
                item(count=2), item(BOLT_LINK), vendor_prices={2589: 10}, recipes=[recipe()]
            )
        ],
        mailbox_reads=[won(T0, count=1, price=500, link=BOLT_LINK, name="Bolt of Linen Cloth")],
    )

    assert [(r.action, r.paid, r.paid_units) for r in result[MARKET].holdings] == [
        (Action.SELL, 500, 1),
        (Action.CRAFT, None, None),
    ]


@pytest.mark.parametrize(("roi_hint", "hinted"), [(0.88, True), (0.89, False)])
def test_a_sell_whose_roi_reaches_the_threshold_is_hinted_at(db, roi_hint, hinted):
    # As above: the Sell nets +88.1%, the Vendor -80%, which is never hinted at.
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), vendor_prices={2589: 10})],
        config=replace(CONFIG, roi_hint=roi_hint),
        mailbox_reads=[won(T0, count=10, price=500)],
    )

    assert [(r.action, r.roi_hint) for r in result[MARKET].holdings] == [
        (Action.SELL, hinted),
        (Action.VENDOR, False),
    ]


def test_hold_rows_get_no_roi(db):
    # Linen bought before a Prediction of it was written, which Holds all 10.
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), money=GOLD, vendor_prices={2589: 10})],
        predictions=[prediction(LINEN_KEY)],
        mailbox_reads=[won(T0 - DAY, count=10, price=500)],
    )

    [hold] = result[MARKET].holdings
    assert (hold.action, hold.paid, hold.roi) == (Action.HOLD, None, None)


# --- Why not (#108) ---


def why_not(db, scans, reads, config=CONFIG):
    import_scans(db, list(scans), Era.BETA, config)
    import_character_reads(db, list(reads), Era.BETA, config)
    [market] = recommend(db, config, why_not=True)
    return market, {w.item_key: w for w in market.why_not}


def test_why_not_an_item_key_with_too_few_sale_events_says_how_many_of_how_many(db):
    # #57: two Sale Events at or above the 999 it would post at once the 500 is bought, of
    # the 3 a Flip needs.
    _, why = why_not(
        db,
        selling_two_linen_an_hour(row(unit=500), unit=1000, sale_events=2),
        [character_read(money=GOLD)],
        config=replace(CONFIG, flip_min_sale_events=3),
    )

    linen = why[LINEN_KEY]
    assert (linen.failed, linen.sale_events, linen.min_sale_events) == (Check.SALE_EVENTS, 2, 3)


def test_why_not_an_item_key_whose_room_the_held_units_fill_says_how_many_of_how_many(db):
    # #67: 6 sell within the 3 h Sale Horizon at 999, once the 500s are bought, and 6 are
    # held.
    _, why = why_not(
        db,
        selling_two_linen_an_hour(row(quantity=6, unit=500), unit=1000),
        [character_read(item(count=6), money=GOLD)],
    )

    linen = why[LINEN_KEY]
    assert (linen.failed, linen.held, linen.room) == (Check.ROOM, 6, 6)


def test_why_not_counts_the_sale_events_where_buying_the_cheapest_ask_would_post(db):
    # The one sale was at 400. Bought, the 300 posts at 999 under the 1000s, where no Sale
    # Event is, though one is at or above 299 under the 300 itself.
    _, why = why_not(
        db,
        [
            scan(T0, row(quantity=2, unit=400), row(quantity=20, unit=1000)),
            scan(T0 + HOUR, row(unit=300), row(quantity=20, unit=1000)),
        ],
        [character_read(money=GOLD)],
    )

    linen = why[LINEN_KEY]
    assert (linen.failed, linen.sale_events) == (Check.SALE_EVENTS, 0)


def test_why_not_an_ask_just_over_the_clearing_price_says_by_how_much(db):
    # Bought, the 280 posts at 399 under the 400s: 379.05 after the cut clears the 1
    # silver margin for up to 279. The Buy Under's way value, once it's bought (ADR-0019).
    _, why = why_not(
        db, selling_two_linen_an_hour(row(unit=280), unit=400), [character_read(money=GOLD)]
    )

    linen = why[LINEN_KEY]
    assert (linen.failed, linen.ask, linen.clear_at) == (Check.MARGIN, 280, 279)


@pytest.mark.parametrize("held", [0, 2])
def test_why_not_a_wall_too_big_for_the_room_above_it_says_room_not_margin(db, held):
    # A wall of 10 at 500 under the 1000s. The cheapest alone posts at 499 under the rest
    # of the wall, short of the margin; the whole wall posts at 999 and clears it, but
    # only 6 sell within the 3 h Sale Horizon there, the held units first (#108).
    bags = [item(count=held)] if held else []
    _, why = why_not(
        db,
        selling_two_linen_an_hour(*[row(quantity=2, unit=500)] * 5, unit=1000),
        [character_read(*bags, money=GOLD)],
    )

    linen = why[LINEN_KEY]
    assert linen.failed is Check.ROOM
    assert (linen.room, linen.held, linen.needs, linen.post_at) == (6, held, 10, 999)
    assert linen.clear_at > linen.ask


def test_why_not_a_flip_the_budget_cant_buy_one_of_says_what_it_costs(db):
    # #86: the Ore clears as a Flip to Vendor at 20, but the Budget is 10.
    _, why = why_not(
        db,
        [scan(T0, row(ORE, quantity=2, unit=20))],
        [character_read(money=GOLD, vendor_prices={2770: 25}, budget=10)],
    )

    ore = why[ORE_KEY]
    assert (ore.failed, ore.cost, ore.spend) == (Check.BUDGET, 20, 10)


def test_why_not_a_flip_outside_the_kept_rows_says_its_best_place(db):
    # shopping_list_rows = 1. The Tin (6 profit, 6 a click, 25% ROI) is second to the Ore
    # (50, 10 a click, 100%) by every measure (#98).
    tin = "item:2771::::::::20:1490"
    _, why = why_not(
        db,
        [scan(T0, *[row(ORE, quantity=2, unit=5)] * 5, row(tin, quantity=3, unit=8))],
        [character_read(money=GOLD, vendor_prices={2770: 10, 2771: 10})],
        config=replace(CONFIG, shopping_list_rows=1),
    )

    assert (why["2771"].failed, why["2771"].rank, why["2771"].rows) == (Check.ROW_CAP, 2, 1)
    assert why[ORE_KEY].failed is None


def test_why_not_says_made_the_list_for_exactly_the_flips_on_the_shopping_list(db):
    # A Flip to Sell of Linen, Flips to Vendor of Ore and Tin that the one kept row splits
    # by measure, a Tin too dear to Vendor and Copper Bars nobody buys.
    tin, bar = "item:2771::::::::20:1490", "item:2840::::::::20:1490"
    market, why = why_not(
        db,
        selling_two_linen_an_hour(
            row(quantity=2, unit=700),
            *[row(ORE, quantity=2, unit=5)] * 5,
            row(tin, quantity=3, unit=6),
            row(tin, quantity=1, unit=50),
            row(bar, quantity=4, unit=300),
            unit=1000,
        ),
        [character_read(money=GOLD, vendor_prices={2770: 10, 2771: 10, 2840: 20})],
        config=replace(CONFIG, shopping_list_rows=1),
    )

    made = {k for k, w in why.items() if w.failed is None}
    listed = {r.item_key for r in market.shopping_list if r.action in (Action.SELL, Action.VENDOR)}
    assert made == listed
    assert len(made) > 1 and why["2840"].failed is not None


# --- Buy Under (#88) ---


def test_the_vendor_way_buys_under_the_vendor_price_less_the_margin(db):
    # A Vendor Price of 10s: the Buy Under B keeps 20% of B (over the 1 silver floor), so
    # B = 1000 / 1.2 = 833.33, floored to the copper. A Vendor way never runs out.
    result = run(
        db,
        [scan(T0, row(quantity=20, unit=500))],
        [character_read(vendor_prices={2589: 1000})],
    )

    assert result[MARKET].buy_under == [
        BuyUnder(LINEN_KEY, 833, Action.VENDOR, units=None, seen=1, window_days=7, listed_now=True)
    ]


@pytest.mark.parametrize(
    ("latest", "seen"),
    [(T0 + 7 * DAY, 2), (T0 + 7 * DAY + 1, 1), (T0 + 7 * DAY + HOUR + 1, 0)],
)
def test_a_buy_under_counts_the_scans_in_the_window_that_saw_a_listing_under_it(db, latest, seen):
    # The Buy Under is 833 (as above). Two Listings under it in the first Scan count
    # once, the one still up an hour later counts again, and the latest Scan's Listing
    # is dearer. The window is the 7 days up to the latest Scan, edge included.
    result = run(
        db,
        [
            scan(T0, row(quantity=20, unit=500), row(quantity=5, unit=600)),
            scan(T0 + HOUR, row(quantity=20, unit=500)),
            scan(latest, row(quantity=20, unit=900)),
        ],
        [character_read(vendor_prices={2589: 1000})],
    )

    assert [(b.seen, b.listed_now) for b in result[MARKET].buy_under] == (
        [(seen, False)] if seen else []
    )


def linen_sold_under_1000(unit=1000):
    """A 5 at 5s that was bought, and 2 of a 20 at `unit`: one Sale Event of 7 units in
    an hour, so 21 sell within the 3 h horizon, posted at `unit` less a copper."""
    return [
        scan(T0, row(quantity=20, unit=unit), row(quantity=5, unit=500)),
        scan(T0 + HOUR, row(quantity=18, unit=unit)),
    ]


@pytest.mark.parametrize(
    ("merchant_costs", "min_sale_events", "expected"),
    [
        # 999 after the 5% cut is 949.05: B = 949.05 / 1.2. The 5 held units sell first.
        (None, 1, [(790, Action.SELL, 16)]),
        # Never posted above what a merchant charges: 800 after the cut is 760.
        ({2589: 800}, 1, [(633, Action.SELL, 16)]),
        # No Sell way without the minimum of Sale Events for a Flip, and no Vendor Price.
        (None, 2, []),
    ],
)
def test_the_sell_way_buys_under_the_price_a_flip_would_post_at(
    db, merchant_costs, min_sale_events, expected
):
    result = run(
        db,
        linen_sold_under_1000(),
        [character_read(item(count=5), merchant_costs=merchant_costs)],
        config=replace(CONFIG, flip_min_sale_events=min_sale_events),
    )

    assert [(b.price, b.way, b.units) for b in result[MARKET].buy_under] == expected


def test_the_sell_way_counts_only_the_sale_events_at_or_above_its_post_price(db):
    # #107: the Linen sold at 900, but that stack is gone, maybe expired, and it would
    # post at 999 under the 1000s. Nothing sold that high, so there's no Sell way, and
    # without a Vendor Price no Buy Under, though a 600 was seen.
    scans = [
        scan(
            T0 + n * HOUR,
            row(quantity=20 - 2 * n, unit=900, time_left=4 if n < 3 else 1),
            row(quantity=5, unit=1000),
            *([row(unit=600, time_left=1)] if n == 0 else []),
        )
        for n in range(4)
    ]
    scans.append(scan(T0 + 4 * HOUR, row(quantity=5, unit=1000)))

    result = run(db, scans, [character_read()])

    assert result[MARKET].buy_under == []


THREAD = "item:2320::::::::20:1490"
THREAD_LINK = "|cffffffff|Hitem:2320::::::::20:1490:::::::::|h[Coarse Thread]|h|r"


@pytest.mark.parametrize("held_thread", [0, 5])
def test_the_craft_way_buys_a_reagent_under_its_best_recipes_output_less_the_rest(db, held_thread):
    # A Bolt Vendors for 50s and takes 2 Linen and a Thread, whose cheapest source is
    # another player's 30c Listing, even with Thread held: (5000 - 30) / 2 = 2485 per
    # Linen. The other recipe, 3 Linen into a 60s Vendor, gives only 2000 per Linen.
    # B = 2485 / 1.2. The Bolt Vendors, so the Buy Under never runs out.
    result = run(
        db,
        [scan(T0, row(quantity=20, unit=500), row(THREAD, quantity=20, unit=30))],
        [
            character_read(
                *([item(THREAD_LINK, count=held_thread)] if held_thread else []),
                vendor_prices={2996: 5000, 4305: 6000},
                recipes=[
                    recipe(reagents=((2589, 2), (2320, 1))),
                    recipe(recipe_id=9999, output=4305, reagents=((2589, 3),)),
                ],
            )
        ],
    )

    assert [b for b in result[MARKET].buy_under if b.item_key == LINEN_KEY] == [
        BuyUnder(
            LINEN_KEY,
            2070,
            Action.CRAFT,
            units=None,
            seen=1,
            window_days=7,
            listed_now=True,
            recipe_id=2963,
            output=BOLT_KEY,
            crafter="Kash-Patel",
        )
    ]


def test_a_craft_way_to_a_sell_is_good_for_the_outputs_room_in_reagent_units(db):
    # 2 Bolts sell an hour, so 6 within the 3 h horizon, and one is held: room for 5
    # more Bolts, 2 Linen each. Linen itself has no sales, so no Sell way.
    result = run(
        db,
        [
            scan(T0, row(quantity=20, unit=100), row(BOLT, quantity=20, unit=1000)),
            scan(T0 + HOUR, row(quantity=20, unit=100), row(BOLT, quantity=18, unit=1000)),
        ],
        [character_read(item(BOLT_LINK), recipes=[recipe()])],
    )

    [linen] = [b for b in result[MARKET].buy_under if b.item_key == LINEN_KEY]
    # 999 after the cut is 949.05 per Bolt, 474.525 per Linen, less the 1 silver floor.
    assert (linen.price, linen.way, linen.units) == (374, Action.CRAFT, 10)


def test_a_buy_under_with_no_units_left_isnt_shown(db):
    # 21 sell within the horizon (as above), and 21 are held.
    result = run(db, linen_sold_under_1000(), [character_read(item(count=21))])

    assert result[MARKET].buy_under == []


def test_buy_unders_come_most_profit_per_unit_first(db):
    # Linen's margin at its Buy Under is 1000 - 833, Ore's 2000 - 1666.
    result = run(
        db,
        [scan(T0, row(quantity=20, unit=500), row(ORE, quantity=20, unit=500))],
        [character_read(vendor_prices={2589: 1000, 2770: 2000})],
    )

    assert [(b.item_key, b.price) for b in result[MARKET].buy_under] == [
        (ORE_KEY, 1666),
        (LINEN_KEY, 833),
    ]


def test_a_craft_way_whose_output_may_bind_counts_only_its_vendor_price(db):
    # As above, but the Bolt's bind type is unknown, so it may not sell, and it has no
    # Vendor Price: no way out for the Linen.
    result = run(
        db,
        [
            scan(T0, row(quantity=20, unit=100), row(BOLT, quantity=20, unit=1000)),
            scan(T0 + HOUR, row(quantity=20, unit=100), row(BOLT, quantity=18, unit=1000)),
        ],
        [character_read(recipes=[recipe(bind_type=None)])],
    )

    assert [b for b in result[MARKET].buy_under if b.item_key == LINEN_KEY] == []


@pytest.mark.parametrize(("sightings", "shown"), [(1, True), (2, False)])
def test_a_buy_under_needs_the_minimum_of_sightings(db, sightings, shown):
    result = run(
        db,
        [scan(T0, row(quantity=20, unit=500))],
        [character_read(vendor_prices={2589: 1000})],
        config=replace(CONFIG, buy_under_min_sightings=sightings),
    )

    assert bool(result[MARKET].buy_under) is shown


def test_the_buy_under_of_a_unit_that_doesnt_stack_pays_for_the_buy(db):
    # Linen only ever seen one at a time doesn't stack, so buying one costs the 5s effort:
    # B = (1000 - 500) less the 1 silver floor, since 20% of it is less.
    result = run(
        db,
        [scan(T0, row(unit=300))],
        [character_read(vendor_prices={2589: 1000})],
    )

    assert [b.price for b in result[MARKET].buy_under] == [400]


def test_a_merged_prediction_buy_keeps_the_room_beta_added_to_over_a_bigger_one():
    # #111: one tier's room was watered down by a quiet Beta, the other's grew with it.
    buys = [
        _HoldBuy(
            "12359",
            "BWL opens",
            unit_buyout=100,
            quantity=5,
            unit_max_loss=10.0,
            beta_room=BetaRoom(900.0, room=12, from_beta=-1),
        ),
        _HoldBuy(
            "12359",
            "BWL opens",
            unit_buyout=120,
            quantity=5,
            unit_max_loss=12.0,
            beta_room=BetaRoom(950.0, room=8, from_beta=3),
        ),
    ]

    (row,) = _spend_on_predictions(buys, 100000, _Caps(100000, DEFAULTS))

    assert row.quantity == 10
    assert row.beta_room == BetaRoom(950.0, room=8, from_beta=3)
