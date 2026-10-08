"""Syncing with the Scan Pool (#122, ADR-0026), against an in-memory fake Pool: pushing the
player's Scans, pulling everyone else's, and rolling back what the pool rolled back."""

from contextlib import closing
from pathlib import Path

import pytest
from fake_pool import FakePool

from brain.config import Config, Era, Install
from brain.history import Market, import_scans, listings, open_history, scan_times
from brain.pool import strip_scan
from brain.pool_sync import pull, push

T0 = 1_790_000_000
MINUTE = 60
DAY = 24 * 60 * MINUTE

MARKET = Market(realm="Classic Beta PvP", faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"


def scan(at, *rows, character="Kash-Patel", realm="Classic Beta PvP"):
    return {
        "requestedAt": at,
        "realm": realm,
        "character": character,
        "faction": "Alliance",
        "droppedRows": 0,
        "listings": list(rows) or [row()],
    }


def row(quantity=1, unit=100, own=False):
    r = {"itemString": LINEN, "quantity": quantity, "buyout": quantity * unit, "timeLeft": 4}
    if own:
        r["own"] = True
    return r


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


@pytest.fixture
def pool():
    return FakePool()


def pool_file(config, at) -> Path:
    return config.archive_dir / "beta" / "Classic Beta PvP-Alliance" / "pool" / f"{at}.json.gz"


def test_the_player_s_archived_scans_are_pushed_stripped_and_only_once(db, config, pool):
    import_scans(db, [scan(T0, row(own=True)), scan(T0 + MINUTE)], Era.BETA, config)

    first = push(db, pool, config)
    again = push(db, pool, config)

    assert first.pushed == 2 and again.pushed == 0
    assert sorted(s["requestedAt"] for s in pool.pushed()) == [T0, T0 + MINUTE]
    assert all("character" not in s for s in pool.pushed())
    assert not any("own" in r for s in pool.pushed() for r in s["listings"])


def test_a_failed_push_warns_and_is_retried_next_cycle(db, config, pool):
    import_scans(db, [scan(T0)], Era.BETA, config)
    pool.fail = True

    failed = push(db, pool, config)
    pool.fail = False
    retried = push(db, pool, config)

    assert failed.pushed == 0 and failed.warnings
    assert retried.pushed == 1


def test_a_rate_limited_market_is_pushed_next_cycle_without_a_warning(db, config, pool):
    import_scans(db, [scan(T0), scan(T0, realm="Other")], Era.BETA, config)
    pool.busy.add(("Classic Beta PvP", "Alliance"))

    first = push(db, pool, config)
    pool.busy.clear()
    second = push(db, pool, config)

    assert (first.pushed, second.pushed) == (1, 1)
    assert not first.warnings


def test_pulled_scans_are_archived_under_pool_and_imported(db, config, pool):
    pool.upload(Era.BETA, strip_scan(scan(T0, character="Friend")))

    report = pull(db, pool, config, now=T0 + MINUTE)

    assert report.pulled == 1
    assert scan_times(db, MARKET) == [T0]
    assert pool_file(config, T0).exists()


def test_a_pooled_body_dated_other_than_its_index_entry_is_left_out(db, config, pool):
    # Probe P5 (#149): a body 30 days ahead of its headers froze the Market until rebuild.
    pool.upload(Era.BETA, strip_scan(scan(T0 + 30 * DAY)), header_overrides={"requestedAt": T0})
    import_scans(db, [scan(T0 - MINUTE)], Era.BETA, config)

    report = pull(db, pool, config, now=T0 + MINUTE)
    later = import_scans(db, [scan(T0 + 30 * MINUTE)], Era.BETA, config)

    assert report.pulled == 0 and report.rejected == 1 and report.warnings
    assert not pool_file(config, T0 + 30 * DAY).exists()
    assert later.scans_imported == 1
    assert scan_times(db, MARKET) == [T0 - MINUTE, T0 + 30 * MINUTE]


@pytest.mark.parametrize("headers", [{"realm": "Other"}, {"faction": "Horde"}])
def test_a_pooled_body_from_another_market_than_its_index_entry_is_left_out(
    db, config, pool, headers
):
    pool.upload(Era.BETA, strip_scan(scan(T0)), header_overrides=headers)

    report = pull(db, pool, config, now=T0 + MINUTE)

    assert report.pulled == 0 and report.rejected == 1
    assert scan_times(db, MARKET) == []
    assert not pool_file(config, T0).exists()


def test_the_player_s_own_uploads_are_skipped_on_pull(db, config, pool):
    # Uploaded with this key, but not in this history: say, from a history since deleted.
    pool.upload(Era.BETA, strip_scan(scan(T0)), uploader="me")

    report = pull(db, pool, config, now=T0 + MINUTE)

    assert report.pulled == 0
    assert pool.fetched == []
    assert not pool_file(config, T0).exists()


def test_a_pull_carries_on_from_where_the_last_one_ended(db, config, pool):
    for i in range(3):
        pool.upload(Era.BETA, strip_scan(scan(T0 + i * MINUTE)))
    pull(db, pool, config, now=T0 + DAY)
    pool.upload(Era.BETA, strip_scan(scan(T0 + 3 * MINUTE)))
    pool.listed_since.clear()

    report = pull(db, pool, config, now=T0 + DAY)

    assert report.pulled == 1
    assert pool.listed_since == [3]
    assert len(scan_times(db, MARKET)) == 4


def test_the_first_pull_backfills_only_the_last_14_days(db, config, pool):
    # The longest window the Decision Engine reads: an older Scan only makes the guildie's
    # first pull longer (#159).
    now = T0 + 40 * DAY
    pool.upload(Era.BETA, strip_scan(scan(now - 15 * DAY)))
    pool.upload(Era.BETA, strip_scan(scan(now - 13 * DAY)))

    report = pull(db, pool, config, now=now)

    assert report.pulled == 1
    assert scan_times(db, MARKET) == [now - 13 * DAY]


def test_a_pull_since_a_date_goes_further_back(db, config, pool):
    now = T0 + 40 * DAY
    pool.upload(Era.BETA, strip_scan(scan(now - 15 * DAY)))
    pool.upload(Era.BETA, strip_scan(scan(now - 13 * DAY)))
    pull(db, pool, config, now=now)

    report = pull(db, pool, config, now=now, since=now - 20 * DAY)

    assert report.pulled == 1
    assert scan_times(db, MARKET) == [now - 15 * DAY, now - 13 * DAY]


def test_a_rolled_back_pooled_scan_leaves_the_archive_and_the_history_is_rematched(
    db, config, pool
):
    import_scans(
        db, [scan(T0, row(quantity=5)), scan(T0 + 20 * MINUTE, row(quantity=3))], Era.BETA, config
    )
    bad = pool.upload(Era.BETA, strip_scan(scan(T0 + 10 * MINUTE, row(quantity=1))))
    pull(db, pool, config, now=T0 + DAY)
    pool.roll_back(bad)

    report = pull(db, pool, config, now=T0 + DAY)

    assert report.rolled_back == 1
    assert not pool_file(config, T0 + 10 * MINUTE).exists()
    assert scan_times(db, MARKET) == [T0, T0 + 20 * MINUTE]
    # As if the bad Scan had never come: the 5 went down to 3, not 5 to 1 and back up.
    with closing(open_history(":memory:")) as clean:
        import_scans(
            clean,
            [scan(T0, row(quantity=5)), scan(T0 + 20 * MINUTE, row(quantity=3))],
            Era.BETA,
            Config(installs=config.installs),
        )
        assert sorted(listings(db, MARKET)) == sorted(listings(clean, MARKET))


def test_a_rollback_never_deletes_an_own_scan_but_pushes_it_again(db, config, pool):
    # The pool answered a duplicate upload with another member's ID, and then that member
    # was revoked.
    import_scans(db, [scan(T0)], Era.BETA, config)
    push(db, pool, config)
    [pushed_id] = pool.scans
    pool.roll_back(pushed_id)

    pull(db, pool, config, now=T0 + DAY)
    again = push(db, pool, config)

    assert scan_times(db, MARKET) == [T0]
    assert again.pushed == 1


def test_rolling_back_a_scan_this_brain_never_pulled_is_a_no_op(db, config, pool):
    import_scans(db, [scan(T0, row(quantity=5))], Era.BETA, config)
    pull(db, pool, config, now=T0 + DAY)
    pool.roll_back("never-seen")

    report = pull(db, pool, config, now=T0 + DAY)

    assert report.rolled_back == 0
    assert not report.failed
    assert scan_times(db, MARKET) == [T0]
    assert [listing.quantity for listing in listings(db, MARKET)] == [5]


def test_a_network_error_warns_and_leaves_the_history_as_it_was(db, config, pool):
    import_scans(db, [scan(T0)], Era.BETA, config)
    pool.upload(Era.BETA, strip_scan(scan(T0 + MINUTE)))
    pool.fail = True

    report = pull(db, pool, config, now=T0 + DAY)

    assert report.warnings
    assert scan_times(db, MARKET) == [T0]
    pool.fail = False
    assert pull(db, pool, config, now=T0 + DAY).pulled == 1
