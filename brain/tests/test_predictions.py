import re
from datetime import date
from pathlib import Path

import pytest

from brain.predictions import Prediction, PredictionsError, load_predictions


def write(tmp_path, text):
    path = tmp_path / "predictions.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_prediction_lapses_8_weeks_after_it_was_written_by_default(tmp_path):
    path = write(
        tmp_path,
        """
[[predictions]]
name = "BWL mats"
reason = "Fire resistance gear needs them once Blackwing Lair opens"
item_keys = ["7068", "7077"]
catalyst = "Blackwing Lair opens"
written = 2026-09-26
""",
    )

    assert load_predictions(path) == [
        Prediction(
            name="BWL mats",
            reason="Fire resistance gear needs them once Blackwing Lair opens",
            item_keys=("7068", "7077"),
            catalyst="Blackwing Lair opens",
            written=date(2026, 9, 26),
            lapse=date(2026, 11, 21),
        )
    ]


def test_the_player_can_set_a_real_lapse_date_and_mark_the_catalyst_as_happened(tmp_path):
    path = write(
        tmp_path,
        """
[[predictions]]
name = "BWL mats"
reason = "Fire resistance"
item_keys = ["7068"]
catalyst = "Blackwing Lair opens"
written = 2026-09-26
lapse = 2026-10-20
happened = 2026-10-14
""",
    )

    [prediction] = load_predictions(path)
    assert (prediction.lapse, prediction.happened) == (date(2026, 10, 20), date(2026, 10, 14))


def test_no_predictions_file_means_no_predictions(tmp_path):
    assert load_predictions(tmp_path / "predictions.toml") == []


BWL = """
[[predictions]]
name = "BWL mats"
reason = "Fire resistance"
item_keys = ["7068"]
catalyst = "Blackwing Lair opens"
written = 2026-09-26
"""


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        (BWL.replace('catalyst = "Blackwing Lair opens"\n', ""), "missing 'catalyst'"),
        (BWL.replace('name = "BWL mats"', 'name = ""'), "name must be"),
        (BWL.replace('["7068"]', "[7068]"), "item_keys must be"),
        (BWL.replace('["7068"]', "[]"), "item_keys must be"),
        (BWL.replace("written = 2026-09-26", 'written = "2026-09-26"'), "written must be"),
        (BWL + "lapse = 2026-09-25\n", "lapse must be"),
        (BWL + "happened = 2026-09-25\n", "happened must be"),
        (BWL + BWL.replace('item_keys = ["7068"]', 'item_keys = ["2589"]'), "named twice"),
        (BWL + BWL.replace('name = "BWL mats"', 'name = "Other"'), "7068 is in two"),
        ('predictions = "none"', "[[predictions]]"),
        ("[[predictions", "predictions.toml"),
    ],
    ids=[
        "missing field",
        "empty name",
        "item keys not strings",
        "no item keys",
        "written not a date",
        "lapse before written",
        "happened before written",
        "same name twice",
        "item key in two predictions",
        "not a list of tables",
        "not toml",
    ],
)
def test_a_malformed_predictions_file_is_rejected_with_the_reason(tmp_path, text, reason):
    with pytest.raises(PredictionsError, match=re.escape(reason)):
        load_predictions(write(tmp_path, text))


def test_example_predictions_load():
    example = Path(__file__).parent.parent / "predictions.example.toml"

    [prediction] = load_predictions(example)
    assert prediction.name == "BWL mats"
