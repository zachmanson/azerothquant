"""Importing Pooled Scans (#122, ADR-0026): archived apart from the player's own, matched
like them, and turned away when truncated."""

import gzip
import json
from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.history import (
    Market,
    import_pooled_scans,
    import_scans,
    listings,
    open_history,
    scan_times,
)
from brain.pool import strip_scan

T0 = 1_790_000_000
MINUTE = 60

MARKET = Market(realm="Classic Beta PvP", faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
WOOL = "item:2592::::::::20:1490"


def scan(at, *rows):
    return {
        "requestedAt": at,
        "realm": "Classic Beta PvP",
        "character": "Kash-Patel",
        "faction": "Alliance",
        "droppedRows": 0,
        "listings": list(rows),
    }


def pooled(at, *rows):
    """A Pooled Scan as it comes down from the pool: someone else's, stripped."""
    return strip_scan({**scan(at, *rows), "character": "Someone-Else"})


def row(item=LINEN, quantity=1, unit=100, time_left=4, own=False):
    r = {"itemString": item, "quantity": quantity, "buyout": quantity * unit, "timeLeft": time_left}
    if own:
        r["own"] = True
    return r


def rows(n):
    """n Listings, each its own price so none of them match another."""
    return [row(unit=100 + i) for i in range(n)]


@pytest.fixture
def config(tmp_path):
    return Config(
        installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),),
        archive_dir=tmp_path / "archive",
    )


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def pool_file(config, at) -> Path:
    return config.archive_dir / "beta" / "Classic Beta PvP-Alliance" / "pool" / f"{at}.json.gz"


def test_a_pooled_scan_is_archived_under_pool_and_imported_like_an_own_scan(db, config):
    import_scans(db, [scan(T0, row(unit=100, own=True))], Era.BETA, config)

    report = import_pooled_scans(db, [("p1", pooled(T0 + MINUTE, row(unit=100)))], Era.BETA, config)

    assert report.scans_imported == 1
    assert scan_times(db, MARKET) == [T0, T0 + MINUTE]
    with gzip.open(pool_file(config, T0 + MINUTE), "rt", encoding="utf-8") as f:
        archived = json.load(f)
    assert archived["poolId"] == "p1"
    assert "character" not in archived["scan"]
    # Seen by the Pooled Scan as someone else's, the Listing is still the player's own.
    [listing] = listings(db, MARKET)
    assert listing.own


def test_a_truncated_pooled_scan_is_archived_but_not_imported(db, config):
    import_scans(db, [scan(T0 + i * MINUTE, *rows(100)) for i in range(3)], Era.BETA, config)

    truncated = pooled(T0 + 3 * MINUTE, *rows(79))
    report = import_pooled_scans(db, [("p1", truncated)], Era.BETA, config)

    assert report.scans_imported == 0
    assert report.scans_incomplete == 1
    assert report.warnings
    assert scan_times(db, MARKET) == [T0, T0 + MINUTE, T0 + 2 * MINUTE]
    assert pool_file(config, T0 + 3 * MINUTE).exists()


def test_a_pooled_scan_at_the_completeness_bar_is_imported(db, config):
    import_scans(db, [scan(T0 + i * MINUTE, *rows(100)) for i in range(3)], Era.BETA, config)

    report = import_pooled_scans(db, [("p1", pooled(T0 + 3 * MINUTE, *rows(80)))], Era.BETA, config)

    assert report.scans_imported == 1


def test_the_player_s_own_scan_is_never_rejected_as_truncated(db, config):
    import_scans(db, [scan(T0 + i * MINUTE, *rows(100)) for i in range(3)], Era.BETA, config)

    report = import_scans(db, [scan(T0 + 3 * MINUTE, *rows(10))], Era.BETA, config)

    assert report.scans_imported == 1


def test_the_completeness_guard_needs_three_scans_to_compare_against(db, config):
    import_scans(db, [scan(T0 + i * MINUTE, *rows(100)) for i in range(2)], Era.BETA, config)

    report = import_pooled_scans(db, [("p1", pooled(T0 + 2 * MINUTE, *rows(10)))], Era.BETA, config)

    assert report.scans_imported == 1


def test_the_completeness_guard_compares_against_the_median_of_the_recent_scans(db, config):
    # Twelve Scans: the two oldest are huge but outside the window of 10, and one recent
    # outlier doesn't move the median.
    sizes = [1000, 1000, 50, 50, 50, 50, 50, 50, 50, 50, 50, 500]
    import_scans(
        db, [scan(T0 + i * MINUTE, *rows(n)) for i, n in enumerate(sizes)], Era.BETA, config
    )

    report = import_pooled_scans(
        db, [("p1", pooled(T0 + 12 * MINUTE, *rows(40)))], Era.BETA, config
    )

    assert report.scans_imported == 1


def history(conn) -> tuple:
    return sorted(listings(conn, MARKET)), scan_times(conn, MARKET)


def test_a_late_pooled_scan_is_matched_into_its_place_in_time(db, config, tmp_path, request):
    own = [
        scan(T0, row(LINEN, quantity=5, own=True), row(WOOL, unit=300)),
        scan(T0 + 20 * MINUTE, row(LINEN, quantity=3, own=True), row(WOOL, unit=300)),
        scan(T0 + 40 * MINUTE, row(LINEN, quantity=3, own=True)),
    ]
    pool = [
        ("p1", pooled(T0 + 10 * MINUTE, row(LINEN, quantity=4), row(WOOL, unit=300))),
        ("p2", pooled(T0 + 30 * MINUTE, row(LINEN, quantity=3), row(WOOL, unit=300))),
    ]
    import_scans(db, own, Era.BETA, config)

    report = import_pooled_scans(db, pool, Era.BETA, config)

    assert report.scans_rematched == 2
    in_order = open_history(":memory:")
    request.addfinalizer(in_order.close)
    time_order_config = Config(installs=config.installs, archive_dir=tmp_path / "in-order")
    import_scans(in_order, own[:1], Era.BETA, time_order_config)
    import_pooled_scans(in_order, pool[:1], Era.BETA, time_order_config)
    import_scans(in_order, own[1:2], Era.BETA, time_order_config)
    import_pooled_scans(in_order, pool[1:], Era.BETA, time_order_config)
    import_scans(in_order, own[2:], Era.BETA, time_order_config)
    assert history(db) == history(in_order)
    # The player's Linen stays one own Listing throughout, never a Disappearance.
    assert [lst.own for lst in listings(db, MARKET) if lst.item_key.startswith("2589")] == [True]


def test_an_own_scan_replaces_a_pooled_scan_from_the_same_second(db, config, tmp_path):
    # `brain rebuild` has no arrival order to go by, so the own Scan always wins, and the
    # history built live has to agree with it.
    pool = [("p1", pooled(T0, row(unit=100)))]
    own = [scan(T0, row(unit=100, own=True)), scan(T0 + MINUTE, row(unit=100, own=True))]
    import_pooled_scans(db, pool, Era.BETA, config)

    report = import_scans(db, own, Era.BETA, config)

    assert report.scans_imported == 2
    [listing] = listings(db, MARKET)
    assert listing.own
    rebuilt = open_history(":memory:")
    no_archive = Config(installs=config.installs)
    import_scans(rebuilt, own, Era.BETA, no_archive)
    try:
        assert history(db) == history(rebuilt)
    finally:
        rebuilt.close()
