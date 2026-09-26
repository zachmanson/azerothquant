"""The Archive: everything the Addon recorded, exactly as recorded, kept forever (ADR-0005).

One gzipped JSON file each:
- a Scan at <era>/<realm>-<faction>/<requestedAt>.json.gz
- a Mailbox Read at <era>/mailbox/<realm>/<character>/<readAt>.json.gz

The history database can be rebuilt from these files, so they are the one thing the Brain
stores that can't be recreated. Files are never overwritten.
"""

import gzip
import json
import os
import re
from collections.abc import Iterator
from pathlib import Path

from brain.config import Era

_SUFFIX = ".json.gz"
_MAILBOX = "mailbox"
# Characters Windows doesn't allow in a folder name. Only the folder name is changed;
# the entry inside keeps its realm, faction and character as recorded.
_UNSAFE = re.compile(r'[<>:"/\\|?*]')


class Archive:
    def __init__(self, root: Path):
        self.root = root

    def write(self, era: Era, raw: dict) -> Path:
        """Archive one entry of AzerothQuantDB.scans, unless it's already there.

        `raw` must have a readable realm, faction and requestedAt (the caller has already
        read it as a Scan), since those name the file.
        """
        folder = self.root / era.value / _safe(f"{raw['realm']}-{raw['faction']}")
        return _write(folder / f"{raw['requestedAt']}{_SUFFIX}", {"era": era.value, "scan": raw})

    def write_mailbox_read(self, era: Era, raw: dict) -> Path:
        """Archive one entry of AzerothQuantDB.mailboxReads, unless it's already there.

        `raw` must have a readable realm, character and readAt, since those name the file.
        """
        folder = self.root / era.value / _MAILBOX / _safe(raw["realm"]) / _safe(raw["character"])
        return _write(folder / f"{raw['readAt']}{_SUFFIX}", {"era": era.value, "mailboxRead": raw})

    def scans(self) -> Iterator[tuple[Era, dict]]:
        """Every archived Scan with its Era, in no particular order."""
        # Exactly <era>/<market>/<file>: Mailbox Reads sit deeper, so they never match.
        for path in sorted(self.root.glob(f"*/*/*{_SUFFIX}")):
            entry = _read(path)
            yield Era(entry["era"]), entry["scan"]

    def mailbox_reads(self) -> Iterator[tuple[Era, dict]]:
        """Every archived Mailbox Read with its Era, in no particular order."""
        for path in sorted(self.root.glob(f"*/{_MAILBOX}/*/*/*{_SUFFIX}")):
            entry = _read(path)
            yield Era(entry["era"]), entry["mailboxRead"]


def _safe(name: str) -> str:
    return _UNSAFE.sub("_", name)


def _write(path: Path, entry: dict) -> Path:
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(entry, ensure_ascii=False).encode("utf-8")
    # Written beside the real name and renamed into place, so a crash mid-write never
    # leaves a truncated file that looks archived.
    partial = path.with_name(path.name + ".partial")
    with open(partial, "wb") as f:
        with gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as gz:
            gz.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(partial, path)
    return path


def _read(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)
