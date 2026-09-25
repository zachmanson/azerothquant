import os
import shutil

import pytest


@pytest.fixture
def lua() -> str:
    """A Lua 5.1 interpreter, to check the Lua the Brain writes against the real thing.

    Skipped when there isn't one (set LUA or put lua on PATH), except in CI, which
    installs one: there a missing interpreter is a broken setup, not a reason to skip.
    """
    found = os.environ.get("LUA") or shutil.which("lua") or shutil.which("lua5.1")
    if found:
        return found
    if os.environ.get("CI"):
        pytest.fail("no Lua interpreter in CI")
    pytest.skip("no Lua interpreter (set LUA or put lua on PATH)")
