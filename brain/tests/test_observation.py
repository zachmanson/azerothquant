from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.history import Market, import_scans, open_history
from brain.observation import (
    ObservationWindow,
    SaleEvent,
    disappearances,
    observation_windows,
    sell_rate_evidence,
)

T0 = 1_790_000_000
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR

# Default cap (1 h) and default time-left buckets (<30m, 30m-2h, 2-12h, 12-48h).
CONFIG = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))
MARKET = Market(realm="Classic Beta PvP", faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
LINEN_KEY = "2589"
SILK = "item:4306::::::::20:1490"
SILK_KEY = "4306"


def scan(at, *rows, faction="Alliance"):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": "Classic Beta PvP",
        "character": "Kash-Patel",
        "faction": faction,
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


# --- Observation Windows ---


def test_gap_exactly_at_the_cap_is_an_observation_window(db):
    run(db, scan(T0), scan(T0 + HOUR))

    assert observation_windows(db, MARKET, CONFIG) == [ObservationWindow(T0, T0 + HOUR)]


def test_gap_just_over_the_cap_is_not_an_observation_window(db):
    run(db, scan(T0), scan(T0 + HOUR + 1), scan(T0 + HOUR + 1 + 20 * MINUTE))

    assert observation_windows(db, MARKET, CONFIG) == [
        ObservationWindow(T0 + HOUR + 1, T0 + HOUR + 1 + 20 * MINUTE)
    ]


def test_a_market_with_a_single_scan_has_no_windows(db):
    run(db, scan(T0))

    assert observation_windows(db, MARKET, CONFIG) == []


def test_markets_do_not_mix_windows(db):
    # Alternating Scans of two Markets, 20 min apart: each Market's own gaps are 40 min.
    horde = Market(realm="Classic Beta PvP", faction="Horde", era=Era.BETA)
    run(
        db,
        scan(T0),
        scan(T0 + 20 * MINUTE, faction="Horde"),
        scan(T0 + 40 * MINUTE),
        scan(T0 + 2 * HOUR, faction="Horde"),
    )

    assert observation_windows(db, MARKET, CONFIG) == [ObservationWindow(T0, T0 + 40 * MINUTE)]
    assert observation_windows(db, horde, CONFIG) == []


# --- the expiry rule for Disappearances ---

# The least time left in each bucket is the previous bucket's longest: 0, 30 min, 2 h, 12 h.
LEAST_TIME_LEFT = {1: 0, 2: 30 * MINUTE, 3: 2 * HOUR, 4: 12 * HOUR}


@pytest.mark.parametrize("bucket", [2, 3, 4])
def test_expiry_is_impossible_when_the_gap_is_shorter_than_the_least_time_left(db, bucket):
    gap = LEAST_TIME_LEFT[bucket] - 1
    run(db, scan(T0, row(time_left=bucket)), scan(T0 + gap))

    [gone] = disappearances(db, MARKET, CONFIG)
    assert not gone.expiry_possible


@pytest.mark.parametrize("bucket", [2, 3, 4])
def test_expiry_is_possible_once_the_gap_reaches_the_least_time_left(db, bucket):
    gap = LEAST_TIME_LEFT[bucket]
    run(db, scan(T0, row(time_left=bucket)), scan(T0 + gap))

    [gone] = disappearances(db, MARKET, CONFIG)
    assert gone.expiry_possible


def test_bucket_1_could_always_have_expired(db):
    run(db, scan(T0, row(time_left=1)), scan(T0 + 1))

    [gone] = disappearances(db, MARKET, CONFIG)
    assert gone.expiry_possible


def test_a_listing_still_in_the_latest_scan_has_not_disappeared(db):
    run(db, scan(T0, row(unit=100), row(unit=200)), scan(T0 + 20 * MINUTE, row(unit=100)))

    assert [d.unit_buyout for d in disappearances(db, MARKET, CONFIG)] == [200]


# --- Sell Rate evidence ---


def test_window_hours_add_up_the_windows_that_end_in_the_range(db):
    run(
        db,
        scan(T0),
        scan(T0 + 20 * MINUTE),  # window: 20 min, before the range
        scan(T0 + 3 * HOUR),  # 2 h 40 min gap: not a window
        scan(T0 + 3 * HOUR + 30 * MINUTE),  # window: 30 min
        scan(T0 + 4 * HOUR + 15 * MINUTE),  # window: 45 min
        scan(T0 + 5 * HOUR),  # window: 45 min, ends at the range's (exclusive) end
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0 + HOUR, until=T0 + 5 * HOUR)

    assert evidence.window_hours == 1.25


def test_partial_sales_count_only_inside_windows(db):
    run(
        db,
        scan(T0, row(quantity=20)),
        scan(T0 + 20 * MINUTE, row(quantity=15)),  # window: 5 sold
        scan(T0 + 3 * HOUR, row(quantity=12)),  # not a window: 3 sold, unseen hours
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.sale_events == [
        SaleEvent(
            item_key=LINEN_KEY,
            unit_buyout=100,
            seen_at=T0 + 20 * MINUTE,
            units=5,
        )
    ]


def test_probable_sales_are_disappearances_in_a_window_that_could_not_expire(db):
    run(
        db,
        scan(
            T0,
            row(unit=100, quantity=3, time_left=4),  # gone within a window, 12 h+ left
            row(unit=200, time_left=1),  # gone within a window, but could have expired
            row(unit=300, time_left=4),  # gone only after a long gap
        ),
        scan(T0 + 20 * MINUTE, row(unit=300, time_left=4)),
        scan(T0 + 3 * HOUR),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.sale_events == [
        SaleEvent(
            item_key=LINEN_KEY,
            unit_buyout=100,
            seen_at=T0 + 20 * MINUTE,
            units=3,
        )
    ]


def test_single_unit_listings_gone_in_one_window_are_one_sale_event(db):
    # Units that don't stack are one Listing each, so one buyer's sweep is many
    # Disappearances (#72).
    run(db, scan(T0, row(), row(), row()), scan(T0 + 20 * MINUTE))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.sale_events == [
        SaleEvent(item_key=LINEN_KEY, unit_buyout=100, seen_at=T0 + 20 * MINUTE, units=3)
    ]


def test_a_sweep_across_prices_is_one_sale_event_at_the_dearest_price(db):
    run(db, scan(T0, row(unit=100), row(unit=110), row(unit=120)), scan(T0 + 20 * MINUTE))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.sale_events == [
        SaleEvent(item_key=LINEN_KEY, unit_buyout=120, seen_at=T0 + 20 * MINUTE, units=3)
    ]


def test_a_partial_sale_and_disappearances_in_one_window_are_one_sale_event(db):
    run(
        db,
        scan(T0, row(quantity=20, unit=100), row(unit=90), row(unit=110)),
        scan(T0 + 20 * MINUTE, row(quantity=15, unit=100)),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.sale_events == [
        SaleEvent(item_key=LINEN_KEY, unit_buyout=110, seen_at=T0 + 20 * MINUTE, units=7)
    ]


def test_the_same_item_key_in_two_windows_is_two_sale_events(db):
    run(
        db,
        scan(T0, row(unit=100), row(unit=110)),
        scan(T0 + 20 * MINUTE, row(unit=110)),
        scan(T0 + 40 * MINUTE),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.sale_events == [
        SaleEvent(item_key=LINEN_KEY, unit_buyout=100, seen_at=T0 + 20 * MINUTE, units=1),
        SaleEvent(item_key=LINEN_KEY, unit_buyout=110, seen_at=T0 + 40 * MINUTE, units=1),
    ]


def test_sale_events_are_counted_per_item_key(db):
    run(
        db,
        scan(T0, row(quantity=20), row(item=SILK, unit=100), row(item=SILK, unit=110)),
        scan(T0 + 20 * MINUTE, row(quantity=15)),  # linen: 1 Partial Sale; silk: 2 gone
        scan(T0 + 40 * MINUTE, row(quantity=10)),  # linen: 1 more Partial Sale
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.event_counts() == {LINEN_KEY: 2, SILK_KEY: 1}


# --- Reposts ---


def sales(evidence):
    return [(e.item_key, e.unit_buyout, e.units) for e in evidence.sale_events]


def test_a_disappearance_reposted_cheaper_is_not_a_probable_sale(db):
    run(db, scan(T0, row(unit=100)), scan(T0 + 20 * MINUTE, row(unit=90)))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert sales(evidence) == []


def test_a_new_listing_explains_only_one_disappearance_and_the_cheapest_stays_a_sale(db):
    # The 60 is the Repost; buyers clear the cheapest first, so the 50 is the sale.
    run(db, scan(T0, row(unit=50), row(unit=60)), scan(T0 + 20 * MINUTE, row(unit=45)))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert sales(evidence) == [(LINEN_KEY, 50, 1)]


def test_pairing_takes_every_repost_the_data_allows(db):
    # Cheapest new Listing to the most expensive Disappearance would pair 44 with 50 and
    # leave 45 with nothing it can explain. Pairing 50 with 48 and 45 with 44 gets both.
    run(
        db,
        scan(T0, row(unit=45), row(unit=50)),
        scan(T0 + 20 * MINUTE, row(unit=44), row(unit=48)),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert sales(evidence) == []


def own_row(**kwargs):
    return row(**kwargs) | {"own": True}


@pytest.mark.parametrize(
    "new_listing",
    [
        pytest.param(row(item=SILK, unit=90), id="other Item Key"),
        pytest.param(row(quantity=2, unit=90), id="other quantity"),
        pytest.param(own_row(unit=90), id="other own flag"),
        pytest.param(row(unit=101), id="priced higher"),
    ],
)
def test_a_new_listing_that_does_not_match_is_not_a_repost(db, new_listing):
    run(db, scan(T0, row(unit=100)), scan(T0 + 20 * MINUTE, new_listing))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert sales(evidence) == [(LINEN_KEY, 100, 1)]


def test_a_repost_at_the_same_price_is_not_a_sale(db):
    # Reposting resets time left, so it can't continue the old Listing (its bucket went up).
    run(db, scan(T0, row(unit=100, time_left=3)), scan(T0 + 20 * MINUTE, row(unit=100)))
    assert len(disappearances(db, MARKET, CONFIG)) == 1

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert sales(evidence) == []


def test_a_new_listing_from_a_later_window_is_not_a_repost(db):
    run(
        db,
        scan(T0, row(unit=100)),
        scan(T0 + 20 * MINUTE),
        scan(T0 + 40 * MINUTE, row(unit=90)),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert sales(evidence) == [(LINEN_KEY, 100, 1)]


def test_a_disappearance_that_could_have_expired_does_not_use_up_a_new_listing(db):
    run(
        db,
        scan(T0, row(unit=100, time_left=1), row(unit=80)),
        scan(T0 + 20 * MINUTE, row(unit=70)),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert sales(evidence) == []


def test_reposts_and_the_coincidence_baseline_are_counted_per_item_key(db):
    run(
        db,
        scan(
            T0,
            row(item=SILK, unit=100),  # reposted at 90
            row(unit=100),  # the only new Listing like it is priced higher: a coincidence
            row(quantity=5, unit=100),  # nothing new like it at all
        ),
        scan(T0 + 20 * MINUTE, row(item=SILK, unit=90), row(unit=120)),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.repost_counts() == {SILK_KEY: 1}
    assert evidence.coincidence_counts() == {LINEN_KEY: 1}


def test_a_disappearance_outside_an_observation_window_is_never_a_repost(db):
    run(db, scan(T0, row(unit=100)), scan(T0 + 3 * HOUR, row(unit=90)))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.repost_counts() == {}


def test_a_new_listing_does_not_explain_away_a_partial_sale(db):
    run(
        db,
        scan(T0, row(quantity=20)),
        scan(T0 + 20 * MINUTE, row(quantity=15), row(quantity=5, unit=90)),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert sales(evidence) == [(LINEN_KEY, 100, 5)]
    assert evidence.repost_counts() == {}


# --- the Probable Sale price check ---


@pytest.mark.parametrize(("unit", "sale"), [(120, True), (121, False)])
def test_a_probable_sale_is_priced_at_most_1_2_times_fair_value(db, unit, sale):
    # 11 units, so Fair Value is the cheapest 2: both at 100.
    run(
        db,
        scan(T0, row(quantity=10, unit=100), row(unit=unit)),
        scan(T0 + 20 * MINUTE, row(quantity=10, unit=100)),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert sales(evidence) == ([(LINEN_KEY, unit, 1)] if sale else [])


def test_the_price_check_uses_fair_value_from_the_scan_the_listing_was_last_seen_in(db):
    # Fair Value was 100 when the 115 was last seen; cheap supply arriving later (today's
    # Fair Value is 50) doesn't make it any less of a sale.
    run(
        db,
        scan(T0, row(quantity=10, unit=100), row(unit=115)),
        scan(T0 + 20 * MINUTE, row(quantity=10, unit=100)),
        scan(T0 + 40 * MINUTE, row(quantity=10, unit=100), row(quantity=10, unit=50)),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert sales(evidence) == [(LINEN_KEY, 115, 1)]


def test_a_probable_sale_is_also_priced_against_fair_value_in_the_scan_it_went_missing_in(db):
    # Fair Value was 100 when the 115 was last seen, but by the Scan it went missing in
    # 10 units at 50 were up (Fair Value 50). A buyer paying 115 while 50s were up is the
    # unlikely story, so it isn't a sale (#74).
    run(
        db,
        scan(T0, row(quantity=10, unit=100), row(unit=115)),
        scan(T0 + 20 * MINUTE, row(quantity=10, unit=100), row(quantity=10, unit=50)),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert sales(evidence) == []


def test_a_probable_sale_that_sold_out_its_item_key_is_priced_by_the_scan_it_was_last_seen_in(
    db,
):
    # Nothing of the Item Key is up in the Scan it went missing in, so only the Fair
    # Value it was last seen at (100) can judge it.
    run(
        db,
        scan(T0, row(quantity=10, unit=100), row(unit=115)),
        scan(T0 + 20 * MINUTE),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert sales(evidence) == [(LINEN_KEY, 115, 11)]


def test_fair_value_counts_units_as_they_stood_in_that_scan(db):
    # In the first Scan there are 21 units, so Fair Value is the cheapest 4, all at 100,
    # and the 125 is too dear to be a sale. 9 of the 100s sell afterward; counting only
    # the 1 left would put the 125 into the slice and let it through. Only the Partial
    # Sale of the 100s is left.
    run(
        db,
        scan(T0, row(quantity=10, unit=100), row(quantity=10, unit=150), row(unit=125)),
        scan(T0 + 20 * MINUTE, row(quantity=1, unit=100), row(quantity=10, unit=150)),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert sales(evidence) == [(LINEN_KEY, 100, 9)]


def test_a_disappearance_too_dear_to_be_a_sale_is_not_a_coincidence_either(db):
    # The 200 fails the price check (Fair Value 100), so a pricier new Listing next to it
    # says nothing about how often real sales look like Reposts.
    run(
        db,
        scan(T0, row(quantity=10, unit=100), row(unit=200)),
        scan(T0 + 20 * MINUTE, row(quantity=10, unit=100), row(unit=250)),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.coincidence_counts() == {}
