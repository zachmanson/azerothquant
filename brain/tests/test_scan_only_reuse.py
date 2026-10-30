"""#143: a watching Brain keeps what it works out from a Market's Scans alone across
passes, and a pass that reuses it gives the same Recommendations as one with nothing
kept."""

import dataclasses
import random
from collections.abc import Sequence
from datetime import date, timedelta
from functools import partial

import pytest
from test_character_reads import character_read, item, profession, recipe
from test_rematch import CONFIG, MARKET, MINUTE, T0, row, scan, simulated_market

from brain.config import Era
from brain.fair_value import FairValueCache
from brain.history import (
    ENCHANTING,
    import_character_reads,
    import_pooled_scans,
    import_scans,
    listings,
    open_history,
    roll_back_pooled,
    scan_times,
)
from brain.predictions import Prediction
from brain.recommend import _others_lows, _others_lows_as_of, recommend

LINEN = "|cffffffff|Hitem:2589::::::::20:1490:::::::::|h[Linen Cloth]|h|r"
WOOL = "|cffffffff|Hitem:2592::::::::20:1490:::::::::|h[Wool Cloth]|h|r"


@pytest.fixture
def config(tmp_path):
    # Low bars, so the small Markets here get Flips, Buy Unders and a Loot Alert.
    return dataclasses.replace(
        CONFIG,
        archive_dir=tmp_path / "archive",
        flip_min_margin_share=0.0,
        flip_min_margin_copper=1,
        flip_min_sale_events=1,
        buy_under_min_sightings=1,
        loot_alert_floor_copper=1,
        loot_alert_share=0.0,
    )


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


@pytest.fixture(params=["kept in memory", "kept in memory and the history", "restarted"])
def next_pass_cache(request):
    """The cache each pass gets: the watcher's one, kept in memory (and in the history, as
    `brain watch` keeps it), or a restarted Brain's, with only what the history kept (#145)."""
    if request.param == "restarted":
        return lambda: FairValueCache(keep_in_history=True)
    cache = FairValueCache(keep_in_history=request.param != "kept in memory")
    return lambda: cache


def assert_kept_pass_matches_a_fresh_one(
    conn, config, cache: FairValueCache, predictions: Sequence[Prediction] = ()
) -> None:
    """One pass with the kept cache, as `brain watch` makes it after an import, must give
    what a pass with nothing kept does."""
    kept = recommend(conn, config, predictions, fair_value_cache=cache, why_not=True)
    assert kept
    assert kept == recommend(conn, config, predictions, why_not=True)


def cheap_flip_scans(rng: random.Random, scans: int) -> list[dict]:
    """`simulated_market` with its cheap Listings one unit at a fraction of the dear ones'
    price, so buying them can be worth it."""
    result = simulated_market(rng, scans)
    for s in result:
        for r in s["listings"]:
            if r["buyout"] // r["quantity"] == 100:
                r["quantity"], r["buyout"] = 1, 40
            else:
                r["buyout"] = r["quantity"] * 400
    return result


HELD = (item(LINEN, count=4),)
BOLT_OF_LINEN = (recipe(),)


def read(at, money=10_000, bags=HELD, recipes=BOLT_OF_LINEN, enchanting=None):
    """A Character Read of the Scanner: what it holds, its gold and its Known Recipes."""
    professions = [profession(recipes, at=at - 30)]
    if enchanting is not None:
        professions.append(profession([], at=at - 30, profession_id=ENCHANTING))
        professions[-1]["skillLevel"] = enchanting
    return character_read(at=at, money=money, bags=bags, professions=professions)


@pytest.mark.parametrize("seed", range(5))
def test_a_kept_pass_matches_a_fresh_one_as_scans_and_character_reads_arrive(seed, db, config):
    rng = random.Random(seed)
    cache = FairValueCache()
    import_character_reads(db, [read(T0 - 60)], Era.BETA, config)
    for s in cheap_flip_scans(rng, scans=8):
        import_scans(db, [s], Era.BETA, config)
        assert_kept_pass_matches_a_fresh_one(db, config, cache)
        # A reload with no Scan: only what's held and the gold change.
        at = s["requestedAt"] + 1
        bags = (item(LINEN, count=rng.randint(1, 9)), item(WOOL, count=rng.randint(0, 3), slot=2))
        import_character_reads(
            db, [read(at, money=rng.randint(0, 50_000), bags=bags)], Era.BETA, config
        )
        assert_kept_pass_matches_a_fresh_one(db, config, cache)


@pytest.mark.parametrize("seed", range(10))
def test_kept_listings_match_fresh_ones_as_scans_arrive_one_or_several_at_a_time(seed, db, config):
    # #155: a new Scan reloads only the Listings seen in it. In `simulated_market` they
    # sell down, lose time-left and turn own (a Pooled Scan showed them as others').
    rng = random.Random(seed)
    cache = FairValueCache()
    import_character_reads(db, [read(T0 - 60)], Era.BETA, config)
    scans = cheap_flip_scans(rng, scans=12)
    while scans:
        take = rng.randint(1, 3)
        import_scans(db, scans[:take], Era.BETA, config)
        scans = scans[take:]
        assert_kept_pass_matches_a_fresh_one(db, config, cache)
        assert cache.listings(db, MARKET) == listings(db, MARKET)


def test_kept_others_lows_match_fresh_ones_as_scans_arrive_and_listings_turn_own(db, config):
    # #155: a new Scan's others' lows are added to the kept ones; an Item Key with a
    # Listing that turned own (no longer others' in any Scan) is worked out afresh.
    cache = FairValueCache()
    brought_up_to_date = 0
    for seed in range(10):
        rng = random.Random(seed)
        market = dataclasses.replace(MARKET, realm=f"Realm {seed}")
        scans = [{**s, "realm": market.realm} for s in simulated_market(rng, 12)]
        while scans:
            take = rng.randint(1, 3)
            import_scans(db, scans[:take], Era.BETA, config)
            scans = scans[take:]
            cache.start_pass()
            brought_up_to_date += cache.before_new_scans(db, market) is not None
            at = scan_times(db, market)[-1]
            seen = cache.listings(db, market)
            kept = cache.scan_only(
                db,
                market,
                ("others_lows", at),
                partial(_others_lows_as_of, db, market, at, seen, cache),
            )
            assert kept == _others_lows(listings(db, market), scan_times(db, market))
    assert brought_up_to_date > 30
    assert db.execute("SELECT COUNT(*) FROM turned_own").fetchone()[0] > 0


@pytest.mark.parametrize("seed", range(10))
def test_a_kept_pass_matches_a_fresh_one_after_an_older_scan_is_inserted(
    seed, db, config, next_pass_cache
):
    rng = random.Random(seed)
    scans = cheap_flip_scans(rng, scans=8)
    import_character_reads(db, [read(T0 - 60)], Era.BETA, config)
    rematched = 0
    for s in rng.sample(scans, len(scans)):
        rematched += import_scans(db, [s], Era.BETA, config).scans_rematched
        assert_kept_pass_matches_a_fresh_one(db, config, next_pass_cache())
    assert rematched


def test_a_kept_pass_matches_a_fresh_one_when_a_pooled_scan_is_replaced(
    db, config, next_pass_cache
):
    import_character_reads(db, [read(T0 - 60)], Era.BETA, config)
    import_scans(
        db, [scan(T0, row(), row(item="item:2592::::::::20:1490", unit=300))], Era.BETA, config
    )
    pooled = scan(
        T0 + 20 * MINUTE, row(), row(item="item:2592::::::::20:1490", quantity=5, unit=200)
    )
    import_pooled_scans(db, [("pool-1", pooled)], Era.BETA, config)
    assert_kept_pass_matches_a_fresh_one(db, config, next_pass_cache())

    # Rolled back, and another from the same second in its place before the next pass.
    roll_back_pooled(db, ["pool-1"], config)
    import_pooled_scans(db, [("pool-2", scan(T0 + 20 * MINUTE, row()))], Era.BETA, config)
    assert_kept_pass_matches_a_fresh_one(db, config, next_pass_cache())


def test_a_kept_pass_matches_a_fresh_one_when_known_recipes_or_skills_change(db, config):
    rng = random.Random(143)
    cache = FairValueCache()
    import_character_reads(db, [read(T0 - 60, recipes=())], Era.BETA, config)
    scans = cheap_flip_scans(rng, scans=6)
    import_scans(db, scans, Era.BETA, config)
    assert_kept_pass_matches_a_fresh_one(db, config, cache)
    at = scans[-1]["requestedAt"]
    # Learns to make Bolts of Linen, then Enchanting, then gets better at it.
    for n, change in enumerate(
        [{}, {"enchanting": 1}, {"enchanting": 300}, {"recipes": ()}], start=1
    ):
        import_character_reads(db, [read(at + n, **change)], Era.BETA, config)
        assert_kept_pass_matches_a_fresh_one(db, config, cache)


def held_prediction(scans: Sequence[dict]) -> Prediction:
    """A Prediction over the held Linen and Wool, written the day after the last Scan, as
    the launch ones were on Beta: no Scan after its written day freezes what it held."""
    written = date.fromtimestamp(scans[-1]["requestedAt"]) + timedelta(days=1)
    return Prediction(
        "Cloth", "reason", ("2589", "2592"), "Launch", written, written + timedelta(days=7)
    )


def graded_prediction(scans: Sequence[dict]) -> Prediction:
    """A Prediction over the held Linen, ended a Sale Horizon before the first Scan: due
    its Grade on every pass, as none is frozen without a grades.toml."""
    first = date.fromtimestamp(scans[0]["requestedAt"])
    return Prediction(
        "Old cloth",
        "reason",
        ("2589",),
        "Gone",
        first - timedelta(days=30),
        first - timedelta(days=20),
    )


def test_a_kept_pass_with_predictions_matches_a_fresh_one(db, config):
    # #116: what a Prediction held at writing is valued with the kept cache too.
    rng = random.Random(116)
    cache = FairValueCache()
    bags = (item(LINEN, count=4), item(WOOL, count=2, slot=2))
    import_character_reads(db, [read(T0 - 60, bags=bags)], Era.BETA, config)
    scans = cheap_flip_scans(rng, scans=6)
    predictions = [held_prediction(scans), graded_prediction(scans)]
    for s in scans:
        import_scans(db, [s], Era.BETA, config)
        assert_kept_pass_matches_a_fresh_one(db, config, cache, predictions)
        # A reload with no Scan: what's held changes, so what the Predictions hold too.
        bags = (item(LINEN, count=rng.randint(1, 9)), item(WOOL, count=rng.randint(0, 3), slot=2))
        import_character_reads(db, [read(s["requestedAt"] + 1, bags=bags)], Era.BETA, config)
        assert_kept_pass_matches_a_fresh_one(db, config, cache, predictions)


def test_a_pass_with_no_new_scan_loads_no_listings_with_predictions_held(db, config, monkeypatch):
    # #116: a reload with no new Scan reuses the kept Listings, even for the Valuers that
    # cost what a Prediction held at writing or Grade one. Without them it took minutes on
    # Beta.
    rng = random.Random(116)
    cache = FairValueCache()
    import_character_reads(db, [read(T0 - 60)], Era.BETA, config)
    scans = cheap_flip_scans(rng, scans=6)
    import_scans(db, scans, Era.BETA, config)
    predictions = [held_prediction(scans), graded_prediction(scans)]
    recommend(db, config, predictions, fair_value_cache=cache)
    loads = []
    monkeypatch.setattr(
        "brain.recommend.listings", lambda *args, **kw: loads.append(args) or listings(*args, **kw)
    )
    monkeypatch.setattr(
        "brain.fair_value.listings_by_id", lambda *args, **kw: loads.append(args) or []
    )

    assert recommend(db, config, predictions, fair_value_cache=cache)
    assert loads == []
