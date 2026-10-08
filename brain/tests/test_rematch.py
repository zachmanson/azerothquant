"""A Scan older than its Market's latest re-matches the Market's tail (#118, ADR-0026):
history built in any arrival order matches history built in time order."""

import dataclasses
import random
import shutil
import sqlite3
from pathlib import Path

import pytest

from brain.archive import Archive
from brain.config import Config, Era, Install
from brain.history import Market, import_scans, listings, open_history, partial_sales
from brain.observation import sell_rate_evidence

T0 = 1_790_000_000
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR

MARKET = Market(realm="Classic Beta PvP", faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
WOOL = "item:2592::::::::20:1490"


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


def row(item=LINEN, quantity=1, unit=100, time_left=4, own=False):
    r = {"itemString": item, "quantity": quantity, "buyout": quantity * unit, "timeLeft": time_left}
    if own:
        r["own"] = True
    return r


CONFIG = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(CONFIG, archive_dir=tmp_path / "archive")


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def history(conn: sqlite3.Connection) -> tuple:
    """Everything a Market's Scans leave in the history, independent of row IDs."""
    evidence = sell_rate_evidence(conn, MARKET, CONFIG, since=0, until=T0 + 30 * DAY)
    return (
        sorted(listings(conn, MARKET)),
        sorted(partial_sales(conn, MARKET)),
        evidence.sale_events,
    )


def in_time_order(scans, tmp_path) -> tuple:
    config = dataclasses.replace(CONFIG, archive_dir=tmp_path / "time-order-archive")
    conn = open_history(":memory:")
    try:
        import_scans(conn, sorted(scans, key=lambda s: s["requestedAt"]), Era.BETA, config)
        return history(conn)
    finally:
        conn.close()


def in_arrival_order(scans, config) -> tuple:
    conn = open_history(":memory:")
    try:
        for s in scans:
            import_scans(conn, [s], Era.BETA, config)
        return history(conn)
    finally:
        conn.close()


def test_a_late_scan_is_merged_into_its_place_in_time(config, tmp_path):
    # The late Scan at T0 + 20 min sees 15 Linen sold down from 20 and its time-left
    # drop, and the Wool Listing gone; later Scans carry on from there.
    scans = [
        scan(T0, row(quantity=20), row(item=WOOL, unit=300)),
        scan(T0 + 40 * MINUTE, row(quantity=10, time_left=3)),
        scan(T0 + 60 * MINUTE, row(quantity=8, time_left=3), row(item=WOOL, unit=250)),
        scan(T0 + 20 * MINUTE, row(quantity=15, time_left=3)),
    ]

    assert in_arrival_order(scans, config) == in_time_order(scans, tmp_path)


def test_a_rematch_keeps_the_items_a_rewound_scan_dropped_rows_of(config, tmp_path):
    # #150: the Scan at T0 + 40 min dropped Wool's rows, so the Wool missing from it never
    # counts as sold, whatever order the Scans came in.
    dropped_wool = scan(T0 + 40 * MINUTE, row(quantity=10, time_left=3))
    dropped_wool["droppedRows"], dropped_wool["droppedItemIDs"] = 1, [2592]
    scans = [
        scan(T0, row(quantity=20), row(item=WOOL, unit=300)),
        dropped_wool,
        scan(T0 + 20 * MINUTE, row(quantity=15, time_left=3), row(item=WOOL, unit=300)),
    ]

    arrived = in_arrival_order(scans, config)

    assert arrived == in_time_order(scans, tmp_path)
    assert {e.item_key for e in arrived[2]} == {"2589"}


def test_a_rematch_takes_back_own_from_a_listing_it_no_longer_matches_to_an_own_row(
    config, tmp_path
):
    # Arriving before the late Scan, the own row at T0 + 40 min can only continue the
    # 6-unit Listing (the other one's time-left is already 3), so that one turns own. The
    # late Scan drops its time-left too, so in time order the own row is a new Listing
    # and the 6-unit one never was own.
    scans = [
        scan(T0, row(quantity=5, time_left=3), row(quantity=6, time_left=4)),
        scan(
            T0 + 40 * MINUTE,
            row(quantity=5, time_left=4, own=True),
            row(quantity=5, time_left=3),
        ),
        scan(T0 + 20 * MINUTE, row(quantity=6, time_left=3), row(quantity=5, time_left=3)),
    ]

    assert in_arrival_order(scans, config) == in_time_order(scans, tmp_path)


def simulated_market(rng: random.Random, scans: int) -> list[dict]:
    """Scans of a Market whose auctions sell down, lose time-left, vanish and get posted,
    with interchangeable Listings (same Item Key and price) so matching has ties. Some
    auctions are mine, and some Scans show them as someone else's, as a Pooled Scan does."""
    auctions = []
    result = []
    at = T0
    for _ in range(scans):
        for a in auctions:
            if rng.random() < 0.3:
                a["quantity"] -= rng.randint(0, a["quantity"] - 1)
            if rng.random() < 0.3 and a["time_left"] > 1:
                a["time_left"] -= 1
        auctions = [a for a in auctions if rng.random() > 0.2]
        auctions += [
            {
                "item": rng.choice([LINEN, WOOL]),
                "unit": rng.choice([100, 120]),
                "quantity": rng.randint(1, 5),
                "time_left": rng.randint(2, 4),
                "own": rng.random() < 0.3,
            }
            for _ in range(rng.randint(0, 4))
        ]
        result.append(
            scan(
                at,
                *(
                    row(
                        a["item"],
                        a["quantity"],
                        a["unit"],
                        a["time_left"],
                        own=a["own"] and rng.random() < 0.7,
                    )
                    for a in auctions
                ),
            )
        )
        at += rng.choice([10, 20, 30, 50, 3 * 60]) * MINUTE
    return result


@pytest.mark.parametrize("seed", range(20))
def test_scans_in_any_order_give_the_history_of_time_order(seed, config, tmp_path):
    rng = random.Random(seed)
    scans = simulated_market(rng, scans=10)
    shuffled = rng.sample(scans, len(scans))

    assert in_arrival_order(shuffled, config) == in_time_order(scans, tmp_path)


def test_a_scan_past_the_rematch_cap_waits_for_rebuild(db, config):
    import_scans(db, [scan(T0 + 49 * HOUR, row(quantity=5))], Era.BETA, config)
    before = history(db)

    report = import_scans(db, [scan(T0, row(quantity=20))], Era.BETA, config)

    assert history(db) == before
    assert report.scans_imported == 0
    assert report.scans_waiting_for_rebuild == 1
    assert "brain rebuild" in report.warnings[0]
    assert [
        s.raw["requestedAt"]
        for s in Archive(config.archive_dir).market_scans(
            Era.BETA, "Classic Beta PvP", "Alliance", since=0
        )
    ] == [T0, T0 + 49 * HOUR]


def test_a_scan_just_inside_the_rematch_cap_is_merged(config, tmp_path):
    scans = [scan(T0 + 48 * HOUR, row(quantity=5)), scan(T0, row(quantity=20))]

    assert in_arrival_order(scans, config) == in_time_order(scans, tmp_path)


def test_a_rematch_leaves_other_markets_alone(db, config):
    horde = Market(realm="Classic Beta PvP", faction="Horde", era=Era.BETA)
    import_scans(
        db,
        [
            scan(T0, row(quantity=20), faction="Horde"),
            scan(T0 + 40 * MINUTE, row(quantity=12), faction="Horde"),
            scan(T0 + 40 * MINUTE, row(quantity=10)),
        ],
        Era.BETA,
        config,
    )
    before = (listings(db, horde), partial_sales(db, horde))
    # A Horde re-match would have nothing to come back from.
    shutil.rmtree(config.archive_dir / "beta" / "Classic Beta PvP-Horde")

    report = import_scans(db, [scan(T0 + 20 * MINUTE, row(quantity=15))], Era.BETA, config)

    assert report.scans_rematched == 1
    assert (listings(db, horde), partial_sales(db, horde)) == before


def test_a_rematch_with_an_unreadable_archived_scan_waits_for_rebuild(db, config):
    import_scans(
        db, [scan(T0, row(quantity=20)), scan(T0 + 40 * MINUTE, row(quantity=10))], Era.BETA, config
    )
    before = history(db)
    folder = config.archive_dir / "beta" / "Classic Beta PvP-Alliance"
    (folder / f"{T0 + 40 * MINUTE}.json.gz").write_bytes(b"not gzip")

    report = import_scans(db, [scan(T0 + 20 * MINUTE, row(quantity=15))], Era.BETA, config)

    assert history(db) == before
    assert report.scans_waiting_for_rebuild == 1
