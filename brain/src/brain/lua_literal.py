"""Write Python data as a Lua file the Addon loads: the reverse of savedvariables.py.

Only literals and tables are written, so the output is data a WoW client can load
from the Addon folder (ADR-0001) and that savedvariables.py can read back.

Lists become sequences (keys 1..n) and dicts become keyed tables, with every key
written in the `[key] =` form so any string (a realm like "Quel'Thalas", an item
name with quotes) is a valid key.
"""

import math
import re

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_INDENT = "  "
# Characters with a short escape; every other control character is written as \ddd.
_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def assignment(name: str, value: object) -> str:
    """`name = <value>` as a Lua chunk, ending in a newline."""
    if not _NAME.match(name):
        raise ValueError(f"not a Lua global name: {name!r}")
    return f"{name} = {_literal(value, 0)}\n"


def _literal(value: object, depth: int) -> str:
    # bool first: it is a subclass of int.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"Lua data can't hold {value!r}")
        return repr(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list | tuple):
        return _table([_literal(v, depth + 1) for v in value], depth)
    if isinstance(value, dict):
        return _table(
            [f"[{_key(k)}] = {_literal(v, depth + 1)}" for k, v in value.items()],
            depth,
        )
    # None included: a Lua table can't hold nil, so leave the key out instead.
    raise ValueError(f"Lua data can't hold {value!r}")


def _key(key: object) -> str:
    if isinstance(key, str) or isinstance(key, int) and not isinstance(key, bool):
        return _literal(key, 0)
    raise ValueError(f"a Lua table key must be a string or an integer, got {key!r}")


def _table(entries: list[str], depth: int) -> str:
    if not entries:
        return "{}"
    inner = _INDENT * (depth + 1)
    lines = "".join(f"{inner}{entry},\n" for entry in entries)
    return "{\n" + lines + _INDENT * depth + "}"


def _string(s: str) -> str:
    """A double-quoted Lua string. Non-ASCII text is written as-is (the file is UTF-8)."""
    out = []
    for c in s:
        if c in _ESCAPES:
            out.append(_ESCAPES[c])
        elif ord(c) < 0x20 or ord(c) == 0x7F:
            # Always three digits, so a digit that follows can't be read as part of it.
            out.append(f"\\{ord(c):03d}")
        else:
            out.append(c)
    return '"' + "".join(out) + '"'
