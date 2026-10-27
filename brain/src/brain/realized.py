"""Realized profit (ADR-0039): what the player's own sales really made over a range, from
their Sold mail and the Lots the sold units came from. All amounts are copper."""

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from brain.config import Config
from brain.history import Market, Purchase, listings, outcomes, purchases
from brain.lots import happened_at, link_sales, lots
from brain.mailbox import MailKind
from brain.predictions import Prediction
from brain.recommend import auction_cut, lot_craft_results, split_purchases


@dataclass(frozen=True)
class Realized:
    """One Market's realized profit over a range."""

    # The Sold Outcomes after the cut, less the cost of the Lot units they closed.
    profit: float
    # The Purchases in the range the Brain didn't name, which start no Lot (#55).
    for_use: tuple[Purchase, ...] = ()


def realized(
    conn: sqlite3.Connection,
    config: Config,
    market: Market,
    predictions: Sequence[Prediction],
    since: int,
    until: int,
) -> Realized:
    """Realized profit from the Sold Outcomes in [since, until]: each one's price after
    the cut, less the cost of the Lot units it closed, and the For Use Purchases in the
    range. Units without a Lot (looted, bought For Use, crafted from uncosted reagents)
    cost nothing, and an Unlinked Outcome closes none (ADR-0007, ADR-0025). A crafted
    output's Lot costs what its reagents did (#44)."""
    cut = auction_cut(market, config)
    every = purchases(conn, market)
    bought, for_use = split_purchases(conn, config, market, predictions, every)
    linked = link_sales(outcomes(conn, market), listings(conn, market), every)
    proceeds = sum(
        o.price * (1 - cut)
        for o in linked
        if o.kind is MailKind.SOLD and since <= happened_at(o) <= until
    )
    cost = sum(
        sale.units * lot.cost / lot.units
        for lot in lots(bought, linked, craft_results=lot_craft_results(conn, market))
        for sale in lot.sales
        if since <= sale.sold_at <= until
    )
    return Realized(proceeds - cost, tuple(p for p in for_use if since <= happened_at(p) <= until))
