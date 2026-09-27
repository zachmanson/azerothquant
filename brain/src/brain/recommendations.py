"""Recommendations.lua: what the Brain hands back to the Addon.

The Brain writes it into the Addon's folder in each install, never into
SavedVariables, since the client overwrites SavedVariables on every logout
(ADR-0001). The client reads it on login or `/reload`.

It holds, per Market, when the latest imported Scan was requested.
The Addon then deletes every stored Scan in that Market requested at or before
that time: each one is either imported already or older than an imported one,
which the Brain rejects, so none of them can be of any more use.

Likewise, per Character, when the latest imported Mailbox Read and Character Read were
taken. Reads are imported whatever their order, so every stored Read up to then is
already archived.

And, per Market of the install's Era, its Recommendations as raw data (copper, Item
Keys, Action names) for the Recommendation Table. The Addon formats them itself, since
only it can look up item names.
"""

import os
import sqlite3
import tempfile
from collections.abc import Sequence
from pathlib import Path

from brain.config import Install
from brain.history import (
    Market,
    latest_character_read_times,
    latest_mailbox_read_times,
    latest_scan_times,
)
from brain.lua_literal import assignment
from brain.recommend import Action, MarketRecommendations, ReagentBuy, Row

FILE_NAME = "Recommendations.lua"
GLOBAL_NAME = "AzerothQuantRecommendations"

_HEADER = (
    "-- Written by the azerothquant Brain after every import; edits are overwritten.\n"
    "-- lastImported[realm][faction] is when the latest imported Scan in that Market\n"
    "-- was requested. The Addon deletes stored Scans up to then.\n"
    "-- lastMailboxRead[realm][character] is when the latest imported Mailbox Read of\n"
    "-- that Character was taken. The Addon deletes stored Mailbox Reads up to then.\n"
    "-- lastCharacterRead[realm][character] is the same for Character Reads.\n"
    "-- recommendations[realm][faction] is that Market's Recommendations, in copper. A\n"
    "-- Flip to Craft's row (action Craft on the shoppingList) lists its reagent buys:\n"
    "-- { itemKey, quantity, maxUnitPrice, merchant = true when bought from a merchant }.\n"
)


def addon_folder(install: Install) -> Path:
    return install.path / "Interface" / "AddOns" / "AzerothQuant"


def render(
    last_imported: dict[Market, int],
    last_mailbox_read: dict[tuple[str, str], int] | None = None,
    last_character_read: dict[tuple[str, str], int] | None = None,
    markets: Sequence[MarketRecommendations] = (),
) -> str:
    by_realm: dict[str, dict[str, int]] = {}
    for market, requested_at in last_imported.items():
        by_realm.setdefault(market.realm, {})[market.faction] = requested_at
    return _HEADER + assignment(
        GLOBAL_NAME,
        {
            "lastImported": by_realm,
            "lastMailboxRead": _by_realm(last_mailbox_read or {}),
            "lastCharacterRead": _by_realm(last_character_read or {}),
            "recommendations": _recommendations(markets),
        },
    )


def _recommendations(markets: Sequence[MarketRecommendations]) -> dict[str, dict[str, dict]]:
    by_realm: dict[str, dict[str, dict]] = {}
    for m in markets:
        by_realm.setdefault(m.market.realm, {})[m.market.faction] = {
            "asOf": m.as_of,
            "gold": m.gold,
            "windowHours": m.window_hours,
            "shoppingCost": m.shopping_cost,
            "predictionCost": m.prediction_cost,
            "holdings": [_row(r) for r in m.holdings],
            "shoppingList": [_row(r) for r in m.shopping_list],
            "predictionBuys": [_row(r) for r in m.prediction_buys],
        }
    return by_realm


# Row field -> the key the Addon reads. None and "" are left out: a Lua table can't hold
# nil, and an absent key reads as nil in the Addon either way.
_ROW_KEYS = {
    "item_key": "itemKey",
    "action": "action",
    "quantity": "quantity",
    "price": "price",
    "profit": "profit",
    "post_at": "postAt",
    "margin": "margin",
    "sale_events": "saleEvents",
    "note": "note",
    "cost": "cost",
    "prediction": "prediction",
    "max_loss": "maxLoss",
}


def _row(row: Row) -> dict[str, object]:
    out: dict[str, object] = {}
    for field, key in _ROW_KEYS.items():
        value = getattr(row, field)
        if value is None or value == "":
            continue
        out[key] = str(value) if isinstance(value, Action) else value
    if row.buys:
        out["buys"] = [_buy(b) for b in row.buys]
    return out


def _buy(buy: ReagentBuy) -> dict[str, object]:
    out: dict[str, object] = {
        "itemKey": buy.item_key,
        "quantity": buy.quantity,
        "maxUnitPrice": buy.max_unit_price,
    }
    if buy.merchant:
        out["merchant"] = True
    return out


def _by_realm(read_times: dict[tuple[str, str], int]) -> dict[str, dict[str, int]]:
    by_realm: dict[str, dict[str, int]] = {}
    for (realm, character), read_at in read_times.items():
        by_realm.setdefault(realm, {})[character] = read_at
    return by_realm


def write_recommendations(
    conn: sqlite3.Connection,
    install: Install,
    markets: Sequence[MarketRecommendations] = (),
) -> Path | None:
    """Write the install's Recommendations.lua from the history and the Recommendations of
    its Era's Markets; None if the Addon isn't installed there."""
    folder = addon_folder(install)
    if not folder.is_dir():
        return None
    path = folder / FILE_NAME
    text = render(
        latest_scan_times(conn, install.era),
        latest_mailbox_read_times(conn, install.era),
        latest_character_read_times(conn, install.era),
        [m for m in markets if m.market.era is install.era],
    )
    # Write a temp file and swap it in, so the client never reads a half-written file. The
    # temp name is unique so a `brain import` running beside `brain watch` can't clash.
    fd, temp = tempfile.mkstemp(dir=folder, prefix=FILE_NAME + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    return path
