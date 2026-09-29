from dataclasses import replace
from pathlib import Path

import pytest

from brain.beta_prior import BetaPrice, beta_prior
from brain.config import Config, Era, Install
from brain.history import Market, import_scans, open_history

T0 = 1_790_000_000
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR

CONFIG = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))
BETA_REALM = "Classic Beta PvP"
LIVE_REALM = "Forever"
LIVE = Market(realm=LIVE_REALM, faction="Alliance", era=Era.LIVE)
BETA = Market(realm=BETA_REALM, faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
LINEN_KEY = "2589"
LIVE_START = T0 + 60 * DAY


def scan(at, *rows, realm=BETA_REALM, faction="Alliance"):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": realm,
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


def beta(db, *scans):
    import_scans(db, list(scans), Era.BETA, CONFIG)


def live(db, *scans):
    import_scans(db, list(scans), Era.LIVE, CONFIG)


def stacks(a, b, c):
    """Linen listed at 100, 200 and 300 copper a unit, with a, b and c units left."""
    return row(quantity=a, unit=100), row(quantity=b, unit=200), row(quantity=c, unit=300)


def test_a_live_market_gets_the_median_sale_event_price_of_its_factions_beta_market(db):
    # Three Observation Windows, each seeing one stack sell a unit: Sale Events at 100, 300
    # and 200.
    beta(
        db,
        scan(T0, *stacks(10, 10, 10)),
        scan(T0 + 30 * MINUTE, *stacks(9, 10, 10)),
        scan(T0 + 60 * MINUTE, *stacks(9, 10, 9)),
        scan(T0 + 90 * MINUTE, *stacks(9, 9, 9)),
    )
    live(db, scan(LIVE_START, row(unit=900), realm=LIVE_REALM))

    prior = beta_prior(db, LIVE, CONFIG, now=LIVE_START, item_keys={LINEN_KEY})

    assert prior.market == BETA
    assert prior.prices[LINEN_KEY] == BetaPrice(
        price=200, sold=True, sale_events=3, units_per_day=pytest.approx(3 / 1.5 * 24)
    )


def test_without_three_sale_events_it_is_the_median_daily_fair_value_of_the_last_7_days(db):
    # Scans hours apart, so no Observation Windows. Beta's last day has two Scans, whose
    # Fair Values average 200; the days before it 400 and 150. A Scan 8 days back is out.
    last = T0 + 10 * DAY
    beta(
        db,
        scan(last - 8 * DAY, row(unit=5000)),
        scan(last - 2 * DAY - HOUR, row(unit=150)),
        scan(last - DAY - HOUR, row(unit=400)),
        scan(last - 3 * HOUR, row(unit=100)),
        scan(last, row(unit=300)),
    )
    live(db, scan(LIVE_START, row(unit=900), realm=LIVE_REALM))

    prior = beta_prior(db, LIVE, CONFIG, now=LIVE_START, item_keys={LINEN_KEY})

    assert prior.prices[LINEN_KEY] == BetaPrice(
        price=200, sold=False, sale_events=0, units_per_day=None
    )


def test_a_horde_market_gets_the_horde_beta_market_when_there_is_one(db):
    beta(db, scan(T0, row(unit=100)), scan(T0, row(unit=700), faction="Horde"))
    horde = Market(realm=LIVE_REALM, faction="Horde", era=Era.LIVE)
    live(db, scan(LIVE_START, row(unit=900), realm=LIVE_REALM, faction="Horde"))

    prior = beta_prior(db, horde, CONFIG, now=LIVE_START, item_keys={LINEN_KEY})

    assert prior.market == Market(realm=BETA_REALM, faction="Horde", era=Era.BETA)
    assert prior.prices[LINEN_KEY].price == 700


def test_a_market_without_a_beta_market_of_its_faction_gets_the_alliance_one(db):
    beta(db, scan(T0, row(unit=100)))
    horde = Market(realm=LIVE_REALM, faction="Horde", era=Era.LIVE)
    live(db, scan(LIVE_START, row(unit=900), realm=LIVE_REALM, faction="Horde"))

    prior = beta_prior(db, horde, CONFIG, now=LIVE_START, item_keys={LINEN_KEY})

    assert prior.market == BETA
    assert prior.prices[LINEN_KEY].price == 100


def test_an_item_key_beta_never_listed_has_no_beta_price(db):
    beta(db, scan(T0, row(unit=100)))
    live(db, scan(LIVE_START, row(unit=900), realm=LIVE_REALM))

    prior = beta_prior(db, LIVE, CONFIG, now=LIVE_START, item_keys={LINEN_KEY, "4306"})

    assert set(prior.prices) == {LINEN_KEY}


def test_it_shows_for_beta_column_days_from_the_markets_first_scan(db):
    beta(db, scan(T0, row(unit=100)))
    live(
        db,
        scan(LIVE_START, row(unit=900), realm=LIVE_REALM),
        scan(LIVE_START + 20 * DAY, row(unit=900), realm=LIVE_REALM),
    )
    config = replace(CONFIG, beta_column_days=14)

    shown = beta_prior(db, LIVE, config, now=LIVE_START + 14 * DAY - 1, item_keys={LINEN_KEY})
    gone = beta_prior(db, LIVE, config, now=LIVE_START + 14 * DAY, item_keys={LINEN_KEY})

    assert shown is not None
    assert gone is None


def test_a_beta_market_gets_its_own_prices_while_its_window_is_open(db):
    # So the column can be checked in game on Beta data before Live (#90).
    beta(db, scan(T0, row(unit=100)))

    prior = beta_prior(db, BETA, CONFIG, now=T0, item_keys={LINEN_KEY})

    assert prior.market == BETA
    assert prior.prices[LINEN_KEY].price == 100


def test_a_beta_market_gets_its_own_prices_beside_another_realm_of_its_faction(db):
    # "Another Beta" sorts first, but Classic Beta PvP gets its own.
    beta(db, scan(T0, row(unit=100)), scan(T0, row(unit=700), realm="Another Beta"))

    prior = beta_prior(db, BETA, CONFIG, now=T0, item_keys={LINEN_KEY})

    assert prior.market == BETA
    assert prior.prices[LINEN_KEY].price == 100
