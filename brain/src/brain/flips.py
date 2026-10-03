"""Flip Grades (#60, ADR-0023): did the Flips to Sell the player made sell at the Post at
the Brain named, within the Sale Horizon? A report only: nothing here feeds back into
what the Brain recommends.

A Purchase is a Flip when its Item Key had a Flip to Sell on the Shopping List as of the
Market's last Scan before it, and it cost no more per unit than the dearest Listing that
row bought. All of an Item Key's Purchases matched to the same Scan's row are one Flip.
All amounts are copper.
"""

import sqlite3
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from brain.config import Config
from brain.grades_file import (
    FlipGrade,
    Frozen,
    Named,
    NamedCraft,
    craft_flip_name,
    flip_name,
    freeze_craft_flip_grade,
    freeze_flip_grade,
    load_frozen,
)
from brain.history import (
    Holding,
    Listing,
    Market,
    Outcome,
    Purchase,
    character_markets,
    latest_mailbox_read_times,
    listings,
    outcomes,
    purchases,
    scan_times,
)
from brain.lots import (
    Lot,
    LotsWithCrafts,
    LotUse,
    bought_from,
    bought_under,
    happened_at,
    is_for_use,
    scan_before,
)
from brain.mailbox import MailKind
from brain.predictions import Prediction
from brain.recommend import (
    auction_cut,
    exit_values,
    market_lots,
    market_lots_with_crafts,
    rework,
)


@dataclass(frozen=True)
class Flip:
    """The Purchases of one Item Key matched to one Scan's Flip to Sell row, and what
    that row named. `grade` is None until a Sale Horizon has passed since the first, and
    a Scan at or after that moment prices its open units."""

    item_key: str
    scan_at: int
    named: Named
    bought_at: int  # the first Purchase's
    units: int
    cost: int
    grade: FlipGrade | None = None

    @property
    def expected(self) -> float:
        """The Profit its row named for the units bought: a partial run, per unit."""
        return self.named.profit / self.named.units * self.units

    @property
    def realized_price(self) -> float | None:
        """Per unit, what its units sold within the horizon brought before the cut; None
        ungraded or with none sold."""
        return _realized_price(self.grade)


def _realized_price(grade: FlipGrade | None) -> float | None:
    if grade is None or not grade.sold_units:
        return None
    return grade.gross / grade.sold_units


@dataclass(frozen=True)
class FlipRecord:
    """The graded Flips taken together. A share is None when there's nothing to take it of."""

    graded: int
    paid_off: int
    realized_over_expected: float | None
    price_over_post_at: float | None  # the median Flip's realized price over its Post at
    sold_within: float | None  # of the units bought
    median_days: float | None  # from the Purchase to a sale, over every sale


def flip_record(made: Sequence[Flip] | Sequence["CraftFlip"]) -> FlipRecord | None:
    """The record of the graded Flips in `made`, of one kind: Flips to Sell or Flips to
    Craft, never both (#114); None with none graded. A Flip to Craft's units are its
    output's, and one whose row Vendors all it makes has no Post at to compare."""
    graded = [f for f in made if f.grade is not None]
    if not graded:
        return None
    expected = sum(f.expected for f in graded)
    units = sum(f.grade.units for f in graded)
    prices = [
        f.realized_price / f.named.post_at
        for f in graded
        if f.realized_price is not None and f.named.post_at is not None
    ]
    days = [d for f in graded for d in f.grade.sale_days]
    return FlipRecord(
        len(graded),
        sum(f.grade.paid_off for f in graded),
        sum(f.grade.realized for f in graded) / expected if expected else None,
        statistics.median(prices) if prices else None,
        sum(f.grade.sold_units for f in graded) / units if units else None,
        statistics.median(days) if days else None,
    )


def flips(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    predictions: Sequence[Prediction],
    now: int,
) -> list[Flip]:
    """The Market's Flips to Sell made by `now`, oldest first."""
    times = scan_times(conn, market)
    frozen = load_frozen(config.grades_path, market)
    shown = dict(frozen.shown)
    matched: dict[tuple[str, int], list[Purchase]] = {}
    for p in sorted(purchases(conn, market), key=happened_at):
        bought_at = happened_at(p)
        if bought_at > now or bought_under(p, predictions) is not None:
            continue
        scan_at = scan_before(times, bought_at)
        if scan_at is None:
            continue
        if scan_at not in shown:
            # The slow step: each Scan is worked out once, then read from grades.toml.
            shown[scan_at] = rework(conn, config, market, predictions, scan_at).shown
        named = shown[scan_at].get(p.item_key)
        if named is None or p.price > named.dearest * p.count:
            continue
        matched.setdefault((p.item_key, scan_at), []).append(p)
    record: _Grading | None = None
    settled_by = min(times[-1], _latest_mailbox_read(conn, market)) if times else 0
    result = []
    for (item_key, scan_at), bought in matched.items():
        named = shown[scan_at][item_key]
        flip = Flip(
            item_key,
            scan_at,
            named,
            happened_at(bought[0]),
            sum(p.count for p in bought),
            sum(p.price for p in bought),
        )
        name = flip_name(item_key, scan_at)
        graded_at = flip.bought_at + named.sale_horizon
        if name in frozen.flips:
            grade = frozen.flips[name]
            flip = replace(flip, units=grade.units, cost=grade.cost, grade=grade)
        elif graded_at <= min(now, times[-1]):
            if record is None:
                record = _Grading(
                    market_lots(conn, config, market, predictions),
                    listings(conn, market),
                    outcomes(conn, market),
                )
            grade = _grade(conn, config, market, flip, bought, record, graded_at)
            # Once a Scan and a Mailbox Read at or after its grading moment are in, the
            # Sold mail from within its horizon has been read and its open units priced.
            if config.grades_path is not None and settled_by >= graded_at:
                freeze_flip_grade(config.grades_path, market, name, grade)
            flip = replace(flip, grade=grade)
        result.append(flip)
    return result


class NotGradable(StrEnum):
    """Why a Flip to Craft has no grade a Sale Horizon after its first Purchase (#114)."""

    # A craft of its recipe used looted or For Use reagent units, so opened no Lot (#130).
    UNCOSTED = "uncosted reagents"
    NOT_CRAFTED = "not crafted by the horizon"


@dataclass(frozen=True)
class CraftFlip:
    """The Purchases matched to one Scan's Flip to Craft row (#114), and what that row
    named. `grade` is None until a Sale Horizon has passed since the first, and a Scan at
    or after that moment prices its open output."""

    recipe_id: int
    scan_at: int
    named: NamedCraft
    bought_at: int  # the first Purchase's
    grade: FlipGrade | None = None
    # Why it has no grade once a Sale Horizon has passed, if it can't have one.
    not_gradable: NotGradable | None = None

    @property
    def expected(self) -> float:
        """The Profit its row named for the output graded: a partial run, per output unit."""
        units = self.grade.units if self.grade else 0
        return self.named.profit / self.named.units * units

    @property
    def realized_price(self) -> float | None:
        """Per unit, what its output sold within the horizon brought before the cut."""
        return _realized_price(self.grade)


def craft_flips(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    predictions: Sequence[Prediction],
    now: int,
) -> list[CraftFlip]:
    """The Market's Flips to Craft made by `now`, oldest first. A Purchase not under a
    Prediction matches each Flip to Craft row of the Market's last Scan before it that buys
    its Item Key on the Auction House, at or under that reagent's most to pay."""
    times = scan_times(conn, market)
    frozen = load_frozen(config.grades_path, market)
    shown = dict(frozen.shown_crafts)
    by_scan: dict[int, list[Purchase]] = {}
    for p in sorted(purchases(conn, market), key=happened_at):
        bought_at = happened_at(p)
        if bought_at > now or bought_under(p, predictions) is not None:
            continue
        scan_at = scan_before(times, bought_at)
        if scan_at is not None:
            by_scan.setdefault(scan_at, []).append(p)
    matched: dict[tuple[int, int], list[Purchase]] = {}
    for scan_at, bought in by_scan.items():
        if scan_at not in shown and (
            # A Scan worked out before #114 is worked out again for its Flip to Craft rows
            # only for a Purchase one of them could explain.
            scan_at not in frozen.shown
            or any(_unexplained(p, scan_at, frozen, times, predictions) for p in bought)
        ):
            shown[scan_at] = rework(conn, config, market, predictions, scan_at).flips_to_craft
        for p in bought:
            for named in shown.get(scan_at, ()):
                if any(
                    b.item_key == p.item_key and p.price <= b.max_unit_price * p.count
                    for b in named.buys
                ):
                    matched.setdefault((named.recipe_id, scan_at), []).append(p)
    crafted: LotsWithCrafts | None = None
    record: _Grading | None = None
    settled_by = min(times[-1], _latest_mailbox_read(conn, market)) if times else 0
    result = []
    for (recipe_id, scan_at), bought in matched.items():
        named = next(n for n in shown[scan_at] if n.recipe_id == recipe_id)
        flip = CraftFlip(recipe_id, scan_at, named, happened_at(bought[0]))
        name = craft_flip_name(recipe_id, scan_at)
        graded_at = flip.bought_at + named.sale_horizon
        if name in frozen.craft_flips:
            flip = replace(flip, grade=frozen.craft_flips[name])
        elif graded_at <= min(now, times[-1]):
            if crafted is None:
                crafted = market_lots_with_crafts(conn, config, market, predictions)
                record = _Grading(crafted.lots, listings(conn, market), outcomes(conn, market))
            grade = _grade_craft(conn, config, market, flip, bought, crafted, record, graded_at)
            if isinstance(grade, NotGradable):
                flip = replace(flip, not_gradable=grade)
            else:
                # Frozen once settled, as a Flip to Sell's is.
                if config.grades_path is not None and settled_by >= graded_at:
                    freeze_craft_flip_grade(config.grades_path, market, name, grade)
                flip = replace(flip, grade=grade)
        result.append(flip)
    return result


def _unexplained(
    p: Purchase,
    scan_at: int,
    frozen: Frozen,
    times: Sequence[int],
    predictions: Sequence[Prediction],
) -> bool:
    """Whether a Purchase the Scan at `scan_at` named (not For Use) matched none of its
    frozen Flip to Sell rows. Without what it named frozen, it might have been."""
    if scan_at not in frozen.named:
        return True
    row = frozen.shown[scan_at].get(p.item_key)
    if row is not None and p.price <= row.dearest * p.count:
        return False
    return not is_for_use(p, predictions, times, frozen.named)


def _grade_craft(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    flip: CraftFlip,
    bought: Sequence[Purchase],
    crafted: LotsWithCrafts,
    record: "_Grading",
    graded_at: int,
) -> FlipGrade | NotGradable:
    """The Flip to Craft's Grade at `graded_at`, on the output Lots that crafts of its
    recipe by then opened from any of its Purchases' units: output sold after it is still
    open. A craft counts whole, whatever share of its reagents the Flip bought."""

    def used_bought(lineage: Sequence[LotUse]) -> bool:
        """Whether a craft used up any of the Flip's bought units, through Sub-crafts too."""
        return any(_is_lot_of(lot, p) for lot in bought_from(lineage) for p in bought)

    def of_flip(recipe_id: int | None, at: int, lineage: Sequence[LotUse]) -> bool:
        return recipe_id == flip.recipe_id and at <= graded_at and used_bought(lineage)

    if any(of_flip(c.recipe_id, c.at, c.lineage) for c in crafted.uncosted):
        return NotGradable.UNCOSTED
    output = [
        lot
        for lot in crafted.lots
        if lot.crafted and of_flip(lot.recipe_id, lot.acquired_at, lot.lineage)
    ]
    if not output:
        return NotGradable.NOT_CRAFTED
    grade = _grade_lots(
        conn,
        config,
        market,
        record,
        output,
        flip.named.item_key,
        sum(lot.units for lot in output),
        sum(lot.cost for lot in output),
        flip.bought_at,
        graded_at,
    )
    first_craft = min(_first_craft(lot, used_bought) for lot in output)
    return replace(grade, crafted_after=first_craft - flip.bought_at)


def _first_craft(lot: Lot, used_bought: Callable[[Sequence[LotUse]], bool]) -> int:
    """When the first craft that used the Flip's bought units happened, up the lineage of
    a crafted Lot whose craft did."""
    return min(
        [lot.acquired_at]
        + [
            _first_craft(u.lot, used_bought)
            for u in lot.lineage
            if u.lot.crafted and used_bought(u.lot.lineage)
        ]
    )


def _latest_mailbox_read(conn: sqlite3.Connection, market: Market) -> int:
    """When any of the Market's Characters last read their mail; 0 if never."""
    characters = set(character_markets(conn).get(market, []))
    reads = latest_mailbox_read_times(conn, market.era)
    return max(
        (
            at
            for (realm, character), at in reads.items()
            if realm == market.realm and character in characters
        ),
        default=0,
    )


@dataclass(frozen=True)
class _Grading:
    """What the Market's Flips are graded on, loaded once for them all."""

    # Oldest first, the Brain's queue: held units sell ahead of a Flip's (ADR-0007).
    lots: list[Lot]
    listings: list[Listing]
    outcomes: list[Outcome]


def _lots_of(bought: Sequence[Purchase], closing: Sequence[Lot]) -> list[Lot]:
    """The Lots `bought` made, one each."""
    taken: set[int] = set()
    result = []
    for p in bought:
        for i, lot in enumerate(closing):
            if i in taken or lot.prediction is not None:
                continue
            if _is_lot_of(lot, p):
                taken.add(i)
                result.append(lot)
                break
    return result


def _is_lot_of(lot: Lot, p: Purchase) -> bool:
    """Whether `lot` is the one Purchase `p` started, as it stood at any time."""
    return (lot.item_key, lot.acquired_at, lot.units, lot.cost) == (
        p.item_key,
        happened_at(p),
        p.count,
        p.price,
    )


def _grade(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    flip: Flip,
    bought: Sequence[Purchase],
    record: _Grading,
    graded_at: int,
) -> FlipGrade:
    """The Flip's Grade at `graded_at`: units sold after it are still open."""
    lots = _lots_of(bought, record.lots)
    return _grade_lots(
        conn,
        config,
        market,
        record,
        lots,
        flip.item_key,
        flip.units,
        flip.cost,
        flip.bought_at,
        graded_at,
    )


def _grade_lots(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    record: _Grading,
    lots: Sequence[Lot],
    item_key: str,
    units: int,
    cost: int,
    bought_at: int,
    graded_at: int,
) -> FlipGrade:
    """The Grade at `graded_at` of `units` of `item_key` in `lots`, which cost `cost`,
    the clock started at `bought_at`: units sold after it are still open."""
    sales = [s for lot in lots for s in lot.sales if s.sold_at <= graded_at]
    sold_units = sum(s.units for s in sales)
    gross = sum(s.units * s.unit_price for s in sales)
    open_units = units - sold_units
    held = {item_key: Holding(bags=open_units)} if open_units else {}
    return FlipGrade(
        graded_at,
        units,
        cost,
        sold_units,
        gross,
        gross * (1 - auction_cut(market, config)),
        sum(exit_values(conn, config, market, held, graded_at).values()),
        tuple((s.sold_at - bought_at) / 86400 for s in sorted(sales, key=lambda s: s.sold_at)),
        _listed_after(record.listings, item_key, bought_at, graded_at),
        _expired(record.outcomes, item_key, bought_at, graded_at),
    )


def _listed_after(
    seen: Sequence[Listing], item_key: str, bought_at: int, graded_at: int
) -> int | None:
    """Seconds from `bought_at` to the first own Listing of `item_key` seen by `graded_at`."""
    return min(
        (
            ls.first_seen - bought_at
            for ls in seen
            if ls.own and ls.item_key == item_key and bought_at <= ls.first_seen <= graded_at
        ),
        default=None,
    )


def _expired(mail: Sequence[Outcome], item_key: str, bought_at: int, graded_at: int) -> int:
    """`item_key`'s Expired Outcomes from `bought_at` to `graded_at`."""
    return sum(
        o.kind is MailKind.EXPIRED
        and o.item_key == item_key
        and bought_at <= happened_at(o) <= graded_at
        for o in mail
    )
