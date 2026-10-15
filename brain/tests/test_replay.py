from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.disenchant import Group
from brain.grades_file import freeze_named
from brain.history import (
    Market,
    import_character_reads,
    import_mailbox_reads,
    import_scans,
    open_history,
)
from brain.lots import NamedSet
from brain.predictions import Prediction
from brain.recommend import (
    Action,
    CraftOutput,
    DisenchantFlip,
    ListingBuy,
    MarketRecommendations,
    MatYield,
    ReagentBuy,
    Row,
    recommend_market,
)
from brain.replay import Policy, _brain, db_market, db_min_buyout, options_taken, replay

T0 = 1_790_000_000
HOUR = 3600
DAY = 24 * HOUR
REALM = "Classic Beta PvP"
MARKET = Market(realm=REALM, faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
LINEN_LINK = "|cffffffff|Hitem:2589::::::::20:1490:::::::::|h[Linen Cloth]|h|r"

# A 3 hour Sale Horizon, and no priors, so hourly Scans make a Sell Rate taken at its word
# (as in test_recommend).
CONFIG = replace(
    Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),)),
    sale_horizon_seconds=3 * HOUR,
    sell_rate_prior_hours_holdings=0,
    sell_rate_prior_hours_flips=0,
    sale_size_prior_events_holdings=0,
    sale_size_prior_events_flips=0,
    flip_min_sale_events=1,
    risk_caps=False,  # sized by the gold alone, as written (ADR-0034)
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


def row(item=LINEN, quantity=1, unit=100, time_left=4):
    return {
        "itemString": item,
        "quantity": quantity,
        "buyout": quantity * unit,
        "timeLeft": time_left,
    }


def character_read(*bags, money=0, vendor_prices=None, at=T0, recipes=None, merchant_costs=None):
    read = {
        "readAt": at,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": money,
        "bags": list(bags),
        "vendorPrices": vendor_prices or {},
    }
    if recipes is not None:
        read["professions"] = {
            TAILORING: {"readAt": at, "professionID": TAILORING, "recipes": list(recipes)}
        }
        read["professionList"] = [{"professionID": TAILORING}]
    if merchant_costs is not None:
        read["merchantCosts"] = merchant_costs
    return read


TAILORING = 197
BOLT = "item:2996::::::::20:1490"


def recipe(output=2996, reagents=((2589, 2),), quantity=1, recipe_id=2963):
    """A Known Recipe as the Addon records it, with Basic reagents only."""
    return {
        "recipeID": recipe_id,
        "outputItemID": output,
        "quantityMin": quantity,
        "quantityMax": quantity,
        "bindType": 0,
        "reagents": [
            {"itemID": item_id, "quantity": n, "reagentType": 1} for item_id, n in reagents
        ],
    }


def item(link=LINEN_LINK, count=1):
    return {"bag": 0, "slot": 1, "link": link, "count": count, "isBound": False}


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def run(db, scans=(), reads=(), mailbox_reads=(), since=T0, until=T0 + 100 * HOUR, config=CONFIG):
    import_scans(db, list(scans), Era.BETA, config)
    import_mailbox_reads(db, list(mailbox_reads), Era.BETA, config)
    import_character_reads(db, list(reads), Era.BETA, config)
    return {r.market: r for r in replay(db, config, [], since, until)}


def linen_selling_then_crashing(*extra_at_t, unit=100, bolts=False):
    """2 Linen sell each hour from T0. The replayed Scan is T0 + 1 h, and the three after
    it show 2 more selling at `unit` each hour, until a Linen at 20 turns up at T0 + 4 h,
    the end of its Sale Horizon. With `bolts`, a Bolt sells at 1000 each hour too."""
    scans = [
        scan(T0, row(quantity=20, unit=unit)),
        scan(T0 + HOUR, row(quantity=18, unit=unit), *extra_at_t),
        scan(T0 + 2 * HOUR, row(quantity=16, unit=unit)),
        scan(T0 + 3 * HOUR, row(quantity=14, unit=unit)),
        scan(T0 + 4 * HOUR, row(quantity=12, unit=unit), row(unit=20)),
    ]
    if bolts:
        for n, s in enumerate(scans):
            s["listings"].append(row(BOLT, quantity=6 - n, unit=1000))
    return scans


def test_the_brain_is_graded_by_what_its_actions_bring_over_holding_on(db):
    result = run(
        db,
        linen_selling_then_crashing(),
        [character_read(item(count=10), vendor_prices={2589: 10})],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    # The Brain posts the 6 units that sell within 3 h at 99 and vendors 4 for 10 each.
    # All 6 sell to the next 3 h's buyers, who paid up to 100: 6 x 99 after the 5% cut,
    # plus 40. Holding on, the 10 units are worth only 6 x 19 after the cut, plus 40, once
    # the Linen at 20 turns up.
    assert result[MARKET].scans == 1
    assert result[MARKET].graded[Policy.BRAIN] == pytest.approx(6 * 99 * 0.95 - 6 * 19 * 0.95)


def test_auctionator_posts_every_held_unit_just_under_the_cheapest_listing(db):
    result = run(
        db,
        linen_selling_then_crashing(),
        [character_read(item(count=10), vendor_prices={2589: 10})],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    # All 10 go up at 99, with no Sell Rate to stop them: the same 6 sell, and the other 4
    # are still held at the end of the horizon, when 4 Sell at 19. The Brain vendored them.
    brain = 6 * 99 * 0.95 - 6 * 19 * 0.95
    auctionator = 6 * 99 * 0.95 + 4 * 19 * 0.95 - (6 * 19 * 0.95 + 40)
    assert result[MARKET].graded[Policy.AUCTIONATOR] == pytest.approx(auctionator)
    assert result[MARKET].over(Policy.AUCTIONATOR) == pytest.approx(
        (brain - auctionator) / auctionator
    )


def test_auctionator_flips_an_ask_under_the_next_one_by_more_than_the_cut_and_deposit(db):
    result = run(
        db,
        linen_selling_then_crashing(row(unit=50)),
        [character_read(item(count=2), money=10_000, vendor_prices={2589: 10})],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    # The Linen at 50 sits 50 under the next ask, more than its 5 of cut and 6 of deposit
    # (60% of the Vendor Price), so it's bought and posted at 99 with the 2 held: all 3
    # sell. Held untouched, the 2 would Sell at 19 at the end of the horizon.
    auctionator = 3 * 99 * 0.95 - 50 - 2 * 19 * 0.95
    assert result[MARKET].graded[Policy.AUCTIONATOR] == pytest.approx(auctionator)


def test_the_brains_flips_to_sell_are_graded_by_what_they_resell_for(db):
    result = run(
        db,
        linen_selling_then_crashing(row(quantity=5, unit=200), unit=1000),
        [character_read(money=10_000, vendor_prices={2589: 10})],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    # 5 Linen at 200 are bought and posted at 999, and all 5 sell.
    assert result[MARKET].graded[Policy.BRAIN] == pytest.approx(5 * 999 * 0.95 - 5 * 200)


def test_the_brain_buys_with_the_days_to_sell_set_as_of_each_replayed_scan(db):
    # #109: Days to Sell of 1 h at the replayed Scan: 2 Linen sell in it, so the 200s are
    # bought and posted under the 500s. It's cleared by a Read after the Scan, which the
    # replay doesn't see.
    result = run(
        db,
        linen_selling_then_crashing(
            row(quantity=2, unit=200), row(quantity=3, unit=500), unit=1000
        ),
        [
            character_read(money=10_000, vendor_prices={2589: 10}) | {"daysToSell": 1 / 24},
            character_read(money=10_000, vendor_prices={2589: 10}, at=T0 + 2 * HOUR),
        ],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    assert result[MARKET].graded[Policy.BRAIN] == pytest.approx(2 * 499 * 0.95 - 2 * 200)


def test_days_to_sell_leaves_the_held_units_graded_over_the_sale_horizon(db):
    # As without it: the 6 held units that sell within 3 h are posted and all 6 sell.
    result = run(
        db,
        linen_selling_then_crashing(),
        [character_read(item(count=10), vendor_prices={2589: 10}) | {"daysToSell": 1 / 24}],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    assert result[MARKET].graded[Policy.BRAIN] == pytest.approx(6 * 99 * 0.95 - 6 * 19 * 0.95)


ORE = "item:2770::::::::20:1490"


def test_the_brains_buys_to_vendor_bring_the_vendor_price(db):
    result = run(
        db,
        linen_selling_then_crashing(row(ORE, quantity=3, unit=5)),
        [character_read(money=10_000, vendor_prices={2589: 10, 2770: 50})],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    assert result[MARKET].graded[Policy.BRAIN] == pytest.approx(3 * (50 - 5))


def test_the_brain_takes_its_options_most_profit_first_while_the_gold_lasts(db):
    # #86: 20 copper. Each option is sized on its own: all 3 Ore to Vendor (15 copper, 135
    # profit) and both Tin (20 copper, 40 profit). Together they'd need 35, so the replay
    # takes the Ore, and the 5 left can't buy the Tin.
    tin = "item:2771::::::::20:1490"
    result = run(
        db,
        linen_selling_then_crashing(row(ORE, quantity=3, unit=5), row(tin, quantity=2, unit=10)),
        [character_read(money=20, vendor_prices={2589: 10, 2770: 50, 2771: 30})],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    assert result[MARKET].graded[Policy.BRAIN] == pytest.approx(3 * (50 - 5))


def test_the_brain_takes_only_the_most_profitable_flips_as_before_the_other_measures(db):
    # #98: shopping_list_rows = 1. The Tin (12 profit on one Listing) is on the Shopping
    # List only for its Per click. The replay takes the Flips from the top rows by Profit
    # alone, so it grades the same options as before #98: just the Ore (50 profit).
    tin = "item:2771::::::::20:1490"
    result = run(
        db,
        linen_selling_then_crashing(
            *[row(ORE, quantity=2, unit=5)] * 5, row(tin, quantity=3, unit=6)
        ),
        [character_read(money=10_000, vendor_prices={2589: 10, 2770: 10, 2771: 10})],
        since=T0 + HOUR,
        until=T0 + HOUR,
        config=replace(CONFIG, shopping_list_rows=1),
    )

    assert result[MARKET].graded[Policy.BRAIN] == pytest.approx(10 * 10 - 50)


def test_a_held_reagent_the_brains_flip_to_craft_uses_is_not_also_sold(db):
    # #86: the held Linen is on a Holdings Sell row and the Flip to Craft uses it too
    # (buying 5 more at 100 for 3 Bolts, posted at 999). Taken, the craft has it. Held
    # untouched, the Linen would Sell at 19 at the end of the horizon.
    result = run(
        db,
        linen_selling_then_crashing(bolts=True),
        [character_read(item(), money=10_000, vendor_prices={2589: 10}, recipes=[recipe()])],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    brain = 3 * 999 * 0.95 - 5 * 100 - 19 * 0.95
    assert result[MARKET].graded[Policy.BRAIN] == pytest.approx(brain)


ORE_LINK = "|cffffffff|Hitem:2770::::::::20:1490:::::::::|h[Copper Ore]|h|r"


def test_units_the_brain_has_no_data_for_are_held_on_to_and_add_nothing(db):
    result = run(
        db,
        linen_selling_then_crashing(),
        [character_read(item(ORE_LINK, count=3), vendor_prices={2589: 10, 2770: 50})],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    assert result[MARKET].graded[Policy.BRAIN] == 0


def test_the_brains_crafts_pay_for_their_merchant_reagents(db):
    # 4 Linen and 2 Thread from a merchant at 10 each make 2 Bolts, which vendor for 500.
    result = run(
        db,
        linen_selling_then_crashing(),
        [
            character_read(
                item(count=4),
                vendor_prices={2589: 10, 2996: 500},
                recipes=[recipe(reagents=((2589, 2), (2320, 1)))],
                merchant_costs={2320: 10},
            )
        ],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    # The Bolts have no market data, so they're held on to, worth their Vendor Price at
    # the end of the horizon. Held untouched, the 4 Linen would Sell at 19.
    assert result[MARKET].graded[Policy.BRAIN] == pytest.approx(2 * 500 - 2 * 10 - 4 * 19 * 0.95)


# --- The emulated TSM's prices (ADR-0015) ---


def units(*prices):
    return [row(unit=p) for p in prices]


@pytest.mark.parametrize(
    ("prices", "value"),
    [
        # The cheapest 15% (2 of 10 units) always count, and more up to 30% while each is
        # under 120% of the one before it.
        ((100, 102, 104, 110, 115, 200, 300, 300, 300, 300), 102),
        ((100, 101, 150, 150, 150, 150, 150, 150, 150, 150), 100.5),
        # Of the cheapest 30%, a unit over 1.5 standard deviations from their mean is left out.
        ((10,) + (100,) * 19, 100),
    ],
)
def test_db_market_in_one_scan_is_the_mean_of_its_cheapest_units(db, prices, value):
    import_scans(db, [scan(T0, *units(*prices))], Era.BETA, CONFIG)

    assert db_market(db, MARKET, T0) == {"2589": pytest.approx(value)}


def test_db_market_weights_each_of_the_last_14_days_less_the_older_it_is(db):
    scans = [
        scan(T0 - 15 * DAY, *units(1000)),  # too old to count
        scan(T0 - 13 * DAY, *units(200)),  # weight 1
        scan(T0 - HOUR, *units(90)),  # today's, weight 14, the mean of today's Scans
        scan(T0, *units(110)),
    ]
    import_scans(db, scans, Era.BETA, CONFIG)

    assert db_market(db, MARKET, T0) == {"2589": pytest.approx((14 * 100 + 200) / 15)}


def test_db_min_buyout_is_the_cheapest_unit_in_the_scan(db):
    import_scans(db, [scan(T0 - HOUR, *units(50)), scan(T0, *units(120, 110))], Era.BETA, CONFIG)

    assert db_min_buyout(db, MARKET, T0) == {"2589": 110}


def test_tsm_posts_at_db_market_when_the_cheapest_listing_is_under_its_floor(db):
    result = run(
        db,
        linen_selling_then_crashing(row(unit=50)),
        [character_read(item(count=10), vendor_prices={2589: 10})],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    # DBMarket is 100 (the Linen at 50 is an outlier), so the one at 50 is under the 80
    # floor, and all 10 go up at 100. The buyers of the next 3 h take 7, and the other 3
    # are still held at the end of the horizon, when 3 Sell at 19, where the 10 held
    # untouched would bring 6 at 19 and 4 to Vendor.
    tsm = 7 * 100 * 0.95 + 3 * 19 * 0.95 - (6 * 19 * 0.95 + 4 * 10)
    assert result[MARKET].graded[Policy.TSM] == pytest.approx(tsm)


def test_tsm_crafts_while_db_market_beats_the_reagents_db_min_buyout(db):
    # A Bolt's DBMarket is 1000, over 2 Linen at their DBMinBuyout of 100 and a Thread
    # from a merchant at 10.
    result = run(
        db,
        linen_selling_then_crashing(bolts=True),
        [
            character_read(
                item(count=4),
                money=10_000,
                vendor_prices={2589: 10},
                recipes=[recipe(reagents=((2589, 2), (2320, 1)))],
                merchant_costs={2320: 10},
            )
        ],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    # With no Sell Rate or inventory limit, it crafts the 4 held Linen and all 18 on sale
    # into 11 Bolts, buying 11 Thread, and posts them at 999. The next 3 h's buyers take
    # 3, and 3 more Sell at the end of the horizon. Held untouched, the 4 Linen would
    # Sell at 19.
    tsm = 6 * 999 * 0.95 - 18 * 100 - 11 * 10 - 4 * 19 * 0.95
    assert result[MARKET].graded[Policy.TSM] == pytest.approx(tsm)


def test_a_recipe_learned_after_a_replayed_scan_is_not_used_at_it():
    def replayed(later_recipes, learned_at=T0 + 2 * HOUR):
        conn = open_history(":memory:")
        # The later Read holds the same, so only the recipes change.
        reads = [
            character_read(
                item(count=4),
                money=10_000,
                vendor_prices={2589: 10},
                at=at,
                recipes=recipes,
                merchant_costs={2320: 10},
            )
            for at, recipes in [(T0, []), (learned_at, later_recipes)]
        ]
        try:
            graded = run(conn, linen_selling_then_crashing(bolts=True), reads, until=T0 + HOUR)
            return graded[MARKET].graded
        finally:
            conn.close()

    bolt = [recipe(reagents=((2589, 2), (2320, 1)))]

    assert replayed(bolt) == replayed([])
    # Learned by the replayed Scan instead, TSM crafts with it.
    assert replayed(bolt, learned_at=T0 + HOUR) != replayed([])


# --- Ablations: the Brain with one feature switched off ---


def test_the_brain_is_replayed_without_flips_to_craft_beside_the_full_brain(db):
    result = run(
        db,
        linen_selling_then_crashing(bolts=True),
        [
            character_read(
                money=10_000,
                vendor_prices={2589: 10},
                recipes=[recipe(reagents=((2589, 2), (2320, 1)))],
                merchant_costs={2320: 10},
            )
        ],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    # The full Brain buys 6 Linen and 3 Thread for the 3 Bolts that sell in 3 h, posts
    # them at 999, and all 3 sell. Without Flips to Craft it has nothing to do.
    graded = result[MARKET].graded
    assert graded[Policy.BRAIN] == pytest.approx(3 * 999 * 0.95 - 6 * 100 - 3 * 10)
    assert graded[Policy.BRAIN_WITHOUT_FLIPS_TO_CRAFT] == 0


def test_the_brain_is_replayed_without_sub_crafts(db):
    # A Shirt, which vendors for 5000, takes a Bolt, crafted from 2 Linen.
    result = run(
        db,
        linen_selling_then_crashing(),
        [
            character_read(
                item(count=4),
                vendor_prices={2589: 10, 2576: 5000},
                recipes=[recipe(), recipe(output=2576, reagents=((2996, 1),), recipe_id=2393)],
            )
        ],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    # The full Brain crafts the 4 Linen into 2 Shirts through 2 Bolts, which it holds on
    # to (no market data), worth their Vendor Price. Without Sub-crafts no Shirt can be
    # made, and a Bolt isn't worth making, so it posts the 4 Linen at 99, and all 4 sell.
    graded = result[MARKET].graded
    assert graded[Policy.BRAIN] == pytest.approx(2 * 5000 - 4 * 19 * 0.95)
    assert graded[Policy.BRAIN_WITHOUT_SUB_CRAFTS] == pytest.approx(4 * 99 * 0.95 - 4 * 19 * 0.95)


def test_the_brain_is_replayed_without_deposits_and_graded_with_them(db):
    # Each posting lasts 1 h and costs a 48 deposit (60% of the 80 Vendor Price).
    result = run(
        db,
        linen_selling_then_crashing(),
        [character_read(item(count=6), vendor_prices={2589: 80})],
        since=T0 + HOUR,
        until=T0 + HOUR,
        config=replace(CONFIG, post_duration_hours=1),
    )

    # The full Brain posts the 2 units that sell before a posting expires and vendors 4,
    # and both sell in the first hour. Without Deposits it posts all 6: the 2 sold in the
    # second hour lose one deposit, and the 2 in the third hour two. Held untouched, all 6
    # are Vendored at the end of the horizon.
    graded = result[MARKET].graded
    assert graded[Policy.BRAIN] == pytest.approx(2 * 99 * 0.95 + 4 * 80 - 6 * 80)
    assert graded[Policy.BRAIN_WITHOUT_DEPOSITS] == pytest.approx(
        6 * 99 * 0.95 - 2 * 48 - 2 * 2 * 48 - 6 * 80
    )


def test_without_the_sell_rate_a_flip_buys_past_its_room_and_posts_at_db_market(db):
    # 1 Linen at 1000 sold in the hour before the replayed Scan, T0 + 1 h, which shows 5
    # more at 200 that stay up. Then 3 at 1000 sell each hour.
    cheap = row(quantity=5, unit=200)
    scans = [
        scan(T0, row(quantity=20, unit=1000)),
        scan(T0 + HOUR, row(quantity=19, unit=1000), cheap),
        scan(T0 + 2 * HOUR, row(quantity=16, unit=1000), cheap),
        scan(T0 + 3 * HOUR, row(quantity=13, unit=1000), cheap),
        scan(T0 + 4 * HOUR, row(quantity=10, unit=1000), cheap),
    ]
    result = run(db, scans, [character_read(money=10_000)], since=T0 + HOUR, until=T0 + HOUR)

    # The Brain's Sell Rate has room for 3 in 3 h, so it could only take part of the
    # Listing at 200, posted at 199 under the rest of it: no profit, so it buys nothing.
    # Without the Sell Rate there's no room limit: all 5 are bought and posted at
    # DBMarket, 600 (T0's Scan is worth 1000, T0 + 1 h's 200), since 999 under the next
    # ask is over it. All 5 sell to the 1000 buyers.
    graded = result[MARKET].graded
    assert graded[Policy.BRAIN] == 0
    assert graded[Policy.BRAIN_WITHOUT_SELL_RATE] == pytest.approx(5 * 600 * 0.95 - 5 * 200)


def test_without_the_sell_rate_an_item_key_with_no_sale_events_is_priced_by_db_market(db):
    # 5 Ore at 100 sat unsold up to the replayed Scan, T0 + 1 h, then 2 sell each hour.
    scans = [
        scan(T0, row(ORE, quantity=5)),
        scan(T0 + HOUR, row(ORE, quantity=5)),
        scan(T0 + 2 * HOUR, row(ORE, quantity=3)),
        scan(T0 + 3 * HOUR, row(ORE, quantity=1)),
        scan(T0 + 4 * HOUR),
    ]
    result = run(
        db,
        scans,
        [character_read(item(ORE_LINK, count=3), vendor_prices={2770: 10})],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    # The Brain has no Sale Event to value the 3 held Ore by ("no data"), so it holds on to
    # them. Without the Sell Rate, DBMarket is 100, and they go up at 99, under the
    # cheapest ask, and sell. Held untouched, they'd be Vendored at the end of the horizon,
    # when no Ore is listed.
    graded = result[MARKET].graded
    assert graded[Policy.BRAIN] == 0
    assert graded[Policy.BRAIN_WITHOUT_SELL_RATE] == pytest.approx(3 * 99 * 0.95 - 3 * 10)


def test_a_pricer_prices_a_flip_to_craft_output_with_no_room_limit_under_its_merchant_cost(db):
    # A merchant sells Bolts at 1500, and the pricer asks 5000 for one.
    import_scans(db, linen_selling_then_crashing(bolts=True), Era.BETA, CONFIG)
    read = character_read(
        money=10_000,
        recipes=[recipe(reagents=((2589, 2), (2320, 1)))],
        merchant_costs={2320: 10, 2996: 1500},
    )
    import_character_reads(db, [read], Era.BETA, CONFIG)

    m = recommend_market(
        db,
        CONFIG,
        MARKET,
        [],
        T0 + HOUR,
        as_of=T0 + HOUR,
        buy_under=False,
        pricer=lambda item_key, cheapest: 5000 if item_key == "2996" else None,
    )

    # The Bolt Sell Rate has room for 3 in 3 h. With the pricer there's no limit, so all
    # 18 Linen on sale make 9 Bolts, every one posted at the merchant's 1500.
    crafts = [r for r in m.shopping_list if r.action is Action.CRAFT]
    assert [r.made for r in crafts] == [CraftOutput(units=9, selling=9, post_at=1500)]


# --- Realized profit, the confirmation ---


def auction_mail(subject, name, bid, count, days_left, link=None):
    mail = {
        "index": 1,
        "sender": "Alliance Auction House",
        "subject": f"{subject}: {name}",
        "money": 0 if link else bid,
        "daysLeft": days_left,
        "invoice": {
            "invoiceType": "buyer" if link else "seller",
            "itemName": name,
            "bid": bid,
            "count": count,
        },
    }
    if link:
        mail |= {"firstItemQuantity": count, "firstItemLink": link}
    return mail


def realized_read():
    """A Mailbox Read at T0 + 14 h: 2 Linen bought for 100 in all at T0 + 1 h, then 1 sold
    for 500 at T0 + 2 h, and 1 for 700 at T0 + 13 h."""
    mails = [
        auction_mail("Auction won", "Linen Cloth", 100, 2, 30 - 13 / 24, link=LINEN_LINK),
        auction_mail("Auction successful", "Linen Cloth", 500, 1, 29.5),
        auction_mail("Auction successful", "Linen Cloth", 700, 1, 30 - 1 / 24),
    ]
    return {
        "readAt": T0 + 14 * HOUR,
        "realm": REALM,
        "character": "Kash-Patel",
        "shownCount": len(mails),
        "totalCount": len(mails),
        "skippedMails": 0,
        "mails": mails,
    }


def named_at(tmp_path, scan_at, *item_keys):
    """CONFIG with a grades.toml in which the Scan at `scan_at` named `item_keys` to buy
    at any price (#55)."""
    path = tmp_path / "grades.toml"
    freeze_named(path, MARKET, scan_at, NamedSet({k: 1_000_000 for k in item_keys}))
    return replace(CONFIG, grades_path=path)


@pytest.mark.parametrize(("named", "cost"), [(("2589",), 50), ((), 0)], ids=["named", "for use"])
def test_realized_profit_is_the_range_s_sales_after_the_cut_less_their_lots_cost(
    db, tmp_path, named, cost
):
    # The sale at T0 + 2 h is in range, the one at T0 + 13 h after it. Bought For Use (#55),
    # the Linen starts no Lot, so the sale is of a looted unit, say, and costs nothing.
    result = run(
        db,
        linen_selling_then_crashing(),
        [character_read()],
        mailbox_reads=[realized_read()],
        since=T0,
        until=T0 + 4 * HOUR,
        config=named_at(tmp_path, T0 + HOUR, *named),
    )

    assert result[MARKET].realized_profit == pytest.approx(500 * 0.95 - cost)


def test_units_with_no_vendor_price_to_vendor_at_bring_nothing(db):
    # The Linen's Vendor Price was never seen, and the Sale Horizon only sells 6 of 10.
    result = run(
        db,
        linen_selling_then_crashing(),
        [character_read(item(count=10))],
        since=T0 + HOUR,
        until=T0 + HOUR,
    )

    # The 4 left over bring nothing either way. Held untouched, 6 Sell at 19.
    assert result[MARKET].graded[Policy.BRAIN] == pytest.approx(6 * 99 * 0.95 - 6 * 19 * 0.95)


def test_the_brain_is_replayed_without_the_beta_sell_rate_only_when_it_is_on(db):
    # #110: Live's first Scan, 5 Linen at 100 and 10 at 120 under a Prediction, and a Beta
    # Market at twice the price whose 240s sold 3 in 1.5 h: as in test_beta_sell_rate,
    # the Brain buys to Hold on Beta's room. Without it, nothing is bought.
    live_start = T0 + 60 * DAY
    live_realm = "Forever"
    live = Market(realm=live_realm, faction="Alliance", era=Era.LIVE)
    config = replace(CONFIG, beta_sell_rate_weight=0.5)
    beta = [
        scan(T0 + n * 1800, row(quantity=5, unit=200), row(quantity=10 - n, unit=240))
        for n in range(4)
    ]
    live_scans = [
        scan(live_start + n * HOUR, row(quantity=5, unit=100), row(quantity=10, unit=120))
        | {"realm": live_realm}
        for n in range(4)
    ]
    import_scans(db, beta, Era.BETA, config)
    import_scans(db, live_scans, Era.LIVE, config)
    read = character_read(money=10_000, at=live_start) | {"realm": live_realm}
    import_character_reads(db, [read], Era.LIVE, config)
    written = date.fromtimestamp(live_start)
    linen = Prediction(
        "Linen spike", "Tailoring quests", ("2589",), "Phase 2", written, written + timedelta(7)
    )

    [on] = replay(db, config, [linen], live_start, live_start)
    [off] = replay(db, replace(config, beta_sell_rate_weight=0), [linen], live_start, live_start)

    assert on.market == live
    assert on.graded[Policy.BRAIN_WITHOUT_BETA_SELL_RATE] == 0
    assert on.graded[Policy.BRAIN] != 0
    assert Policy.BRAIN_WITHOUT_BETA_SELL_RATE not in off.graded


GREENS = Group(2, "armor", 16, 20, ())
DUST_KEY = "10940"


def flip_to_disenchant(profit=500):
    """A Flip to Disenchant of 2 Green Chests (9999) and another green (9998)."""
    flip = DisenchantFlip(
        GREENS, (ListingBuy("9999", 100), ListingBuy("9998", 150), ListingBuy("9999", 300))
    )
    return Row(
        "",
        Action.DISENCHANT,
        3,
        price=300,
        profit=profit,
        cost=550,
        character="Bob",
        mats=(MatYield(DUST_KEY, 5.625),),
        listings=3,
        disenchant=flip,
    )


def test_a_taken_flip_to_disenchant_blocks_later_options_on_its_items_or_mats():
    dust_craft = Row(DUST_KEY, Action.CRAFT, 1, profit=300, cost=50, buys=(ReagentBuy("2", 1, 50),))
    other_green = Row("9998", Action.SELL, 1, price=160, profit=200, cost=160)
    linen = Row("2589", Action.SELL, 1, price=10, profit=100, cost=10)
    m = MarketRecommendations(
        MARKET, T0, 10000, shopping_list=[flip_to_disenchant(), dust_craft, other_green, linen]
    )

    # A Flip to Disenchant isn't one of the Flips to Sell and Vendor the row cap counts.
    shopping, _ = options_taken(m, flip_rows=2)

    assert shopping == [flip_to_disenchant(), linen]


def test_a_taken_flip_to_disenchants_units_are_kept_for_their_best_exit_value():
    m = MarketRecommendations(MARKET, T0, 10000, shopping_list=[flip_to_disenchant()])

    moves = _brain(m, {}, flip_rows=50)

    assert (moves.spent, dict(moves.kept)) == (550, {"9999": 2, "9998": 1})


def test_options_are_taken_while_the_room_lasts_as_well_as_the_gold():
    # #170, ADR-0034: 1g of gold but 50s of room, so after the 40s Ore only the 10s Linen
    # fits, not the 30s Bolt.
    ore = Row("2770", Action.SELL, 4, price=10, profit=300, cost=4000)
    bolt = Row("2996", Action.SELL, 3, price=10, profit=200, cost=3000)
    linen = Row("2589", Action.SELL, 1, price=10, profit=100, cost=1000)
    m = MarketRecommendations(MARKET, T0, 10000, room=5000, shopping_list=[ore, bolt, linen])

    shopping, _ = options_taken(m, flip_rows=50)

    assert shopping == [ore, linen]
