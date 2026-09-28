import pytest

from brain.grades_file import Grade, GradesError, freeze_grade, freeze_held, load_frozen
from brain.lots import Held

# A name that needs escaping in TOML, and one outside ASCII.
QUOTED = 'Linen "spike" \\ Phase 2'
ACCENTED = "Épice de Sombrelune 🌙"


def test_frozen_entries_come_back_as_written(tmp_path):
    path = tmp_path / "grades.toml"
    freeze_held(path, QUOTED, [Held(QUOTED, "2589", 10, 604), Held(QUOTED, "2770", 3, 0)])
    freeze_held(path, ACCENTED, [])
    freeze_grade(path, Grade(QUOTED, 1_790_000_000, 570.0, 564.3, 604))
    freeze_grade(path, Grade(ACCENTED, 1_790_000_001, 0.1 + 0.2, 0, 0))

    frozen = load_frozen(path)

    assert frozen.held == {
        QUOTED: (Held(QUOTED, "2589", 10, 604), Held(QUOTED, "2770", 3, 0)),
        ACCENTED: (),
    }
    assert frozen.grades == {
        QUOTED: Grade(QUOTED, 1_790_000_000, 570.0, 564.3, 604),
        ACCENTED: Grade(ACCENTED, 1_790_000_001, 0.1 + 0.2, 0.0, 0),
    }


def test_nothing_is_frozen_before_the_file_is_written(tmp_path):
    assert load_frozen(tmp_path / "grades.toml").grades == {}
    assert load_frozen(None).held == {}


def test_an_entry_edited_into_nonsense_names_the_file(tmp_path):
    path = tmp_path / "grades.toml"
    path.write_text('[grades."Linen spike"]\ngraded_at = "soon"\n', encoding="utf-8")

    with pytest.raises(GradesError, match="grades.toml"):
        load_frozen(path)
