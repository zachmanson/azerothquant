"""Recommendations.lua: what the Brain hands back to the Addon.

The Brain writes it into the Addon's folder in each install, never into
SavedVariables, since the client overwrites SavedVariables on every logout
(ADR-0001). The client reads it on login or `/reload`.

For now it only holds, per Market, when the latest imported Scan was requested.
The Addon then deletes every stored Scan in that Market requested at or before
that time: each one is either imported already or older than an imported one,
which the Brain rejects, so none of them can be of any more use.
"""

import os
import sqlite3
import tempfile
from pathlib import Path

from brain.config import Install
from brain.history import Market, latest_scan_times
from brain.lua_literal import assignment

FILE_NAME = "Recommendations.lua"
GLOBAL_NAME = "AzerothQuantRecommendations"

_HEADER = (
    "-- Written by the azerothquant Brain after every import; edits are overwritten.\n"
    "-- lastImported[realm][faction] is when the latest imported Scan in that Market\n"
    "-- was requested. The Addon deletes stored Scans up to then.\n"
)


def addon_folder(install: Install) -> Path:
    return install.path / "Interface" / "AddOns" / "AzerothQuant"


def render(last_imported: dict[Market, int]) -> str:
    by_realm: dict[str, dict[str, int]] = {}
    for market, requested_at in last_imported.items():
        by_realm.setdefault(market.realm, {})[market.faction] = requested_at
    return _HEADER + assignment(GLOBAL_NAME, {"lastImported": by_realm, "recommendations": []})


def write_recommendations(conn: sqlite3.Connection, install: Install) -> Path | None:
    """Write the install's Recommendations.lua from the history; None if the Addon isn't
    installed there."""
    folder = addon_folder(install)
    if not folder.is_dir():
        return None
    path = folder / FILE_NAME
    text = render(latest_scan_times(conn, install.era))
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
