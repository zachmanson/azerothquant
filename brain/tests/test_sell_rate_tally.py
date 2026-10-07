"""#142: the Sell Rate tally a watching Brain keeps from one pass to the next gives the
same Sell Rates as building it again from every Scan."""

import dataclasses
import random

import pytest
from test_rematch import CONFIG, DAY, HOUR, MARKET, MINUTE, T0, WOOL, row, scan, simulated_market

from brain.config import Era
from brain.fair_value import FairValueCache
from brain.history import import_pooled_scans, import_scans, open_history, roll_back_pooled
from brain.observation import sell_rate_evidence
from brain.sell_rate import sell_rates

# Short enough that the simulated Markets' early windows slide out of it.
SHORT_RANGE = dataclasses.replace(CONFIG, sell_rate_range_seconds=3 * HOUR)
ALL_HISTORY = dataclasses.replace(CONFIG, sell_rate_range_seconds=365 * DAY)


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(CONFIG, archive_dir=tmp_path / "archive")


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def _comparable(evidence) -> tuple:
    """Everything Sell Rate reads from the evidence. Reposts and coincidences are only
    ever counted, so their order doesn't matter."""
    return (
        evidence.window_hours,
        evidence.sale_events,
        evidence.windows,
        sorted(evidence.reposts),
        sorted(evidence.coincidences),
    )


def assert_kept_tally_matches_a_rebuild(conn, cache: FairValueCache, now: int) -> None:
    """One pass with the kept cache, as `brain watch` makes it after an import: the
    Valuer's Sell Rates over the range and the Beta Prior's over all history. Each must
    equal the same call with nothing kept."""
    cache.start_pass()
    for config in (SHORT_RANGE, ALL_HISTORY):
        kept = sell_rates(conn, MARKET, config, now, fair_value_cache=cache)
        assert kept == sell_rates(conn, MARKET, config, now)
    kept = sell_rate_evidence(conn, MARKET, CONFIG, 0, now + 1, fair_value_cache=cache)
    assert _comparable(kept) == _comparable(sell_rate_evidence(conn, MARKET, CONFIG, 0, now + 1))


@pytest.mark.parametrize("seed", range(10))
def test_adding_a_scan_gives_the_sell_rates_of_a_rebuild(seed, db, config):
    # The short range also makes the early windows slide out of it as Scans arrive.
    cache = FairValueCache()
    for s in simulated_market(random.Random(seed), scans=12):
        import_scans(db, [s], Era.BETA, config)
        assert_kept_tally_matches_a_rebuild(db, cache, s["requestedAt"])


@pytest.mark.parametrize("seed", range(30))
def test_an_older_scan_inserted_gives_the_sell_rates_of_a_rebuild(seed, db, config):
    rng = random.Random(seed)
    scans = simulated_market(rng, scans=12)
    cache = FairValueCache()
    latest = 0
    rematched = 0
    for s in rng.sample(scans, len(scans)):
        rematched += import_scans(db, [s], Era.BETA, config).scans_rematched
        latest = max(latest, s["requestedAt"])
        assert_kept_tally_matches_a_rebuild(db, cache, latest)
    assert rematched


def test_an_own_scan_replacing_a_pooled_one_gives_the_sell_rates_of_a_rebuild(db, config):
    # The Pooled Scan at T0 + 20 min had Wool at 200c, so the 300c one gone by then was
    # priced too dear to be a sale. The own Scan from the same second has no Wool, so it
    # was.
    first = scan(T0, row(), row(item=WOOL, unit=300))
    pooled = scan(T0 + 20 * MINUTE, row(), row(item=WOOL, quantity=5, unit=200))
    own = scan(T0 + 20 * MINUTE, row())
    cache = FairValueCache()

    import_scans(db, [first], Era.BETA, config)
    assert_kept_tally_matches_a_rebuild(db, cache, T0)
    import_pooled_scans(db, [("pool-1", pooled)], Era.BETA, config)
    assert_kept_tally_matches_a_rebuild(db, cache, T0 + 20 * MINUTE)
    import_scans(db, [own], Era.BETA, config)
    assert_kept_tally_matches_a_rebuild(db, cache, T0 + 20 * MINUTE)


def test_a_pooled_scan_rolled_back_gives_the_sell_rates_of_a_rebuild(db, config):
    # Without the Pooled Scan at T0 + 20 min, the 300c Wool goes missing only at T0 + 40,
    # where nothing else is up: then it was a sale.
    cache = FairValueCache()
    import_scans(db, [scan(T0, row(), row(item=WOOL, unit=300))], Era.BETA, config)
    pooled = scan(T0 + 20 * MINUTE, row(), row(item=WOOL, quantity=5, unit=200))
    import_pooled_scans(db, [("pool-1", pooled)], Era.BETA, config)
    import_scans(db, [scan(T0 + 40 * MINUTE, row())], Era.BETA, config)
    assert_kept_tally_matches_a_rebuild(db, cache, T0 + 40 * MINUTE)

    assert roll_back_pooled(db, ["pool-1"], config).scans_rematched == 1
    assert_kept_tally_matches_a_rebuild(db, cache, T0 + 40 * MINUTE)


def test_another_pooled_scan_in_place_of_a_rolled_back_one_gives_the_sell_rates_of_a_rebuild(
    db, config
):
    # The pool rolls back its Scan at T0 + 20 min and brings another from the same second
    # before the next pass. That one gets the same Scan ID back, but has no Wool.
    cache = FairValueCache()
    import_scans(db, [scan(T0, row(), row(item=WOOL, unit=300))], Era.BETA, config)
    pooled = scan(T0 + 20 * MINUTE, row(), row(item=WOOL, quantity=5, unit=200))
    import_pooled_scans(db, [("pool-1", pooled)], Era.BETA, config)
    assert_kept_tally_matches_a_rebuild(db, cache, T0 + 20 * MINUTE)

    roll_back_pooled(db, ["pool-1"], config)
    import_pooled_scans(db, [("pool-2", scan(T0 + 20 * MINUTE, row()))], Era.BETA, config)
    assert_kept_tally_matches_a_rebuild(db, cache, T0 + 20 * MINUTE)
