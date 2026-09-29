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
from brain.disenchant import DisenchantTable, load_table
from brain.history import (
    Market,
    latest_character_read_times,
    latest_mailbox_read_times,
    latest_scan_times,
)
from brain.lua_literal import assignment
from brain.recommend import (
    Action,
    Blocked,
    BuyUnder,
    ChainNode,
    MarketRecommendations,
    ReagentBuy,
    Row,
)

FILE_NAME = "Recommendations.lua"
GLOBAL_NAME = "AzerothQuantRecommendations"

_HEADER = (
    "-- Written by the azerothquant Brain after every import; edits are overwritten.\n"
    "-- lastImported[realm][faction] is when the latest imported Scan in that Market\n"
    "-- was requested. The Addon deletes stored Scans up to then.\n"
    "-- lastMailboxRead[realm][character] is when the latest imported Mailbox Read of\n"
    "-- that Character was taken. The Addon deletes stored Mailbox Reads up to then.\n"
    "-- lastCharacterRead[realm][character] is the same for Character Reads.\n"
    "-- recommendations[realm][faction] is that Market's Recommendations, in copper.\n"
    "-- budget is the Budget the Brain sized them within (nil for all the gold), and each\n"
    "-- shoppingList row is an option sized as if it were the only buy. A Flip to Sell or\n"
    "-- Flip to Vendor row has listings (bought), posts (stacks posted) and days (until\n"
    "-- its last unit sells; nil on a Flip to Vendor, which sells now). A\n"
    "-- Flip to Craft's row (action Craft on the shoppingList) lists its reagent buys:\n"
    "-- { itemKey, quantity, maxUnitPrice, merchant = true when bought from a merchant }.\n"
    "-- Every Craft row names its character, and lists the held reagents it uses as\n"
    "-- uses = { { itemKey, quantity } }. One that can't be made says why as\n"
    '-- blocked = { reason = "noData", itemKey } or { reason = "unknownBindType" }.\n'
    "-- A Craft that crafts a short reagent first lists those Sub-crafts, deepest first,\n"
    "-- as via = { { itemKey, crafts, character } }; uses and buys cover the whole chain.\n"
    "-- Every Craft row has its Craft Chain as chain = { node }: its exits (sell or vendor),\n"
    "-- the last with the craft as its one child, over the sources that feed it. A node is\n"
    '-- { kind = "sell"|"vendor"|"craft"|"use"|"buy"|"merchant"|"leftover", itemKey,\n'
    "-- quantity (the row's total), gold (signed; nil where unknown), children }. A craft\n"
    "-- also has crafts and character, a sell postAt, cut, deposit and effort, a buy\n"
    "-- maxUnitPrice and effort, and the node that blocks a row blocked. Every node's gold\n"
    "-- but a craft's (the sum of its children's) adds up to the row's profit. A blocked\n"
    "-- row's chain is one craft, as it would be sourced, with no exit.\n"
    "-- A Holdings Sell or Vendor row whose units were bought on the Auction House has\n"
    "-- paid (per unit), paidUnits (how many units that covers), roi (a share, after\n"
    "-- the cut) and roiHint = true when it's a good time to sell (only a hint).\n"
    "-- held[itemKey] says which Characters hold it, by name: { { character, bags, bank,\n"
    "-- bound } }, where bound is the part of bags and bank that can't be mailed or sold.\n"
    "-- buyUnder lists the Buy Unders, the most to pay per unit on the Auction House:\n"
    '-- { itemKey, price, way = "Vendor"|"Sell"|"Craft", units (nil for no limit), seen\n'
    "-- (Scans that saw a Listing at or under it), windowDays, listedNow = true when the\n"
    "-- latest Scan did }, and a Craft way's recipe (recipeID), output (Item Key) and\n"
    "-- crafter. A Disenchant way names its disenchanter and the expected mats of one\n"
    "-- Disenchant as mats = { { itemKey, quantity } }. A Disenchant source group's entry\n"
    '-- has no itemKey but group = { quality, class = "armor"|"weapon", minLevel, maxLevel }:\n'
    "-- the most to pay for any item in it that can be Disenchanted.\n"
    "-- disenchantExcluded is what can't be Disenchanted, whatever its group: itemIDs and\n"
    "-- equipLocs, each a set.\n"
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
            "disenchantExcluded": _disenchant_excluded(load_table()),
        },
    )


def _recommendations(markets: Sequence[MarketRecommendations]) -> dict[str, dict[str, dict]]:
    by_realm: dict[str, dict[str, dict]] = {}
    for m in markets:
        by_realm.setdefault(m.market.realm, {})[m.market.faction] = {
            "asOf": m.as_of,
            "gold": m.gold,
            "windowHours": m.window_hours,
            "predictionCost": m.prediction_cost,
            "holdings": [_row(r) for r in m.holdings],
            "shoppingList": [_row(r) for r in m.shopping_list],
            "predictionBuys": [_row(r) for r in m.prediction_buys],
            "held": {
                item_key: [
                    {"character": h.character, "bags": h.bags, "bank": h.bank, "bound": h.bound}
                    for h in whose
                ]
                for item_key, whose in m.held.items()
            },
            "buyUnder": [_buy_under(b) for b in m.buy_under],
        }
        if m.budget is not None:  # a Lua table can't hold nil
            by_realm[m.market.realm][m.market.faction]["budget"] = m.budget
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
    "character": "character",
    "paid": "paid",
    "paid_units": "paidUnits",
    "roi": "roi",
    "listings": "listings",
    "posts": "posts",
    "days": "days",
}


def _row(row: Row) -> dict[str, object]:
    out: dict[str, object] = {}
    for field, key in _ROW_KEYS.items():
        value = getattr(row, field)
        if value is None or value == "":
            continue
        out[key] = str(value) if isinstance(value, Action) else value
    if row.roi_hint:
        out["roiHint"] = True
    if row.buys:
        out["buys"] = [_buy(b) for b in row.buys]
    if row.uses:
        out["uses"] = [{"itemKey": u.item_key, "quantity": u.quantity} for u in row.uses]
    if row.blocked:
        out["blocked"] = _blocked(row.blocked)
    if row.mats:
        out["mats"] = [{"itemKey": m.item_key, "quantity": m.quantity} for m in row.mats]
    if row.via:
        out["via"] = [
            {"itemKey": v.item_key, "crafts": v.crafts, "character": v.character} for v in row.via
        ]
    if row.chain:
        out["chain"] = [_node(n) for n in row.chain]
    return out


_NODE_KEYS = {
    "quantity": "quantity",
    "gold": "gold",
    "crafts": "crafts",
    "character": "character",
    "post_at": "postAt",
    "max_unit_price": "maxUnitPrice",
    "cut": "cut",
    "deposit": "deposit",
    "effort": "effort",
}


def _node(node: ChainNode) -> dict[str, object]:
    out: dict[str, object] = {"kind": str(node.kind), "itemKey": node.item_key}
    for field, key in _NODE_KEYS.items():
        value = getattr(node, field)
        if value is not None and value != "":
            out[key] = value
    if node.blocked:
        out["blocked"] = _blocked(node.blocked)
    if node.children:
        out["children"] = [_node(c) for c in node.children]
    return out


def _buy_under(buy: BuyUnder) -> dict[str, object]:
    out: dict[str, object] = {
        "price": buy.price,
        "way": str(buy.way),
        "seen": buy.seen,
        "windowDays": buy.window_days,
    }
    optional = {
        "itemKey": buy.item_key,
        "units": buy.units,
        "recipe": buy.recipe_id,
        "output": buy.output,
        "crafter": buy.crafter,
        "disenchanter": buy.disenchanter,
    }
    out |= {key: value for key, value in optional.items() if value is not None}
    if buy.mats:
        out["mats"] = [{"itemKey": m.item_key, "quantity": m.quantity} for m in buy.mats]
    if buy.group:
        g = buy.group
        out["group"] = {
            "quality": g.quality,
            "class": g.kind,
            "minLevel": g.min_level,
            "maxLevel": g.max_level,
        }
    if buy.listed_now:
        out["listedNow"] = True
    return out


def _disenchant_excluded(table: DisenchantTable) -> dict[str, dict]:
    return {
        "itemIDs": {item_id: True for item_id in sorted(table.excluded_item_ids)},
        "equipLocs": {loc: True for loc in sorted(table.excluded_equip_locs)},
    }


def _blocked(blocked: Blocked) -> dict[str, object]:
    out: dict[str, object] = {"reason": str(blocked.reason)}
    if blocked.item_key:
        out["itemKey"] = blocked.item_key
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
