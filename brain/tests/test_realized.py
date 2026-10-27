from dataclasses import replace
from pathlib import Path

import pytest

from brain.config import Config, Era, Install
from brain.grades_file import freeze_named
from brain.history import (
    Market,
    import_character_reads,
    import_mailbox_reads,
    import_scans,
    open_history,
)
from brain.lots import NamedSet
from brain.realized import realized

T0 = 1_790_000_000
HOUR = 3600
REALM = "Classic Beta PvP"
MARKET = Market(realm=REALM, faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
LINEN_LINK = "|cffffffff|Hitem:2589::::::::20:1490:::::::::|h[Linen Cloth]|h|r"
CONFIG = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def scan(at, quantity):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "droppedRows": 0,
        "listings": [
            {"itemString": LINEN, "quantity": quantity, "buyout": quantity * 100, "timeLeft": 4}
        ],
        "vendorPrices": {},
    }


def character_read():
    return {
        "readAt": T0,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 0,
        "bags": [],
        "vendorPrices": {},
    }


def auction_mail(subject, bid, count, days_left, link=None):
    mail = {
        "index": 1,
        "sender": "Alliance Auction House",
        "subject": f"{subject}: Linen Cloth",
        "money": 0 if link else bid,
        "daysLeft": days_left,
        "invoice": {
            "invoiceType": "buyer" if link else "seller",
            "itemName": "Linen Cloth",
            "bid": bid,
            "count": count,
        },
    }
    if link:
        mail |= {"firstItemQuantity": count, "firstItemLink": link}
    return mail


def mailbox_read():
    """A Mailbox Read at T0 + 14 h: 2 Linen bought for 100 in all at T0 + 1 h, then 1 sold
    for 500 at T0 + 2 h, and 1 for 700 at T0 + 13 h."""
    mails = [
        auction_mail("Auction won", 100, 2, 30 - 13 / 24, link=LINEN_LINK),
        auction_mail("Auction successful", 500, 1, 29.5),
        auction_mail("Auction successful", 700, 1, 30 - 1 / 24),
    ]
    return {
        "readAt": T0 + 14 * HOUR,
        "realm": REALM,
        "character": "Kash-Patel",
        "shownCount": len(mails),
        "totalCount": len(mails),
        "skippedMails": 0,
        "mails": mails,
    }


def named_at(tmp_path, scan_at, *item_keys) -> Config:
    """CONFIG with a grades.toml in which the Scan at `scan_at` named `item_keys` to buy
    at any price (#55)."""
    path = tmp_path / "grades.toml"
    freeze_named(path, MARKET, scan_at, NamedSet({k: 1_000_000 for k in item_keys}))
    return replace(CONFIG, grades_path=path)


def seed(db, config):
    import_scans(db, [scan(T0, 20), scan(T0 + HOUR, 18)], Era.BETA, config)
    import_mailbox_reads(db, [mailbox_read()], Era.BETA, config)
    import_character_reads(db, [character_read()], Era.BETA, config)


@pytest.mark.parametrize(("named", "cost"), [(("2589",), 50), ((), 0)], ids=["named", "for use"])
def test_realized_profit_is_the_range_s_sales_after_the_cut_less_their_lots_cost(
    db, tmp_path, named, cost
):
    # The sale at T0 + 2 h is in range, the one at T0 + 13 h after it. Bought For Use (#55),
    # the Linen starts no Lot, so the sale is of a looted unit, say, and costs nothing.
    config = named_at(tmp_path, T0 + HOUR, *named)
    seed(db, config)

    r = realized(db, config, MARKET, [], T0, T0 + 4 * HOUR)

    assert r.profit == pytest.approx(500 * 0.95 - cost)


def test_the_for_use_purchases_are_the_range_s_ones_the_brain_didnt_name(db, tmp_path):
    config = named_at(tmp_path, T0 + HOUR)
    seed(db, config)

    assert [p.price for p in realized(db, config, MARKET, [], T0, T0 + 4 * HOUR).for_use] == [100]
    assert realized(db, config, MARKET, [], T0 + 2 * HOUR, T0 + 4 * HOUR).for_use == ()
