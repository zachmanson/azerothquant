"""The Archive: everything the Addon recorded, exactly as recorded, kept forever (ADR-0005).

One gzipped JSON file each:
- a Scan at <era>/<realm>-<faction>/<requestedAt>.json.gz
- a Pooled Scan at <era>/<realm>-<faction>/pool/<requestedAt>.json.gz, as downloaded
  (already stripped), with its pool ID (ADR-0026)
- a Mailbox Read at <era>/mailbox/<realm>/<character>/<readAt>.json.gz
- a Character Read at <era>/character/<realm>/<character>/<readAt>.json.gz

The history database can be rebuilt from these files, so they are the one thing the Brain
stores that can't be recreated. Files are never overwritten. The one thing ever deleted is a
Pooled Scan the pool has rolled back.
"""

import gzip
import json
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from brain.config import Era
from brain.scan import ScanSource

_SUFFIX = ".json.gz"
_MAILBOX = "mailbox"
_CHARACTER = "character"
_POOL = "pool"
# Characters Windows doesn't allow in a folder name. Only the folder name is changed;
# the entry inside keeps its realm, faction and character as recorded.
_UNSAFE = re.compile(r'[<>:"/\\|?*]')


@dataclass(frozen=True)
class ArchivedScan:
    raw: dict
    source: ScanSource = ScanSource.OWN
    # The pool's ID for a Pooled Scan.
    pool_id: str | None = None


class Archive:
    def __init__(self, root: Path):
        self.root = root

    def write(self, era: Era, raw: dict) -> Path:
        """Archive one entry of AzerothQuantDB.scans, unless it's already there.

        `raw` must have a readable realm, faction and requestedAt (the caller has already
        read it as a Scan), since those name the file.
        """
        folder = self._market(era, raw["realm"], raw["faction"])
        return _write(folder / f"{raw['requestedAt']}{_SUFFIX}", {"era": era.value, "scan": raw})

    def write_pooled(self, era: Era, raw: dict, pool_id: str) -> Path:
        """Archive a Pooled Scan, as downloaded, unless it's already there. `raw` as in
        `write`."""
        folder = self._market(era, raw["realm"], raw["faction"]) / _POOL
        return _write(
            folder / f"{raw['requestedAt']}{_SUFFIX}",
            {"era": era.value, "scan": raw, "poolId": pool_id},
        )

    def delete_pooled(self, era: Era, realm: str, faction: str, requested_at: int) -> None:
        """Delete a Pooled Scan the pool rolled back, if it's there."""
        path = self._market(era, realm, faction) / _POOL / f"{requested_at}{_SUFFIX}"
        path.unlink(missing_ok=True)

    def own_scan(self, era: Era, realm: str, faction: str, requested_at: int) -> dict:
        """The player's own Scan as archived. Raises OSError if it isn't there."""
        return _read(self._market(era, realm, faction) / f"{requested_at}{_SUFFIX}")["scan"]

    def write_mailbox_read(self, era: Era, raw: dict) -> Path:
        """Archive one entry of AzerothQuantDB.mailboxReads, unless it's already there.

        `raw` must have a readable realm, character and readAt, since those name the file.
        """
        folder = self.root / era.value / _MAILBOX / _safe(raw["realm"]) / _safe(raw["character"])
        return _write(folder / f"{raw['readAt']}{_SUFFIX}", {"era": era.value, "mailboxRead": raw})

    def write_character_read(self, era: Era, raw: dict) -> Path:
        """Archive one entry of AzerothQuantDB.characterReads, unless it's already there.

        `raw` must have a readable realm, character and readAt, since those name the file.
        """
        folder = self.root / era.value / _CHARACTER / _safe(raw["realm"]) / _safe(raw["character"])
        return _write(
            folder / f"{raw['readAt']}{_SUFFIX}", {"era": era.value, "characterRead": raw}
        )

    def scans(self) -> Iterator[tuple[Era, dict]]:
        """Every archived own Scan with its Era, in no particular order."""
        # Exactly <era>/<market>/<file>: Pooled Scans, Mailbox and Character Reads sit
        # deeper, so they never match.
        for path in sorted(self.root.glob(f"*/*/*{_SUFFIX}")):
            entry = _read(path)
            yield Era(entry["era"]), entry["scan"]

    def pooled_scans(self) -> Iterator[tuple[Era, ArchivedScan]]:
        """Every archived Pooled Scan with its Era, in no particular order."""
        for path in sorted(self.root.glob(f"*/*/{_POOL}/*{_SUFFIX}")):
            entry = _read(path)
            yield Era(entry["era"]), _pooled(entry)

    def market_scans(self, era: Era, realm: str, faction: str, since: int) -> list[ArchivedScan]:
        """The Market's archived Scans, own and Pooled, requested at or after `since`,
        oldest first. At the same requestedAt the own one comes first."""
        folder = self._market(era, realm, faction)
        found = []
        for rank, pattern in enumerate((f"*{_SUFFIX}", f"{_POOL}/*{_SUFFIX}")):
            for path in folder.glob(pattern):
                requested_at = path.name.removesuffix(_SUFFIX)
                if requested_at.isdigit() and int(requested_at) >= since:
                    found.append((int(requested_at), rank, path))
        result = []
        for _, rank, path in sorted(found):
            entry = _read(path)
            result.append(_pooled(entry) if rank else ArchivedScan(entry["scan"]))
        return result

    def mailbox_reads(self) -> Iterator[tuple[Era, dict]]:
        """Every archived Mailbox Read with its Era, in no particular order."""
        for path in sorted(self.root.glob(f"*/{_MAILBOX}/*/*/*{_SUFFIX}")):
            entry = _read(path)
            yield Era(entry["era"]), entry["mailboxRead"]

    def character_reads(self) -> Iterator[tuple[Era, dict]]:
        """Every archived Character Read with its Era, in no particular order."""
        for path in sorted(self.root.glob(f"*/{_CHARACTER}/*/*/*{_SUFFIX}")):
            entry = _read(path)
            yield Era(entry["era"]), entry["characterRead"]

    def _market(self, era: Era, realm: str, faction: str) -> Path:
        return self.root / era.value / _safe(f"{realm}-{faction}")


def _pooled(entry: dict) -> ArchivedScan:
    return ArchivedScan(entry["scan"], ScanSource.POOL, entry["poolId"])


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
