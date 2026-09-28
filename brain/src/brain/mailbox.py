"""Auction House mail, as the Brain reads it from a Mailbox Read (see CONTEXT.md: Mailbox
Read, Outcome, Purchase).

The Addon stores each mail raw (addon/AzerothQuant/MailboxRead.lua). This module says what
kind of mail it is, which item and how much, and whether a mail in one Read is the same
mail seen in the Character's previous Read.
"""

import math
from dataclasses import dataclass, field
from enum import StrEnum

from brain.scan import ItemKey, ItemStringError


class MailKind(StrEnum):
    SOLD = "sold"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    WON = "won"


OUTCOME_KINDS = (MailKind.SOLD, MailKind.CANCELLED, MailKind.EXPIRED)

# Subject prefixes, as the client writes them. Sold, won and "canceled" are confirmed on
# Forever (#15 spike); "cancelled", expired and outbid are the client's other strings and
# not seen yet. A subject that matches none is an error, so a wrong guess shows up.
_KINDS_BY_PREFIX = {
    "Auction successful: ": MailKind.SOLD,
    "Auction won: ": MailKind.WON,
    "Auction canceled: ": MailKind.CANCELLED,
    "Auction cancelled: ": MailKind.CANCELLED,
    "Auction expired: ": MailKind.EXPIRED,
}
# Mail that is neither an Outcome nor a Purchase: bids are ignored (CONTEXT.md: Listing).
_IGNORED_PREFIXES = ("Outbid on ",)

# Which faction's Auction House sent a mail. Only "Alliance Auction House" is confirmed on
# Forever; the neutral houses' sender isn't known, and is never guessed: its mail is
# left without a Market. Adding a sender here and running `brain rebuild` assigns it.
_FACTIONS_BY_SENDER = {
    "Alliance Auction House": "Alliance",
    "Horde Auction House": "Horde",
}

# Mail lasts 30 days; daysLeft counts down from here (#15 spike).
MAIL_DAYS = 30
# How far apart two derived arrival times can be and still be the same mail. daysLeft
# is precise to about a second, so this only has to absorb clock differences.
ARRIVAL_TOLERANCE_SECONDS = 5 * 60


class MailFormatError(ValueError):
    """An Auction House mail the Brain can't read."""


@dataclass(frozen=True)
class AuctionMail:
    """One Auction House mail: everything that identifies it except when it arrived.

    Two mails that are equal are interchangeable, which is what matching across Reads
    relies on.
    """

    kind: MailKind
    sender: str
    subject: str
    item_name: str
    # Only mail with the item attached has one; a sale mail has just the item's name.
    item_key: str | None
    count: int
    # Copper for the whole stack: the gross sale price or the price paid. None when
    # the auction ended without a sale.
    price: int | None
    # Copper attached; for a sale, the payout after the Auction House cut plus the deposit.
    money: int
    # Copper a sale's posting cost, from its invoice (#78); None for other mail, or when
    # the invoice has none. Not part of what identifies a mail: a history from before it
    # was kept has none for mail still in the inbox, which must still match itself.
    deposit: int | None = field(default=None, compare=False)


def parse_mail(raw: object) -> tuple[AuctionMail, float] | None:
    """The mail and its daysLeft, or None for Auction House mail that is neither an
    Outcome nor a Purchase (outbid notices, and mail caught mid-take)."""
    if not isinstance(raw, dict):
        raise MailFormatError(f"a mail must be a table, got {raw!r}")
    sender = _required(raw, "sender", str)
    subject = _required(raw, "subject", str)
    money = _required(raw, "money", int)
    days_left = _required(raw, "daysLeft", float | int)

    if subject.startswith(_IGNORED_PREFIXES):
        return None
    prefix = next((p for p in _KINDS_BY_PREFIX if subject.startswith(p)), None)
    if prefix is None:
        raise MailFormatError(f"unrecognized Auction House mail subject {subject!r}")
    kind = _KINDS_BY_PREFIX[prefix]

    # Every Auction House mail brings money or an item. Taking one empties it a moment
    # before it is deleted, and a Read can land in between (#100): it's on its way out,
    # and read as a new mail it would count twice.
    if money == 0 and raw.get("firstItemLink") is None:
        return None

    if kind in (MailKind.SOLD, MailKind.WON):
        # The price and count are only in the invoice.
        invoice = raw.get("invoice")
        expected = "seller" if kind is MailKind.SOLD else "buyer"
        if not isinstance(invoice, dict) or invoice.get("invoiceType") != expected:
            raise MailFormatError(f"{subject!r} has no {expected} invoice")
        item_name = _required(invoice, "itemName", str)
        count = _required(invoice, "count", int)
        price = _required(invoice, "bid", int)
        deposit = invoice.get("deposit") if kind is MailKind.SOLD else None
        if isinstance(deposit, bool) or not isinstance(deposit, int):
            deposit = None
        # Won items are attached; a sale mail carries only the money.
        item_key = _item_key(raw) if kind is MailKind.WON else None
    else:
        # Cancelled and expired mail has no invoice, only the returned stack.
        item_name = subject[len(prefix) :]
        count = _required(raw, "firstItemQuantity", int)
        price = deposit = None
        item_key = _item_key(raw)

    mail = AuctionMail(kind, sender, subject, item_name, item_key, count, price, money, deposit)
    return mail, float(days_left)


def _item_key(raw: dict) -> str:
    link = _required(raw, "firstItemLink", str)
    try:
        return str(ItemKey.from_link(link))
    except ItemStringError as e:
        raise MailFormatError(str(e)) from None


def _required(raw: dict, field: str, kind: type) -> object:
    value = raw.get(field)
    if not isinstance(value, kind) or isinstance(value, bool):
        raise MailFormatError(f"missing or bad '{field}' in mail {raw!r:.200}")
    return value


def faction_of(sender: str) -> str | None:
    """The faction whose Auction House sent the mail, or None for a sender not in the table."""
    return _FACTIONS_BY_SENDER.get(sender)


def arrived_at(read_at: int, days_left: float) -> int | None:
    """When the mail arrived, worked back from its daysLeft at read_at (Unix time).

    None while daysLeft is still the full 30 days: every sale mail in the #15 spike read
    exactly 30, so it may not count down, and its arrival can't be told.
    """
    if days_left >= MAIL_DAYS:
        return None
    return read_at - round((MAIL_DAYS - days_left) * 86_400)


@dataclass(frozen=True)
class LiveMail:
    """A mail that was in the Character's inbox at their previous Read."""

    id: int
    mail: AuctionMail
    arrived_at: int | None


def match_mails(
    live: list[LiveMail], current: list[tuple[AuctionMail, int | None]]
) -> list[int | None]:
    """For each (mail, arrival) in the current Read, the id of the live mail it is, or None
    when it is new.

    A mail stays in the inbox until taken, so an equal mail from the previous Read is
    the same one. Matching is one to one, so two identical mails now and one before means
    one is new. When both arrival times are known they must also agree, which tells a
    mail apart from an identical one that arrived after the first was taken. When one
    isn't known, the mails are assumed to be the same: identical mail is interchangeable.
    """
    claimed: set[int] = set()
    result: list[int | None] = []
    for mail, arrival in current:
        best: LiveMail | None = None
        best_gap = math.inf
        for candidate in live:
            if candidate.id in claimed or candidate.mail != mail:
                continue
            gap = _arrival_gap(candidate.arrived_at, arrival)
            if gap <= ARRIVAL_TOLERANCE_SECONDS and gap < best_gap:
                best, best_gap = candidate, gap
        if best is not None:
            claimed.add(best.id)
        result.append(best.id if best is not None else None)
    return result


def _arrival_gap(a: int | None, b: int | None) -> float:
    return 0 if a is None or b is None else abs(a - b)
