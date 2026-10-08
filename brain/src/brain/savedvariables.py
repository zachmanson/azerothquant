"""Read the Addon's SavedVariables file: a Lua file of `Name = <table>` assignments.

The file is data only (WoW's serializer writes nothing but literals and tables), so
this is a small parser for Lua literals, not a Lua interpreter. It never runs code:
anything that isn't a literal is an error.

Lua tables come back as a Python list when their keys are exactly 1..n (an empty
table included), and as a dict otherwise.
"""

import re
from typing import Any


class SavedVariablesError(Exception):
    """The file isn't the data-only Lua that WoW writes."""


_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_DECIMAL_ESCAPE = re.compile(r"\d{1,3}")
_ASSIGNMENT = re.compile(r"\s*=(?!=)")
# A run of string characters that need no handling: a Scan's packed rows are one ~2 MB run
# (#144), too slow to read a character at a time.
_PLAIN_RUN = re.compile(r"[^\\\n\"']+")
_SIMPLE_ESCAPES = {
    "n": b"\n",
    "t": b"\t",
    "r": b"\r",
    "a": b"\a",
    "b": b"\b",
    "f": b"\f",
    "v": b"\v",
    "\\": b"\\",
    '"': b'"',
    "'": b"'",
    "\n": b"\n",
}


def parse_savedvariables(text: str) -> dict[str, Any]:
    """Every top-level `Name = value` in the file, by name."""
    return _Parser(text).parse_file()


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0

    # --- file and values ---

    def parse_file(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        self._skip_space()
        while self.pos < len(self.text):
            name = self._name()
            self._expect("=")
            result[name] = self._value()
            self._skip_space()
            if self._peek() == ";":
                self.pos += 1
                self._skip_space()
        return result

    def _value(self) -> Any:
        self._skip_space()
        c = self._peek()
        # Checked first: "" (end of file) is "in" every string below.
        if c == "":
            raise self._error("unexpected end of file")
        if c == "{":
            return self._table()
        if c in "\"'":
            return self._string()
        if c == "-" or c == "." or c.isdigit():
            return self._number()
        match = _NAME.match(self.text, self.pos)
        if match:
            word = match.group()
            literals = {"true": True, "false": False, "nil": None}
            if word in literals:
                self.pos = match.end()
                return literals[word]
        raise self._error("expected a value")

    def _table(self) -> list[Any] | dict[Any, Any]:
        self._expect("{")
        entries: dict[Any, Any] = {}
        next_index = 1
        while True:
            self._skip_space()
            if self._peek() == "}":
                self.pos += 1
                break
            if self._peek() == "[":
                self.pos += 1
                key = self._value()
                self._expect("]")
                self._expect("=")
                entries[key] = self._value()
            elif (match := _NAME.match(self.text, self.pos)) and self._is_keyed_field(match):
                self.pos = match.end()
                self._expect("=")
                entries[match.group()] = self._value()
            else:
                entries[next_index] = self._value()
                next_index += 1
            self._skip_space()
            if self._peek() in (",", ";"):
                self.pos += 1
            elif self._peek() != "}":
                raise self._error("expected ',' or '}' in table")

        if list(sorted(entries, key=_sort_key)) == list(range(1, len(entries) + 1)):
            return [entries[i] for i in range(1, len(entries) + 1)]
        return entries

    def _is_keyed_field(self, name_match: re.Match[str]) -> bool:
        # `name = value` rather than a bare `true`/`nil` etc. used as a sequence entry.
        # Matched in place: slicing off the rest of the text would copy the whole file.
        return _ASSIGNMENT.match(self.text, name_match.end()) is not None

    def _number(self) -> int | float:
        negative = self._peek() == "-"
        if negative:
            self.pos += 1
            self._skip_space()
        match = _NUMBER.match(self.text, self.pos)
        if not match:
            raise self._error("expected a number")
        self.pos = match.end()
        literal = match.group()
        if literal[:2] in ("0x", "0X"):
            number: int | float = int(literal, 16)
        elif any(c in literal for c in ".eE"):
            number = float(literal)
        else:
            number = int(literal)
        return -number if negative else number

    def _string(self) -> str:
        quote = self.text[self.pos]
        # The line is only worked out on error: counting it up front for every string
        # makes parsing quadratic in the file size.
        start = self.pos
        self.pos += 1
        out = bytearray()
        while True:
            if self.pos >= len(self.text):
                raise SavedVariablesError(f"line {self._line(start)}: unterminated string")
            plain = _PLAIN_RUN.match(self.text, self.pos)
            if plain:
                out += plain.group().encode("utf-8")
                self.pos = plain.end()
                continue
            c = self.text[self.pos]
            if c == quote:
                self.pos += 1
                break
            if c == "\n":
                raise self._error("newline inside a string")
            if c != "\\":
                out += c.encode("utf-8")
                self.pos += 1
                continue
            escape = self.text[self.pos + 1 : self.pos + 2]
            if escape in _SIMPLE_ESCAPES:
                out += _SIMPLE_ESCAPES[escape]
                self.pos += 2
            elif escape.isdigit():
                digits = _DECIMAL_ESCAPE.match(self.text, self.pos + 1).group()
                if int(digits) > 255:
                    raise self._error(f"escape \\{digits} is out of range")
                out.append(int(digits))
                self.pos += 1 + len(digits)
            else:
                raise self._error(f"unknown escape '\\{escape}'")
        try:
            return out.decode("utf-8")
        except UnicodeDecodeError:
            raise SavedVariablesError(
                f"line {self._line(start)}: string is not valid UTF-8"
            ) from None

    # --- low-level helpers ---

    def _name(self) -> str:
        self._skip_space()
        match = _NAME.match(self.text, self.pos)
        if not match:
            raise self._error("expected a name")
        self.pos = match.end()
        return match.group()

    def _expect(self, token: str) -> None:
        self._skip_space()
        if not self.text.startswith(token, self.pos):
            raise self._error(f"expected '{token}'")
        self.pos += len(token)

    def _peek(self) -> str:
        return self.text[self.pos : self.pos + 1]

    def _skip_space(self) -> None:
        while self.pos < len(self.text):
            if self.text[self.pos].isspace():
                self.pos += 1
            elif self.text.startswith("--[[", self.pos):
                end = self.text.find("]]", self.pos)
                if end == -1:
                    raise self._error("unterminated block comment")
                self.pos = end + 2
            elif self.text.startswith("--", self.pos):
                end = self.text.find("\n", self.pos)
                self.pos = len(self.text) if end == -1 else end
            else:
                break

    def _line(self, pos: int | None = None) -> int:
        # Scans the text up to `pos`, so only call it on the way to an error.
        return self.text.count("\n", 0, self.pos if pos is None else pos) + 1

    def _error(self, message: str) -> SavedVariablesError:
        found = self.text[self.pos : self.pos + 20] or "end of file"
        return SavedVariablesError(f"line {self._line()}: {message}, found {found!r}")


def _sort_key(key: Any) -> tuple[int, Any]:
    # Keys can mix types; sort numbers first so the 1..n check can compare them.
    if isinstance(key, bool) or not isinstance(key, int | float):
        return (1, str(key))
    return (0, key)
