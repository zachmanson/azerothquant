"""predictions.toml: the player's Predictions (ADR-0006).

The player writes them by hand next to config.toml. The Addon doesn't record them, so
they can't be rebuilt from the Archive (ADR-0005) and live in their own file.
"""

import tomllib
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

FILE_NAME = "predictions.toml"

# A Prediction whose Catalyst isn't marked as happened by then Lapses.
DEFAULT_LAPSE = timedelta(weeks=8)


class PredictionsError(Exception):
    """predictions.toml is malformed or contradicts itself."""


@dataclass(frozen=True)
class Prediction:
    name: str
    reason: str
    item_keys: tuple[str, ...]
    catalyst: str
    written: date
    lapse: date
    happened: date | None = None  # when the player marked the Catalyst as happened

    def active_on(self, day: date) -> bool:
        """Whether it stands on `day`: it has been written, its Catalyst hasn't happened and
        it hasn't Lapsed. It starts on its written day and lasts through its lapse date."""
        return (
            self.written <= day
            and (self.happened is None or day < self.happened)
            and day <= self.lapse
        )


def load_predictions(path: Path) -> list[Prediction]:
    """The Predictions in `path`; none if the player hasn't written the file."""
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        return []
    except tomllib.TOMLDecodeError as e:
        raise PredictionsError(f"{path}: {e}") from None

    entries = raw.get("predictions", [])
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise PredictionsError(f"{path}: each Prediction must be a [[predictions]] table")

    predictions = [_parse(path, entry) for entry in entries]
    names: set[str] = set()
    owner: dict[str, str] = {}
    for p in predictions:
        if p.name in names:
            raise PredictionsError(f"{path}: the Prediction {p.name!r} is named twice")
        names.add(p.name)
        for item_key in p.item_keys:
            if item_key in owner:
                raise PredictionsError(
                    f"{path}: Item Key {item_key} is in two Predictions, "
                    f"{owner[item_key]!r} and {p.name!r}"
                )
            owner[item_key] = p.name
    return predictions


def _parse(path: Path, entry: dict) -> Prediction:
    for key in ("name", "reason", "item_keys", "catalyst", "written"):
        if key not in entry:
            raise PredictionsError(f"{path}: a [[predictions]] entry is missing '{key}'")
    name = entry["name"]
    where = f"{path}: Prediction {name!r}"
    for key in ("name", "reason", "catalyst"):
        if not isinstance(entry[key], str) or not entry[key]:
            raise PredictionsError(f"{where}: {key} must be some text, got {entry[key]!r}")
    item_keys = entry["item_keys"]
    if (
        not isinstance(item_keys, list)
        or not item_keys
        or not all(isinstance(k, str) and k for k in item_keys)
    ):
        raise PredictionsError(
            f'{where}: item_keys must be a list of Item Keys in quotes, such as ["2589"], '
            f"got {item_keys!r}"
        )
    written = entry["written"]
    if type(written) is not date:
        raise PredictionsError(
            f"{where}: written must be a date such as 2026-09-26, got {written!r}"
        )
    lapse = entry.get("lapse", written + DEFAULT_LAPSE)
    happened = entry.get("happened")
    for key, value in (("lapse", lapse), ("happened", happened)):
        if value is not None and (type(value) is not date or value < written):
            raise PredictionsError(
                f"{where}: {key} must be a date such as 2026-11-21, on or after written, "
                f"got {value!r}"
            )
    return Prediction(
        name=name,
        reason=entry["reason"],
        item_keys=tuple(item_keys),
        catalyst=entry["catalyst"],
        written=written,
        lapse=lapse,
        happened=happened,
    )
