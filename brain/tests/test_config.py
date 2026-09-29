from pathlib import Path

import pytest

from brain.config import ConfigError, Era, load_config

EXAMPLE_CONFIG = Path(__file__).parent.parent / "config.example.toml"


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_maps_each_install_folder_to_its_era(tmp_path):
    config = load_config(
        write_config(
            tmp_path,
            r"""
            [[installs]]
            path = 'C:\WoW\_classic_beta_'
            era = "beta"

            [[installs]]
            path = 'C:\WoW\_classic_'
            era = "live"
            """,
        )
    )

    assert [(i.path, i.era) for i in config.installs] == [
        (Path(r"C:\WoW\_classic_beta_"), Era.BETA),
        (Path(r"C:\WoW\_classic_"), Era.LIVE),
    ]


def test_example_config_loads():
    config = load_config(EXAMPLE_CONFIG)

    assert config.installs


def test_rejects_unknown_era(tmp_path):
    path = write_config(
        tmp_path,
        r"""
        [[installs]]
        path = 'C:\WoW\_classic_ptr_'
        era = "ptr"
        """,
    )

    with pytest.raises(ConfigError, match="ptr"):
        load_config(path)


def test_rejects_the_same_folder_listed_twice(tmp_path):
    # One folder can't belong to two Eras: that would mix their data.
    path = write_config(
        tmp_path,
        r"""
        [[installs]]
        path = 'C:\WoW\_classic_'
        era = "beta"

        [[installs]]
        path = 'C:\WoW\_classic_'
        era = "live"
        """,
    )

    with pytest.raises(ConfigError, match="more than once"):
        load_config(path)


def test_rejects_config_with_no_installs(tmp_path):
    with pytest.raises(ConfigError, match="installs"):
        load_config(write_config(tmp_path, ""))


def test_rejects_install_missing_its_era(tmp_path):
    path = write_config(
        tmp_path,
        r"""
        [[installs]]
        path = 'C:\WoW\_classic_'
        """,
    )

    with pytest.raises(ConfigError, match="era"):
        load_config(path)


def test_rejects_install_missing_its_path(tmp_path):
    path = write_config(
        tmp_path,
        """
        [[installs]]
        era = "beta"
        """,
    )

    with pytest.raises(ConfigError, match="path"):
        load_config(path)


def test_rejects_installs_that_are_not_tables(tmp_path):
    # installs = "x" would otherwise be iterated character by character.
    path = write_config(tmp_path, 'installs = "C:/WoW/_classic_"')

    with pytest.raises(ConfigError, match="must be a list of tables"):
        load_config(path)


INSTALL = r"""
[[installs]]
path = 'C:\WoW\_classic_'
era = "beta"
"""


def test_time_left_buckets_default_to_the_forever_labels(tmp_path):
    config = load_config(write_config(tmp_path, INSTALL))

    # The client's labels are <30m, 30m-2h, 2-12h, >12h (#95), and Forever posts for at most
    # 24 h (#78). The longest time left in each bucket, in seconds.
    assert config.time_left_max_seconds == (30 * 60, 2 * 3600, 12 * 3600, 24 * 3600)


def test_time_left_buckets_can_be_set(tmp_path):
    config = load_config(write_config(tmp_path, "time_left_max_minutes = [1, 2, 3, 4]" + INSTALL))

    assert config.time_left_max_seconds == (60, 120, 180, 240)


@pytest.mark.parametrize("value", ["[30, 120, 720]", "[30, 20, 720, 2880]", "[0, 1, 2, 3]", '"x"'])
def test_rejects_bad_time_left_buckets(tmp_path, value):
    path = write_config(tmp_path, f"time_left_max_minutes = {value}" + INSTALL)

    with pytest.raises(ConfigError, match="time_left_max_minutes"):
        load_config(path)


def test_history_defaults_to_a_file_next_to_the_config(tmp_path):
    config = load_config(write_config(tmp_path, INSTALL))

    assert config.history_path == tmp_path / "history.sqlite"


def test_history_path_can_be_set_relative_to_the_config(tmp_path):
    config = load_config(write_config(tmp_path, "history_path = 'data/h.sqlite'" + INSTALL))

    assert config.history_path == tmp_path / "data" / "h.sqlite"


def test_observation_window_cap_defaults_to_an_hour(tmp_path):
    config = load_config(write_config(tmp_path, INSTALL))

    assert config.observation_window_max_seconds == 3600


def test_observation_window_cap_can_be_set(tmp_path):
    config = load_config(write_config(tmp_path, "observation_window_max_minutes = 45" + INSTALL))

    assert config.observation_window_max_seconds == 45 * 60


@pytest.mark.parametrize("value", ["0", "-5", "1.5", "true", '"60"', "[60]"])
def test_rejects_bad_observation_window_cap(tmp_path, value):
    path = write_config(tmp_path, f"observation_window_max_minutes = {value}" + INSTALL)

    with pytest.raises(ConfigError, match="observation_window_max_minutes"):
        load_config(path)


def test_archive_defaults_to_a_folder_next_to_the_config(tmp_path):
    config = load_config(write_config(tmp_path, INSTALL))

    assert config.archive_dir == tmp_path / "archive"


def test_archive_can_be_set_anywhere(tmp_path):
    elsewhere = tmp_path / "synced" / "aq-archive"
    config = load_config(write_config(tmp_path, f"archive_dir = '{elsewhere}'" + INSTALL))

    assert config.archive_dir == elsewhere


def test_archive_must_be_a_folder_path(tmp_path):
    with pytest.raises(ConfigError, match="archive_dir"):
        load_config(write_config(tmp_path, "archive_dir = 3" + INSTALL))


def test_fair_value_knobs_default_to_the_designed_values(tmp_path):
    config = load_config(write_config(tmp_path, INSTALL))

    assert config.fair_value_slice_share == 0.15
    assert config.fair_value_outlier_share == 0.5
    assert config.probable_sale_max_fair_value_multiple == 1.2


def test_fair_value_knobs_can_be_set(tmp_path):
    text = (
        "fair_value_slice_share = 0.25\n"
        "fair_value_outlier_share = 0\n"
        "probable_sale_max_fair_value_multiple = 1.5\n"
    )
    config = load_config(write_config(tmp_path, text + INSTALL))

    assert config.fair_value_slice_share == 0.25
    assert config.fair_value_outlier_share == 0
    assert config.probable_sale_max_fair_value_multiple == 1.5


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("fair_value_slice_share", "0"),  # the slice would be empty
        ("fair_value_slice_share", "1.5"),
        ("fair_value_slice_share", '"0.15"'),
        ("fair_value_outlier_share", "-0.1"),
        ("fair_value_outlier_share", "1"),  # would leave out everything under the median
        ("fair_value_outlier_share", "true"),
        ("probable_sale_max_fair_value_multiple", "0"),
        ("probable_sale_max_fair_value_multiple", "[1.2]"),
    ],
)
def test_rejects_bad_fair_value_knobs(tmp_path, key, value):
    path = write_config(tmp_path, f"{key} = {value}" + INSTALL)

    with pytest.raises(ConfigError, match=key):
        load_config(path)


def test_sell_rate_range_defaults_to_14_days(tmp_path):
    config = load_config(write_config(tmp_path, INSTALL))

    assert config.sell_rate_range_seconds == 14 * 24 * 3600


def test_sell_rate_range_can_be_set(tmp_path):
    config = load_config(write_config(tmp_path, "sell_rate_days = 7" + INSTALL))

    assert config.sell_rate_range_seconds == 7 * 24 * 3600


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "true", '"14"'])
def test_rejects_bad_sell_rate_range(tmp_path, value):
    path = write_config(tmp_path, f"sell_rate_days = {value}" + INSTALL)

    with pytest.raises(ConfigError, match="sell_rate_days"):
        load_config(path)


def test_decision_engine_knobs_default_to_the_designed_values(tmp_path):
    config = load_config(write_config(tmp_path, INSTALL))

    assert config.ah_cut == 0.05
    assert config.neutral_ah_cut == 0.15
    assert config.sale_horizon_seconds == 7 * 24 * 3600
    assert config.flip_min_margin_share == 0.2
    assert config.flip_min_margin_copper == 100
    assert config.sell_rate_prior_hours_holdings == 3
    assert config.sell_rate_prior_hours_flips == 24
    assert config.sale_size_prior_events_holdings == 1
    assert config.sale_size_prior_events_flips == 5
    assert config.flip_min_sale_events == 3
    assert config.post_undercut_copper == 1
    assert config.craft_min_gain == 0
    assert config.craft_chain_depth == 3
    assert config.shopping_list_rows == 50
    assert config.craft_list_rows == 25
    assert config.roi_hint == 0.2
    assert config.non_stacking_effort_copper == 500
    assert config.ah_deposit_share == 0.6
    assert config.post_duration_hours == 24
    assert config.disenchant_check_min_results == 20
    assert config.buy_under_min_sightings == 1
    assert config.buy_under_window_days == 7


def test_decision_engine_knobs_can_be_set(tmp_path):
    text = (
        "ah_cut = 0.1\n"
        "neutral_ah_cut = 0.25\n"
        "sale_horizon_days = 1.5\n"
        "flip_min_margin_share = 0\n"
        "flip_min_margin_copper = 500\n"
        "sell_rate_prior_hours_holdings = 0\n"
        "sell_rate_prior_hours_flips = 12.5\n"
        "sale_size_prior_events_holdings = 0\n"
        "sale_size_prior_events_flips = 2.5\n"
        "flip_min_sale_events = 5\n"
        "post_undercut_copper = 0\n"
        "craft_min_gain = 50\n"
        "craft_chain_depth = 1\n"
        "shopping_list_rows = 10\n"
        "craft_list_rows = 5\n"
        "roi_hint = 0.5\n"
        "non_stacking_effort_copper = 0\n"
        "ah_deposit_share = 0.15\n"
        "post_duration_hours = 12\n"
        "disenchant_check_min_results = 50\n"
        "buy_under_min_sightings = 3\n"
        "buy_under_window_days = 14\n"
    )
    config = load_config(write_config(tmp_path, text + INSTALL))

    assert config.ah_cut == 0.1
    assert config.neutral_ah_cut == 0.25
    assert config.sale_horizon_seconds == 36 * 3600
    assert config.flip_min_margin_share == 0
    assert config.flip_min_margin_copper == 500
    assert config.sell_rate_prior_hours_holdings == 0
    assert config.sell_rate_prior_hours_flips == 12.5
    assert config.sale_size_prior_events_holdings == 0
    assert config.sale_size_prior_events_flips == 2.5
    assert config.flip_min_sale_events == 5
    assert config.post_undercut_copper == 0
    assert config.craft_min_gain == 50
    assert config.craft_chain_depth == 1
    assert config.shopping_list_rows == 10
    assert config.craft_list_rows == 5
    assert config.roi_hint == 0.5
    assert config.non_stacking_effort_copper == 0
    assert config.ah_deposit_share == 0.15
    assert config.post_duration_hours == 12
    assert config.disenchant_check_min_results == 50
    assert (config.buy_under_min_sightings, config.buy_under_window_days) == (3, 14)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ah_cut", "-0.05"),
        ("ah_cut", "1"),  # a sale would bring in nothing
        ("neutral_ah_cut", '"0.15"'),
        ("sale_horizon_days", "0"),
        ("sale_horizon_days", "true"),
        ("flip_min_margin_share", "-0.2"),
        ("flip_min_margin_copper", "-1"),
        ("flip_min_margin_copper", "1.5"),  # whole copper
        ("sell_rate_prior_hours_holdings", "-1"),
        ("sell_rate_prior_hours_holdings", "false"),
        ("sell_rate_prior_hours_flips", '"24"'),
        ("sell_rate_prior_hours_flips", "-0.5"),
        ("sale_size_prior_events_holdings", "-1"),
        ("sale_size_prior_events_holdings", '"1"'),
        ("sale_size_prior_events_flips", "true"),
        ("sale_size_prior_events_flips", "-0.5"),
        ("flip_min_sale_events", "0"),
        ("flip_min_sale_events", "2.5"),  # whole Sale Events
        ("flip_min_sale_events", "true"),
        ("post_undercut_copper", "-1"),
        ("post_undercut_copper", "0.5"),  # whole copper
        ("post_undercut_copper", "true"),
        ("craft_min_gain", "-1"),
        ("craft_min_gain", '"0"'),
        ("craft_chain_depth", "0"),  # counts the top craft
        ("craft_chain_depth", "2.5"),
        ("craft_chain_depth", "true"),
        ("buy_under_min_sightings", "0"),
        ("buy_under_window_days", "1.5"),
        ("disenchant_check_min_results", "1"),  # an interval needs 2
        ("disenchant_check_min_results", "2.5"),
        ("disenchant_check_min_results", "true"),
        ("shopping_list_rows", "0"),
        ("shopping_list_rows", "2.5"),
        ("craft_list_rows", "0"),
        ("craft_list_rows", "2.5"),
        ("roi_hint", '"0.2"'),
        ("roi_hint", "true"),
        ("roi_hint", "-0.1"),
        ("non_stacking_effort_copper", "-1"),
        ("ah_deposit_share", "-0.1"),
        ("ah_deposit_share", "true"),
        ("post_duration_hours", "0"),
        ("post_duration_hours", '"48"'),
        ("non_stacking_effort_copper", "0.5"),  # whole copper
        ("non_stacking_effort_copper", "true"),
    ],
)
def test_rejects_bad_decision_engine_knobs(tmp_path, key, value):
    path = write_config(tmp_path, f"{key} = {value}" + INSTALL)

    with pytest.raises(ConfigError, match=key):
        load_config(path)


def test_predictions_are_read_from_next_to_the_config(tmp_path):
    config = load_config(write_config(tmp_path, INSTALL))

    assert config.predictions_path == tmp_path / "predictions.toml"
    assert config.grades_path == tmp_path / "grades.toml"


def test_prediction_guards_default_to_the_designed_values(tmp_path):
    config = load_config(write_config(tmp_path, INSTALL))

    assert config.prediction_max_loss_share == 0.10
    assert config.prediction_cap_share == 0.15
    assert config.predictions_cap_share == 0.40


def test_prediction_guards_can_be_set(tmp_path):
    text = "prediction_max_loss_share = 0\nprediction_cap_share = 0.5\npredictions_cap_share = 1\n"
    config = load_config(write_config(tmp_path, text + INSTALL))

    assert config.prediction_max_loss_share == 0
    assert config.prediction_cap_share == 0.5
    assert config.predictions_cap_share == 1


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("prediction_max_loss_share", "-0.1"),
        ("prediction_max_loss_share", "1.5"),  # more than the whole cost can't be lost
        ("prediction_max_loss_share", '"0.1"'),
        ("prediction_cap_share", "-0.15"),
        ("prediction_cap_share", "1.5"),
        ("predictions_cap_share", "true"),
        ("predictions_cap_share", "2"),
    ],
)
def test_rejects_bad_prediction_guards(tmp_path, key, value):
    path = write_config(tmp_path, f"{key} = {value}" + INSTALL)

    with pytest.raises(ConfigError, match=key):
        load_config(path)
