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


def test_time_left_buckets_default_to_retail(tmp_path):
    config = load_config(write_config(tmp_path, INSTALL))

    # <30m, 30m-2h, 2-12h, 12-48h, as the longest time left in each bucket (seconds).
    assert config.time_left_max_seconds == (30 * 60, 2 * 3600, 12 * 3600, 48 * 3600)


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
