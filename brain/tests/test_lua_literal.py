import subprocess

import pytest

from brain.lua_literal import assignment
from brain.savedvariables import parse_savedvariables

# Names the Brain will write that break naive quoting: realms with apostrophes, item names
# with quotes, and anything a player can type into a name.
AWKWARD_STRINGS = [
    "Quel'Thalas",
    'Tome of "Ancient" Lore',
    "back\\slash",
    "line\nbreak and\r\nCRLF",
    "tab\there",
    "nul\0byte and bell\a",
    "\x01\x1f\x7f",
    "escape then digits \x01" + "23",
    "Mondëjäger, Кровь, 龍",
    "]] and [[ and --[[ not a comment",
    "",
]


def test_awkward_strings_come_back_unchanged():
    data = {"names": AWKWARD_STRINGS, "byName": {s: i for i, s in enumerate(AWKWARD_STRINGS)}}

    text = assignment("AzerothQuantTest", data)

    parsed = parse_savedvariables(text)["AzerothQuantTest"]
    assert parsed["names"] == AWKWARD_STRINGS
    assert parsed["byName"] == {s: i for i, s in enumerate(AWKWARD_STRINGS)}


def test_numbers_booleans_and_nested_tables_come_back_unchanged():
    data = {
        "count": 3,
        "negative": -1790000000,
        "ratio": 0.1,
        "flag": True,
        "off": False,
        "empty": [],
        "nested": {"Alliance": {"Kash": [1, 2, 3]}},
        "byId": {2680: "item", 9768: "other"},
    }

    parsed = parse_savedvariables(assignment("X", data))["X"]

    assert parsed == data


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), object()])
def test_values_lua_cant_hold_are_rejected(value):
    with pytest.raises(ValueError):
        assignment("X", {"bad": value})


def test_a_name_that_isnt_a_lua_identifier_is_rejected():
    with pytest.raises(ValueError):
        assignment("not a name", {})


def test_a_real_lua_reads_the_same_strings(tmp_path, lua):
    # The Python parser above is ours, so also check against real Lua (5.1, as in WoW).
    file = tmp_path / "out.lua"
    file.write_text(assignment("Out", {"names": AWKWARD_STRINGS}), encoding="utf-8")
    # Print each string's bytes as numbers, so the check doesn't depend on console encoding.
    script = (
        f"dofile([==[{file}]==]) "
        "for _, s in ipairs(Out.names) do print(table.concat({s:byte(1, -1)}, ',')) end"
    )

    result = subprocess.run([lua, "-e", script], capture_output=True, text=True, check=True)

    expected = [",".join(str(b) for b in s.encode("utf-8")) for s in AWKWARD_STRINGS]
    assert result.stdout.splitlines() == expected
