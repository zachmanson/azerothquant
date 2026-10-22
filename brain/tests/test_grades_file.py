import pytest

from brain.config import Era
from brain.grades_file import (
    FlipGrade,
    Grade,
    GradesError,
    Named,
    NamedBuy,
    NamedCraft,
    craft_flip_name,
    flip_name,
    freeze_craft_flip_grade,
    freeze_flip_grade,
    freeze_grade,
    freeze_held,
    freeze_named,
    freeze_shown,
    freeze_shown_crafts,
    load_frozen,
)
from brain.history import Market
from brain.lots import Held, NamedSet

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


def test_frozen_flip_entries_come_back_as_written(tmp_path):
    # #60: what two Scans named, one of them nothing, and two Flip Grades, one without a
    # sale or an own Listing seen. The Ore was a Risky row (#194).
    path = tmp_path / "grades.toml"
    linen = Named("2589", 5, 200, 999.0, 3745.25, 0.1 + 0.2, 10_800)
    ore = Named("2770", 3, 40, 80.5, 60.0, None, 10_800, risky=True)
    sold = FlipGrade(1_790_015_000, 5, 1000, 3, 2997.0, 2847.15, 20.0, (0.03, 0.5), 3000, 1)
    unsold = FlipGrade(1_790_015_001, 3, 120, 0, 0.0, 0.0, 0.1 + 0.2, (), None, 0)
    freeze_shown(path, MARKET, 1_790_003_600, 10_800, [linen, ore])
    freeze_shown(path, MARKET, 1_790_007_200, 10_800, [])
    freeze_flip_grade(path, MARKET, flip_name("2589", 1_790_003_600), sold)
    freeze_flip_grade(path, MARKET, flip_name("2770", 1_790_003_600), unsold)

    frozen = load_frozen(path, MARKET)

    assert frozen.shown == {1_790_003_600: {"2589": linen, "2770": ore}, 1_790_007_200: {}}
    assert frozen.flips == {
        flip_name("2589", 1_790_003_600): sold,
        flip_name("2770", 1_790_003_600): unsold,
    }


def test_frozen_flip_to_craft_entries_come_back_as_written(tmp_path):
    # #114: what two Scans named to craft, one of them nothing, and a Flip to Craft's Grade.
    path = tmp_path / "grades.toml"
    bolt = NamedCraft(
        "2996",
        2963,
        ACCENTED,
        3,
        (NamedBuy("2589", 6, 0.1 + 0.2), NamedBuy("2592", 1, 45.0)),
        999.0,
        3745.25,
        1.5,
        10_800,
    )
    vendored = NamedCraft(
        "2997", 2964, "Kash", 1, (NamedBuy("2589", 2, 40.0),), None, 12.0, None, 10_800
    )
    grade = FlipGrade(1_790_015_000, 3, 400, 1, 999.0, 949.05, 20.0, (0.5,), 3000, 0, 600)
    freeze_shown_crafts(path, MARKET, 1_790_003_600, 10_800, [bolt, vendored])
    freeze_shown_crafts(path, MARKET, 1_790_007_200, 10_800, [])
    freeze_craft_flip_grade(path, MARKET, craft_flip_name(2963, 1_790_003_600), grade)

    frozen = load_frozen(path, MARKET)

    assert frozen.shown_crafts == {1_790_003_600: (bolt, vendored), 1_790_007_200: ()}
    assert frozen.craft_flips == {craft_flip_name(2963, 1_790_003_600): grade}


def test_what_scans_named_to_buy_comes_back_as_written(tmp_path):
    # #55: an Item Key and a Disenchant source group, and a Scan that named nothing.
    path = tmp_path / "grades.toml"
    named = NamedSet({ACCENTED: 45.5, "2589": 0.1 + 0.2}, {(2, "armor", 21, 25): 300.0})
    freeze_named(path, MARKET, 1_790_003_600, named)
    freeze_named(path, MARKET, 1_790_007_200, NamedSet())

    frozen = load_frozen(path, MARKET)

    assert frozen.named == {1_790_003_600: named, 1_790_007_200: NamedSet()}


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
