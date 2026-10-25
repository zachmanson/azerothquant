"""An in-memory Scan Pool for tests, following the Worker's contract in pool/README.md."""

import json

from brain.config import Era
from brain.pool import PoolBusy, PoolEntry, PoolError, PoolPage


class FakePool:
    """The Worker's contract (pool/README.md) in memory. `fail` makes every call raise as a
    network error would, and `fail_fetching` only fetches of those IDs, so a pull can fail
    partway; `busy` Markets answer a push as rate limited."""

    def __init__(self, page_size: int = 2):
        # Small pages by default, so paging gets exercised.
        self.page_size = page_size
        self.scans: dict[str, tuple[Era, dict, str]] = {}  # id -> (era, Scan, uploader)
        # id -> the headers (realm, faction, requestedAt) that differ from the body
        self.header_overrides: dict[str, dict] = {}
        self.events: list[tuple[str, str]] = []  # ("add" | "rollback", id), cursor = index + 1
        self.fail = False
        self.fail_fetching: set[str] = set()
        self.busy: set[tuple[str, str]] = set()
        self.listed_since: list[int | None] = []
        self.fetched: list[str] = []
        self.calls: list[str] = []  # "push", "list" and "fetch", in order

    def upload(
        self, era: Era, raw: dict, uploader: str = "friend", header_overrides: dict | None = None
    ) -> str:
        """`header_overrides` replace the body's realm, faction or requestedAt in the index,
        as an upload whose headers disagree with its body would."""
        pool_id = f"p{len(self.scans) + 1}"
        self.scans[pool_id] = (era, raw, uploader)
        self.header_overrides[pool_id] = header_overrides or {}
        self.events.append(("add", pool_id))
        return pool_id

    def roll_back(self, pool_id: str) -> None:
        self.events.append(("rollback", pool_id))

    def pushed(self) -> list[dict]:
        return [raw for _, raw, uploader in self.scans.values() if uploader == "me"]

    def push(self, era: Era, raw: dict) -> str:
        self.calls.append("push")
        self._maybe_fail()
        if (raw["realm"], raw["faction"]) in self.busy:
            raise PoolBusy("rate limited")
        return self.upload(era, raw, uploader="me")

    def list_since(self, cursor: int | None) -> PoolPage:
        self.calls.append("list")
        self._maybe_fail()
        self.listed_since.append(cursor)
        start = cursor or 0
        page = self.events[start : start + self.page_size]
        gone = {pool_id for kind, pool_id in self.events if kind == "rollback"}
        entries = []
        rolled_back = []
        for kind, pool_id in page:
            if kind == "rollback":
                rolled_back.append(pool_id)
                continue
            # The Worker leaves a rolled-back Scan out of the entries for good.
            if pool_id in gone:
                continue
            era, raw, uploader = self.scans[pool_id]
            headers = {**raw, **self.header_overrides[pool_id]}
            entries.append(
                PoolEntry(
                    id=pool_id,
                    era=era,
                    realm=headers["realm"],
                    faction=headers["faction"],
                    requested_at=headers["requestedAt"],
                    mine=uploader == "me",
                )
            )
        end = start + len(page)
        return PoolPage(entries, rolled_back, cursor=end, more=end < len(self.events))

    def fetch(self, pool_id: str) -> dict:
        self.calls.append("fetch")
        self._maybe_fail()
        if pool_id in self.fail_fetching:
            raise PoolError("connection reset")
        self.fetched.append(pool_id)
        return json.loads(json.dumps(self.scans[pool_id][1]))

    def _maybe_fail(self):
        if self.fail:
            raise PoolError("connection refused")
