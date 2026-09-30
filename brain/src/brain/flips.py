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
from collections.abc import Sequence
from dataclasses import dataclass, replace

from brain.config import Config
from brain.grades_file import FlipGrade, Named, flip_name, freeze_flip_grade, load_frozen
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
from brain.lots import Lot, bought_under, happened_at, scan_before
from brain.mailbox import MailKind
from brain.predictions import Prediction
from brain.recommend import auction_cut, exit_values, market_lots, rework


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
        if self.grade is None or not self.grade.sold_units:
            return None
        return self.grade.gross / self.grade.sold_units


@dataclass(frozen=True)
class FlipRecord:
    """The graded Flips taken together. A share is None when there's nothing to take it of."""

    graded: int
    paid_off: int
    realized_over_expected: float | None
    price_over_post_at: float | None  # the median Flip's realized price over its Post at
    sold_within: float | None  # of the units bought
    median_days: float | None  # from the Purchase to a sale, over every sale


def flip_record(made: Sequence[Flip]) -> FlipRecord | None:
    """The record of the graded Flips in `made`; None with none graded."""
    graded = [f for f in made if f.grade is not None]
    if not graded:
        return None
    expected = sum(f.expected for f in graded)
    units = sum(f.grade.units for f in graded)
    prices = [f.realized_price / f.named.post_at for f in graded if f.realized_price is not None]
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
            if (lot.item_key, lot.acquired_at, lot.units, lot.cost) == (
                p.item_key,
                happened_at(p),
                p.count,
                p.price,
            ):
                taken.add(i)
                result.append(lot)
                break
    return result


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
    sales = [s for lot in lots for s in lot.sales if s.sold_at <= graded_at]
    sold_units = sum(s.units for s in sales)
    gross = sum(s.units * s.unit_price for s in sales)
    open_units = flip.units - sold_units
    held = {flip.item_key: Holding(bags=open_units)} if open_units else {}
    return FlipGrade(
        graded_at,
        flip.units,
        flip.cost,
        sold_units,
        gross,
        gross * (1 - auction_cut(market, config)),
        sum(exit_values(conn, config, market, held, graded_at).values()),
        tuple((s.sold_at - flip.bought_at) / 86400 for s in sorted(sales, key=lambda s: s.sold_at)),
        min(
            (
                ls.first_seen - flip.bought_at
                for ls in record.listings
                if ls.own
                and ls.item_key == flip.item_key
                and flip.bought_at <= ls.first_seen <= graded_at
            ),
            default=None,
        ),
        sum(
            o.kind is MailKind.EXPIRED
            and o.item_key == flip.item_key
            and flip.bought_at <= happened_at(o) <= graded_at
            for o in record.outcomes
        ),
    )
