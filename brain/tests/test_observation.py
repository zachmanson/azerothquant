from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.history import Market, import_scans, open_history
from brain.observation import (
    ObservationWindow,
    SaleEvent,
    SaleKind,
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
            own=False,
            seen_at=T0 + 20 * MINUTE,
            units=5,
            kind=SaleKind.PARTIAL_SALE,
        )
    ]


def test_probable_sale_candidates_are_disappearances_in_a_window_that_could_not_expire(db):
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
            own=False,
            seen_at=T0 + 20 * MINUTE,
            units=3,
            kind=SaleKind.PROBABLE_SALE_CANDIDATE,
        )
    ]


def test_sale_events_are_counted_per_item_key(db):
    run(
        db,
        scan(T0, row(quantity=20), row(item=SILK, unit=100), row(item=SILK, unit=200)),
        scan(T0 + 20 * MINUTE, row(quantity=15)),  # linen: 1 Partial Sale; silk: 2 gone
        scan(T0 + 40 * MINUTE, row(quantity=10)),  # linen: 1 more Partial Sale
    )

    evidence = sell_rate_evidence(db, MARKET, CONFIG, since=T0, until=T0 + DAY)

    assert evidence.event_counts() == {LINEN_KEY: 2, SILK_KEY: 2}
