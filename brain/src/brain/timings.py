"""How long each stage of an import took, so the slow part of the Scan to table loop
shows (#131)."""

import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field


@dataclass
class Timings:
    clock: Callable[[], float] = time.monotonic
    # Seconds by stage, in the order each was first timed.
    seconds: dict[str, float] = field(default_factory=dict)
    # Of each stage being timed, innermost last: the seconds of the stages timed inside it.
    _inner: list[float] = field(default_factory=list, repr=False)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Time the block as `name`, adding to any time it already has. A stage timed
        inside another counts only toward itself, so the stages add up to the time they
        cover."""
        start = self.clock()
        self._inner.append(0.0)
        try:
            yield
        finally:
            elapsed = self.clock() - start
            inner = self._inner.pop()
            self.seconds[name] = self.seconds.get(name, 0.0) + elapsed - inner
            if self._inner:
                self._inner[-1] += elapsed


def timed(timings: Timings | None, name: str) -> AbstractContextManager[None]:
    """`timings.stage(name)`, or nothing without Timings."""
    return nullcontext() if timings is None else timings.stage(name)
