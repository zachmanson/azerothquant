import subprocess
from pathlib import Path

from brain.config import Era
from brain.history import Market
from brain.recommendations import FILE_NAME, GLOBAL_NAME, render

ADDON = Path(__file__).parents[2] / "addon" / "AzerothQuant"


def _load_in_lua(lua: str, file: Path) -> str:
    """Load the file the way the client does and describe what it defined."""
    script = (
        f"dofile([==[{file}]==]) "
        f"local r = {GLOBAL_NAME} "
        "local out = {} "
        "for realm, byFaction in pairs(r.lastImported) do "
        "  for faction, at in pairs(byFaction) do "
        "    out[#out + 1] = realm .. '/' .. faction .. '=' .. at "
        "  end "
        "end "
        "table.sort(out) "
        "print(type(r.recommendations), table.concat(out, ';'))"
    )
    return subprocess.run(
        [lua, "-e", script], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_the_addon_ships_a_file_that_loads(lua):
    # The client only picks up files that exist when it starts, so the Addon ships a stub
    # for the Brain to overwrite. (With the Addon symlinked into WoW, this reads whatever
    # the Brain last wrote, which must load too.)
    assert _load_in_lua(lua, ADDON / FILE_NAME).startswith("table")


def test_a_real_lua_reads_the_last_imported_times(tmp_path, lua):
    file = tmp_path / FILE_NAME
    file.write_text(
        render(
            {
                Market("Quel'Thalas", "Horde", Era.BETA): 1790000000,
                Market("Quel'Thalas", "Neutral", Era.BETA): 1790000100,
                Market('Say "hi"', "Alliance", Era.BETA): 1790000200,
            }
        ),
        encoding="utf-8",
    )

    assert _load_in_lua(lua, file) == (
        "table\tQuel'Thalas/Horde=1790000000;Quel'Thalas/Neutral=1790000100;"
        'Say "hi"/Alliance=1790000200'
    )
