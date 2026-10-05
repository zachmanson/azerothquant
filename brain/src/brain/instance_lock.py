"""One Brain at a time per data folder (#115), so two watchers never write to the same
history.

The lock is an OS file lock, not just the file being there: the OS drops it when the Brain
exits, crash or not, so a leftover file never blocks the next start. The file also holds
the running Brain's PID, for an update or uninstall to stop it by.
"""

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK_FILE = "brain.lock"

# Windows locks are mandatory: a locked byte can't be read through another handle. So the
# lock is on a byte far past the PID (past any read buffer), and the PID stays readable
# while the Brain runs.
_LOCKED_BYTE = 1 << 40


@contextmanager
def instance_lock(data_dir: Path) -> Iterator[bool]:
    """Hold the data folder's lock for the duration of the block. Yields False, holding
    nothing, when another Brain already holds it."""
    data_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(data_dir / LOCK_FILE, os.O_RDWR | os.O_CREAT)
    try:
        if not _try_lock(fd):
            yield False
            return
        try:
            _write_pid(fd, str(os.getpid()))
            yield True
        finally:
            _write_pid(fd, "")
            _unlock(fd)
    finally:
        os.close(fd)


def _write_pid(fd: int, text: str) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, text.encode("ascii"))


if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        os.lseek(fd, _LOCKED_BYTE, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, _LOCKED_BYTE, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
