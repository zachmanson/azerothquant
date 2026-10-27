from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.flips import Flip, flip_record, flips
from brain.grades_file import FlipGrade, Named, freeze_named, freeze_shown
from brain.history import (
    Market,
    import_character_reads,
    import_mailbox_reads,
    import_scans,
    open_history,
)
from brain.lots import NamedSet
from brain.predictions import Prediction

T0 = 1_790_000_000
MINUTE = 60
HOUR = 3600
REALM = "Classic Beta PvP"
MARKET = Market(realm=REALM, faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
LINEN_KEY = "2589"
LINEN_LINK = "|cffffffff|Hitem:2589::::::::20:1490:::::::::|h[Linen Cloth]|h|r"

# A 3 hour Sale Horizon, and no priors, so hourly Scans make a Sell
# Rate taken at its word.
CONFIG = replace(
    Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),)),
    sale_horizon_seconds=3 * HOUR,
    sell_rate_prior_hours_holdings=0,
    sell_rate_prior_hours_flips=0,
    sale_size_prior_events_holdings=0,
    sale_size_prior_events_flips=0,
    flip_min_sale_events=1,
    risk_caps=False,  # sized by the gold alone, as written (ADR-0034)
)


def scan(at, *rows):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "droppedRows": 0,
        "listings": list(rows),
        "vendorPrices": {},
    }


def row(quantity=1, unit=100, own=False):
    listing = {"itemString": LINEN, "quantity": quantity, "buyout": quantity * unit, "timeLeft": 4}
    return listing | {"own": True, "name": "Linen Cloth"} if own else listing


def character_read(money=10_000):
    return {
        "readAt": T0,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": money,
        "bags": [],
        "vendorPrices": {2589: 10},
    }


def mailbox_read(read_at, *mails):
    return {
        "readAt": read_at,
        "realm": REALM,
        "character": "Kash-Patel",
        "shownCount": len(mails),
        "totalCount": len(mails),
        "skippedMails": 0,
        "mails": list(mails),
    }


def won(at, count, unit, read_after=12 * HOUR):
    """A Purchase of Linen that arrived at `at`, read `read_after` later."""
    mail = {
        "index": 1,
        "sender": "Alliance Auction House",
        "subject": "Auction won: Linen Cloth",
        "money": 0,
        "daysLeft": 30 - read_after / 86400,
        "firstItemQuantity": count,
        "firstItemLink": LINEN_LINK,
        "invoice": {
            "invoiceType": "buyer",
            "itemName": "Linen Cloth",
            "bid": count * unit,
            "count": count,
        },
    }
    return mailbox_read(at + read_after, mail)


def linen_market(*scans_after):
    """2 Linen at 1000 sell each hour from T0, and at T0 + 1 h there are 5 more at 200:
    the Brain names a Flip to Sell of those 5, posted at 999."""
    return [
        scan(T0, row(quantity=20, unit=1000)),
        scan(T0 + HOUR, row(quantity=18, unit=1000), row(quantity=5, unit=200)),
        scan(T0 + 2 * HOUR, row(quantity=16, unit=1000)),
        *scans_after,
    ]


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def load(db, scans, mailbox_reads=(), config=CONFIG):
    import_scans(db, list(scans), Era.BETA, config)
    import_mailbox_reads(db, list(mailbox_reads), Era.BETA, config)
    import_character_reads(db, [character_read()], Era.BETA, config)


def test_a_purchase_at_or_under_the_rows_dearest_listing_is_a_flip_of_what_was_named(db):
    load(db, linen_market(), [won(T0 + HOUR + 10 * MINUTE, count=5, unit=200)])

    [flip] = flips(db, CONFIG, MARKET, [], now=T0 + 2 * HOUR)

    assert flip.item_key == LINEN_KEY
    assert flip.scan_at == T0 + HOUR
    named = flip.named
    assert (named.item_key, named.units, named.dearest, named.post_at) == (LINEN_KEY, 5, 200, 999)
    assert named.profit == pytest.approx(5 * 999 * 0.95 - 5 * 200)
    assert named.sale_horizon == 3 * HOUR
    assert (flip.units, flip.cost, flip.bought_at) == (5, 1000, T0 + HOUR + 10 * MINUTE)
    assert flip.grade is None


def test_a_purchase_dearer_than_the_rows_dearest_listing_is_no_flip(db):
    load(db, linen_market(), [won(T0 + HOUR + 10 * MINUTE, count=5, unit=201)])

    assert flips(db, CONFIG, MARKET, [], now=T0 + 2 * HOUR) == []


def test_a_run_straddling_a_scan_is_two_flips_each_against_its_own_row(db):
    load(
        db,
        [
            scan(T0, row(quantity=20, unit=1000)),
            scan(T0 + HOUR, row(quantity=18, unit=1000), row(quantity=5, unit=200)),
            scan(T0 + 2 * HOUR, row(quantity=16, unit=1000), row(quantity=3, unit=200)),
        ],
        [
            won(T0 + HOUR + 10 * MINUTE, count=5, unit=200),
            won(T0 + 2 * HOUR + 10 * MINUTE, count=3, unit=200),
        ],
    )

    result = flips(db, CONFIG, MARKET, [], now=T0 + 3 * HOUR)

    assert [(f.scan_at, f.units, f.named.units) for f in result] == [
        (T0 + HOUR, 5, 5),
        (T0 + 2 * HOUR, 3, 3),
    ]


def test_a_purchase_under_a_prediction_is_no_flip(db):
    load(db, linen_market(), [won(T0 + HOUR + 10 * MINUTE, count=5, unit=200)])
    written = date.fromtimestamp(T0) - timedelta(days=1)
    spike = Prediction(
        "Linen spike", "a patch", (LINEN_KEY,), "the patch", written, written + timedelta(weeks=8)
    )

    assert flips(db, CONFIG, MARKET, [spike], now=T0 + 2 * HOUR) == []


def freezing(tmp_path, config=CONFIG):
    return replace(config, grades_path=tmp_path / "grades.toml")


# Flip margins so high nothing is ever a Flip.
NO_FLIPS = replace(CONFIG, flip_min_margin_share=100.0)


def test_what_a_scan_named_is_frozen_the_first_time_and_pricing_later_doesnt_change_it(
    db, tmp_path
):
    load(db, linen_market(), [won(T0 + HOUR + 10 * MINUTE, count=5, unit=200)])
    [flip] = flips(db, freezing(tmp_path), MARKET, [], now=T0 + 2 * HOUR)

    assert flips(db, freezing(tmp_path, NO_FLIPS), MARKET, [], now=T0 + 2 * HOUR) == [flip]


def test_a_scan_that_named_no_flip_is_frozen_too_so_it_isnt_worked_out_again(db, tmp_path):
    load(db, linen_market(), [won(T0 + HOUR + 10 * MINUTE, count=5, unit=200)])
    assert flips(db, freezing(tmp_path, NO_FLIPS), MARKET, [], now=T0 + 2 * HOUR) == []

    assert flips(db, freezing(tmp_path), MARKET, [], now=T0 + 2 * HOUR) == []


def sold(at, count, unit):
    """A Sold Outcome of Linen that arrived at `at`, read 12 hours later."""
    invoice = {"invoiceType": "seller", "itemName": "Linen Cloth", "bid": count * unit}
    mail = {
        "index": 1,
        "sender": "Alliance Auction House",
        "subject": "Auction successful: Linen Cloth",
        "money": round(count * unit * 0.95),
        "daysLeft": 29.5,
        "invoice": invoice | {"count": count},
    }
    return mailbox_read(at + 12 * HOUR, mail)


BOUGHT = T0 + HOUR + 10 * MINUTE
GRADED = BOUGHT + 3 * HOUR  # a Sale Horizon after the Purchase


def later_linen(*at):
    """Scans after the matched one, with 2 Linen at 1000 selling each hour."""
    return [scan(t, row(quantity=14 - 2 * n, unit=1000)) for n, t in enumerate(at)]


def test_a_flip_is_graded_on_its_units_sold_within_the_sale_horizon_after_the_cut(db):
    load(
        db,
        linen_market(*later_linen(T0 + 3 * HOUR, GRADED)),
        [won(BOUGHT, count=5, unit=200), sold(T0 + 2 * HOUR, count=5, unit=999)],
    )

    [flip] = flips(db, CONFIG, MARKET, [], now=GRADED)

    grade = flip.grade
    assert (grade.graded_at, grade.sold_units, grade.open_units) == (GRADED, 5, 0)
    assert grade.proceeds == pytest.approx(5 * 999 * 0.95)
    assert grade.realized == pytest.approx(5 * 999 * 0.95 - 1000)
    assert grade.sale_days == (pytest.approx((T0 + 2 * HOUR - BOUGHT) / 86400),)


def test_units_sold_after_the_sale_horizon_count_open_at_their_best_exit_value_then(db):
    # 3 sell within the horizon. At its end the 2 left would post at 999, as 2 Linen at
    # 1000 go each hour, and sell: 2 x 999 after the cut. Their sale an hour later counts
    # for nothing more.
    load(
        db,
        linen_market(*later_linen(T0 + 3 * HOUR, GRADED, GRADED + HOUR)),
        [
            won(BOUGHT, count=5, unit=200),
            sold(T0 + 2 * HOUR, count=3, unit=999),
            sold(GRADED + HOUR, count=2, unit=999),
        ],
    )

    [flip] = flips(db, CONFIG, MARKET, [], now=GRADED + HOUR)

    grade = flip.grade
    assert (grade.sold_units, grade.open_units) == (3, 2)
    assert grade.proceeds == pytest.approx(3 * 999 * 0.95)
    assert grade.open_value == pytest.approx(2 * 999 * 0.95)


def test_a_purchase_the_brain_didnt_name_takes_none_of_a_flips_sales(db):
    # 3 Linen bought at T0, when nothing was a Flip or a Buy Under: For Use (#55), so the
    # sales close the Flip's units, not theirs.
    load(
        db,
        linen_market(*later_linen(T0 + 3 * HOUR, GRADED)),
        [
            won(T0 + 10 * MINUTE, count=3, unit=1000),
            won(BOUGHT, count=5, unit=200),
            sold(T0 + 2 * HOUR, count=4, unit=999),
        ],
    )

    [flip] = flips(db, CONFIG, MARKET, [], now=GRADED)

    assert flip.grade.sold_units == 4


@pytest.mark.parametrize("now", [GRADED - 1, GRADED])
def test_a_flip_is_graded_once_a_sale_horizon_has_passed_since_its_purchase(db, now):
    load(db, linen_market(*later_linen(T0 + 3 * HOUR, GRADED)), [won(BOUGHT, count=5, unit=200)])

    [flip] = flips(db, CONFIG, MARKET, [], now=now)

    assert (flip.grade is not None) == (now == GRADED)


def test_a_grade_is_frozen_once_a_scan_at_its_grading_moment_is_in(db, tmp_path):
    load(
        db,
        linen_market(*later_linen(T0 + 3 * HOUR, GRADED)),
        [won(BOUGHT, count=5, unit=200), sold(T0 + 2 * HOUR, count=3, unit=999)],
    )
    [flip] = flips(db, freezing(tmp_path), MARKET, [], now=GRADED)

    # Worth nothing held, later: the frozen open value stands.
    config = freezing(tmp_path, replace(CONFIG, sale_horizon_seconds=1))
    assert flips(db, config, MARKET, [], now=GRADED + HOUR) == [flip]


def test_a_flip_is_not_graded_before_a_scan_at_its_grading_moment_prices_its_open_units(
    db, tmp_path
):
    load(
        db,
        linen_market(*later_linen(T0 + 3 * HOUR)),
        [won(BOUGHT, count=5, unit=200), sold(T0 + 2 * HOUR, count=3, unit=999)],
    )
    [first] = flips(db, freezing(tmp_path), MARKET, [], now=GRADED)
    load(db, later_linen(GRADED + HOUR), [sold(GRADED - MINUTE, count=2, unit=999)])

    [flip] = flips(db, freezing(tmp_path), MARKET, [], now=GRADED + HOUR)

    assert (first.grade, flip.grade.sold_units) == (None, 5)


def expired(at, count):
    """An Expired Outcome of Linen that arrived at `at`, read 12 hours later."""
    mail = {
        "index": 1,
        "sender": "Alliance Auction House",
        "subject": "Auction expired: Linen Cloth",
        "money": 0,
        "daysLeft": 29.5,
        "itemCount": 1,
        "wasReturned": False,
        "firstItemQuantity": count,
        "firstItemLink": LINEN_LINK,
    }
    return mailbox_read(at + 12 * HOUR, mail)


def test_a_grade_notes_the_lag_to_the_first_own_listing_and_the_expired_ones_in_its_horizon(
    db,
):
    load(
        db,
        [
            *linen_market(),
            scan(T0 + 3 * HOUR, row(quantity=14, unit=1000), row(quantity=5, unit=999, own=True)),
            *later_linen(GRADED),
        ],
        # One expires within the horizon, one after it.
        [
            won(BOUGHT, count=5, unit=200),
            expired(GRADED - HOUR, count=5),
            expired(GRADED + HOUR, count=5),
        ],
    )

    [flip] = flips(db, CONFIG, MARKET, [], now=GRADED)

    assert (flip.grade.listed_after, flip.grade.expired) == (T0 + 3 * HOUR - BOUGHT, 1)


def test_a_grade_is_not_frozen_before_a_mailbox_read_at_its_grading_moment(db, tmp_path):
    # The Sold mail from within the horizon is only read after the Scan at its end.
    load(
        db,
        linen_market(*later_linen(T0 + 3 * HOUR, GRADED)),
        [won(BOUGHT, count=5, unit=200, read_after=10 * MINUTE)],
    )
    [first] = flips(db, freezing(tmp_path), MARKET, [], now=GRADED)
    load(db, [], [sold(T0 + 2 * HOUR, count=5, unit=999)])

    [flip] = flips(db, freezing(tmp_path), MARKET, [], now=GRADED)

    assert (first.grade.sold_units, flip.grade.sold_units) == (0, 5)


def graded_flip(units, named_units, profit, cost, sold_units, gross, open_value, days):
    named = Named("2589", named_units, 200, 1000.0, profit, 1.0, 3 * HOUR)
    grade = FlipGrade(
        GRADED, units, cost, sold_units, gross, gross * 0.95, open_value, days, None, 0
    )
    return Flip("2589", T0 + HOUR, named, BOUGHT, units, cost, grade)


def test_the_record_of_graded_flips_takes_them_together():
    # A partial run: 2 of a row's 4 units, expected 2 x 500. It sold 1 at 900 and 1 is
    # open at 800. The other sold its 3 at 1100 and 1000 and 1200.
    partial = graded_flip(2, 4, 2000.0, 400, 1, 900.0, 800.0, (0.5,))
    whole = graded_flip(3, 3, 1500.0, 600, 3, 3300.0, 0.0, (0.25, 1.0, 2.0))
    pending = replace(whole, grade=None)

    record = flip_record([partial, whole, pending])

    assert (record.graded, record.paid_off) == (2, 2)
    realized = (900 * 0.95 + 800 - 400) + (3300 * 0.95 - 600)
    assert record.realized_over_expected == pytest.approx(realized / (1000 + 1500))
    assert record.price_over_post_at == pytest.approx((0.9 + 1.1) / 2)
    assert record.sold_within == pytest.approx(4 / 5)
    assert record.median_days == pytest.approx((0.5 + 1.0) / 2)


def test_there_is_no_record_with_nothing_graded():
    assert flip_record([replace(graded_flip(1, 1, 1.0, 1, 0, 0.0, 0.0, ()), grade=None)]) is None


def test_a_flip_matched_to_a_row_frozen_before_named_sets_keeps_its_lot(db, tmp_path):
    # #55: the Scan's Flip to Sell row was frozen before `named` existed, and its named
    # set, worked out later, lacks it. The row still names the Purchase, so its sales
    # close the Flip's units.
    config = freezing(tmp_path)
    linen = Named(LINEN_KEY, 5, 200, 999.0, 3745.0, None, 3 * HOUR)
    freeze_shown(config.grades_path, MARKET, T0 + HOUR, 3 * HOUR, [linen])
    freeze_named(config.grades_path, MARKET, T0 + HOUR, NamedSet())
    load(
        db,
        linen_market(*later_linen(T0 + 3 * HOUR, GRADED)),
        [won(BOUGHT, count=5, unit=200), sold(T0 + 2 * HOUR, count=3, unit=999)],
    )

    [flip] = flips(db, config, MARKET, [], now=GRADED)

    assert flip.grade.sold_units == 3
