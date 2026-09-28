import pytest

from brain.config import Era
from brain.grades_file import Grade, GradesError, freeze_grade, freeze_held, load_frozen
from brain.history import Market
from brain.lots import Held

MARKET = Market(realm="Classic Beta PvP", faction="Alliance", era=Era.BETA)
# A name that needs escaping in TOML, and one outside ASCII.
QUOTED = 'Linen "spike" \\ Phase 2'
ACCENTED = "Épice de Sombrelune 🌙"


def test_frozen_entries_come_back_as_written(tmp_path):
    path = tmp_path / "grades.toml"
    freeze_held(path, MARKET, QUOTED, [Held(QUOTED, "2589", 10, 604), Held(QUOTED, "2770", 3, 0)])
    freeze_held(path, MARKET, ACCENTED, [])
    freeze_grade(path, MARKET, Grade(QUOTED, 1_790_000_000, 570.0, 564.3, 604))
    freeze_grade(path, MARKET, Grade(ACCENTED, 1_790_000_001, 0.1 + 0.2, 0, 0))

    frozen = load_frozen(path, MARKET)

    assert frozen.held == {
        QUOTED: (Held(QUOTED, "2589", 10, 604), Held(QUOTED, "2770", 3, 0)),
        ACCENTED: (),
    }
    assert frozen.grades == {
        QUOTED: Grade(QUOTED, 1_790_000_000, 570.0, 564.3, 604),
        ACCENTED: Grade(ACCENTED, 1_790_000_001, 0.1 + 0.2, 0.0, 0),
    }


def test_each_market_has_its_own_entries(tmp_path):
    # A Prediction names Item Keys, not a Market, so each Market holds and grades it apart.
    path = tmp_path / "grades.toml"
    horde = Market(realm="Classic Beta PvP", faction="Horde", era=Era.BETA)
    freeze_held(path, MARKET, "Linen spike", [Held("Linen spike", "2589", 10, 604)])
    freeze_grade(path, MARKET, Grade("Linen spike", 1_790_000_000, 570.0, 564.3, 604))
    freeze_held(path, horde, "Linen spike", [])

    assert load_frozen(path, horde).held == {"Linen spike": ()}
    assert load_frozen(path, horde).grades == {}
    held = (Held("Linen spike", "2589", 10, 604),)
    assert load_frozen(path, MARKET).held == {"Linen spike": held}


def test_an_entry_already_frozen_is_never_written_again(tmp_path):
    # Another Brain process (`brain watch` beside `brain recommend`) may have frozen it
    # since this one loaded the file. A second table of the same name wouldn't load.
    path = tmp_path / "grades.toml"
    freeze_grade(path, MARKET, Grade("Linen spike", 1_790_000_000, 570.0, 564.3, 604))
    freeze_grade(path, MARKET, Grade("Linen spike", 1_790_000_000, 0.0, 0.0, 604))
    freeze_held(path, MARKET, "Linen spike", [])
    freeze_held(path, MARKET, "Linen spike", [Held("Linen spike", "2589", 1, 1)])

    frozen = load_frozen(path, MARKET)

    assert frozen.grades == {"Linen spike": Grade("Linen spike", 1_790_000_000, 570.0, 564.3, 604)}
    assert frozen.held == {"Linen spike": ()}


def test_nothing_is_frozen_before_the_file_is_written(tmp_path):
    assert load_frozen(tmp_path / "grades.toml", MARKET).grades == {}
    assert load_frozen(None, MARKET).held == {}


def test_an_entry_edited_into_nonsense_names_the_file(tmp_path):
    path = tmp_path / "grades.toml"
    path.write_text(
        '[grades.beta."Classic Beta PvP".Alliance."Linen spike"]\ngraded_at = "soon"\n',
        encoding="utf-8",
    )

    with pytest.raises(GradesError, match="grades.toml"):
        load_frozen(path, MARKET)
