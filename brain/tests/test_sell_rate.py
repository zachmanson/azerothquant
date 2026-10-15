from dataclasses import replace
from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.history import Market, import_scans, open_history
from brain.sell_rate import SellRate, sell_rates

T0 = 1_790_000_000
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR

# Default cap (1 h), default time-left buckets and the default 14-day range.
CONFIG = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))
MARKET = Market(realm="Classic Beta PvP", faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
LINEN_KEY = "2589"
SILK = "item:4306::::::::20:1490"
SILK_KEY = "4306"


def scan(at, *rows):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": "Classic Beta PvP",
        "character": "Kash-Patel",
        "faction": "Alliance",
        "droppedRows": 0,
        "listings": list(rows),
    }


def row(item=LINEN, quantity=1, unit=100, time_left=4):
    return {
        "itemString": item,
        "quantity": quantity,
        "buyout": quantity * unit,
        "timeLeft": time_left,
    }


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def run(db, *scans):
    import_scans(db, list(scans), Era.BETA, CONFIG)


def test_a_market_without_observation_windows_has_no_data(db):
    # Two Scans 13 h apart: Listings were seen, but the gap is too long to count.
    run(db, scan(T0, row(quantity=20)), scan(T0 + 13 * HOUR, row(quantity=15)))

    assert sell_rates(db, MARKET, CONFIG, now=T0 + 13 * HOUR) == {}


def test_an_item_key_with_windows_but_no_sales_sells_zero_a_day(db):
    run(db, scan(T0, row(), row(item=SILK)), scan(T0 + 30 * MINUTE, row(), row(item=SILK)))

    rates = sell_rates(db, MARKET, CONFIG, now=T0 + 30 * MINUTE)

    assert {key: rate.units_per_day for key, rate in rates.items()} == {LINEN_KEY: 0, SILK_KEY: 0}


def test_partial_sales_over_window_hours_scaled_to_a_day(db):
    run(
        db,
        scan(T0, row(quantity=20)),
        scan(T0 + 30 * MINUTE, row(quantity=15)),  # 5 sold
        scan(T0 + HOUR, row(quantity=12)),  # 3 sold: 8 units in 1 h of windows
    )

    rates = sell_rates(db, MARKET, CONFIG, now=T0 + HOUR)

    assert rates[LINEN_KEY].units_per_day == 8 * 24


def test_a_probable_sale_that_fails_the_price_check_does_not_count(db):
    # 12 units, so Fair Value is the cheapest 2: both at 100. The 110 is within 1.2x of it
    # and counts; the 200 is too dear to be a sale.
    run(
        db,
        scan(T0, row(quantity=10, unit=100), row(unit=110), row(unit=200)),
        scan(T0 + 30 * MINUTE, row(quantity=10, unit=100)),
    )

    rates = sell_rates(db, MARKET, CONFIG, now=T0 + 30 * MINUTE)

    assert rates[LINEN_KEY].units_per_day == 1 / 0.5 * 24


def test_each_sell_rate_carries_its_evidence(db):
    run(
        db,
        scan(
            T0,
            row(quantity=20),  # 5 sell: a Partial Sale
            row(unit=100),  # gone; the only new one like it is dearer: a coincidence and a sale
            row(item=SILK, unit=100),  # reposted at 90
        ),
        scan(T0 + 30 * MINUTE, row(quantity=15), row(unit=120), row(item=SILK, unit=90)),
    )

    rates = sell_rates(db, MARKET, CONFIG, now=T0 + 30 * MINUTE)

    assert rates[LINEN_KEY] == SellRate(
        units_per_day=6 / 0.5 * 24,
        sale_events=1,  # both in one Observation Window
        window_hours=0.5,
        reposts=0,
        coincidences=1,
        sale_units=6,
        # #132: each Sale Event's time, and the Observation Windows, to cut them at.
        sale_prices=((100, 6, T0 + 30 * MINUTE),),
        windows=((T0, T0 + 30 * MINUTE),),
    )
    assert rates[SILK_KEY] == SellRate(
        units_per_day=0,
        sale_events=0,
        window_hours=0.5,
        reposts=1,
        coincidences=0,
        windows=((T0, T0 + 30 * MINUTE),),
    )


def test_the_max_sale_price_is_the_dearest_of_the_sale_events(db):
    # 2 of the stack sell at 100 and the 110 is a Probable Sale, one Sale Event between
    # them. The 200 is gone too, but too dear to be a sale, so it doesn't count.
    run(
        db,
        scan(T0, row(quantity=10, unit=100), row(unit=110), row(unit=200)),
        scan(T0 + 30 * MINUTE, row(quantity=8, unit=100)),
    )

    rates = sell_rates(db, MARKET, CONFIG, now=T0 + 30 * MINUTE)

    assert rates[LINEN_KEY].sale_events == 1
    assert rates[LINEN_KEY].max_sale_price == 110


def test_the_sell_rate_at_a_price_counts_only_the_sale_events_at_or_above_it():
    # #107: 3 Sale Events over 10 h. At 100, the two at 100 and 150 count, 5 units of 6.
    rate = SellRate(
        units_per_day=6 / 10 * 24,
        sale_events=3,
        window_hours=10,
        reposts=1,
        coincidences=0,
        sale_units=6,
        typical_sale_size=2,
        sale_prices=((99, 1, T0), (100, 2, T0), (150, 3, T0)),
    )

    assert rate.at_or_above(100) == SellRate(
        units_per_day=5 / 10 * 24,
        sale_events=2,
        window_hours=10,
        reposts=1,
        coincidences=0,
        sale_units=5,
        typical_sale_size=2,
        sale_prices=((100, 2, T0), (150, 3, T0)),
    )
    assert rate.at_or_above(151).sale_events == 0


# --- Cut at the Scan the cheapest Listings showed up in (#132) ---

CUTOFF = T0 + 10 * HOUR


def hourly(before_events, after_hours, after_events=()):
    """A Sell Rate over 10 hourly windows up to CUTOFF and `after_hours` more after it:
    `before_events` Sale Events of 2 units at 100 before it, and one at each of the
    `after_events` times."""
    windows = tuple((T0 + h * HOUR, T0 + (h + 1) * HOUR) for h in range(10 + after_hours))
    sales = tuple((100, 2, T0 + (h + 1) * HOUR) for h in range(before_events))
    sales += tuple((100, 2, at) for at in after_events)
    hours = 10 + after_hours
    return SellRate(
        units_per_day=2 * len(sales) / hours * 24,
        sale_events=len(sales),
        window_hours=hours,
        reposts=0,
        coincidences=0,
        sale_units=2 * len(sales),
        sale_prices=sales,
        windows=windows,
    )


@pytest.mark.parametrize("after_hours", [2, 4])
def test_a_cutoff_drops_the_events_and_hours_before_it_however_few_hours_since(after_hours):
    # #135: 6 events in 10 h would expect only 1.2 or 2.4 since, but the cut applies anyway.
    rate = hourly(before_events=6, after_hours=after_hours, after_events=(CUTOFF + HOUR,))

    assert rate.since_cheap(CUTOFF) == replace(
        rate,
        units_per_day=2 / after_hours * 24,
        sale_events=1,
        window_hours=after_hours,
        sale_units=2,
        sale_prices=((100, 2, CUTOFF + HOUR),),
        windows=tuple((CUTOFF + h * HOUR, CUTOFF + (h + 1) * HOUR) for h in range(after_hours)),
    )


def test_a_cut_with_nothing_sold_since_sells_zero_a_day():
    rate = hourly(before_events=10, after_hours=24)

    cut = rate.since_cheap(CUTOFF)

    assert (cut.units_per_day, cut.sale_events, cut.window_hours) == (0, 0, 24)


def test_a_cutoff_with_no_hours_watched_since_leaves_the_sell_rate_whole():
    # #168, ADR-0033: the cheap stock went up after the last Observation Window. Nothing
    # watched since is unknown demand, not zero, however long the stretch has been up.
    rate = hourly(before_events=10, after_hours=0)

    assert rate.since_cheap(CUTOFF) == rate


def test_no_cutoff_leaves_the_sell_rate_whole():
    rate = hourly(before_events=10, after_hours=24)

    assert rate.since_cheap(None) == rate


@pytest.mark.parametrize(("ended_ago", "counted"), [(14 * DAY - 1, True), (14 * DAY, False)])
def test_only_windows_ending_in_the_last_14_days_count(db, ended_ago, counted):
    now = T0 + 30 * MINUTE + ended_ago
    run(db, scan(T0, row(quantity=20)), scan(T0 + 30 * MINUTE, row(quantity=15)))

    rates = sell_rates(db, MARKET, CONFIG, now=now)

    assert (LINEN_KEY in rates) == counted


def test_a_setting_for_the_range_changes_which_windows_count(db):
    config = replace(CONFIG, sell_rate_range_seconds=DAY)
    run(
        db,
        scan(T0, row(quantity=20)),
        scan(T0 + 30 * MINUTE, row(quantity=15)),  # 5 sold, 2 days before now
        scan(T0 + 2 * DAY),
        scan(T0 + 2 * DAY + 30 * MINUTE),  # nothing sold
    )

    rates = sell_rates(db, MARKET, config, now=T0 + 2 * DAY + 30 * MINUTE)

    assert rates[LINEN_KEY] == SellRate(
        units_per_day=0,
        sale_events=0,
        window_hours=0.5,
        reposts=0,
        coincidences=0,
        windows=((T0 + 2 * DAY, T0 + 2 * DAY + 30 * MINUTE),),
    )


# --- The typical Sale Event size, for the Sale Size Prior (#24) ---


def typical_sizes(db, now, config=CONFIG):
    return {
        key: rate.typical_sale_size for key, rate in sell_rates(db, MARKET, config, now).items()
    }


def test_the_typical_size_is_the_item_keys_usual_listing_quantity_when_smaller(db):
    # One buyer takes a whole 20-stack: the Market's usual Sale Event is 20 units, but
    # Linen is usually listed 2 at a time (20, 2, 2).
    run(
        db,
        scan(T0, row(quantity=20), row(quantity=2), row(quantity=2)),
        scan(T0 + 30 * MINUTE, row(quantity=2), row(quantity=2)),
    )

    assert typical_sizes(db, now=T0 + 30 * MINUTE) == {LINEN_KEY: 2}


def test_the_typical_size_is_the_markets_usual_sale_event_when_smaller(db):
    # Linen is listed 15 at a time, but buyers take 5 at a time.
    run(
        db,
        scan(T0, row(quantity=20), row(item=SILK, quantity=10)),
        scan(T0 + 30 * MINUTE, row(quantity=15), row(item=SILK, quantity=5)),  # 5 and 5 sold
    )

    assert typical_sizes(db, now=T0 + 30 * MINUTE) == {LINEN_KEY: 5, SILK_KEY: 5}


def test_item_keys_that_never_stack_are_left_out_of_the_markets_usual_sale_event(db):
    # Three Swords sell one at a time. Counted, they'd make the Market's usual Sale Event
    # 1 unit; left out, it's Linen's 5.
    sword = "item:2488::::::::20:1490"
    run(
        db,
        scan(T0, row(quantity=20), *(row(item=sword, unit=u) for u in (100, 101, 102))),
        scan(T0 + 30 * MINUTE, row(quantity=15)),
    )

    assert typical_sizes(db, now=T0 + 30 * MINUTE) == {LINEN_KEY: 5, "2488": 1}


def test_without_sale_events_of_stacks_the_typical_size_is_the_usual_listing_quantity(db):
    run(db, scan(T0, row(quantity=20)), scan(T0 + 30 * MINUTE, row(quantity=20)))

    assert typical_sizes(db, now=T0 + 30 * MINUTE) == {LINEN_KEY: 20}


def test_an_item_key_without_listings_in_the_range_has_a_typical_size_of_1(db):
    # Silk was only listed 2 days before the 1-day range.
    config = replace(CONFIG, sell_rate_range_seconds=DAY)
    run(
        db,
        scan(T0, row(item=SILK, quantity=20)),
        scan(T0 + 2 * DAY, row(quantity=20)),
        scan(T0 + 2 * DAY + 30 * MINUTE, row(quantity=20)),
    )

    assert typical_sizes(db, now=T0 + 2 * DAY + 30 * MINUTE, config=config) == {
        LINEN_KEY: 20,
        SILK_KEY: 1,
    }
