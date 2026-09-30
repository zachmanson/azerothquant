"""The Scan Pool, as the Brain sees it (ADR-0026): what a Scan looks like once stripped
for upload, and the Pool interface the sync step talks to.

Only Scans ever leave the PC, and only stripped: nothing in an uploaded Scan says who took
it or which auctions were theirs.
"""

import copy
import gzip
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from brain.config import Era


class PoolError(Exception):
    """The pool couldn't be reached or refused the request. The sync stops and the next
    cycle tries again."""


class PoolBusy(PoolError):
    """The pool took an upload of this Market from this key in the last 10 minutes. Not a
    failure: that Market's next Scan goes up next cycle."""


@dataclass(frozen=True)
class PoolEntry:
    """One Scan in the pool's index."""

    id: str
    era: Era
    realm: str
    faction: str
    requested_at: int
    # Uploaded with this Brain's key.
    mine: bool


@dataclass(frozen=True)
class PoolPage:
    """What was added to and rolled back from the pool after a cursor, in order."""

    entries: list[PoolEntry]
    rolled_back: list[str]
    cursor: int
    # More after `cursor`: list again from it.
    more: bool


class Pool(Protocol):
    def push(self, era: Era, scan: dict) -> str:
        """Upload a stripped Scan. Returns its pool ID, or the ID already there for its
        Market and requestedAt. Raises PoolBusy when rate limited."""
        ...

    def list_since(self, cursor: int | None) -> PoolPage:
        """The index after `cursor`, or from the start for None."""
        ...

    def fetch(self, pool_id: str) -> dict:
        """The Scan, as uploaded."""
        ...


# Positions of the level and spec fields in an itemString, after the "item:" prefix. They
# belong to the Character who ran the Scan, and the Item Key ignores them already.
_LEVEL = 8
_SPEC = 9


def strip_scan(raw: dict) -> dict:
    """A copy of the Scan with nothing in it that identifies the player: no character, no
    own flag or item name on any row, and no level or spec in any itemString. Every Item
    Key comes out as it was."""
    stripped = copy.deepcopy(raw)
    stripped.pop("character", None)
    listings = stripped.get("listings")
    if isinstance(listings, list):
        for row in listings:
            if not isinstance(row, dict):
                continue
            row.pop("own", None)
            row.pop("name", None)
            if isinstance(row.get("itemString"), str):
                row["itemString"] = _strip_item_string(row["itemString"])
    return stripped


def _strip_item_string(item_string: str) -> str:
    prefix, sep, rest = item_string.partition(":")
    fields = rest.split(":")
    for i in (_LEVEL, _SPEC):
        if i < len(fields):
            fields[i] = ""
    return prefix + sep + ":".join(fields)


class HttpPool:
    """The Pool, over HTTP to the Scan Pool Worker (pool/README.md)."""

    def __init__(self, url: str, key: str, timeout: float = 60):
        self.url = url.rstrip("/")
        self.key = key
        self.timeout = timeout

    def push(self, era: Era, scan: dict) -> str:
        # The Worker never unzips a Scan, so its Market and requestedAt go in headers.
        headers = {
            "Content-Type": "application/gzip",
            "X-Scan-Era": era.value,
            "X-Scan-Realm": scan["realm"],
            "X-Scan-Faction": scan["faction"],
            "X-Scan-Requested-At": str(scan["requestedAt"]),
        }
        body = gzip.compress(json.dumps(scan, ensure_ascii=False).encode("utf-8"))
        answer = self._request("POST", "/scans", body, headers)
        try:
            return str(json.loads(answer)["id"])
        except (ValueError, KeyError, TypeError) as e:
            raise PoolError(f"the pool's answer to an upload has no ID: {e}") from None

    def list_since(self, cursor: int | None) -> PoolPage:
        path = "/scans" if cursor is None else f"/scans?since={cursor}"
        try:
            page = json.loads(self._request("GET", path))
            entries = [
                PoolEntry(
                    id=e["id"],
                    era=Era(e["era"]),
                    realm=e["realm"],
                    faction=e["faction"],
                    requested_at=e["requestedAt"],
                    mine=e["mine"] is True,
                )
                for e in page["entries"]
                # An Era this Brain doesn't know yet can't be imported anyway.
                if e["era"] in {era.value for era in Era}
            ]
            # The Worker sends the cursor as a string.
            cursor = int(page["cursor"])
            return PoolPage(entries, list(page["rolledBack"]), cursor, page["more"] is True)
        except (ValueError, KeyError, TypeError) as e:
            raise PoolError(f"the pool's index isn't in the expected shape: {e}") from None

    def fetch(self, pool_id: str) -> dict:
        body = self._request("GET", f"/scans/{urllib.parse.quote(pool_id, safe='')}")
        try:
            return json.loads(gzip.decompress(body).decode("utf-8"))
        except (OSError, ValueError, EOFError) as e:
            raise PoolError(f"the pool's Scan {pool_id} can't be read: {e}") from None

    def _request(
        self, method: str, path: str, body: bytes | None = None, headers: dict | None = None
    ) -> bytes:
        return _request(self.url, self.key, self.timeout, method, path, body, headers)


class PoolAdmin:
    """The Worker's member keys, with its ADMIN_SECRET (pool/README.md)."""

    def __init__(self, url: str, secret: str, timeout: float = 60):
        self.url = url.rstrip("/")
        self.secret = secret
        self.timeout = timeout

    def add_key(self, name: str) -> str:
        """A new member key for `name`. The Worker shows it only this once."""
        body = json.dumps({"name": name}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        answer = _request(self.url, self.secret, self.timeout, "POST", "/keys", body, headers)
        try:
            return str(json.loads(answer)["key"])
        except (ValueError, KeyError, TypeError) as e:
            raise PoolError(f"the pool's answer to a new key has no key: {e}") from None

    def revoke_key(self, name: str) -> None:
        """Revoke `name`'s key. The pool rolls back all their Scans."""
        path = f"/keys/{urllib.parse.quote(name, safe='')}"
        _request(self.url, self.secret, self.timeout, "DELETE", path)


def _request(
    url: str,
    token: str,
    timeout: float,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict | None = None,
) -> bytes:
    request = urllib.request.Request(
        url + path,
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {token}", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise PoolBusy(f"{method} {path}: rate limited") from None
        raise PoolError(f"{method} {path}: HTTP {e.code} {_reason(e)}") from None
    except (urllib.error.URLError, OSError, UnicodeError) as e:
        # UnicodeError: a header the HTTP library can't send, say a realm name outside
        # Latin-1.
        raise PoolError(f"{method} {path}: {e}") from None


def _reason(error: urllib.error.HTTPError) -> str:
    """The Worker's {"error"} message, if it sent one."""
    try:
        return json.loads(error.read())["error"]
    except (ValueError, KeyError, TypeError, OSError):
        return error.reason or ""
