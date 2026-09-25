"""Brain config: which WoW install folders to read, which Era each one belongs to,
and how long each Auction House time-left bucket can last.

Beta and Live data are never mixed (CONTEXT.md: Era), and the install folder a
SavedVariables file came from is what tells the Brain which Era it is.
"""

import tomllib
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


@dataclass(frozen=True)
class Config:
    installs: tuple[Install, ...]
    # Index 0 is bucket 1. Used to rule out Listing matches that couldn't have lasted
    # the time between two Scans.
    time_left_max_seconds: tuple[int, ...] = tuple(m * 60 for m in DEFAULT_TIME_LEFT_MAX_MINUTES)


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
    return Config(installs=installs, time_left_max_seconds=tuple(m * 60 for m in minutes))


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
