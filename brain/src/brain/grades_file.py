"""grades.toml: Grades and held-at-writing costs, frozen once computed (#66, ADR-0006),
the Flips to Sell each Scan named and their Flip Grades (#60, ADR-0023), its Flips to
Craft and theirs (#114, ADR-0027), and what each Scan named to buy (#55, ADR-0025).

They are worked out from history, so a later change to how Best Exit Value is priced
would silently rewrite them. The history DB is rebuildable (ADR-0005), so they live in
their own file next to predictions.toml. The Brain only ever appends to it: an entry,
once written, is never overwritten. To regrade, the player deletes the entry by hand.
"""

import json
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from brain.history import Market
from brain.lots import Held, NamedSet

_HEADER = (
    "# Written by the Brain: Grades and held-at-writing costs, frozen once worked out.\n"
    "# It never changes an entry. Delete one by hand to have it worked out again.\n"
)


class GradesError(Exception):
    """grades.toml is malformed."""


# The risky entry of a shown row that was a Risky row for too few Sale Events (#224).
NO_SALES = "noSales"


@dataclass(frozen=True)
class Grade:
    """A Prediction's realized result, fixed at its grading moment (ADR-0006): its sold
    units after the Auction House cut, plus its open units at their Best Exit Value
    without it then, against what all of them cost."""

    prediction: str
    graded_at: int
    proceeds: float
    open_value: float
    cost: int

    @property
    def return_(self) -> float | None:
        """Gain over cost, or None if its units cost nothing."""
        if not self.cost:
            return None
        return (self.proceeds + self.open_value - self.cost) / self.cost


@dataclass(frozen=True)
class Named:
    """A Flip to Sell row as the Shopping List showed it at one Scan: what the Brain named
    (#60)."""

    item_key: str
    units: int
    dearest: int  # per unit, the dearest Listing its run bought
    post_at: float
    profit: float  # expected, for all `units`
    days: float | None  # expected until its last unit sells
    sale_horizon: int  # seconds, in force then
    # A Risky row's (#194, ADR-0037), so its Flip Grades can be split out from the rest.
    risky: bool = False
    # A Risky row for too few Sale Events (#224, ADR-0043), written risky = "noSales".
    no_sales: bool = False


@dataclass(frozen=True)
class NamedBuy:
    """A Flip to Craft row's Auction House buys of one reagent: `quantity` at up to
    `max_unit_price` each."""

    item_key: str
    quantity: int
    max_unit_price: float


@dataclass(frozen=True)
class NamedCraft:
    """A Flip to Craft row as the Shopping List showed it at one Scan (#114): what the
    Brain named. Only its Auction House buys: a merchant reagent's Purchase is no Flip."""

    item_key: str  # the output's
    recipe_id: int
    character: str
    units: int  # output units
    buys: tuple[NamedBuy, ...]
    post_at: float | None  # None when it all goes to Vendor
    profit: float  # expected, for all `units`
    days: float | None
    sale_horizon: int  # seconds, in force then


@dataclass(frozen=True)
class FlipGrade:
    """A Flip's realized result a Sale Horizon after its first Purchase (#60): its units
    Sold by then after the Auction House cut, plus its units still open at their Best Exit
    Value then, against what they cost. Deposits are left out (ADR-0023)."""

    graded_at: int
    units: int
    cost: int
    sold_units: int
    gross: float  # what the sold units brought before the cut
    proceeds: float  # after it
    open_value: float
    sale_days: tuple[float, ...]  # from the first Purchase to each sale that closed units
    # Seconds from the first Purchase to the first own Listing of its Item Key seen, None
    # if none was by the grading moment: the post lag, which the grade includes.
    listed_after: int | None
    # The Item Key's Expired Outcomes within the horizon, which may not be this Flip's.
    expired: int
    # A Flip to Craft's (#114): seconds from the first Purchase to the first craft that
    # used its units. Its `units` and `cost` are then its output Lots'.
    crafted_after: int | None = None

    @property
    def open_units(self) -> int:
        return self.units - self.sold_units

    @property
    def realized(self) -> float:
        """Realized Profit."""
        return self.proceeds + self.open_value - self.cost

    @property
    def paid_off(self) -> bool:
        return self.realized > 0


@dataclass(frozen=True)
class Frozen:
    """What grades.toml holds for one Market: Prediction entries by its name, what each
    Scan named by its time, and Flip Grades by `flip_name`."""

    held: dict[str, tuple[Held, ...]] = field(default_factory=dict)
    grades: dict[str, Grade] = field(default_factory=dict)
    # By the requested_at of each Scan worked out again, its Flip to Sell rows by Item Key.
    shown: dict[int, dict[str, Named]] = field(default_factory=dict)
    # By `flip_name`.
    flips: dict[str, FlipGrade] = field(default_factory=dict)
    # By the requested_at of each Scan worked out again, what it named to buy.
    named: dict[int, NamedSet] = field(default_factory=dict)
    # By the requested_at of each Scan worked out for crafts, its Flip to Craft rows.
    shown_crafts: dict[int, tuple[NamedCraft, ...]] = field(default_factory=dict)
    # By `craft_flip_name`.
    craft_flips: dict[str, FlipGrade] = field(default_factory=dict)


def flip_name(item_key: str, scan_at: int) -> str:
    """A Flip's name in grades.toml: its Item Key and the Scan whose row it matched."""
    return f"{item_key}@{scan_at}"


def craft_flip_name(recipe_id: int, scan_at: int) -> str:
    """A Flip to Craft's name in grades.toml: its recipe and the Scan whose row it matched."""
    return f"{recipe_id}@{scan_at}"


# A file's (modified time, size): the Brain only appends to grades.toml, which grows it,
# and a hand edit changes its modified time.
type _Stamp = tuple[int, int]
# Each file as last parsed, and what `load_frozen` last gave for each of its Markets, with
# the file's stamp when they were read.
_parsed_by_file: dict[Path, tuple[_Stamp, dict]] = {}
_frozen_by_market: dict[tuple[Path, Market], tuple[_Stamp, "Frozen"]] = {}


def load_frozen(path: Path | None, market: Market) -> Frozen:
    """What's frozen in `path` for `market`; nothing without a path or before the file is
    written. A Prediction names Item Keys, not a Market, so each Market has its own.

    Kept until the file changes: a pass loads it ~10 times for each Market, and parsing it
    each time was ~11% of a pass with no new Scan on Live (#235). Nobody may change what it
    returns."""
    if path is None:
        return _frozen({}, path, market)
    try:
        stat = path.stat()
    except FileNotFoundError:
        return _frozen({}, path, market)
    stamp = (stat.st_mtime_ns, stat.st_size)
    kept = _frozen_by_market.get((path, market))
    if kept is not None and kept[0] == stamp:
        return kept[1]
    parsed = _parsed_by_file.get(path)
    if parsed is None or parsed[0] != stamp:
        parsed = stamp, _load(path)
        _parsed_by_file[path] = parsed
    frozen = _frozen(parsed[1], path, market)
    _frozen_by_market[(path, market)] = stamp, frozen
    return frozen


def _frozen(raw: dict, path: Path | None, market: Market) -> Frozen:
    try:
        held = {
            name: tuple(
                Held(
                    name,
                    _typed(u["item_key"], str),
                    _typed(u["units"], int),
                    _typed(u["cost"], int),
                )
                for u in entry["units"]
            )
            for name, entry in _entries(raw, "held", market).items()
        }
        grades = {
            name: Grade(
                name,
                _typed(entry["graded_at"], int),
                float(_typed(entry["proceeds"], int | float)),
                float(_typed(entry["open_value"], int | float)),
                _typed(entry["cost"], int),
            )
            for name, entry in _entries(raw, "grades", market).items()
        }
        shown = {
            int(scan_at): {
                r["item_key"]: _named(r, _typed(entry["sale_horizon"], int)) for r in entry["rows"]
            }
            for scan_at, entry in _entries(raw, "shown", market).items()
        }
        flips = {name: _flip_grade(e) for name, e in _entries(raw, "flips", market).items()}
        shown_crafts = {
            int(scan_at): tuple(
                _named_craft(r, _typed(entry["sale_horizon"], int)) for r in entry["rows"]
            )
            for scan_at, entry in _entries(raw, "shown_crafts", market).items()
        }
        craft_flips = {
            name: _flip_grade(e) for name, e in _entries(raw, "craft_flips", market).items()
        }
        named = {
            int(scan_at): NamedSet(
                {
                    _typed(i["item_key"], str): float(_typed(i["price"], int | float))
                    for i in entry["items"]
                },
                {
                    (
                        _typed(g["quality"], int),
                        _typed(g["kind"], str),
                        _typed(g["min_level"], int),
                        _typed(g["max_level"], int),
                    ): float(_typed(g["price"], int | float))
                    for g in entry["groups"]
                },
            )
            for scan_at, entry in _entries(raw, "named", market).items()
        }
    except (KeyError, TypeError, AttributeError, ValueError) as e:
        raise GradesError(f"{path}: an entry is malformed ({e!r}); delete it to redo it") from None
    return Frozen(held, grades, shown, flips, named, shown_crafts, craft_flips)


def _flip_grade(entry: dict) -> FlipGrade:
    return FlipGrade(
        _typed(entry["graded_at"], int),
        _typed(entry["units"], int),
        _typed(entry["cost"], int),
        _typed(entry["sold_units"], int),
        float(_typed(entry["gross"], int | float)),
        float(_typed(entry["proceeds"], int | float)),
        float(_typed(entry["open_value"], int | float)),
        tuple(float(_typed(d, int | float)) for d in entry["sale_days"]),
        _optional(entry, "listed_after", int),
        _typed(entry["expired"], int),
        _optional(entry, "crafted_after", int),
    )


def _named_craft(row: dict, sale_horizon: int) -> NamedCraft:
    post_at = row.get("post_at")
    days = row.get("days")
    return NamedCraft(
        _typed(row["item_key"], str),
        _typed(row["recipe_id"], int),
        _typed(row["character"], str),
        _typed(row["units"], int),
        tuple(
            NamedBuy(
                _typed(b["item_key"], str),
                _typed(b["quantity"], int),
                float(_typed(b["max_unit_price"], int | float)),
            )
            for b in row["buys"]
        ),
        None if post_at is None else float(_typed(post_at, int | float)),
        float(_typed(row["profit"], int | float)),
        None if days is None else float(_typed(days, int | float)),
        sale_horizon,
    )


def _optional[T](entry: dict, key: str, kind: type[T]) -> T | None:
    # TOML has no null: a None is written as a missing key.
    return None if key not in entry else _typed(entry[key], kind)


def _named(row: dict, sale_horizon: int) -> Named:
    days = row.get("days")
    return Named(
        _typed(row["item_key"], str),
        _typed(row["units"], int),
        _typed(row["dearest"], int),
        float(_typed(row["post_at"], int | float)),
        float(_typed(row["profit"], int | float)),
        None if days is None else float(_typed(days, int | float)),
        sale_horizon,
        *_risky(row.get("risky", False)),
    )


def freeze_held(path: Path, market: Market, prediction: str, held: Sequence[Held]) -> None:
    """Append a Prediction's held-at-writing units, which may be none."""
    units = ", ".join(
        f"{{ item_key = {_string(h.item_key)}, units = {h.units}, cost = {h.cost} }}" for h in held
    )
    _append(path, "held", market, prediction, f"units = [{units}]\n")


def freeze_grade(path: Path, market: Market, grade: Grade) -> None:
    """Append a Prediction's Grade."""
    _append(
        path,
        "grades",
        market,
        grade.prediction,
        f"graded_at = {grade.graded_at}\n"
        f"proceeds = {float(grade.proceeds)!r}\n"
        f"open_value = {float(grade.open_value)!r}\n"
        f"cost = {grade.cost}\n",
    )


def freeze_shown(
    path: Path, market: Market, scan_at: int, sale_horizon: int, named: Sequence[Named]
) -> None:
    """Append the Flip to Sell rows a Scan named, which may be none."""
    rows = ", ".join(
        f"{{ item_key = {_string(n.item_key)}, units = {n.units}, dearest = {n.dearest}, "
        f"post_at = {float(n.post_at)!r}, profit = {float(n.profit)!r}"
        + ("" if n.days is None else f", days = {float(n.days)!r}")
        + _risky_entry(n)
        + " }"
        for n in named
    )
    body = f"sale_horizon = {sale_horizon}\nrows = [{rows}]\n"
    _append(path, "shown", market, str(scan_at), body)


def freeze_named(path: Path, market: Market, scan_at: int, named: NamedSet) -> None:
    """Append what a Scan named to buy, which may be nothing."""
    items = ", ".join(
        f"{{ item_key = {_string(k)}, price = {float(p)!r} }}" for k, p in named.items.items()
    )
    groups = ", ".join(
        f"{{ quality = {q}, kind = {_string(kind)}, min_level = {lo}, max_level = {hi}, "
        f"price = {float(p)!r} }}"
        for (q, kind, lo, hi), p in named.groups.items()
    )
    _append(path, "named", market, str(scan_at), f"items = [{items}]\ngroups = [{groups}]\n")


def freeze_shown_crafts(
    path: Path, market: Market, scan_at: int, sale_horizon: int, named: Sequence[NamedCraft]
) -> None:
    """Append the Flip to Craft rows a Scan named, which may be none."""
    rows = ", ".join(
        f"{{ item_key = {_string(n.item_key)}, recipe_id = {n.recipe_id}, "
        f"character = {_string(n.character)}, units = {n.units}, buys = ["
        + ", ".join(
            f"{{ item_key = {_string(b.item_key)}, quantity = {b.quantity}, "
            f"max_unit_price = {float(b.max_unit_price)!r} }}"
            for b in n.buys
        )
        + "]"
        + ("" if n.post_at is None else f", post_at = {float(n.post_at)!r}")
        + f", profit = {float(n.profit)!r}"
        + ("" if n.days is None else f", days = {float(n.days)!r}")
        + " }"
        for n in named
    )
    body = f"sale_horizon = {sale_horizon}\nrows = [{rows}]\n"
    _append(path, "shown_crafts", market, str(scan_at), body)


def freeze_flip_grade(path: Path, market: Market, name: str, grade: FlipGrade) -> None:
    """Append a Flip's Grade under its `flip_name`."""
    _append(path, "flips", market, name, _flip_grade_body(grade))


def freeze_craft_flip_grade(path: Path, market: Market, name: str, grade: FlipGrade) -> None:
    """Append a Flip to Craft's Grade under its `craft_flip_name`."""
    _append(path, "craft_flips", market, name, _flip_grade_body(grade))


def _flip_grade_body(grade: FlipGrade) -> str:
    days = ", ".join(repr(float(d)) for d in grade.sale_days)
    return (
        f"graded_at = {grade.graded_at}\n"
        f"units = {grade.units}\n"
        f"cost = {grade.cost}\n"
        f"sold_units = {grade.sold_units}\n"
        f"gross = {float(grade.gross)!r}\n"
        f"proceeds = {float(grade.proceeds)!r}\n"
        f"open_value = {float(grade.open_value)!r}\n"
        f"sale_days = [{days}]\n"
        + ("" if grade.listed_after is None else f"listed_after = {grade.listed_after}\n")
        + f"expired = {grade.expired}\n"
        + ("" if grade.crafted_after is None else f"crafted_after = {grade.crafted_after}\n")
    )


def _load(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        raise GradesError(f"{path}: {e}") from None


def _entries(raw: dict, kind: str, market: Market) -> dict:
    """One kind of entry for one Market: [<kind>.<era>.<realm>.<faction>.<Prediction>]."""
    return raw.get(kind, {}).get(market.era, {}).get(market.realm, {}).get(market.faction, {})


def _append(path: Path, kind: str, market: Market, name: str, body: str) -> None:
    # Read again right before writing: another Brain process may have frozen it since the
    # caller loaded, and a second table of the same name would make the file unreadable.
    if name in _entries(_load(path), kind, market):
        return
    header = ".".join(
        _string(part) for part in (kind, market.era, market.realm, market.faction, name)
    )
    new = not path.exists()
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write((_HEADER if new else "") + f"\n[{header}]\n" + body)


def _string(text: str) -> str:
    # A JSON string is a TOML basic string, as long as it isn't escaped to ASCII (TOML has
    # no surrogate pairs).
    return json.dumps(text, ensure_ascii=False)


def _typed[T](value: object, kind: type[T]) -> T:
    # bool is an int in Python, but never a count of copper or units.
    if not isinstance(value, kind) or isinstance(value, bool):
        raise TypeError(f"{value!r} is not {kind}")
    return value


def _risky_entry(n: Named) -> str:
    """A shown row's risky entry, written only for a Risky row: "noSales" for one for too
    few Sale Events (#224), else true."""
    if n.no_sales:
        return f", risky = {_string(NO_SALES)}"
    if n.risky:
        return ", risky = true"
    return ""


def _risky(value: object) -> tuple[bool, bool]:
    """A shown row's `risky` and `no_sales` from its risky entry: true, or "noSales" for a
    Risky row for too few Sale Events (#224)."""
    if value == NO_SALES:
        return True, True
    return _flag(value), False


def _flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{value!r} is not a bool")
    return value
