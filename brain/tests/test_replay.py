from dataclasses import replace
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
from brain.replay import Policy, db_market, db_min_buyout, replay

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


def test_realized_profit_is_the_range_s_sales_after_the_cut_less_their_lots_cost(db):
    # Read at T0 + 14 h: 2 Linen bought for 100 in all, then 1 sold for 500 at T0 + 2 h,
    # in range, and 1 for 700 at T0 + 13 h, after it.
    mails = [
        auction_mail("Auction won", "Linen Cloth", 100, 2, 29, link=LINEN_LINK),
        auction_mail("Auction successful", "Linen Cloth", 500, 1, 29.5),
        auction_mail("Auction successful", "Linen Cloth", 700, 1, 30 - 1 / 24),
    ]
    read = {
        "readAt": T0 + 14 * HOUR,
        "realm": REALM,
        "character": "Kash-Patel",
        "shownCount": len(mails),
        "totalCount": len(mails),
        "skippedMails": 0,
        "mails": mails,
    }
    result = run(
        db,
        linen_selling_then_crashing(),
        [character_read()],
        mailbox_reads=[read],
        since=T0,
        until=T0 + 4 * HOUR,
    )

    assert result[MARKET].realized_profit == pytest.approx(500 * 0.95 - 50)


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
