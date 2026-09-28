"""Disenchant: what Disenchanting an item is expected to yield, from the static tables in
`data/disenchant.toml` (ADR-0018).

An item's Disenchant source group is its quality, armor or weapon, and item-level band.
Each group lists its mats with a chance and a quantity range, and the Enchanting skill
a group needs follows from its item level.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "disenchant.toml"

# GetItemInfo's classID.
_KINDS = {"armor": 4, "weapon": 2}


@dataclass(frozen=True)
class ItemInfo:
    """What the client says about an item, from C_Item.GetItemInfo at Scan time."""

    item_level: int
    quality: int
    class_id: int
    equip_loc: str


@dataclass(frozen=True)
class Mat:
    item_id: int
    chance: float
    min_qty: int
    max_qty: int

    @property
    def expected(self) -> float:
        return self.chance * (self.min_qty + self.max_qty) / 2


@dataclass(frozen=True)
class Group:
    """A Disenchant source group: every item of one quality and kind in a level band."""

    quality: int
    kind: str  # "armor" or "weapon"
    min_level: int
    max_level: int
    mats: tuple[Mat, ...]

    @property
    def expected(self) -> dict[int, float]:
        """Expected quantity per Disenchant, by mat itemID."""
        expected: dict[int, float] = {}
        for mat in self.mats:
            expected[mat.item_id] = expected.get(mat.item_id, 0.0) + mat.expected
        return expected


@dataclass(frozen=True)
class DisenchantTable:
    groups: tuple[Group, ...]
    # (highest item level, skill), lowest level first.
    skills: tuple[tuple[int, int], ...]
    excluded_item_ids: frozenset[int]
    excluded_equip_locs: frozenset[str]

    def group(self, item_id: int, info: ItemInfo) -> Group | None:
        """The item's Disenchant source group, or None if it can't be Disenchanted."""
        if item_id in self.excluded_item_ids:
            return None
        if not info.equip_loc or info.equip_loc in self.excluded_equip_locs:
            return None
        for g in self.groups:
            if (
                g.quality == info.quality
                and _KINDS[g.kind] == info.class_id
                and g.min_level <= info.item_level <= g.max_level
            ):
                return g
        return None

    def required_skill(self, item_level: int) -> int | None:
        """The Enchanting skill needed to Disenchant an item of that level, or None above
        every level the table knows."""
        for highest, skill in self.skills:
            if item_level <= highest:
                return skill
        return None


def load_table(path: Path = DATA_FILE) -> DisenchantTable:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    groups = tuple(
        Group(
            quality=band["quality"],
            kind=kind,
            min_level=band["levels"][0],
            max_level=band["levels"][1],
            mats=tuple(Mat(**mat) for mat in band["mats"]),
        )
        for band in raw["band"]
        for kind in band["kinds"]
    )
    return DisenchantTable(
        groups=groups,
        skills=tuple((level, skill) for level, skill in raw["required_skill"]),
        excluded_item_ids=frozenset(raw["excluded_item_ids"]),
        excluded_equip_locs=frozenset(raw["excluded_equip_locs"]),
    )
