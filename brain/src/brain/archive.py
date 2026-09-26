"""The Scan Archive: every Scan exactly as the Addon recorded it, kept forever (ADR-0005).

One gzipped JSON file per Scan at <era>/<realm>-<faction>/<requestedAt>.json.gz. The
history database can be rebuilt from these files, so they are the one thing the Brain
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
# Characters Windows doesn't allow in a folder name. Only the folder name is changed;
# the Scan inside keeps its realm and faction as recorded.
_UNSAFE = re.compile(r'[<>:"/\\|?*]')


class ScanArchive:
    def __init__(self, root: Path):
        self.root = root

    def write(self, era: Era, raw: dict) -> Path:
        """Archive one entry of AzerothQuantDB.scans, unless it's already there.

        `raw` must have a readable realm, faction and requestedAt (the caller has already
        read it as a Scan), since those name the file.
        """
        folder = self.root / era.value / _UNSAFE.sub("_", f"{raw['realm']}-{raw['faction']}")
        path = folder / f"{raw['requestedAt']}{_SUFFIX}"
        if path.exists():
            return path

        folder.mkdir(parents=True, exist_ok=True)
        data = json.dumps({"era": era.value, "scan": raw}, ensure_ascii=False).encode("utf-8")
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

    def scans(self) -> Iterator[tuple[Era, dict]]:
        """Every archived Scan with its Era, in no particular order."""
        for path in sorted(self.root.glob(f"*/*/*{_SUFFIX}")):
            with gzip.open(path, "rt", encoding="utf-8") as f:
                entry = json.load(f)
            yield Era(entry["era"]), entry["scan"]
