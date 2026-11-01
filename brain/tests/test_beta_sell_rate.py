"""The Beta Sell Rate (#110, ADR-0024): early in Live, a Prediction buy's Max Loss may
count on Beta's Sale Events for its room, priced for Live by the Beta/Live Fair Value
ratio, each at `beta_sell_rate_weight`."""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.history import Market, import_character_reads, import_scans, open_history
from brain.predictions import Prediction
from brain.recommend import recommend

T0 = 1_790_000_000
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR
BETA_REALM = "Classic Beta PvP"
LIVE_REALM = "Forever"
LIVE = Market(realm=LIVE_REALM, faction="Alliance", era=Era.LIVE)
BETA = Market(realm=BETA_REALM, faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
LINEN_KEY = "2589"
LIVE_START = T0 + 60 * DAY
GOLD = 100 * 100 * 100

# A Sale Horizon of 3 hours, no Sell Rate or Sale Size Prior and a minimum of 1 Sale
# Event, so the room is the pooled rate taken at its word; and a Beta Sell Rate weight of
# a half.
CONFIG = replace(
    Config(installs=(Install(path=Path("C:/WoW/_forever_"), era=Era.LIVE),)),
    sale_horizon_seconds=3 * HOUR,
    sell_rate_prior_hours_flips=0,
    sale_size_prior_events_flips=0,
    flip_min_sale_events=1,
    beta_sell_rate_weight=0.5,
)


def scan(at, *rows, realm=BETA_REALM):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": realm,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "droppedRows": 0,
        "listings": list(rows),
    }


def row(quantity=1, unit=100, time_left=4):
    return {
        "itemString": LINEN,
        "quantity": quantity,
        "buyout": quantity * unit,
        "timeLeft": time_left,
    }


def character_read(at, realm=LIVE_REALM):
    return {
        "readAt": at,
        "realm": realm,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": GOLD,
        "bags": [],
        "vendorPrices": {},
    }


def prediction(on):
    written = date.fromtimestamp(on)
    return Prediction(
        name="Linen spike",
        reason="Tailoring quests",
        item_keys=(LINEN_KEY,),
        catalyst="Phase 2",
        written=written,
        lapse=written + timedelta(weeks=8),
    )


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def beta_selling_linen_at(unit, cheap=200):
    """Beta Scans half an hour apart, 1.5 h of Observation Window, in which a stack at
    `unit` sells a unit each time: 3 Sale Events, 48 a day. The 5 at `cheap` never sell,
    so Beta's Fair Value is `cheap`."""
    return [
        scan(T0 + n * 30 * MINUTE, row(quantity=5, unit=cheap), row(quantity=10 - n, unit=unit))
        for n in range(4)
    ]


def live_first_scan(at=LIVE_START):
    """Live's first Scan: 5 Linen at 100 and 10 at 120, so Live's Fair Value is 100 and
    the 100s post at 119 once bought. No Observation Window, so no Live Sell Rate."""
    return scan(at, row(quantity=5, unit=100), row(quantity=10, unit=120), realm=LIVE_REALM)


def run(db, beta_scans, live_scans, config=CONFIG, now=LIVE_START):
    import_scans(db, beta_scans, Era.BETA, config)
    import_scans(db, live_scans, Era.LIVE, config)
    import_character_reads(db, [character_read(now)], Era.LIVE, config)
    return {r.market: r for r in recommend(db, config, [prediction(now)])}


def test_early_in_live_a_prediction_buy_counts_on_beta_sale_events_for_its_room(db):
    # Beta's Fair Value is twice Live's, so a Beta Sale Event counts at 119 if it's at 238
    # or more: the 240s do. At half weight they're 1.5 Sale Events in 0.75 h, 48 a day,
    # so 6 sell in the 3 h horizon. Posted at 119, a resale brings 113.05: the 5 100s and
    # one 120 are within the 10% Max Loss; no vendor price, so the rest aren't.
    result = run(db, beta_selling_linen_at(240), [live_first_scan()])

    [buy] = result[LIVE].prediction_buys
    assert (buy.quantity, buy.cost) == (6, 5 * 100 + 120)


def test_with_no_weight_nothing_is_borrowed_and_nothing_is_bought(db):
    result = run(
        db,
        beta_selling_linen_at(240),
        [live_first_scan()],
        config=replace(CONFIG, beta_sell_rate_weight=0),
    )

    assert result[LIVE].prediction_buys == []


def test_a_beta_sale_event_counts_only_at_or_above_the_post_price_scaled_to_beta(db):
    # As above, but the Beta stack sells at 230: under 119 x 2 = 238, so there's no room
    # for all 5 100s posted at 119. Four of them posted at 99, under the fifth, need 198,
    # so the 230s count there: those 4 are bought, each losing at most 100 - 94.05.
    result = run(db, beta_selling_linen_at(230), [live_first_scan()])

    [buy] = result[LIVE].prediction_buys
    assert (buy.quantity, buy.cost) == (4, 4 * 100)
    assert buy.max_loss == pytest.approx(4 * 5.95)


def test_nothing_is_borrowed_from_beta_column_days_after_lives_first_scan(db):
    later = LIVE_START + 14 * DAY
    result = run(
        db, beta_selling_linen_at(240), [live_first_scan(), live_first_scan(later)], now=later
    )

    assert result[LIVE].prediction_buys == []


def test_live_and_beta_sale_events_count_together_toward_the_minimum(db):
    # Live saw 2 Sale Events at 120 in an hour and Beta adds 1.5, so 3.5 of the 3 needed:
    # Live alone, with no weight, has too few.
    now = LIVE_START + HOUR
    live = [
        scan(
            LIVE_START + n * 30 * MINUTE,
            row(quantity=5, unit=100),
            row(quantity=12 - n, unit=120),
            realm=LIVE_REALM,
        )
        for n in range(3)
    ]
    config = replace(CONFIG, flip_min_sale_events=3)

    result = run(db, beta_selling_linen_at(240), live, config=config, now=now)
    alone = recommend(db, replace(config, beta_sell_rate_weight=0), [prediction(now)])

    [buy] = result[LIVE].prediction_buys
    assert buy.quantity >= 5
    assert alone[0].prediction_buys == []


def test_a_beta_market_never_borrows_from_itself(db):
    # Beta's own 3 Sale Events are short of 4; counted again at half weight they'd be 4.5.
    import_character_reads(db, [character_read(T0, realm=BETA_REALM)], Era.BETA, CONFIG)
    config = replace(CONFIG, flip_min_sale_events=4)
    import_scans(db, beta_selling_linen_at(240), Era.BETA, config)

    [beta] = recommend(db, config, [prediction(T0)])

    assert beta.market == BETA
    assert beta.prediction_buys == []


def test_flips_never_count_beta_sale_events(db):
    # Linen isn't under a Prediction here, so the 100s are a Flip to Sell at 119 only if
    # a Live Sell Rate has room for them, which there isn't.
    import_scans(db, beta_selling_linen_at(240), Era.BETA, CONFIG)
    import_scans(db, [live_first_scan()], Era.LIVE, CONFIG)
    import_character_reads(db, [character_read(LIVE_START)], Era.LIVE, CONFIG)

    [live] = recommend(db, CONFIG, [])

    assert live.shopping_list == []


def test_beta_hours_without_a_sale_event_at_the_price_still_count_as_hours(db):
    # Live sold 2 at 120 in an hour: 48 a day, room for 6 at 119. Beta watched 1.5 h and
    # sold nothing, so at half weight it adds 0.75 h: 2 in 1.75 h, room for 3. Those
    # post at 99, under the rest of the 100s.
    now = LIVE_START + HOUR
    live = [
        scan(
            LIVE_START + n * 30 * MINUTE,
            row(quantity=5, unit=100),
            row(quantity=12 - n, unit=120),
            realm=LIVE_REALM,
        )
        for n in range(3)
    ]
    quiet_beta = [scan(T0 + n * 30 * MINUTE, row(quantity=5, unit=200)) for n in range(4)]

    result = run(db, quiet_beta, live, now=now)
    alone = recommend(db, replace(CONFIG, beta_sell_rate_weight=0), [prediction(now)])

    assert [b.quantity for b in result[LIVE].prediction_buys] == [3]
    assert [b.quantity for b in alone[0].prediction_buys] == [6]


def test_a_prediction_buys_exit_can_step_down_to_a_beta_sale_event_price(db):
    # #205: Beta's Linen sold at 196 before that stack expired, under the 200 that's Beta's
    # Fair Value now, so it counts at 98 scaled to Live: under the 119 and 99 the 100s would
    # post at, so neither has room. At half weight, 4 sell at 98 in the 3 h horizon. Undercut
    # down to 98, each brings in 93.10, losing 6.90 (within 10%); the 5th has no exit.
    beta = [
        scan(
            T0 + n * 30 * MINUTE,
            row(quantity=5, unit=200),
            row(quantity=10 - n, unit=196, time_left=4 if n < 3 else 1),
        )
        for n in range(4)
    ]
    beta.append(scan(T0 + 4 * 30 * MINUTE, row(quantity=5, unit=200)))

    result = run(db, beta, [live_first_scan()])
    without = recommend(db, replace(CONFIG, beta_sell_rate_weight=0), [prediction(LIVE_START)])

    [buy] = result[LIVE].prediction_buys
    assert (buy.quantity, buy.cost) == (4, 4 * 100)
    assert buy.max_loss == pytest.approx(4 * (100 - 98 * 0.95))
    assert buy.beta_room is not None and buy.beta_room.from_beta > 0
    assert [r.prediction_buys for r in without if r.market == LIVE] == [[]]


@pytest.mark.parametrize(
    ("weight", "reason"), [(0.5, "would lose 100%"), (0, "no Live sales seen yet")]
)
def test_beta_sale_events_count_toward_no_live_sales_only_while_the_beta_sell_rate_is_on(
    db, weight, reason
):
    # #210: in a 1-minute horizon Beta's 48 Sale Events a day give no room, so the 100s
    # have no exit (no Vendor Price). With the Beta Sell Rate on, its Sale Events say that's
    # a real loss; off, Live has none, so what's missing is evidence.
    config = replace(CONFIG, sale_horizon_seconds=MINUTE, beta_sell_rate_weight=weight)
    result = run(db, beta_selling_linen_at(240), [live_first_scan()], config=config)

    [p] = result[LIVE].predictions
    assert [line.reason for line in p.lines] == [reason]
