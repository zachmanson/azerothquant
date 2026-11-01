from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.fair_value import FairValueCache
from brain.history import Market, import_mailbox_reads, import_scans, open_history
from brain.mailbox import MailKind
from brain.observation import (
    ObservationWindow,
    SaleEvent,
    SaleRecord,
    disappearances,
    grader_calibration,
    observation_windows,
    own_outcomes,
    sale_records,
    sell_rate_calibration,
    sell_rate_evidence,
)

T0 = 1_790_000_000
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR

# Default cap (12 h, ADR-0035) and default time-left buckets (<30m, 30m-2h, 2-12h, 12-24h).
CONFIG = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))
# The old 1 h cap, for a gap that's no window but too short for its Listings to expire.
HOUR_CAP = replace(CONFIG, observation_window_max_seconds=HOUR)
MARKET = Market(realm="Classic Beta PvP", faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
LINEN_KEY = "2589"
SILK = "item:4306::::::::20:1490"
SILK_KEY = "4306"


def scan(at, *rows, faction="Alliance", dropped=()):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": "Classic Beta PvP",
        "character": "Kash-Patel",
        "faction": faction,
        "droppedRows": len(dropped),
        "droppedItemIDs": list(dropped),
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
    run(db, scan(T0), scan(T0 + 12 * HOUR))

    assert observation_windows(db, MARKET, CONFIG) == [ObservationWindow(T0, T0 + 12 * HOUR)]


def test_gap_just_over_the_cap_is_not_an_observation_window(db):
    over = 12 * HOUR + 1
    run(db, scan(T0), scan(T0 + over), scan(T0 + over + 20 * MINUTE))

    assert observation_windows(db, MARKET, CONFIG) == [
        ObservationWindow(T0 + over, T0 + over + 20 * MINUTE)
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
        scan(T0 + 13 * HOUR, faction="Horde"),
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
        scan(T0 + 13 * HOUR),  # 12 h 40 min gap: not a window
        scan(T0 + 13 * HOUR + 30 * MINUTE),  # window: 30 min
        scan(T0 + 14 * HOUR + 15 * MINUTE),  # window: 45 min
        scan(T0 + 15 * HOUR),  # window: 45 min, ends at the range's (exclusive) end
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0 + HOUR, until=T0 + 15 * HOUR)

    assert evidence.window_hours == 1.25


def test_partial_sales_count_only_inside_windows(db):
    run(
        db,
        scan(T0, row(quantity=20)),
        scan(T0 + 20 * MINUTE, row(quantity=15)),  # window: 5 sold
        scan(T0 + 13 * HOUR, row(quantity=12)),  # not a window: 3 sold, unseen hours
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

    evidence = sell_rate_evidence(db, MARKET, HOUR_CAP, since=T0, until=T0 + DAY)

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


def test_an_item_a_scan_dropped_rows_of_has_no_sale_events_in_the_windows_either_side(db):
    # #150: the middle Scan missed linen's rows for unloaded item data. The linen gone at
    # T0 + 20 min was missed, not sold, and the linen back at T0 + 40 min is no news either.
    # Even the linen that did go in the second window can't be told apart, so it's left out.
    run(
        db,
        scan(T0, *[row(unit=100) for _ in range(10)], row(item=SILK)),
        scan(T0 + 20 * MINUTE, row(unit=110), dropped=[2589]),
        # Stacks of 2, so nothing here pairs as a Repost of the linen gone at 110.
        scan(T0 + 40 * MINUTE, *[row(unit=100, quantity=2) for _ in range(5)]),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.event_counts() == {SILK_KEY: 1}


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
        pytest.param(row(unit=101), id="priced higher"),
    ],
)
def test_a_new_listing_that_does_not_match_is_not_a_repost(db, new_listing):
    run(db, scan(T0, row(unit=100)), scan(T0 + 20 * MINUTE, new_listing))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert sales(evidence) == [(LINEN_KEY, 100, 1)]


def test_a_repost_pairs_regardless_of_own(db):
    # A Pooled Scan sees my auctions as someone else's, so own can't tell Reposts apart.
    run(db, scan(T0, row(unit=100)), scan(T0 + 20 * MINUTE, own_row(unit=90)))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert sales(evidence) == []


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

    evidence = sell_rate_evidence(db, MARKET, HOUR_CAP, since=T0, until=T0 + DAY)

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


# --- Observation Windows up to 12 hours (ADR-0035) ---


def test_a_6_hour_gap_is_a_window_where_only_a_listing_that_outlasts_it_is_a_probable_sale(db):
    run(
        db,
        scan(
            T0,
            row(item=LINEN, quantity=3, time_left=4),  # 12 h+ left: can't have expired in 6 h
            row(item=SILK, time_left=3),  # 2-12 h left: may have expired
        ),
        scan(T0 + 6 * HOUR),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.window_hours == 6
    assert evidence.sale_events == [
        SaleEvent(item_key=LINEN_KEY, unit_buyout=100, seen_at=T0 + 6 * HOUR, units=3)
    ]


def test_a_partial_sale_in_a_6_hour_gap_is_a_sale_event(db):
    run(db, scan(T0, row(quantity=20)), scan(T0 + 6 * HOUR, row(quantity=15)))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.sale_events == [
        SaleEvent(item_key=LINEN_KEY, unit_buyout=100, seen_at=T0 + 6 * HOUR, units=5)
    ]


@pytest.mark.parametrize(("gap", "counts"), [(12 * HOUR, True), (12 * HOUR + 1, False)])
def test_a_gap_counts_up_to_12_hours_and_past_them_adds_no_hours_or_sale_events(db, gap, counts):
    run(db, scan(T0, row(quantity=20)), scan(T0 + gap, row(quantity=15)))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.window_hours == (gap / HOUR if counts else 0)
    assert evidence.sale_events == (
        [SaleEvent(item_key=LINEN_KEY, unit_buyout=100, seen_at=T0 + gap, units=5)]
        if counts
        else []
    )


# --- Sale Records, the Backtest's evidence (#167) ---


def test_a_partial_sale_in_a_long_gap_is_a_sale_record(db):
    run(
        db,
        scan(T0, row(quantity=20)),
        scan(T0 + 20 * HOUR, row(quantity=15)),
    )

    assert sale_records(db, MARKET, CONFIG) == [
        SaleRecord(
            item_key=LINEN_KEY, unit_buyout=100, units=5, last_seen=T0, seen_at=T0 + 20 * HOUR
        )
    ]


# The 12-48 h bucket set to 14-48 h, so expiry can't explain a 13 h gap and only the cap does.
LONG_BUCKETS = replace(CONFIG, time_left_max_seconds=(30 * MINUTE, 2 * HOUR, 14 * HOUR, 48 * HOUR))


@pytest.mark.parametrize(("gap", "counts"), [(12 * HOUR, True), (13 * HOUR, False)])
def test_a_vanished_listing_is_a_sale_record_over_a_gap_of_at_most_12_hours(db, gap, counts):
    import_scans(
        db, [scan(T0, row(quantity=3, time_left=4)), scan(T0 + gap)], Era.BETA, LONG_BUCKETS
    )

    expected = [SaleRecord(LINEN_KEY, 100, 3, T0, T0 + gap)] if counts else []
    assert sale_records(db, MARKET, LONG_BUCKETS) == expected


def test_a_listing_reposted_cheaper_over_a_long_gap_is_not_a_sale_record(db):
    # 2-12 h left, gone 3 h later: it can't have expired, but the same stack is back cheaper.
    run(
        db,
        scan(T0, row(quantity=3, unit=100, time_left=4)),
        scan(T0 + 3 * HOUR, row(quantity=3, unit=90)),
    )

    assert sale_records(db, MARKET, CONFIG) == []


@pytest.mark.parametrize(("unit", "counts"), [(120, True), (121, False)])
@pytest.mark.parametrize("partial", [False, True], ids=["vanished", "partial"])
def test_a_sale_record_is_priced_at_most_1_2_times_fair_value_where_last_seen(
    db, unit, counts, partial
):
    # 11 or 12 units, so Fair Value is the cheapest 2: both at 100.
    # Either one of the 2 sells from the stack, or the 1 vanishes.
    sold = row(quantity=2 if partial else 1, unit=unit, time_left=4)
    left = [row(quantity=1, unit=unit, time_left=4)] if partial else []
    run(
        db,
        scan(T0, row(quantity=10, unit=100), sold),
        scan(T0 + 3 * HOUR, row(quantity=10, unit=100), *left),
    )

    assert [r.unit_buyout for r in sale_records(db, MARKET, CONFIG)] == ([unit] if counts else [])


@pytest.mark.parametrize("dropped_in", ["before", "after"])
def test_an_item_either_scan_dropped_rows_of_has_no_sale_records(db, dropped_in):
    run(
        db,
        scan(
            T0, row(quantity=20), row(item=SILK), dropped=[2589] if dropped_in == "before" else []
        ),
        scan(T0 + 3 * HOUR, row(quantity=15), dropped=[2589] if dropped_in == "after" else []),
    )

    assert [r.item_key for r in sale_records(db, MARKET, CONFIG)] == [SILK_KEY]


def test_a_listing_that_could_have_expired_over_the_gap_is_not_a_sale_record(db):
    # 30 min-2 h left, gone 3 h later.
    run(db, scan(T0, row(time_left=2)), scan(T0 + 3 * HOUR))

    assert sale_records(db, MARKET, CONFIG) == []


# --- the grader checked on own Listings (#167) ---


def named_row(name, **kwargs):
    return row(**kwargs) | {"own": True, "name": name}


def sold(name, count, price):
    return {
        "sender": "Alliance Auction House",
        "subject": f"Auction successful: {name}",
        "money": price,
        "daysLeft": 30,
        "invoice": {"invoiceType": "seller", "itemName": name, "bid": price, "count": count},
    }


def cancelled(name, item, count):
    return {
        "sender": "Alliance Auction House",
        "subject": f"Auction cancelled: {name}",
        "money": 0,
        "daysLeft": 30,
        "firstItemQuantity": count,
        "firstItemLink": f"|cffffffff|H{item}|h[{name}]|h|r",
    }


def test_the_grader_is_checked_on_own_listings_against_the_mail_that_says_what_became_of_them(db):
    # Four own Listings gone an hour later. The Sale Record rule calls three of them gone
    # (a Linen of 1, a Linen of 2, the Silk); the fourth had under 30 min left, so it
    # could have expired. The mail: both Linen called gone sold, the Silk was cancelled,
    # and the Linen that could have expired sold too, a sale the rule didn't catch. Sold
    # mails count only when matched to an own Listing that went missing (as p6).
    run(
        db,
        scan(
            T0,
            named_row("Linen Cloth", unit=100),
            named_row("Linen Cloth", quantity=2, unit=100),
            named_row("Silk Cloth", item=SILK, unit=300),
            named_row("Linen Cloth", unit=50, time_left=1),
        ),
        scan(T0 + HOUR),
    )
    mails = [
        sold("Linen Cloth", 1, 100),
        cancelled("Silk Cloth", SILK, 1),
        sold("Linen Cloth", 1, 50),
        sold("Linen Cloth", 2, 200),
        # Sold between two Scans, so no Listing went missing for it: not counted.
        sold("Silk Cloth", 1, 999),
    ]
    read = {
        "readAt": T0 + 2 * HOUR,
        "realm": MARKET.realm,
        "character": "Kash-Patel",
        "shownCount": len(mails),
        "totalCount": len(mails),
        "skippedMails": 0,
        "mails": [{"index": i + 1, **m} for i, m in enumerate(mails)],
    }
    import_mailbox_reads(db, [read], Era.BETA, CONFIG)

    calibration = grader_calibration(db, MARKET, CONFIG)

    assert (calibration.matched, calibration.sold, calibration.sold_mails) == (3, 2, 3)


# --- own Cancelled/Expired Listings leave Sell Rate (#153) ---


def expired(name, item, count):
    return cancelled(name, item, count) | {"subject": f"Auction expired: {name}"}


def read_mail(db, at, *mails):
    read = {
        "readAt": at,
        "realm": MARKET.realm,
        "character": "Kash-Patel",
        "shownCount": len(mails),
        "totalCount": len(mails),
        "skippedMails": 0,
        "mails": [{"index": i + 1, **m} for i, m in enumerate(mails)],
    }
    import_mailbox_reads(db, [read], Era.BETA, CONFIG)


def own_linen_gone(db):
    """An own Linen gone an hour later, next to another player's Linen that stays."""
    run(
        db,
        scan(T0, row(unit=100), named_row("Linen Cloth", unit=100)),
        scan(T0 + HOUR, row(unit=100)),
    )


@pytest.mark.parametrize(
    "mails, sales",
    [
        ([cancelled("Linen Cloth", LINEN, 1)], 0),
        ([expired("Linen Cloth", LINEN, 1)], 0),
        ([sold("Linen Cloth", 1, 100)], 1),
        ([], 1),
    ],
    ids=["cancelled", "expired", "sold", "no mail"],
)
def test_an_own_listing_whose_mail_says_cancelled_or_expired_is_no_probable_sale(db, mails, sales):
    own_linen_gone(db)
    read_mail(db, T0 + 2 * HOUR, *mails)

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert len(evidence.sale_events) == sales
    assert evidence.reposts == []


def test_a_cancelled_mail_read_after_sell_rate_was_worked_out_drops_the_sale_next_pass(db):
    own_linen_gone(db)
    cache = FairValueCache()
    first = sell_rate_evidence(db, MARKET, CONFIG, T0, T0 + DAY, fair_value_cache=cache)

    read_mail(db, T0 + 2 * HOUR, cancelled("Linen Cloth", LINEN, 1))
    cache.start_pass()
    second = sell_rate_evidence(db, MARKET, CONFIG, T0, T0 + DAY, fair_value_cache=cache)

    assert (len(first.sale_events), len(second.sale_events)) == (1, 0)


def test_sell_rate_as_of_a_time_uses_only_the_mail_read_by_then(db):
    # A Backtest asks for Sell Rate as of past Scans: mail read later can't drop a sale yet.
    own_linen_gone(db)
    read_mail(db, T0 + 2 * HOUR, cancelled("Linen Cloth", LINEN, 1))

    before = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + 2 * HOUR)
    after = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + 2 * HOUR + 1)

    assert (len(before.sale_events), len(after.sale_events)) == (1, 0)


def test_an_own_cancelled_listing_paired_as_a_repost_stays_one(db):
    # My Linen at 100 was cancelled and another player's at 90 went missing; one new Linen
    # at 90 came up. Pairing is as it ever was: the new Linen is my Listing's Repost, so
    # the other player's is still the sale. Only Probable Sales are dropped, so mine stays
    # a Repost (and frees no new Listing for the other player's).
    run(
        db,
        scan(T0, row(unit=120), row(unit=90, time_left=3), named_row("Linen Cloth", unit=100)),
        scan(T0 + HOUR, row(unit=120), row(unit=90)),
    )
    read_mail(db, T0 + 2 * HOUR, cancelled("Linen Cloth", LINEN, 1))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert [(e.unit_buyout, e.units) for e in evidence.sale_events] == [(90, 1)]
    assert [(d.own, d.unit_buyout) for d in evidence.reposts] == [(True, 100)]


def test_each_own_listing_is_matched_to_its_outcome_once_oldest_first(db):
    # Two own Linen of 1, gone at T0 + 1 h and T0 + 2 h, and one Cancelled mail for a
    # Linen of 1 read after both: it's the older Listing's.
    run(
        db,
        scan(
            T0,
            row(unit=100),
            named_row("Linen Cloth", unit=100),
            named_row("Linen Cloth", unit=100, time_left=3),
        ),
        scan(T0 + HOUR, row(unit=100), named_row("Linen Cloth", unit=100, time_left=3)),
        scan(T0 + 2 * HOUR, row(unit=100)),
    )
    read_mail(db, T0 + 3 * HOUR, cancelled("Linen Cloth", LINEN, 1))

    matched = own_outcomes(db, MARKET)

    assert [(listing.last_seen, o.kind) for listing, o in matched] == [(T0, MailKind.CANCELLED)]
    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)
    assert [e.seen_at for e in evidence.sale_events] == [T0 + 2 * HOUR]


def test_sell_rate_is_checked_on_own_listings_before_the_drop(db):
    # Three own Listings gone an hour later, next to other players' that stay. The Sell
    # Rate rule calls the Linen of 1 and the Silk Probable Sales; the Linen of 2 had under
    # 30 min left. The mail: the Linen of 1 sold, the Silk was cancelled, the Linen of 2
    # sold too, a sale the rule didn't catch.
    run(
        db,
        scan(
            T0,
            row(unit=100),
            row(item=SILK, unit=300),
            named_row("Linen Cloth", unit=100),
            named_row("Silk Cloth", item=SILK, unit=300),
            named_row("Linen Cloth", quantity=2, unit=100, time_left=1),
        ),
        scan(T0 + HOUR, row(unit=100), row(item=SILK, unit=300)),
    )
    read_mail(
        db,
        T0 + 2 * HOUR,
        sold("Linen Cloth", 1, 100),
        cancelled("Silk Cloth", SILK, 1),
        sold("Linen Cloth", 2, 200),
    )

    calibration = sell_rate_calibration(db, MARKET, CONFIG)

    assert (calibration.matched, calibration.sold, calibration.sold_mails) == (2, 1, 2)


# --- own Purchases leave Sell Rate (#152) ---


def purchase_mail(name, item, count, price):
    """A Purchase of `count` for `price` copper, arrived when its Mailbox Read was read."""
    return {
        "sender": "Alliance Auction House",
        "subject": f"Auction won: {name}",
        "money": 0,
        "daysLeft": 30,
        "firstItemQuantity": count,
        "firstItemLink": f"|cffffffff|H{item}|h[{name}]|h|r",
        "invoice": {"invoiceType": "buyer", "itemName": name, "bid": price, "count": count},
    }


def test_own_purchases_of_the_cheapest_listings_are_no_sale_event(db):
    # Probe P2 of the 2026-10-06 review: the player buys the 3 cheapest of 10 Linen and
    # nothing else trades.
    run(
        db,
        scan(T0, *[row(unit=100 + i) for i in range(10)]),
        scan(T0 + HOUR, *[row(unit=103 + i) for i in range(7)]),
    )
    read_mail(
        db,
        T0 + 30 * MINUTE,
        *[purchase_mail("Linen Cloth", LINEN, 1, unit) for unit in (100, 101, 102)],
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.sale_events == []


def test_an_own_sweep_across_listings_leaves_only_other_buyers_units(db):
    # One Purchase of 3 Linen for 303 took the 100, 101 and 102; another player bought
    # the 105. The Sale Event is theirs alone, at their price.
    run(
        db,
        scan(T0, *[row(unit=100 + i) for i in range(10)]),
        scan(T0 + HOUR, *[row(unit=103 + i) for i in range(7) if i != 2]),
    )
    read_mail(db, T0 + 30 * MINUTE, purchase_mail("Linen Cloth", LINEN, 3, 303))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert [(e.unit_buyout, e.units) for e in evidence.sale_events] == [(105, 1)]


def test_an_own_purchase_of_a_listing_no_scan_saw_takes_nothing(db):
    # The player bought a Linen for 90 posted and gone between the Scans; another player
    # bought the 100.
    run(db, scan(T0, row(unit=100), row(unit=110)), scan(T0 + HOUR, row(unit=110)))
    read_mail(db, T0 + 30 * MINUTE, purchase_mail("Linen Cloth", LINEN, 1, 90))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert [(e.unit_buyout, e.units) for e in evidence.sale_events] == [(100, 1)]


def test_an_own_purchase_out_of_a_stack_is_no_partial_sale(db):
    run(db, scan(T0, row(quantity=10, unit=100)), scan(T0 + HOUR, row(quantity=7, unit=100)))
    read_mail(db, T0 + 30 * MINUTE, purchase_mail("Linen Cloth", LINEN, 3, 300))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.sale_events == []


def test_an_own_purchase_takes_units_only_from_the_window_it_fell_in(db):
    # Another player bought a Linen in the first window; the player bought one in the
    # second.
    run(
        db,
        scan(T0, row(unit=100), row(unit=100)),
        scan(T0 + HOUR, row(unit=100)),
        scan(T0 + 2 * HOUR),
    )
    read_mail(db, T0 + 90 * MINUTE, purchase_mail("Linen Cloth", LINEN, 1, 100))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert [e.seen_at for e in evidence.sale_events] == [T0 + HOUR]


def test_an_own_purchase_read_after_the_range_is_still_a_sale_in_it(db):
    # Arrived at T0 + 30 min, read at T0 + 2 h: a Backtest as of then can't know of it
    # yet (#153).
    run(db, scan(T0, row(unit=100)), scan(T0 + HOUR))
    read_mail(
        db, T0 + 2 * HOUR, purchase_mail("Linen Cloth", LINEN, 1, 100) | {"daysLeft": 30 - 1.5 / 24}
    )

    before = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + 2 * HOUR)
    after = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert ([e.units for e in before.sale_events], after.sale_events) == ([1], [])


def test_own_purchases_are_no_sale_records(db):
    # Over a 6 h gap the player bought 2 of a stack of 20 and a Linen of 1 for 100;
    # other players bought 3 of the stack and the 120.
    run(
        db,
        scan(T0, row(quantity=20), row(unit=100), row(unit=120)),
        scan(T0 + 6 * HOUR, row(quantity=15)),
    )
    read_mail(
        db,
        T0 + HOUR,
        purchase_mail("Linen Cloth", LINEN, 2, 200),
        purchase_mail("Linen Cloth", LINEN, 1, 100),
    )

    units = Counter()
    for r in sale_records(db, MARKET, CONFIG):
        units[r.unit_buyout] += r.units
    assert units == {100: 3, 120: 1}


def test_an_own_purchase_takes_the_listing_at_its_price_before_any_cheaper_one(db):
    # The player bought the 200, priced too high to be a Probable Sale; another player
    # bought the 100.
    run(db, scan(T0, row(unit=100), row(unit=200), row(unit=300)), scan(T0 + HOUR, row(unit=300)))
    read_mail(db, T0 + 30 * MINUTE, purchase_mail("Linen Cloth", LINEN, 1, 200))

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert [(e.unit_buyout, e.units) for e in evidence.sale_events] == [(100, 1)]


# --- a Listing back in the next Scan was missed, not sold (#150) ---


def test_listings_a_scan_missed_that_are_back_in_the_next_are_no_sale_event(db):
    # Probe P1 of the 2026-10-06 review: the middle Scan misses 10 Linen and nothing
    # trades. The dropped rows went unrecorded, as before #150's itemIDs.
    run(
        db,
        scan(T0, *[row(unit=100) for _ in range(10)]),
        scan(T0 + HOUR),
        scan(T0 + 2 * HOUR, *[row(unit=100) for _ in range(10)]),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.sale_events == []


def test_a_listing_back_with_more_time_left_is_a_new_post_so_the_old_one_sold(db):
    run(
        db,
        scan(T0, row(unit=100, time_left=3)),
        scan(T0 + HOUR),
        scan(T0 + 2 * HOUR, row(unit=100, time_left=4)),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert [(e.seen_at, e.units) for e in evidence.sale_events] == [(T0 + HOUR, 1)]


def test_a_listing_back_in_the_next_scan_explains_only_one_that_went_missing(db):
    run(
        db,
        scan(T0, row(unit=100), row(unit=100)),
        scan(T0 + HOUR),
        scan(T0 + 2 * HOUR, row(unit=100)),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert [(e.seen_at, e.units) for e in evidence.sale_events] == [(T0 + HOUR, 1)]


def test_a_scan_after_the_range_does_not_say_a_listing_was_missed(db):
    # A Backtest as of T0 + 2 h hasn't seen the Scan at T0 + 2 h yet.
    run(
        db,
        scan(T0, row(unit=100)),
        scan(T0 + HOUR),
        scan(T0 + 2 * HOUR, row(unit=100)),
    )

    before = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + 2 * HOUR)
    after = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + 2 * HOUR + 1)

    assert ([e.units for e in before.sale_events], after.sale_events) == ([1], [])


def test_a_listing_a_scan_missed_that_is_back_in_the_next_is_no_sale_record(db):
    run(
        db,
        scan(T0, row(unit=100), row(unit=100)),
        scan(T0 + HOUR),
        scan(T0 + 2 * HOUR, row(unit=100)),
    )

    assert [(r.seen_at, r.units) for r in sale_records(db, MARKET, CONFIG)] == [(T0 + HOUR, 1)]


def test_a_listing_is_back_only_as_it_stood_in_the_scan_it_came_back_in(db):
    # Back with more time left at T0 + 2 h (a new post, so the old one sold), even though
    # its bucket drops to the old one's by T0 + 3 h.
    run(
        db,
        scan(T0, row(unit=100, time_left=3)),
        scan(T0 + HOUR),
        scan(T0 + 2 * HOUR, row(unit=100, time_left=4)),
        scan(T0 + 3 * HOUR, row(unit=100, time_left=3)),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert [(e.seen_at, e.units) for e in evidence.sale_events] == [(T0 + HOUR, 1)]


def test_a_listing_back_that_sold_part_since_was_still_missed(db):
    # Back as a stack of 2 at T0 + 2 h, one of which sold by T0 + 3 h.
    run(
        db,
        scan(T0, row(quantity=2, unit=100)),
        scan(T0 + HOUR),
        scan(T0 + 2 * HOUR, row(quantity=2, unit=100)),
        scan(T0 + 3 * HOUR, row(quantity=1, unit=100)),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert [(e.seen_at, e.units) for e in evidence.sale_events] == [(T0 + 3 * HOUR, 1)]


@pytest.mark.parametrize("own_first", [True, False])
def test_an_own_listing_gone_at_a_purchases_price_does_not_take_it(db, own_first):
    # The player cancelled their own Linen at 100 and bought another player's at 100:
    # nothing sold to anyone else, whichever Listing the history has first.
    pair = [named_row("Linen Cloth", unit=100), row(unit=100)]
    run(
        db,
        scan(T0, *(pair if own_first else pair[::-1]), row(unit=300)),
        scan(T0 + HOUR, row(unit=300)),
    )
    read_mail(
        db,
        T0 + 30 * MINUTE,
        purchase_mail("Linen Cloth", LINEN, 1, 100),
        cancelled("Linen Cloth", LINEN, 1),
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.sale_events == []


def test_a_sale_record_is_back_only_as_it_stood_in_the_scan_it_came_back_in(db):
    run(
        db,
        scan(T0, row(unit=100, time_left=3)),
        scan(T0 + HOUR),
        scan(T0 + 2 * HOUR, row(unit=100, time_left=4)),
        scan(T0 + 3 * HOUR, row(unit=100, time_left=3)),
    )

    assert [(r.seen_at, r.units) for r in sale_records(db, MARKET, CONFIG)] == [(T0 + HOUR, 1)]
