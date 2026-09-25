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
