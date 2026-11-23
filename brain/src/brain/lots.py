"""Lots: derived from Purchases, Sold Outcomes and Craft Results, never stored (ADR-0007)."""

import bisect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import NamedTuple

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
    used: int = 0  # units crafts used up as reagents (#44)
    crafted: bool = False  # opened by a craft, as its output
    recipe_id: int | None = None  # a crafted Lot's recipe
    # A crafted Lot's lineage (#114): the Lots its craft used up, as they stood then.
    lineage: tuple["LotUse", ...] = field(default=(), compare=False)

    @property
    def open_units(self) -> int:
        """Units no Sold Outcome or craft has closed yet, and none once folded."""
        if self.folded_at is not None:
            return 0
        return self.units - sum(sale.units for sale in self.sales) - self.used


@dataclass(frozen=True)
class LotUse:
    """Some units of a Lot that a craft used up, the Lot as it stood just before (#114)."""

    lot: Lot
    units: int


def bought_from(lineage: Sequence[LotUse]) -> list[Lot]:
    """The Lots up a craft's `lineage` that no craft opened, through the output Lots of
    the Sub-crafts it used up, as they stood when used up (#114)."""
    result = []
    for use in lineage:
        result += bought_from(use.lot.lineage) if use.lot.crafted else [use.lot]
    return result


@dataclass(frozen=True)
class LotCraftResult:
    """One Craft Result as Lots see it (CONTEXT.md: Craft Result)."""

    at: int
    reagents: Mapping[str, int]  # units used up, by Item Key
    output: str | None  # the Item Key it made, None when it makes no item
    units: int  # output units made
    # Per unit, the lowest latest-seen Merchant Cost as of the craft of each reagent that
    # has one.
    merchant: Mapping[str, float] = field(default_factory=dict)
    recipe_id: int | None = None


@dataclass(frozen=True)
class Held:
    """Units of one Item Key in Holdings at the start of a Prediction's written day, and
    what they were worth then by their Best Exit Value without the Prediction."""

    prediction: str
    item_key: str
    units: int
    cost: int  # copper for all its units


@dataclass(frozen=True)
class UncostedCraft:
    """A craft that opened no output Lot because some of its reagent units were looted or
    bought For Use (#44), with the Lots it did use up (#114)."""

    at: int
    recipe_id: int | None
    lineage: tuple[LotUse, ...]


class LotsWithCrafts(NamedTuple):
    """A realm and faction's Lots, and the crafts that opened none for uncosted reagents."""

    lots: list[Lot]  # oldest first
    uncosted: list[UncostedCraft]  # in the order they happened


def lots(
    purchases: list[Purchase],
    outcomes: list[Outcome],
    predictions: Sequence[Prediction] = (),
    held: Sequence[Held] = (),
    craft_results: Sequence[LotCraftResult] = (),
) -> list[Lot]:
    """One realm and faction's Lots, oldest first."""
    return lots_with_crafts(purchases, outcomes, predictions, held, craft_results).lots


def lots_with_crafts(
    purchases: list[Purchase],
    outcomes: list[Outcome],
    predictions: Sequence[Prediction] = (),
    held: Sequence[Held] = (),
    craft_results: Sequence[LotCraftResult] = (),
) -> LotsWithCrafts:
    """One realm and faction's Lots, and the crafts that opened none for uncosted reagents."""
    written = {p.name: start_of(p.written) for p in predictions}
    result = sorted(
        [
            Lot(p.item_key, happened_at(p), p.count, p.price, (), bought_under(p, predictions))
            for p in purchases
        ]
        + [Lot(h.item_key, written[h.prediction], h.units, h.cost, (), h.prediction) for h in held],
        key=lambda lot: lot.acquired_at,
    )
    # Unlinked Sold Outcomes (no Item Key) close nothing, nor do Cancelled or Expired ones.
    sales = [o for o in outcomes if o.kind is MailKind.SOLD and o.item_key is not None]
    # In the order they happened; a Prediction's held units are as of the start of its
    # written day, so a sale at that same moment comes after it.
    events: list[tuple[int, int, Prediction | Outcome | LotCraftResult]] = sorted(
        [(written[p.name], 0, p) for p in predictions]
        + [(happened_at(o), 1, o) for o in sales]
        + [(c.at, 1, c) for c in craft_results],
        key=lambda event: event[:2],
    )
    uncosted: list[UncostedCraft] = []
    for at, _, event in events:
        if isinstance(event, Prediction):
            _fold(result, event, at)
        elif isinstance(event, LotCraftResult):
            _use_up(result, event, predictions, uncosted)
        else:
            _close(result, event, at)
    return LotsWithCrafts(result, uncosted)


# A Disenchant source group by what names it: quality, kind, and lowest and highest item
# level (disenchant.Group).
GroupKey = tuple[int, str, int, int]


@dataclass(frozen=True)
class NamedSet:
    """What one Scan named to buy (#55, ADR-0025), per unit the most it named for each Item
    Key: a Flip to Sell or Vendor row's dearest Listing, a Flip to Craft's Auction House
    reagent's most to pay, a Flip to Disenchant's dearest Listing of it (#89), or a Buy
    Under. A Disenchant source group's Buy Under names every item in the group."""

    items: Mapping[str, float] = field(default_factory=dict)
    groups: Mapping[GroupKey, float] = field(default_factory=dict)


def is_for_use(
    purchase: Purchase,
    predictions: Sequence[Prediction],
    scan_times: Sequence[int],
    named: Mapping[int, NamedSet],
    group_of: Callable[[str], GroupKey | None] = lambda _: None,
) -> bool:
    """Whether a Purchase was For Use (ADR-0025), so it starts no Lot: it wasn't under a
    Prediction, and the Market's last Scan before it didn't name its Item Key at or over
    its unit price. `scan_times` are the Market's, oldest first, and `named` has what
    each of them before a Purchase named."""
    if bought_under(purchase, predictions) is not None:
        return False
    scan_at = scan_before(scan_times, happened_at(purchase))
    if scan_at is None:
        return True
    at_most = named[scan_at]
    group = group_of(purchase.item_key)
    prices = [at_most.items.get(purchase.item_key), at_most.groups.get(group) if group else None]
    return not any(p is not None and purchase.price <= p * purchase.count for p in prices)


def scan_before(scan_times: Sequence[int], at: int) -> int | None:
    """The last of `scan_times` (oldest first) at or before `at`, None if there's none."""
    i = bisect.bisect_right(scan_times, at)
    return scan_times[i - 1] if i else None


def bought_under(purchase: Purchase, predictions: Sequence[Prediction]) -> str | None:
    """The Prediction a Purchase's units belong to: the one of its Item Key that stood
    when it was bought, from the start of its written day until it ended."""
    return _under(purchase.item_key, happened_at(purchase), predictions)


def _under(item_key: str, at: int, predictions: Sequence[Prediction]) -> str | None:
    """The Prediction of `item_key` standing at `at`: from the start of its written day
    until it ended."""
    for p in predictions:
        if item_key in p.item_keys and start_of(p.written) <= at < ended_at(p):
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


def _use_up(
    result: list[Lot],
    craft: LotCraftResult,
    predictions: Sequence[Prediction],
    uncosted: list[UncostedCraft],
) -> None:
    """Use up the craft's reagent units, oldest open Lot of each first, and open a Lot of
    its output at what they cost, only when every one of them is costed; else add it to
    `uncosted`. A Prediction's units are its own (ADR-0009): no craft uses them up, nor
    opens a Lot of an Item Key under a Prediction standing then."""
    cost = 0.0
    costed = True
    lineage: list[LotUse] = []
    for item_key, units in craft.reagents.items():
        for i, lot in enumerate(result):
            if units == 0 or lot.acquired_at > craft.at:
                break
            if lot.item_key != item_key or lot.prediction is not None or not lot.open_units:
                continue
            taken = min(units, lot.open_units)
            lineage.append(LotUse(lot, taken))
            result[i] = replace(lot, used=lot.used + taken)
            cost += taken * lot.cost / lot.units
            units -= taken
        if units and item_key in craft.merchant:
            cost += units * craft.merchant[item_key]
        elif units:
            costed = False  # some were looted, or bought For Use
    if not costed:
        uncosted.append(UncostedCraft(craft.at, craft.recipe_id, tuple(lineage)))
        return
    if craft.output is None or _under(craft.output, craft.at, predictions):
        return
    output = Lot(
        craft.output,
        craft.at,
        craft.units,
        round(cost),
        (),
        crafted=True,
        recipe_id=craft.recipe_id,
        lineage=tuple(lineage),
    )
    bisect.insort(result, output, key=lambda lot: lot.acquired_at)


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
    keys: dict[str, set[str]] = {}
    for name, item_key in _named(outcomes, listings, purchases):
        keys.setdefault(name, set()).add(item_key)
    return [
        replace(o, item_key=_only(keys.get(o.item_name, set()))) if o.kind is MailKind.SOLD else o
        for o in outcomes
    ]


def item_names(
    outcomes: list[Outcome], listings: list[Listing], purchases: list[Purchase]
) -> dict[str, str]:
    """The item name of each Item Key the player has listed, bought or sold (#108), from
    `outcomes` already linked (`link_sales`). Other players' Listings carry none."""
    return {item_key: name for name, item_key in _named(outcomes, listings, purchases)}


def own_listings(listings: Sequence[Listing]) -> list[Listing]:
    """The player's own Listings: only they carry an item name. `link_sales` and
    `item_names` need no others, so a caller with many Listings can pick these out once."""
    return [ls for ls in listings if ls.item_name is not None]


def _named(
    outcomes: list[Outcome], listings: list[Listing], purchases: list[Purchase]
) -> list[tuple[str, str]]:
    """Every (item name, Item Key) pair the mail and own Listings show."""
    # Only own Listings carry a name.
    named = [(ls.item_name, ls.item_key) for ls in listings if ls.item_name is not None]
    named += [(p.item_name, p.item_key) for p in purchases]
    named += [(o.item_name, o.item_key) for o in outcomes if o.item_key is not None]
    return named


def deposits(outcomes: list[Outcome], minimum: int) -> dict[str, float]:
    """What posting one unit of each Item Key cost (#78): the deposit per unit on its
    latest Sold Outcome's invoice, from `outcomes` already linked (`link_sales`). An
    invoice that paid no more than the `minimum` deposit shows the minimum, not the rate
    (#192), so it teaches none."""
    sold = [
        o
        for o in outcomes
        if o.kind is MailKind.SOLD
        and o.item_key is not None
        and o.deposit is not None
        and o.deposit > minimum
    ]
    return {o.item_key: o.deposit / o.count for o in sorted(sold, key=happened_at)}


def _only(item_keys: set[str]) -> str | None:
    """The one Item Key, or None when there are none or several (Unlinked)."""
    return next(iter(item_keys)) if len(item_keys) == 1 else None


def start_of(day: date) -> int:
    """The moment `day` starts, in local time like the Prediction dates it's used for."""
    return int(datetime(day.year, day.month, day.day).timestamp())


def happened_at(mail: Purchase | Outcome) -> int:
    """When the mail's event happened: its arrival, else when the Brain first saw it."""
    return mail.arrived_at if mail.arrived_at is not None else mail.first_seen
