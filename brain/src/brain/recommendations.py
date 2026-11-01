"""Recommendations.lua: what the Brain hands back to the Addon.

The Brain writes it into the Addon's folder in each install, never into
SavedVariables, since the client overwrites SavedVariables on every logout
(ADR-0001). The client reads it on login or `/reload`. It writes the same file into
three Data slots too, LoadOnDemand addons the Brain creates, whose files the client
reads when the Addon loads one, once a session. The Addon tries them in turn after a
reload, so a new import needs no second reload (ADR-0030).

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

import math
import os
import sqlite3
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from brain import __version__
from brain.beta_prior import BetaPrior
from brain.config import DEFAULT_POST_DURATION_HOURS, Era, Install
from brain.disenchant import DisenchantTable, Group, load_table
from brain.history import (
    Market,
    latest_character_read_times,
    latest_mailbox_read_times,
    latest_own_scan_times,
)
from brain.lua_literal import assignment
from brain.recommend import (
    Action,
    Blocked,
    BuyUnder,
    ChainNode,
    DisenchantFlip,
    LootAlert,
    MarketRecommendations,
    PredictionLine,
    PredictionSummary,
    ReagentBuy,
    Row,
)

FILE_NAME = "Recommendations.lua"
# A Live Market with fewer Scans than this is young: the Addon says the table is still
# filling in. By 10 Scans the Holdings had settled in a replay of Beta's first Scans (#147).
YOUNG_MARKET_SCANS = 10
GLOBAL_NAME = "AzerothQuantRecommendations"

_HEADER = (
    "-- Written by the azerothquant Brain after every import; edits are overwritten.\n"
    "-- lastImported[realm][faction] is when the latest of your own imported Scans in\n"
    "-- that Market was requested. The Addon deletes stored Scans up to then.\n"
    "-- lastMailboxRead[realm][character] is when the latest imported Mailbox Read of\n"
    "-- that Character was taken. The Addon deletes stored Mailbox Reads up to then.\n"
    "-- lastCharacterRead[realm][character] is the same for Character Reads.\n"
    "-- recommendations[realm][faction] is that Market's Recommendations, in copper.\n"
    "-- budget is the Budget the Brain sized them within (nil for all the gold), and each\n"
    "-- shoppingList row is an option sized as if it were the only buy. stake is the gold\n"
    "-- plus the own Listings up at cost, room what an option may cost and lossCap the\n"
    "-- most Unsold Loss it may have under the risk caps (nil without them); a row they\n"
    "-- shrank has capped, its units by the gold alone, and cappedBy, the cap that shrank\n"
    '-- it ("room" or "loss"). A Flip to Sell the loss cap dropped that comes back whole as\n'
    "-- a Risky row has risky = true and unsoldLoss, what it loses if none of it sells.\n"
    "-- A Flip to Sell or Flip to Vendor row has listings (bought),\n"
    "-- posts (stacks posted) and days (until its last unit sells; nil on a Flip to\n"
    "-- Vendor, which sells now). A\n"
    "-- Flip to Craft's row (action Craft on the shoppingList) lists its reagent buys:\n"
    "-- { itemKey, quantity, maxUnitPrice, merchant = true when bought from a merchant },\n"
    "-- and its output's postAt (nil when none of it beats vendoring).\n"
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
    "-- A Holdings Sell, Wait or Vendor row whose units were bought on the Auction House\n"
    "-- has paid (per unit), paidUnits (how many units that covers), roi (a share, after\n"
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
    "-- the most to pay for any item in it that can be Disenchanted. A Sell way (off but in\n"
    "-- the Backtest) has postAt: worth buying only while nothing else is listed under it.\n"
    "-- A Flip to Disenchant's row (action Disenchant on the shoppingList, no itemKey) has\n"
    "-- disenchant = { group, disenchanter, mats, buys = { { itemKey, price } } }: the\n"
    "-- group it buys, as a Buy Under's, and the Listings it buys, cheapest first.\n"
    "-- lootAlert is what a drop must be worth for a Loot Alert: { threshold (one unit),\n"
    '-- items = { [itemKey] = { value, action = "Sell"|"Vendor"|"Disenchant"|"Craft" } } }:\n'
    "-- each Item Key in the Scan whose one unit alone is worth at least the threshold.\n"
    "-- disenchantExcluded is what can't be Disenchanted, whatever its group: itemIDs and\n"
    "-- equipLocs, each a set.\n"
    "-- postDurationHours is how long every post lasts (2, 8 or 24): the Brain charges\n"
    "-- Deposits for that long, so the Addon's Post button posts for it too.\n"
    "-- young = true while a Live Market has too few Scans for a full table.\n"
    "-- brain is the Brain's status: { version, problem (a line for the player, nil when\n"
    "-- all is well) }. The shipped stub has none, which tells the Addon the Brain has\n"
    "-- never run.\n"
)


DATA_SLOTS = ("AzerothQuant_Data1", "AzerothQuant_Data2", "AzerothQuant_Data3")
# The one Data addon before ADR-0030's slots: setup and uninstall remove it.
OLD_DATA_ADDON = "AzerothQuant_Data"
_DATA_TOC = (
    "## Title: AzerothQuant Data {n}\n"
    "## Notes: The Brain's latest Recommendations, loaded by the Addon after a reload."
    " Written by the Brain; edits are overwritten.\n"
    "## LoadOnDemand: 1\n"
    "## Dependencies: AzerothQuant\n"
    "\n"
    f"{FILE_NAME}\n"
)


def addon_folder(install: Install) -> Path:
    return install.path / "Interface" / "AddOns" / "AzerothQuant"


def data_slot_folders(install: Install) -> list[Path]:
    return [install.path / "Interface" / "AddOns" / slot for slot in DATA_SLOTS]


def old_data_addon_folder(install: Install) -> Path:
    return install.path / "Interface" / "AddOns" / OLD_DATA_ADDON


def render(
    last_imported: dict[Market, int],
    last_mailbox_read: dict[tuple[str, str], int] | None = None,
    last_character_read: dict[tuple[str, str], int] | None = None,
    markets: Sequence[MarketRecommendations] = (),
    beta_priors: Mapping[Market, BetaPrior] | None = None,
    post_duration_hours: float = DEFAULT_POST_DURATION_HOURS,
    problem: str | None = None,
    catching_up_since: int | None = None,
) -> str:
    by_realm: dict[str, dict[str, int]] = {}
    for market, requested_at in last_imported.items():
        by_realm.setdefault(market.realm, {})[market.faction] = requested_at
    brain: dict[str, str | int] = {"version": __version__}
    if problem:  # a Lua table can't hold nil
        brain["problem"] = problem
    if catching_up_since is not None:
        brain["catchingUpSince"] = catching_up_since
    return _HEADER + assignment(
        GLOBAL_NAME,
        {
            "lastImported": by_realm,
            "lastMailboxRead": _by_realm(last_mailbox_read or {}),
            "lastCharacterRead": _by_realm(last_character_read or {}),
            "recommendations": _recommendations(markets, beta_priors or {}),
            "disenchantExcluded": _disenchant_excluded(load_table()),
            "postDurationHours": post_duration_hours,
            "brain": brain,
        },
    )


def _recommendations(
    markets: Sequence[MarketRecommendations], beta_priors: Mapping[Market, BetaPrior]
) -> dict[str, dict[str, dict]]:
    by_realm: dict[str, dict[str, dict]] = {}
    for m in markets:
        by_realm.setdefault(m.market.realm, {})[m.market.faction] = {
            "asOf": m.as_of,
            "gold": m.gold,
            "stake": math.floor(m.stake),
            "windowHours": m.window_hours,
            "predictionCost": m.prediction_cost,
            "holdings": [_row(r) for r in m.holdings],
            "shoppingList": [_row(r) for r in m.shopping_list],
            "predictionBuys": [_row(r) for r in m.prediction_buys],
            "predictions": [_prediction(p) for p in m.predictions],
            "held": {
                item_key: [
                    {"character": h.character, "bags": h.bags, "bank": h.bank, "bound": h.bound}
                    for h in whose
                ]
                for item_key, whose in m.held.items()
            },
            "buyUnder": [_buy_under(b) for b in m.buy_under],
            "lootAlert": _loot_alert(m.loot_alert),
        }
        if m.budget is not None:  # a Lua table can't hold nil
            by_realm[m.market.realm][m.market.faction]["budget"] = m.budget
        if m.room is not None:
            by_realm[m.market.realm][m.market.faction]["room"] = math.floor(m.room)
        if m.loss_cap is not None:
            by_realm[m.market.realm][m.market.faction]["lossCap"] = math.floor(m.loss_cap)
        if m.market.era is Era.LIVE and m.scan_count < YOUNG_MARKET_SCANS:
            by_realm[m.market.realm][m.market.faction]["young"] = True
        if m.market in beta_priors:
            by_realm[m.market.realm][m.market.faction]["beta"] = _beta(beta_priors[m.market])
    return by_realm


def _prediction(p: PredictionSummary) -> dict[str, object]:
    """A Prediction for the Predictions tab (#207): its header, and a line per Item Key
    with its buy or the Brain's reason it has none."""
    out: dict[str, object] = {
        "name": p.name,
        "held": p.held,
        "tiedUp": math.floor(p.tied_up),
        "cap": math.floor(p.cap),
        "lapse": p.lapse.isoformat(),
        "lines": [_prediction_line(line) for line in p.lines],
    }
    if p.happened is not None:
        out["happened"] = p.happened.isoformat()
    return out


def _prediction_line(line: PredictionLine) -> dict[str, object]:
    out: dict[str, object] = {"itemKey": line.item_key, "held": line.held}
    if line.buy is not None:
        out["buy"] = _row(line.buy)
    if line.reason is not None:
        out["reason"] = line.reason
    return out


def _beta(prior: BetaPrior) -> dict[str, object]:
    prices: dict[str, dict[str, object]] = {}
    for item_key, p in prior.prices.items():
        out: dict[str, object] = {"price": p.price, "saleEvents": p.sale_events}
        if p.sold:
            out["sold"] = True
        if p.units_per_day is not None:
            out["perDay"] = p.units_per_day
        prices[item_key] = out
    return {"realm": prior.market.realm, "faction": prior.market.faction, "prices": prices}


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
    "sibling_sales": "siblingSales",
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
    "capped": "capped",
    "capped_by": "cappedBy",
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
    # Only a Risky row states its Unsold Loss (#194): its details tell the player the risk.
    if row.risky:
        out["risky"] = True
        if row.unsold_loss is not None:
            out["unsoldLoss"] = math.floor(row.unsold_loss)
    # A Prediction buy's room is partly the Beta Sell Rate's only when Beta added to it (#110).
    if row.beta_room and row.beta_room.from_beta > 0:
        out["roomFromBeta"] = True
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
    if row.disenchant:
        out["disenchant"] = _disenchant(row.disenchant, row)
    return out


def _disenchant(flip: DisenchantFlip, row: Row) -> dict[str, object]:
    return {
        "group": _group(flip.group),
        "disenchanter": row.character,
        "mats": [{"itemKey": m.item_key, "quantity": m.quantity} for m in row.mats],
        "buys": [{"itemKey": b.item_key, "price": b.price} for b in flip.buys],
    }


def _group(g: Group) -> dict[str, object]:
    return {"quality": g.quality, "class": g.kind, "minLevel": g.min_level, "maxLevel": g.max_level}


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
        "postAt": buy.post_at,
    }
    out |= {key: value for key, value in optional.items() if value is not None}
    if buy.mats:
        out["mats"] = [{"itemKey": m.item_key, "quantity": m.quantity} for m in buy.mats]
    if buy.group:
        out["group"] = _group(buy.group)
    if buy.listed_now:
        out["listedNow"] = True
    return out


def _loot_alert(alert: LootAlert) -> dict[str, object]:
    return {
        "threshold": alert.threshold,
        "items": {
            item_key: {"value": round(v.value), "action": str(v.way)}
            for item_key, v in alert.items.items()
        },
    }


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
    beta_priors: Mapping[Market, BetaPrior] | None = None,
    post_duration_hours: float = DEFAULT_POST_DURATION_HOURS,
    problem: str | None = None,
    catching_up_since: int | None = None,
) -> Path | None:
    """Write the install's Recommendations.lua from the history and the Recommendations of
    its Era's Markets, with their Beta Priors and the Brain's status (its version, the
    problem to tell the player, if any, and when a long pull started, if one is running);
    None if the Addon isn't installed there."""
    folder = addon_folder(install)
    if not folder.is_dir():
        return None
    path = folder / FILE_NAME
    text = render(
        latest_own_scan_times(conn, install.era),
        latest_mailbox_read_times(conn, install.era),
        latest_character_read_times(conn, install.era),
        [m for m in markets if m.market.era is install.era],
        beta_priors,
        post_duration_hours,
        problem,
        catching_up_since,
    )
    # The Addon's own copy first: the Addon prunes by it, so a failed Data write mustn't
    # cost it.
    _write_atomically(path, text)
    for data in _write_data_tocs(install):
        _write_atomically(data / FILE_NAME, text)
    return path


def create_data_slots(install: Install) -> None:
    """Create the install's Data slots from its Addon, keeping any Recommendations they
    already have. Setup does this up front (#115), so the game finds them at its first
    start rather than only after a restart once the Brain has run."""
    stub = (addon_folder(install) / FILE_NAME).read_text(encoding="utf-8")
    for data in _write_data_tocs(install):
        if not (data / FILE_NAME).exists():
            _write_atomically(data / FILE_NAME, stub)


def _write_data_tocs(install: Install) -> list[Path]:
    """Make the install's Data slot folders with their TOCs, and return the folders."""
    interface = _interface_line(addon_folder(install))
    folders = data_slot_folders(install)
    # Numbered titles, so the AddOns list doesn't show three identical rows.
    for n, data in enumerate(folders, start=1):
        data.mkdir(exist_ok=True)
        _write_atomically(data / f"{data.name}.toc", interface + _DATA_TOC.format(n=n))
    return folders


def _interface_line(addon: Path) -> str:
    """The Addon's Interface line, for a Data slot's TOC, so the client doesn't list the
    slot as out of date whenever the Addon is current."""
    toc = addon / "AzerothQuant.toc"
    lines = toc.read_text(encoding="utf-8").splitlines() if toc.is_file() else []
    interface = [line + "\n" for line in lines if line.startswith("## Interface:")]
    return "".join(interface[:1])


def _write_atomically(path: Path, text: str) -> None:
    # Write a temp file and swap it in, so the client never reads a half-written file. The
    # temp name is unique so a `brain import` running beside `brain watch` can't clash.
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
