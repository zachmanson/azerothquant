"""Shared setup for the probes.

Every probe works on a private copy of data/history.sqlite (and grades.toml) under
probes/_work/, so the Brain's Fair Value cache writes and Grade freezes never touch data/.
The Brain code imported is code/brain/src (identical, modulo CRLF, to the live venv's).
Run with  Z:\\vibing\\azerothquant\\.venv\\Scripts\\python.exe probes\\<probe>.py
"""

import json
import shutil
import sqlite3
import sys
import time
from contextlib import closing
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code" / "brain" / "src"))

from brain.config import load_config  # noqa: E402
from brain.fair_value import FairValueCache  # noqa: E402
from brain.history import character_markets, scan_times  # noqa: E402
from brain.predictions import load_predictions  # noqa: E402

WORK = ROOT / "probes" / "_work"
OUT = ROOT / "probes" / "out"


def setup():
    """(conn, config, market, predictions, cache) on the work copy."""
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    db = WORK / "history.sqlite"
    if not db.exists():
        shutil.copy2(ROOT / "data" / "history.sqlite", db)
    for name in ("grades.toml",):
        if not (WORK / name).exists() and (ROOT / "data" / name).exists():
            shutil.copy2(ROOT / "data" / name, WORK / name)
    (WORK / "fake-wow").mkdir(exist_ok=True)
    cfg = WORK / "config.toml"
    cfg.write_text(
        "flip_min_margin_share = 0.1\n\n[[installs]]\n"
        f"path = '{WORK / 'fake-wow'}'\nera = \"beta\"\n"
    )
    config = load_config(cfg)
    predictions = load_predictions(config.predictions_path)
    conn = sqlite3.connect(db)
    market = next(iter(character_markets(conn)))
    return conn, config, market, predictions, FairValueCache()


def times(conn, market):
    return scan_times(conn, market)


def dump(name, obj):
    def default(o):
        if is_dataclass(o):
            return asdict(o)
        if isinstance(o, (set, frozenset)):
            return sorted(o)
        return str(o)

    path = OUT / name
    path.write_text(json.dumps(obj, default=default, indent=1))
    return path


class Clock:
    def __init__(self):
        self.t = time.monotonic()

    def lap(self, what):
        now = time.monotonic()
        print(f"[{now - self.t:7.1f}s] {what}", flush=True)
        self.t = now


__all__ = ["setup", "times", "dump", "Clock", "replace", "closing", "OUT", "WORK", "ROOT"]
