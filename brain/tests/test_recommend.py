from dataclasses import replace
from datetime import date, timedelta
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
from brain.lots import Held
from brain.predictions import Prediction
from brain.recommend import Action, Row, held_at_writing, recommend, sellable_units
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

# Default knobs (5% faction cut, 20% and 1 silver Flip margin), except a Sale Horizon of
# 3 hours, so a Sell Rate from a single short Observation Window is small enough to cap,
# and no Sell Rate Prior or Sale Size Prior, so these tests take the raw rate at its word.
DEFAULTS = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))
CONFIG = replace(
    DEFAULTS,
    sale_horizon_seconds=3 * HOUR,
    sell_rate_prior_hours_holdings=0,
    sell_rate_prior_hours_flips=0,
    sale_size_prior_events_holdings=0,
    sale_size_prior_events_flips=0,
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
    *bags, character="Kash-Patel", faction="Alliance", money=0, vendor_prices=None, at=T0
):
    return {
        "readAt": at,
        "realm": REALM,
        "character": character,
        "faction": faction,
        "money": money,
        "bags": list(bags),
        "vendorPrices": vendor_prices or {},
    }


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def run(db, scans=(), reads=(), config=CONFIG, predictions=(), mailbox_reads=()):
    import_scans(db, list(scans), Era.BETA, config)
    import_mailbox_reads(db, list(mailbox_reads), Era.BETA, config)
    import_character_reads(db, list(reads), Era.BETA, config)
    return {r.market: r for r in recommend(db, config, list(predictions))}


def selling_two_linen_an_hour(*latest_rows, unit=100):
    """Two Scans an hour apart in which 2 Linen sold: 48 a day, so 6 in the 3 h horizon.
    Fair Value in the latest Scan is `unit`, before any `latest_rows` are added to it."""
    return [
        scan(T0, row(quantity=20, unit=unit)),
        scan(T0 + HOUR, row(quantity=18, unit=unit), *latest_rows),
    ]


# --- Holdings: Vendor vs Sell ---


def test_units_that_sell_within_the_horizon_are_sold_and_the_rest_vendored(db):
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=10), vendor_prices={2589: 10})],
    )

    assert result[MARKET].holdings == [
        # Sold at Fair Value less the 5% cut: 95 each, 85 more than a vendor pays.
        Row(LINEN_KEY, Action.SELL, 6, price=100, profit=6 * 95, margin=85, sale_events=1),
        Row(LINEN_KEY, Action.VENDOR, 4, price=10, profit=40),
    ]


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
        Row(LINEN_KEY, Action.SELL, 4, price=100, profit=4 * 95, margin=85, sale_events=1),
        Row("5000", Action.VENDOR, 1, price=250, profit=250),
        Row(LINEN_KEY, Action.VENDOR, 3, price=10, profit=30),
    ]


def test_an_item_with_no_vendor_price_is_shown_as_such(db):
    # Selling is the only exit whose value is known, so what sells is still Sold.
    result = run(db, selling_two_linen_an_hour(), [character_read(item(count=10))])

    assert result[MARKET].holdings == [
        Row(LINEN_KEY, Action.SELL, 6, price=100, profit=6 * 95, sale_events=1),
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
        Row(LINEN_KEY, Action.SELL, 6, price=100, profit=6 * 95, margin=85, sale_events=1),
        Row(LINEN_KEY, Action.VENDOR, 4, price=10, profit=40),
    ]


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
    assert result[MARKET].shopping_cost == 21


def test_resale_is_priced_without_the_units_being_bought(db):
    # 20 Linen: Fair Value averages the cheapest 3, (700 + 700 + 1000) / 3 = 800. Resold at
    # that, the 700s clear only 60 after the cut, under the 1 silver minimum. But once
    # they're bought the cheapest 3 are all 1000, so they resell for 950 each.
    result = run(
        db,
        selling_two_linen_an_hour(row(quantity=2, unit=700), unit=1000),
        [character_read(money=GOLD)],
    )

    assert result[MARKET].shopping_list == [
        Row(LINEN_KEY, Action.SELL, 2, price=700, profit=2 * 250, sale_events=1, cost=1400)
    ]


@pytest.mark.parametrize(
    ("fair", "unit", "bought"),
    [
        # Resale 950: 158 over 792 is under 20% of it; 159 over 791 isn't.
        (1000, 791, True),
        (1000, 792, False),
        # Resale 380: 100 over 280 is exactly 1 silver, and more than 20% of it.
        (400, 280, True),
        (400, 281, False),
    ],
)
def test_a_flip_to_sell_must_clear_20_percent_and_1_silver(db, fair, unit, bought):
    result = run(
        db, selling_two_linen_an_hour(row(unit=unit), unit=fair), [character_read(money=GOLD)]
    )

    assert bool(result[MARKET].shopping_list) == bought


def test_a_flip_to_sell_buys_no_more_than_sells_within_the_horizon(db):
    # A deep Market, so the 4 cheap units left behind don't drag the resale under 1 silver.
    result = run(
        db,
        [
            scan(T0, row(quantity=200, unit=1000)),
            scan(T0 + HOUR, row(quantity=198, unit=1000), row(quantity=10, unit=500)),
        ],
        [character_read(money=GOLD)],
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity, flip.price) == (Action.SELL, 6, 500)


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


def test_pooled_gold_is_spent_on_the_most_profit_per_gold_first(db):
    tin = "item:2771::::::::20:1490"
    result = run(
        db,
        [scan(T0, row(ORE, quantity=2, unit=20), row(tin, quantity=3, unit=5))],
        [
            # 35 copper between them: all the Tin (1 profit per copper spent) is 15, which
            # leaves enough for one of the Ore (0.25 per copper).
            character_read(money=20, vendor_prices={2770: 25, 2771: 10}),
            character_read(money=15, character="Alt-One"),
        ],
    )

    assert result[MARKET].shopping_list == [
        Row("2771", Action.VENDOR, 3, price=5, profit=15, cost=15),
        Row(ORE_KEY, Action.VENDOR, 1, price=20, profit=5, cost=20),
    ]
    assert result[MARKET].shopping_cost == 35


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
        (LINEN_KEY, Action.SELL, 190),
        ("2770", None, None),
        ("6303", None, None),
    ]


# --- The Sell Rate Prior (#25) ---


def one_sale_in_18_minutes(*latest_rows):
    """One Linen sold in a single 18-minute Observation Window: a raw Sell Rate of 80 a
    day, from 0.3 h of watching. A deep Market at 1000, so resale stays well clear."""
    return [
        scan(T0, row(quantity=200, unit=1000)),
        scan(T0 + 18 * MINUTE, row(quantity=199, unit=1000), *latest_rows),
    ]


def test_a_flip_buys_only_what_the_discounted_sell_rate_says_will_sell(db):
    # As if 24 more hours had been watched with no sales: 1 / 24.3 h * 24 * 7 days = 6.9,
    # not the raw 80 a day * 7 = 560.
    config = replace(DEFAULTS, sell_rate_prior_hours_flips=24)
    result = run(
        db,
        one_sale_in_18_minutes(row(quantity=10, unit=500)),
        [character_read(money=GOLD)],
        config=config,
    )

    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity, flip.price) == (Action.SELL, 6, 500)


def test_holdings_are_discounted_less_than_flips(db):
    # The default Sell Rate Prior for Holdings, 3 h: 1 / 3.3 h * 24 * 7 days = 50.9 of the 100
    # held are Sold. Flips get the default 24: 1 / 24.3 h * 24 * 7 = 6.9, so 6 bought.
    result = run(
        db,
        one_sale_in_18_minutes(row(quantity=10, unit=500)),
        [character_read(item(count=100), money=GOLD, vendor_prices={2589: 10})],
        config=DEFAULTS,
    )

    sell, vendor = result[MARKET].holdings
    assert (sell.action, sell.quantity) == (Action.SELL, 50)
    assert (vendor.action, vendor.quantity) == (Action.VENDOR, 50)
    [flip] = result[MARKET].shopping_list
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
    Sale Event is 2 units. A deep Market at 1000."""
    stacks_of_2 = [row(quantity=2, unit=1000) for _ in range(50)]
    return [
        scan(T0, row(quantity=20, unit=1000), *stacks_of_2),
        scan(T0 + 30 * MINUTE, *stacks_of_2, *latest_rows),
    ]


def test_holdings_and_flips_shrink_the_sale_event_size_by_their_own_prior(db):
    # Holdings, 1 Sale Event: (20 + 1 * 2) / 2 = 11 units, at 48 events a day = 66 in 3 h.
    # Flips, 5: (20 + 5 * 2) / 6 = 5 units, 30 in 3 h.
    config = replace(CONFIG, sale_size_prior_events_holdings=1, sale_size_prior_events_flips=5)
    result = run(
        db,
        one_buyer_takes_a_20_stack(row(quantity=40, unit=500)),
        [character_read(item(count=100), money=GOLD, vendor_prices={2589: 10})],
        config=config,
    )

    sell, vendor = result[MARKET].holdings
    assert (sell.action, sell.quantity) == (Action.SELL, 66)
    assert (vendor.action, vendor.quantity) == (Action.VENDOR, 34)
    [flip] = result[MARKET].shopping_list
    assert (flip.action, flip.quantity, flip.price) == (Action.SELL, 30, 500)


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

    # The gold they tie up is what letting them go would bring today: 6 Sold at 95 after
    # the cut and 4 Vendored at 10.
    assert result[MARKET].holdings == [
        Row(LINEN_KEY, Action.HOLD, 10, cost=6 * 95 + 4 * 10, prediction="Linen spike")
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


def test_held_units_over_the_cap_go_to_their_best_action_cheapest_exit_held_first(db):
    # 15% of 16s is 2s 40c. The 4 unbound units a vendor would take (10 each) fit first,
    # then 2 of the 6 that would Sell (95 each): 2s 30c. Bound units can't be sold after
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
        Row(LINEN_KEY, Action.SELL, 4, price=100, profit=4 * 95, margin=85, sale_events=1),
        Row(LINEN_KEY, Action.VENDOR, 3, price=10, profit=30),
        Row(LINEN_KEY, Action.HOLD, 6, cost=4 * 10 + 2 * 95, prediction="Linen spike"),
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
    # 6 sell within the horizon. Without the Prediction the two 700s are a Flip reselling
    # at 950 (the Max Loss is negative), and 4 of the 1000s would resell at 950, losing 50
    # each. Beyond the horizon there's no exit, so nothing more is bought.
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
            max_loss=2 * -250 + 4 * 50,
            prediction="Linen spike",
        )
    ]


def test_held_units_take_the_sale_horizon_first_when_pricing_a_buys_exit(db):
    # 6 sell within the horizon, and the 4 held would go first if the Prediction is wrong,
    # so only 2 of the 100s could be resold at 95.
    result = run(
        db,
        selling_two_linen_an_hour(),
        [character_read(item(count=4), money=GOLD)],
        predictions=[prediction(LINEN_KEY)],
    )

    [buy] = result[MARKET].prediction_buys
    assert (buy.quantity, buy.max_loss) == (2, 2 * 5)


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


def test_flips_are_bought_first_and_predictions_get_the_gold_left(db):
    # Of 10s, the Ore Flip to Vendor takes 9s. The Prediction's cap is 1s 50c, but only 1s
    # is left: 5 Linen at 20c.
    result = run(
        db,
        [scan(T0, row(ORE, quantity=9, unit=100), row(quantity=20, unit=20))],
        [character_read(money=1000, vendor_prices={2589: 19, 2770: 200})],
        predictions=[prediction(LINEN_KEY)],
    )

    assert result[MARKET].shopping_cost == 900
    [buy] = result[MARKET].prediction_buys
    assert (buy.quantity, buy.cost) == (5, 100)


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

    # As in the Hold test: 6 Sold at 95 after the cut and 4 Vendored at 10.
    assert held_at_writing(db, CONFIG, MARKET, [prediction(LINEN_KEY, written=written)]) == [
        Held("Linen spike", LINEN_KEY, units=10, cost=6 * 95 + 4 * 10)
    ]
