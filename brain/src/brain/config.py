"""Brain config: which WoW install folders to read, which Era each one belongs to,
and how long each Auction House time-left bucket can last.

Beta and Live data are never mixed (CONTEXT.md: Era), and the install folder a
SavedVariables file came from is what tells the Brain which Era it is.
"""

import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ConfigError(Exception):
    """The config file is missing something or contradicts itself."""


class Era(StrEnum):
    BETA = "beta"
    LIVE = "live"


@dataclass(frozen=True)
class Install:
    path: Path
    era: Era


# Longest time left in each bucket (1 = shortest), in minutes: <30m, 30m-2h, 2-12h, 12-48h.
# These are retail's; still to be verified on the Forever client.
DEFAULT_TIME_LEFT_MAX_MINUTES = (30, 120, 12 * 60, 48 * 60)


# Longest gap between two Scans of a Market that still counts as an Observation Window
# (ADR-0004).
DEFAULT_OBSERVATION_WINDOW_MAX_MINUTES = 60


# Fair Value averages the cheapest this share of a Market's units of an Item Key (#21).
DEFAULT_FAIR_VALUE_SLICE_SHARE = 0.15
# Units in that slice priced under this share of its median are Flips, not the price.
DEFAULT_FAIR_VALUE_OUTLIER_SHARE = 0.5
# A Disappearance priced over this multiple of the Fair Value of the Scan it was last
# seen in is not a Probable Sale.
DEFAULT_PROBABLE_SALE_MAX_FAIR_VALUE_MULTIPLE = 1.2


# Sell Rate counts the Observation Windows that ended in this many days before now (#22).
DEFAULT_SELL_RATE_RANGE_DAYS = 14


DEFAULT_HISTORY_FILE = "history.sqlite"
DEFAULT_ARCHIVE_DIR = "archive"


@dataclass(frozen=True)
class Config:
    installs: tuple[Install, ...]
    # Index 0 is bucket 1. Used to rule out Listing matches that couldn't have lasted
    # the time between two Scans.
    time_left_max_seconds: tuple[int, ...] = tuple(m * 60 for m in DEFAULT_TIME_LEFT_MAX_MINUTES)
    # The SQLite history. A relative path in the file is relative to the config file.
    history_path: Path = Path(DEFAULT_HISTORY_FILE)
    # Only gaps between Scans up to this long count toward Sell Rate (ADR-0004).
    observation_window_max_seconds: int = DEFAULT_OBSERVATION_WINDOW_MAX_MINUTES * 60
    # The Archive folder (ADR-0005). A loaded config always has one; None, for
    # tests and for rebuilding from the archive itself, means Scans aren't archived.
    archive_dir: Path | None = None
    # Fair Value is the average of the cheapest this share of units (always at least one).
    fair_value_slice_share: float = DEFAULT_FAIR_VALUE_SLICE_SHARE
    # ...leaving out units priced under this share of the slice's median.
    fair_value_outlier_share: float = DEFAULT_FAIR_VALUE_OUTLIER_SHARE
    # Probable Sales are priced at most this multiple of Fair Value in their last Scan.
    probable_sale_max_fair_value_multiple: float = DEFAULT_PROBABLE_SALE_MAX_FAIR_VALUE_MULTIPLE
    # Sell Rate counts only the Observation Windows that ended this recently.
    sell_rate_range_seconds: int = DEFAULT_SELL_RATE_RANGE_DAYS * 24 * 3600


def load_config(path: Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    raw_installs = raw.get("installs")
    if not raw_installs:
        raise ConfigError(f"{path}: needs at least one [[installs]] entry")
    if not isinstance(raw_installs, list) or not all(isinstance(e, dict) for e in raw_installs):
        raise ConfigError(f"{path}: [[installs]] must be a list of tables")

    installs = tuple(_parse_install(path, entry) for entry in raw_installs)

    seen: set[Path] = set()
    for install in installs:
        if install.path in seen:
            raise ConfigError(f"{path}: install folder {install.path} is listed more than once")
        seen.add(install.path)

    minutes = _parse_time_left(
        path, raw.get("time_left_max_minutes", DEFAULT_TIME_LEFT_MAX_MINUTES)
    )
    window_minutes = raw.get(
        "observation_window_max_minutes", DEFAULT_OBSERVATION_WINDOW_MAX_MINUTES
    )
    if (
        isinstance(window_minutes, bool)
        or not isinstance(window_minutes, int)
        or window_minutes < 1
    ):
        raise ConfigError(
            f"{path}: observation_window_max_minutes must be a positive whole number of minutes, "
            f"got {window_minutes!r}"
        )
    sell_rate_days = raw.get("sell_rate_days", DEFAULT_SELL_RATE_RANGE_DAYS)
    if (
        isinstance(sell_rate_days, bool)
        or not isinstance(sell_rate_days, int)
        or sell_rate_days < 1
    ):
        raise ConfigError(
            f"{path}: sell_rate_days must be a positive whole number of days, "
            f"got {sell_rate_days!r}"
        )
    history = raw.get("history_path", DEFAULT_HISTORY_FILE)
    if not isinstance(history, str) or not history:
        raise ConfigError(f"{path}: history_path must be a file path, got {history!r}")
    archive = raw.get("archive_dir", DEFAULT_ARCHIVE_DIR)
    if not isinstance(archive, str) or not archive:
        raise ConfigError(f"{path}: archive_dir must be a folder path, got {archive!r}")

    slice_share = _parse_number(
        path,
        raw.get("fair_value_slice_share", DEFAULT_FAIR_VALUE_SLICE_SHARE),
        "fair_value_slice_share",
        lambda x: 0 < x <= 1,
        "above 0 and at most 1",
    )
    outlier_share = _parse_number(
        path,
        raw.get("fair_value_outlier_share", DEFAULT_FAIR_VALUE_OUTLIER_SHARE),
        "fair_value_outlier_share",
        lambda x: 0 <= x < 1,
        "from 0 up to (not including) 1",
    )
    multiple = _parse_number(
        path,
        raw.get(
            "probable_sale_max_fair_value_multiple", DEFAULT_PROBABLE_SALE_MAX_FAIR_VALUE_MULTIPLE
        ),
        "probable_sale_max_fair_value_multiple",
        lambda x: x > 0,
        "above 0",
    )

    return Config(
        installs=installs,
        time_left_max_seconds=tuple(m * 60 for m in minutes),
        history_path=path.parent / history,
        observation_window_max_seconds=window_minutes * 60,
        archive_dir=path.parent / archive,
        fair_value_slice_share=slice_share,
        fair_value_outlier_share=outlier_share,
        probable_sale_max_fair_value_multiple=multiple,
        sell_rate_range_seconds=sell_rate_days * 24 * 3600,
    )


def _parse_number(
    config_path: Path, value: object, key: str, allowed: Callable[[float], bool], wording: str
) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not allowed(value):
        raise ConfigError(f"{config_path}: {key} must be a number {wording}, got {value!r}")
    return value


def _parse_time_left(config_path: Path, value: object) -> tuple[int, ...]:
    expected = len(DEFAULT_TIME_LEFT_MAX_MINUTES)
    if (
        not isinstance(value, list | tuple)
        or len(value) != expected
        or not all(isinstance(m, int) and not isinstance(m, bool) and m > 0 for m in value)
        or list(value) != sorted(set(value))
    ):
        raise ConfigError(
            f"{config_path}: time_left_max_minutes must be {expected} increasing positive "
            f"whole numbers of minutes, got {value!r}"
        )
    return tuple(value)


def _parse_install(config_path: Path, entry: dict) -> Install:
    for field in ("path", "era"):
        if field not in entry:
            raise ConfigError(f"{config_path}: an [[installs]] entry is missing '{field}'")

    try:
        era = Era(entry["era"])
    except ValueError:
        allowed = ", ".join(e.value for e in Era)
        raise ConfigError(
            f"{config_path}: unknown era '{entry['era']}' (expected one of: {allowed})"
        ) from None

    return Install(path=Path(entry["path"]), era=era)
