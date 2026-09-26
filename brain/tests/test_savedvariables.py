import time

import pytest

from brain.savedvariables import SavedVariablesError, parse_savedvariables


def test_parses_a_file_the_way_wow_writes_it():
    # WoW writes keyed fields as ["key"] = value and tags sequence entries with -- [n].
    text = """
AzerothQuantDB = {
	["nextScanId"] = 2,
	["scans"] = {
		{
			["realm"] = "Classic Beta PvP",
			["droppedRows"] = 0,
			["listings"] = {
				{
					["own"] = true,
					["itemString"] = "item:9768::::::::20:1490::1:1:12743",
					["quantity"] = 20,
					["buyout"] = 1940,
				}, -- [1]
			},
		}, -- [1]
	},
}
"""

    assert parse_savedvariables(text) == {
        "AzerothQuantDB": {
            "nextScanId": 2,
            "scans": [
                {
                    "realm": "Classic Beta PvP",
                    "droppedRows": 0,
                    "listings": [
                        {
                            "own": True,
                            "itemString": "item:9768::::::::20:1490::1:1:12743",
                            "quantity": 20,
                            "buyout": 1940,
                        }
                    ],
                }
            ],
        }
    }


def test_empty_table_is_an_empty_list():
    # An empty Scan (no Listings) is written as {}; it is a sequence with nothing in it.
    assert parse_savedvariables("X = {}") == {"X": []}


def test_parses_scalars():
    text = r"""
a = -12
b = 1.5
c = 1e3
d = 0x1F
e = false
f = nil
g = "say \"hi\"\\ \n\065"
h = { bare = 1, [2] = "two", [1] = "one" }
"""

    assert parse_savedvariables(text) == {
        "a": -12,
        "b": 1.5,
        "c": 1000.0,
        "d": 31,
        "e": False,
        "f": None,
        "g": 'say "hi"\\ \nA',
        "h": {"bare": 1, 2: "two", 1: "one"},
    }


def test_integer_keys_one_to_n_in_any_order_are_a_list():
    assert parse_savedvariables('t = { [2] = "b", [1] = "a" }') == {"t": ["a", "b"]}


def test_skips_comments():
    text = """
-- line comment
--[[ block
comment ]]
t = { 1, -- [1]
      2 } -- trailing
"""

    assert parse_savedvariables(text) == {"t": [1, 2]}


def test_rejects_anything_that_is_not_data():
    with pytest.raises(SavedVariablesError, match="line 1"):
        parse_savedvariables("t = print('x')")


def test_rejects_an_unterminated_table():
    with pytest.raises(SavedVariablesError):
        parse_savedvariables("t = { 1, 2")


def test_an_unterminated_string_reports_the_line_it_started_on():
    with pytest.raises(SavedVariablesError, match="line 2: unterminated string"):
        parse_savedvariables('t = {\n"abc')


def test_parses_a_full_scan_in_linear_time():
    # A real Scan is ~60k Listings (~7 MB). Parsing used to rescan the text before each
    # string, which took minutes on a file that size.
    listing = (
        '\t\t\t\t{\n\t\t\t\t\t["quantity"] = 1,\n'
        '\t\t\t\t\t["itemString"] = "item:20744::::::::20:1490",\n'
        '\t\t\t\t\t["buyout"] = 600,\n\t\t\t\t\t["timeLeft"] = 2,\n\t\t\t\t},\n'
    )
    text = 'AzerothQuantDB = {\n\t["listings"] = {\n' + listing * 10_000 + "\t},\n}\n"

    start = time.perf_counter()
    db = parse_savedvariables(text)["AzerothQuantDB"]

    assert len(db["listings"]) == 10_000
    assert time.perf_counter() - start < 5
