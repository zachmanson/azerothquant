"""Notice when the Addon's SavedVariables file has been rewritten and is safe to read.

The client writes the file on `/reload` or logout and may do it in several steps, so a
change is only reported once the file has stopped changing for a while (the settle
time). The Watcher polls file stats instead of using OS change notifications: it is
only a handful of files, and polling works the same on every OS and filesystem.
"""

import os
from dataclasses import dataclass
from pathlib import Path

# What a file looks like from the outside; a rewrite changes at least one of these.
type _Signature = tuple[int, int]  # (mtime in ns, size in bytes)


@dataclass
class _FileState:
    signature: _Signature | None
    changed_at: float
    reported: _Signature | None = None


class Watcher:
    def __init__(self, settle_seconds: float):
        self.settle_seconds = settle_seconds
        self._files: dict[Path, _FileState] = {}

    def poll(self, paths: list[Path], now: float) -> list[Path]:
        """The files that changed since they were last reported and have now settled.

        `now` is a monotonic clock in seconds. A file seen for the first time counts as
        changed, so files already there when watching starts get reported too.
        """
        ready = []
        for path in paths:
            signature = _signature(path)
            state = self._files.get(path)
            if state is None or state.signature != signature:
                reported = state.reported if state else None
                self._files[path] = _FileState(signature, now, reported)
                continue
            if (
                signature is not None
                and signature != state.reported
                and now - state.changed_at >= self.settle_seconds
            ):
                state.reported = signature
                ready.append(path)
        return ready

    def retry(self, path: Path, now: float) -> None:
        """Report `path` again once another settle time has passed, even if unchanged.

        For a file whose import failed for a reason outside the file, such as the
        client still holding it open.
        """
        state = self._files.get(path)
        if state is not None:
            state.reported = None
            state.changed_at = now


def _signature(path: Path) -> _Signature | None:
    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return None
    return (stat.st_mtime_ns, stat.st_size)
