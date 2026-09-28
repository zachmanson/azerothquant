"""grades.toml: Grades and held-at-writing costs, frozen once computed (#66, ADR-0006).

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

from brain.lots import Held

_HEADER = (
    "# Written by the Brain: Grades and held-at-writing costs, frozen once worked out.\n"
    "# It never changes an entry. Delete one by hand to have it worked out again.\n"
)


class GradesError(Exception):
    """grades.toml is malformed."""


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
class Frozen:
    """What grades.toml holds, by Prediction name."""

    held: dict[str, tuple[Held, ...]] = field(default_factory=dict)
    grades: dict[str, Grade] = field(default_factory=dict)


def load_frozen(path: Path | None) -> Frozen:
    """What's frozen in `path`; nothing without a path or before the file is written."""
    if path is None:
        return Frozen()
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        return Frozen()
    except tomllib.TOMLDecodeError as e:
        raise GradesError(f"{path}: {e}") from None
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
            for name, entry in raw.get("held", {}).items()
        }
        grades = {
            name: Grade(
                name,
                _typed(entry["graded_at"], int),
                float(_typed(entry["proceeds"], int | float)),
                float(_typed(entry["open_value"], int | float)),
                _typed(entry["cost"], int),
            )
            for name, entry in raw.get("grades", {}).items()
        }
    except (KeyError, TypeError, AttributeError) as e:
        raise GradesError(f"{path}: an entry is malformed ({e!r}); delete it to redo it") from None
    return Frozen(held, grades)


def freeze_held(path: Path, prediction: str, held: Sequence[Held]) -> None:
    """Append a Prediction's held-at-writing units, which may be none."""
    units = ", ".join(
        f"{{ item_key = {_string(h.item_key)}, units = {h.units}, cost = {h.cost} }}" for h in held
    )
    _append(path, f"[held.{_string(prediction)}]\nunits = [{units}]\n")


def freeze_grade(path: Path, grade: Grade) -> None:
    """Append a Prediction's Grade."""
    _append(
        path,
        f"[grades.{_string(grade.prediction)}]\n"
        f"graded_at = {grade.graded_at}\n"
        f"proceeds = {float(grade.proceeds)!r}\n"
        f"open_value = {float(grade.open_value)!r}\n"
        f"cost = {grade.cost}\n",
    )


def _append(path: Path, table: str) -> None:
    new = not path.exists()
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write((_HEADER if new else "") + "\n" + table)


def _string(text: str) -> str:
    # A JSON string is a TOML basic string, as long as it isn't escaped to ASCII (TOML has
    # no surrogate pairs).
    return json.dumps(text, ensure_ascii=False)


def _typed[T](value: object, kind: type[T]) -> T:
    # bool is an int in Python, but never a count of copper or units.
    if not isinstance(value, kind) or isinstance(value, bool):
        raise TypeError(f"{value!r} is not {kind}")
    return value
