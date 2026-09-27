from dataclasses import replace
from datetime import date, datetime

import pytest

from brain.history import Listing, Outcome, Purchase
from brain.lots import Held, Lot, LotSale, link_sales, lots
from brain.mailbox import MailKind
from brain.predictions import Prediction

LINEN = "2589:0"
WOOL = "2592:0"


def _purchase(item_key, count, price, arrived_at, first_seen=None):
    return Purchase("Kash", "item", item_key, count, price, arrived_at, first_seen or arrived_at)


def _sold(item_key, count, price, arrived_at, first_seen=None):
    return Outcome(
        "Kash",
        MailKind.SOLD,
        "item",
        item_key,
        count,
        price,
        0,
        arrived_at,
        first_seen or arrived_at,
    )


def test_a_purchase_starts_an_open_lot_at_its_price():
    assert lots([_purchase(LINEN, 20, 1000, arrived_at=100)], []) == [
        Lot(LINEN, acquired_at=100, units=20, cost=1000, sales=())
    ]


def test_a_purchase_without_an_arrival_time_is_acquired_when_first_seen():
    [lot] = lots([_purchase(LINEN, 20, 1000, arrived_at=None, first_seen=300)], [])
    assert lot.acquired_at == 300


def test_a_sold_outcome_closes_units_of_a_lot_at_its_unit_price():
    [lot] = lots(
        [_purchase(LINEN, 20, 1000, arrived_at=100)],
        [_sold(LINEN, 5, 400, arrived_at=200)],
    )
    assert lot.sales == (LotSale(units=5, unit_price=80, sold_at=200),)
    assert lot.open_units == 15


def test_a_sale_closes_the_oldest_lot_first_and_spills_into_the_next():
    older, newer = lots(
        [_purchase(LINEN, 20, 2000, arrived_at=200), _purchase(LINEN, 10, 500, arrived_at=100)],
        [_sold(LINEN, 15, 1500, arrived_at=300)],
    )
    assert (older.acquired_at, older.sales) == (100, (LotSale(10, 100, 300),))
    assert (newer.acquired_at, newer.sales) == (200, (LotSale(5, 100, 300),))


def test_a_sale_closes_nothing_bought_after_it_and_its_excess_units_close_nothing():
    # 15 sold at 150 but only 10 were bought by then: the other 5 were looted or crafted.
    before, after = lots(
        [_purchase(LINEN, 10, 500, arrived_at=100), _purchase(LINEN, 10, 500, arrived_at=200)],
        [_sold(LINEN, 15, 1500, arrived_at=150)],
    )
    assert before.open_units == 0
    assert after.sales == ()


def test_sales_close_lots_in_the_order_they_happened_not_the_order_they_were_read():
    [lot] = lots(
        [_purchase(LINEN, 10, 500, arrived_at=100)],
        [_sold(LINEN, 10, 2000, arrived_at=300), _sold(LINEN, 10, 1000, arrived_at=200)],
    )
    assert lot.sales == (LotSale(10, 100, 200),)


def test_only_a_sold_outcome_with_an_item_key_closes_units():
    cancelled = Outcome("Kash", MailKind.CANCELLED, "item", LINEN, 5, None, 0, 200, 200)
    expired = Outcome("Kash", MailKind.EXPIRED, "item", LINEN, 5, None, 0, 200, 200)
    unlinked = _sold(None, 5, 400, arrived_at=200)
    [lot] = lots([_purchase(LINEN, 20, 1000, arrived_at=100)], [cancelled, expired, unlinked])
    assert lot.open_units == 20


def test_a_sale_closes_only_lots_of_its_own_item_key():
    wool, linen = lots(
        [_purchase(WOOL, 20, 3000, arrived_at=100), _purchase(LINEN, 20, 1000, arrived_at=150)],
        [_sold(LINEN, 5, 400, arrived_at=200)],
    )
    assert wool.sales == ()
    assert linen.open_units == 15


def _own_listing(item_key, item_name, own=True):
    return Listing(item_key, 50, own, 5, 4, 100, 100, item_name if own else None)


def test_a_sold_outcome_is_linked_to_the_item_key_of_an_own_listing_with_its_name():
    sold = replace(_sold(None, 5, 400, arrived_at=200), item_name="Linen Cloth")
    [linked] = link_sales([sold], [_own_listing(LINEN, "Linen Cloth")], [])
    assert linked.item_key == LINEN


def _linen_sold():
    return replace(_sold(None, 5, 400, arrived_at=200), item_name="Linen Cloth")


def _returned(kind, item_key, item_name):
    return Outcome("Alt", kind, item_name, item_key, 5, None, 0, 150, 150)


@pytest.mark.parametrize(
    ("outcomes", "purchases"),
    [
        ([], [replace(_purchase(LINEN, 5, 250, arrived_at=50), item_name="Linen Cloth")]),
        ([_returned(MailKind.CANCELLED, LINEN, "Linen Cloth")], []),
        ([_returned(MailKind.EXPIRED, LINEN, "Linen Cloth")], []),
    ],
    ids=["won", "cancelled", "expired"],
)
def test_a_sold_outcome_is_linked_by_mail_that_carried_an_item_with_its_name(outcomes, purchases):
    linked = link_sales([_linen_sold(), *outcomes], [], purchases)
    assert [o.item_key for o in linked] == [LINEN] * len(linked)


@pytest.mark.parametrize(
    "listings",
    [[], [_own_listing(LINEN, "Linen Cloth"), _own_listing(WOOL, "Linen Cloth")]],
    ids=["no match", "several"],
)
def test_a_sold_outcome_whose_name_matches_no_item_key_or_several_stays_unlinked(listings):
    [linked] = link_sales([_linen_sold()], listings, [])
    assert linked.item_key is None


# A Prediction written on Oct 1, with its day boundaries in local time.
OCT_1 = int(datetime(2026, 10, 1).timestamp())
OCT_2 = int(datetime(2026, 10, 2).timestamp())
HOUR = 3600


def _prediction(
    item_keys=(LINEN,), written=date(2026, 10, 1), lapse=date(2026, 11, 26), happened=None
):
    return Prediction("Tailoring", "reason", item_keys, "Phase 2", written, lapse, happened)


def test_units_held_when_a_prediction_is_written_start_a_lot_at_the_start_of_that_day():
    [lot] = lots([], [], [_prediction()], [Held("Tailoring", LINEN, units=20, cost=1200)])
    assert lot == Lot(
        LINEN, acquired_at=OCT_1, units=20, cost=1200, sales=(), prediction="Tailoring"
    )


def test_writing_a_prediction_folds_earlier_open_lots_of_its_item_keys_into_its_held_lot():
    bought, held = lots(
        [_purchase(LINEN, 20, 1000, arrived_at=OCT_1 - 10 * HOUR)],
        [_sold(LINEN, 5, 400, arrived_at=OCT_1 - 5 * HOUR), _sold(LINEN, 5, 500, arrived_at=OCT_2)],
        [_prediction()],
        [Held("Tailoring", LINEN, units=15, cost=900)],
    )
    assert (bought.sales, bought.folded_at, bought.open_units) == (
        (LotSale(5, 80, OCT_1 - 5 * HOUR),),
        OCT_1,
        0,
    )
    assert held.sales == (LotSale(5, 100, OCT_2),)


OCT_10 = int(datetime(2026, 10, 10).timestamp())
OCT_11 = int(datetime(2026, 10, 11).timestamp())


@pytest.mark.parametrize(
    ("prediction", "end"),
    [
        (_prediction(happened=date(2026, 10, 10)), OCT_10),
        (_prediction(lapse=date(2026, 10, 10)), OCT_11),
        (_prediction(lapse=date(2026, 10, 10), happened=date(2026, 10, 20)), OCT_11),
    ],
    ids=["happened", "lapsed", "happened after it lapsed"],
)
def test_purchases_of_its_item_keys_from_its_written_day_until_it_ends_belong_to_a_prediction(
    prediction, end
):
    result = lots(
        [
            _purchase(LINEN, 1, 100, arrived_at=OCT_1 - 1),
            _purchase(LINEN, 1, 100, arrived_at=OCT_1),
            _purchase(WOOL, 1, 100, arrived_at=OCT_1 + HOUR),
            _purchase(LINEN, 1, 100, arrived_at=end - 1),
            _purchase(LINEN, 1, 100, arrived_at=end),
        ],
        [],
        [prediction],
    )
    assert [lot.prediction for lot in result] == [None, "Tailoring", None, "Tailoring", None]
