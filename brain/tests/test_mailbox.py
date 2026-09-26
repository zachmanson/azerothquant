import pytest

from brain.mailbox import (
    AuctionMail,
    LiveMail,
    MailFormatError,
    MailKind,
    arrived_at,
    faction_of,
    match_mails,
    parse_mail,
)

T0 = 1_790_447_060
DAY = 86_400

FERMENTER_LINK = (
    "|cnIQ2:|Hitem:273085::::::::20:1490::1::1:28:5256:::::|h[Blueprint: Fermenter]|h|r"
)
HEAVY_SHOT_LINK = "|cnIQ1:|Hitem:2519::::::::20:1490:::::::::|h[Heavy Shot]|h|r"

# Mails as the Addon stores them (addon/AzerothQuant/MailboxRead.lua), from the #15 spike.
SOLD = {
    "index": 1,
    "sender": "Alliance Auction House",
    "subject": "Auction successful: Small Glimmering Shard (8)",
    "money": 2289,
    "daysLeft": 30,
    "wasReturned": False,
    "invoice": {
        "invoiceType": "seller",
        "itemName": "Small Glimmering Shard",
        "bid": 2304,
        "buyout": 8,
        "deposit": 100,
        "consignment": 115,
        "moneyDelay": 0,
        "etaHour": 0,
        "etaMin": 0,
        "count": 8,
        "commerceAuction": False,
    },
}
WON = {
    "index": 6,
    "sender": "Alliance Auction House",
    "subject": "Auction won: Heavy Shot",
    "money": 0,
    "daysLeft": 29.997314453125,
    "itemCount": 1,
    "wasReturned": False,
    "firstItemQuantity": 1,
    "firstItemLink": HEAVY_SHOT_LINK,
    "invoice": {
        "invoiceType": "buyer",
        "itemName": "Heavy Shot",
        "playerName": "",
        "bid": 1,
        "buyout": 1,
        "deposit": 0,
        "consignment": 0,
        "moneyDelay": 0,
        "etaHour": 0,
        "etaMin": 0,
        "count": 1,
        "commerceAuction": False,
    },
}
CANCELLED = {
    "index": 5,
    "sender": "Alliance Auction House",
    "subject": "Auction canceled: Blueprint: Fermenter",
    "money": 0,
    "daysLeft": 29.99739646911621,
    "itemCount": 1,
    "wasReturned": False,
    "firstItemQuantity": 1,
    "firstItemLink": FERMENTER_LINK,
}


def with_(mail, **changes):
    return {**mail, **changes}


# --- parse_mail ---


def test_a_sale_has_its_gross_price_and_net_payout():
    mail, days_left = parse_mail(SOLD)

    assert mail == AuctionMail(
        kind=MailKind.SOLD,
        sender="Alliance Auction House",
        subject="Auction successful: Small Glimmering Shard (8)",
        item_name="Small Glimmering Shard",
        item_key=None,  # a sale mail has no attachment, so only the name is known
        count=8,
        price=2304,
        money=2289,
    )
    assert days_left == 30


def test_a_won_auction_takes_its_item_key_from_the_attachment():
    mail, _ = parse_mail(WON)

    assert mail.kind is MailKind.WON
    assert (mail.item_name, mail.item_key, mail.count, mail.price) == ("Heavy Shot", "2519", 1, 1)


def test_a_cancellation_reads_the_item_from_the_subject_and_attachment():
    # No invoice: the name is everything after the prefix, colons and all.
    mail, days_left = parse_mail(CANCELLED)

    assert mail.kind is MailKind.CANCELLED
    assert mail.item_name == "Blueprint: Fermenter"
    assert (mail.item_key, mail.count, mail.price) == ("273085", 1, None)
    assert days_left == pytest.approx(29.9974, abs=1e-4)


def test_cancellation_count_is_the_attached_stack():
    mail, _ = parse_mail(with_(CANCELLED, firstItemQuantity=20))

    assert mail.count == 20


def test_cancelled_is_read_in_either_spelling():
    mail, _ = parse_mail(with_(CANCELLED, subject="Auction cancelled: Blueprint: Fermenter"))

    assert mail.kind is MailKind.CANCELLED


def test_an_expiry_reads_like_a_cancellation():
    mail, _ = parse_mail(with_(CANCELLED, subject="Auction expired: Blueprint: Fermenter"))

    assert mail.kind is MailKind.EXPIRED
    assert (mail.item_name, mail.item_key, mail.count) == ("Blueprint: Fermenter", "273085", 1)


def test_outbid_mail_is_neither_an_outcome_nor_a_purchase():
    # Bids are ignored everywhere (CONTEXT.md: Listing).
    assert parse_mail(with_(CANCELLED, subject="Outbid on Blueprint: Fermenter")) is None


@pytest.mark.parametrize(
    "mail",
    [
        with_(SOLD, subject="Something new: Tigerseye"),
        with_(SOLD, invoice={**SOLD["invoice"], "invoiceType": "buyer"}),
        {k: v for k, v in SOLD.items() if k != "invoice"},
        with_(SOLD, invoice={**SOLD["invoice"], "bid": None}),
        with_(WON, firstItemLink=None),
        with_(CANCELLED, firstItemQuantity=None),
        with_(CANCELLED, daysLeft=None),
        with_(CANCELLED, sender=None),
        "junk",
    ],
)
def test_mail_the_brain_cant_read_is_an_error(mail):
    with pytest.raises(MailFormatError):
        parse_mail(mail)


def test_an_attachment_link_that_isnt_an_item_is_an_error():
    with pytest.raises(MailFormatError):
        parse_mail(with_(CANCELLED, firstItemLink="|Hbattlepet:1:1|h[Pet]|h"))


# --- faction_of ---


def test_known_senders_map_to_their_faction():
    assert faction_of("Alliance Auction House") == "Alliance"
    assert faction_of("Horde Auction House") == "Horde"


def test_an_unknown_sender_has_no_faction_rather_than_a_guess():
    assert faction_of("Blackwater Auction House") is None


# --- arrived_at ---


def test_arrival_is_worked_back_from_days_left():
    assert arrived_at(T0, 29.5) == T0 - DAY // 2


def test_a_mail_still_at_the_full_30_days_has_no_known_arrival():
    # Sold mail sat at exactly 30 in the spike, so its clock may not be running.
    assert arrived_at(T0, 30) is None


# --- match_mails ---


def mail(**changes):
    return parse_mail(with_(SOLD, **changes))[0]


def test_a_mail_still_in_the_inbox_matches_itself():
    live = [LiveMail(id=7, mail=mail(), arrived_at=None)]

    assert match_mails(live, [(mail(), None)]) == [7]


def test_a_mail_that_wasnt_there_before_is_new():
    live = [LiveMail(id=7, mail=mail(), arrived_at=None)]

    assert match_mails(live, [(mail(money=1), None)]) == [None]


def test_identical_mails_match_one_to_one():
    live = [LiveMail(id=7, mail=mail(), arrived_at=None)]

    # Two identical sales now, one before: one of them is new.
    assert match_mails(live, [(mail(), None), (mail(), None)]) == [7, None]


def test_arrival_times_far_apart_are_different_mails():
    # The earlier one was taken and an identical one arrived since.
    live = [LiveMail(id=7, mail=mail(), arrived_at=T0)]

    assert match_mails(live, [(mail(), T0 + 3600)]) == [None]


def test_arrival_times_a_little_apart_are_the_same_mail():
    live = [LiveMail(id=7, mail=mail(), arrived_at=T0)]

    assert match_mails(live, [(mail(), T0 + 2)]) == [7]


def test_the_closest_arrival_wins():
    live = [
        LiveMail(id=7, mail=mail(), arrived_at=T0),
        LiveMail(id=8, mail=mail(), arrived_at=T0 + 120),
    ]

    assert match_mails(live, [(mail(), T0 + 119)]) == [8]


def test_an_unknown_arrival_on_either_side_doesnt_rule_out_a_match():
    live = [LiveMail(id=7, mail=mail(), arrived_at=None)]
    assert match_mails(live, [(mail(), T0)]) == [7]

    live = [LiveMail(id=7, mail=mail(), arrived_at=T0)]
    assert match_mails(live, [(mail(), None)]) == [7]
