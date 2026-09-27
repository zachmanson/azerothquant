"""Lots: derived from Purchases and Sold Outcomes, never stored (ADR-0007)."""

from dataclasses import dataclass, replace

from brain.history import Listing, Outcome, Purchase
from brain.mailbox import MailKind


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

    @property
    def open_units(self) -> int:
        """Units no Sold Outcome has closed yet."""
        return self.units - sum(sale.units for sale in self.sales)


def lots(purchases: list[Purchase], outcomes: list[Outcome]) -> list[Lot]:
    """One realm and faction's Lots, oldest first."""
    result = sorted(
        (Lot(p.item_key, _when(p), p.count, p.price, ()) for p in purchases),
        key=lambda lot: lot.acquired_at,
    )
    # Unlinked Sold Outcomes (no Item Key) close nothing, nor do Cancelled or Expired ones.
    sales = [o for o in outcomes if o.kind is MailKind.SOLD and o.item_key is not None]
    for outcome in sorted(sales, key=_when):
        sold_at = _when(outcome)
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
    return result


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


def _only(item_keys: set[str]) -> str | None:
    """The one Item Key, or None when there are none or several (Unlinked)."""
    return next(iter(item_keys)) if len(item_keys) == 1 else None


def _when(mail: Purchase | Outcome) -> int:
    """When the mail's event happened: its arrival, else when the Brain first saw it."""
    return mail.arrived_at if mail.arrived_at is not None else mail.first_seen
