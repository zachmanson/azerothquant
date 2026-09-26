"""The Addon's Scans, as the Brain sees them (see CONTEXT.md: Scan, Item Key, Listing).

The Addon stores each row almost raw (addon/AzerothQuant/Scan.lua). This module
turns that into Brain terms: the Item Key and the unit buyout.
"""

import re
from dataclasses import dataclass

# Positions in "item:itemID:enchant:gem1:gem2:gem3:gem4:suffix:unique:level:spec:
# modifiersMask:context:numBonusIDs:bonusID1:..." (after the "item:" prefix).
_SUFFIX = 6
_NUM_BONUS_IDS = 12
_ITEM_IN_LINK = re.compile(r"\|H(item:[^|]*)\|h")


class ItemStringError(ValueError):
    """An item string the Brain doesn't know how to turn into an Item Key."""


@dataclass(frozen=True)
class ItemKey:
    """itemID plus bonus IDs. The random suffix ("of the Monkey") is one of the bonus IDs."""

    item_id: int
    bonus_ids: tuple[int, ...]

    @classmethod
    def from_item_string(cls, item_string: str) -> "ItemKey":
        """Build the Item Key from an Addon itemString like "item:9768::::::::20:1490::1:1:12743".

        Only the itemID and bonus IDs are kept. The level and spec fields belong to the
        Character who ran the Scan, so keeping them would give one Listing different
        keys depending on who scanned it.
        """
        prefix, _, rest = item_string.partition(":")
        if prefix != "item":
            raise ItemStringError(f"not an item string: {item_string!r}")
        fields = rest.split(":")

        item_id = _int_field(fields, 0, item_string)
        if item_id is None:
            raise ItemStringError(f"no itemID in {item_string!r}")
        if _int_field(fields, _SUFFIX, item_string):
            # The Forever client puts the random suffix in the bonus IDs. A legacy suffix
            # would be a second place for it, which this key doesn't account for.
            raise ItemStringError(f"unexpected legacy suffix field in {item_string!r}")

        count = _int_field(fields, _NUM_BONUS_IDS, item_string) or 0
        bonus_ids = []
        for i in range(_NUM_BONUS_IDS + 1, _NUM_BONUS_IDS + 1 + count):
            bonus_id = _int_field(fields, i, item_string)
            if bonus_id is None:
                raise ItemStringError(f"expected {count} bonus IDs in {item_string!r}")
            bonus_ids.append(bonus_id)

        # Bonus IDs are a set; sorting makes the key independent of the order they came in.
        return cls(item_id=item_id, bonus_ids=tuple(sorted(bonus_ids)))

    @classmethod
    def from_link(cls, link: str) -> "ItemKey":
        """Build the Item Key from an item link ("|cff...|Hitem:2589::...|h[Name]|h|r")."""
        found = _ITEM_IN_LINK.search(link)
        if found is None:
            raise ItemStringError(f"not an item link: {link!r}")
        return cls.from_item_string(found.group(1))

    def __str__(self) -> str:
        """ "itemID" or "itemID:bonus1:bonus2..." (bonus IDs ascending). Used as the stored key."""
        return ":".join(str(n) for n in (self.item_id, *self.bonus_ids))


def _int_field(fields: list[str], index: int, item_string: str) -> int | None:
    """The field as an int, or None when it's empty or past the end (trailing ones get stripped)."""
    if index >= len(fields) or fields[index] == "":
        return None
    try:
        return int(fields[index])
    except ValueError:
        raise ItemStringError(f"field {index} isn't a number in {item_string!r}") from None


def unit_buyout(buyout: int, quantity: int) -> int | None:
    """Unit buyout in whole copper, or None when buyout / quantity isn't a whole number.

    None means the row must be flagged, never rounded: rounding would merge two
    different Listings' prices.
    """
    unit, remainder = divmod(buyout, quantity)
    return None if remainder else unit


class ScanFormatError(ValueError):
    """A Scan in SavedVariables is missing a field the Brain needs."""


# Time-left buckets as the Addon stores them: 1 (shortest) to 4 (longest).
TIME_LEFT_BUCKETS = range(1, 5)


@dataclass(frozen=True)
class ScanRow:
    """One Listing as it stood in one Scan."""

    item_key: str
    unit_buyout: int
    own: bool
    quantity: int
    time_left: int
    # The item name, on own rows only: sale mail names the item but has no Item Key (#17).
    # None for Scans from before the Addon recorded it.
    item_name: str | None = None


@dataclass(frozen=True)
class Scan:
    requested_at: int
    realm: str
    faction: str
    character: str
    rows: tuple[ScanRow, ...]
    # Rows the Addon already dropped for missing item data.
    dropped_rows: int
    # Rows whose buyout / quantity isn't whole copper (flagged, not rounded).
    inexact_rows: int
    # Rows with an item string or field the Brain can't read.
    unreadable_rows: int

    @classmethod
    def from_saved(cls, raw: object) -> "Scan":
        """Build a Scan from one entry of AzerothQuantDB.scans (see addon/AzerothQuant/Scan.lua)."""
        if not isinstance(raw, dict):
            raise ScanFormatError(f"a Scan must be a table, got {raw!r}")
        requested_at = _required(raw, "requestedAt", int)
        header = {f: _required(raw, f, str) for f in ("realm", "faction", "character")}
        raw_listings = raw.get("listings", [])
        if not isinstance(raw_listings, list):
            raise ScanFormatError(f"Scan at {requested_at}: listings must be a sequence")

        rows = []
        inexact = unreadable = 0
        for raw_row in raw_listings:
            try:
                row = _row(raw_row)
            except (ItemStringError, ScanFormatError):
                unreadable += 1
                continue
            if row is None:
                inexact += 1
                continue
            rows.append(row)

        return cls(
            requested_at=requested_at,
            rows=tuple(rows),
            dropped_rows=_required(raw, "droppedRows", int) if "droppedRows" in raw else 0,
            inexact_rows=inexact,
            unreadable_rows=unreadable,
            **header,
        )


def _row(raw: object) -> ScanRow | None:
    """The row as a ScanRow, or None when its unit buyout isn't whole copper."""
    if not isinstance(raw, dict):
        raise ScanFormatError(f"a Listing row must be a table, got {raw!r}")
    item_key = ItemKey.from_item_string(_required(raw, "itemString", str))
    quantity = _required(raw, "quantity", int)
    buyout = _required(raw, "buyout", int)
    time_left = _required(raw, "timeLeft", int)
    if quantity <= 0 or buyout <= 0 or time_left not in TIME_LEFT_BUCKETS:
        raise ScanFormatError(f"out-of-range field in Listing row {raw!r}")

    unit = unit_buyout(buyout, quantity)
    if unit is None:
        return None
    # The Addon writes own = true or leaves it out.
    own = raw.get("own") is True
    name = raw.get("name")
    return ScanRow(
        item_key=str(item_key),
        unit_buyout=unit,
        own=own,
        quantity=quantity,
        time_left=time_left,
        # The Addon only names own rows; a name anywhere else is ignored, not an error.
        item_name=name if own and isinstance(name, str) else None,
    )


def _required[T](raw: dict, field: str, kind: type[T]) -> T:
    value = raw.get(field)
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        raise ScanFormatError(f"missing or bad '{field}' in {raw!r}")
    return value
