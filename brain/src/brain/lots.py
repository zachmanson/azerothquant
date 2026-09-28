"""Lots: derived from Purchases and Sold Outcomes, never stored (ADR-0007)."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from brain.history import Listing, Outcome, Purchase
from brain.mailbox import MailKind
from brain.predictions import Prediction


@dataclass(frozen=True)
class LotSale:
    """Some of a Lot's units, closed by one Sold Outcome."""

    units: int
    unit_price: float  # gross copper per unit, before the Auction House cut
    sold_at: int


@dataclass(frozen=True)
class Lot:
    """A quantity of one Item Key acquired together at one cost (CONTEXT.md: Lot)."""

    item_key: str
    acquired_at: int
    units: int
    cost: int  # copper for all its units
    sales: tuple[LotSale, ...]
    prediction: str | None = None  # the Prediction its units belong to, if any
    # When a Prediction of its Item Key was written, which folded its open units into
    # that Prediction's held Lot so they aren't counted twice.
    folded_at: int | None = None

    @property
    def open_units(self) -> int:
        """Units no Sold Outcome has closed yet, and none once folded."""
        if self.folded_at is not None:
            return 0
        return self.units - sum(sale.units for sale in self.sales)


@dataclass(frozen=True)
class Held:
    """Units of one Item Key in Holdings at the start of a Prediction's written day, and
    what they were worth then by their Best Exit Value without the Prediction."""

    prediction: str
    item_key: str
    units: int
    cost: int  # copper for all its units


def lots(
    purchases: list[Purchase],
    outcomes: list[Outcome],
    predictions: Sequence[Prediction] = (),
    held: Sequence[Held] = (),
) -> list[Lot]:
    """One realm and faction's Lots, oldest first."""
    written = {p.name: start_of(p.written) for p in predictions}
    result = sorted(
        [
            Lot(p.item_key, _when(p), p.count, p.price, (), _bought_under(p, predictions))
            for p in purchases
        ]
        + [Lot(h.item_key, written[h.prediction], h.units, h.cost, (), h.prediction) for h in held],
        key=lambda lot: lot.acquired_at,
    )
    # Unlinked Sold Outcomes (no Item Key) close nothing, nor do Cancelled or Expired ones.
    sales = [o for o in outcomes if o.kind is MailKind.SOLD and o.item_key is not None]
    # In the order they happened; a Prediction's held units are as of the start of its
    # written day, so a sale at that same moment comes after it.
    events: list[tuple[int, int, Prediction | Outcome]] = sorted(
        [(written[p.name], 0, p) for p in predictions] + [(_when(o), 1, o) for o in sales],
        key=lambda event: event[:2],
    )
    for at, _, event in events:
        if isinstance(event, Prediction):
            _fold(result, event, at)
        else:
            _close(result, event, at)
    return result


def _bought_under(purchase: Purchase, predictions: Sequence[Prediction]) -> str | None:
    """The Prediction a Purchase's units belong to: the one of its Item Key that stood
    when it was bought, from the start of its written day until it ended."""
    bought_at = _when(purchase)
    for p in predictions:
        if purchase.item_key in p.item_keys and start_of(p.written) <= bought_at < ended_at(p):
            return p.name
    return None


def ended_at(prediction: Prediction) -> int:
    """When a Prediction ends: the start of the day its Catalyst happened, or the end of
    its lapse day (it lasts through that day), whichever comes first."""
    lapsed = start_of(prediction.lapse + timedelta(days=1))
    if prediction.happened is not None:
        return min(start_of(prediction.happened), lapsed)
    return lapsed


def _fold(result: list[Lot], prediction: Prediction, written_at: int) -> None:
    """End the open Lots of the Prediction's Item Keys acquired before it was written."""
    for i, lot in enumerate(result):
        if (
            lot.acquired_at < written_at
            and lot.item_key in prediction.item_keys
            and lot.open_units > 0
        ):
            result[i] = replace(lot, folded_at=written_at)


def _close(result: list[Lot], outcome: Outcome, sold_at: int) -> None:
    """Close the Sold Outcome's units, oldest open Lot of its Item Key first."""
    unit_price = outcome.price / outcome.count
    remaining = outcome.count
    for i, lot in enumerate(result):
        if remaining == 0 or lot.acquired_at > sold_at:
            break
        if lot.item_key != outcome.item_key or lot.open_units == 0:
            continue
        units = min(remaining, lot.open_units)
        sale = LotSale(units, unit_price, sold_at)
        result[i] = replace(lot, sales=(*lot.sales, sale))
        remaining -= units


@dataclass(frozen=True)
class Settlement:
    """Where a Prediction's units stand at its grading moment: what its sold units brought
    in, what all of them cost, and the units still open, which the caller values."""

    proceeds: float  # copper after the Auction House cut
    cost: int
    open_units: dict[str, int]  # by Item Key


def settle(prediction: Prediction, result: list[Lot], graded_at: int, cut: float) -> Settlement:
    """Settle a Prediction's Lots at `graded_at`: units sold after it are still open."""
    proceeds = 0.0
    cost = 0
    open_units: dict[str, int] = {}
    for lot in result:
        if lot.prediction != prediction.name:
            continue
        cost += lot.cost
        sold = [s for s in lot.sales if s.sold_at <= graded_at]
        proceeds += sum(s.units * s.unit_price for s in sold) * (1 - cut)
        open_units[lot.item_key] = (
            open_units.get(lot.item_key, 0) + lot.units - sum(s.units for s in sold)
        )
    return Settlement(proceeds, cost, open_units)


def link_sales(
    outcomes: list[Outcome], listings: list[Listing], purchases: list[Purchase]
) -> list[Outcome]:
    """The Outcomes with each Sold one's Item Key found by its item name (ADR-0007)."""
    # Only own Listings carry a name.
    named = [(ls.item_name, ls.item_key) for ls in listings if ls.item_name is not None]
    named += [(p.item_name, p.item_key) for p in purchases]
    named += [(o.item_name, o.item_key) for o in outcomes if o.item_key is not None]
    keys: dict[str, set[str]] = {}
    for name, item_key in named:
        keys.setdefault(name, set()).add(item_key)
    return [
        replace(o, item_key=_only(keys.get(o.item_name, set()))) if o.kind is MailKind.SOLD else o
        for o in outcomes
    ]


def deposits(outcomes: list[Outcome]) -> dict[str, float]:
    """What posting one unit of each Item Key cost (#78): the deposit per unit on its
    latest Sold Outcome's invoice, from `outcomes` already linked (`link_sales`)."""
    sold = [
        o
        for o in outcomes
        if o.kind is MailKind.SOLD and o.item_key is not None and o.deposit is not None
    ]
    return {o.item_key: o.deposit / o.count for o in sorted(sold, key=_when)}


def _only(item_keys: set[str]) -> str | None:
    """The one Item Key, or None when there are none or several (Unlinked)."""
    return next(iter(item_keys)) if len(item_keys) == 1 else None


def start_of(day: date) -> int:
    """The moment `day` starts, in local time like the Prediction dates it's used for."""
    return int(datetime(day.year, day.month, day.day).timestamp())


def _when(mail: Purchase | Outcome) -> int:
    """When the mail's event happened: its arrival, else when the Brain first saw it."""
    return mail.arrived_at if mail.arrived_at is not None else mail.first_seen
