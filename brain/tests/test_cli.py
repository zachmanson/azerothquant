import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from brain.archive import ScanArchive
from brain.cli import RebuildError, run_import, run_rebuild, savedvariables_files
from brain.config import Config, Era, Install
from brain.history import Market, listings, open_history
from brain.recommendations import FILE_NAME, GLOBAL_NAME, addon_folder
from brain.savedvariables import parse_savedvariables

FIXTURE = Path(__file__).parent / "fixtures" / "AzerothQuant.lua"
MARKET = Market(realm="Classic Beta PvP", faction="Alliance", era=Era.BETA)


def install_with_savedvariables(root: Path, account: str = "ACCOUNT1") -> Path:
    """A WoW install folder with the fixture as one account's SavedVariables file."""
    folder = root / "WTF" / "Account" / account / "SavedVariables"
    folder.mkdir(parents=True)
    shutil.copy(FIXTURE, folder / "AzerothQuant.lua")
    return folder / "AzerothQuant.lua"


def config_for(tmp_path: Path, *installs: Install) -> Config:
    return Config(
        installs=installs,
        history_path=tmp_path / "history.sqlite",
        archive_dir=tmp_path / "archive",
    )


def test_finds_the_savedvariables_file_of_every_account_in_every_install(tmp_path):
    beta = tmp_path / "_classic_beta_"
    live = tmp_path / "_classic_"
    a = install_with_savedvariables(beta, "ACCOUNT1")
    b = install_with_savedvariables(beta, "ACCOUNT2")
    c = install_with_savedvariables(live, "ACCOUNT1")
    # WoW keeps the previous version as a .bak, which is never imported.
    shutil.copy(FIXTURE, a.with_suffix(".lua.bak"))
    config = config_for(tmp_path, Install(beta, Era.BETA), Install(live, Era.LIVE))

    assert sorted(savedvariables_files(config)) == sorted([a, b, c])


def test_imports_every_savedvariables_file_into_the_history(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))

    results = run_import(config, [file])

    assert [r.path for r in results] == [file]
    assert results[0].error is None
    assert results[0].report.scans_imported > 0
    with closing(open_history(config.history_path)) as conn:
        assert listings(conn, MARKET)


def test_a_half_written_file_is_reported_without_stopping_the_others(tmp_path):
    install = tmp_path / "_classic_beta_"
    good = install_with_savedvariables(install, "ACCOUNT1")
    half = install_with_savedvariables(install, "ACCOUNT2")
    text = half.read_text(encoding="utf-8")
    half.write_text(text[: len(text) // 2], encoding="utf-8")
    config = config_for(tmp_path, Install(install, Era.BETA))

    results = run_import(config, [half, good])

    assert results[0].path == half
    assert results[0].error is not None
    assert results[1].error is None
    assert results[1].report.scans_imported > 0


def test_a_file_outside_every_install_is_reported_as_an_error(tmp_path):
    install = tmp_path / "_classic_beta_"
    stray = install_with_savedvariables(tmp_path / "elsewhere")
    config = config_for(tmp_path, Install(install, Era.BETA))

    [result] = run_import(config, [stray])

    assert "isn't inside any install folder" in result.error


def install_addon(install: Path) -> None:
    addon_folder(Install(install, Era.BETA)).mkdir(parents=True)


def read_recommendations(install: Path) -> dict:
    file = addon_folder(Install(install, Era.BETA)) / FILE_NAME
    return parse_savedvariables(file.read_text(encoding="utf-8"))[GLOBAL_NAME]


def test_import_tells_the_addon_the_latest_scan_imported_for_each_market(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    install_addon(install)
    config = config_for(tmp_path, Install(install, Era.BETA))

    run_import(config, [file])

    # The fixture holds two Alliance Scans on "Classic Beta PvP"; the later one is 1790001200.
    assert read_recommendations(install) == {
        "lastImported": {"Classic Beta PvP": {"Alliance": 1790001200}},
        "recommendations": [],
    }


def test_each_install_only_hears_about_its_own_era(tmp_path):
    beta = tmp_path / "_classic_beta_"
    live = tmp_path / "_classic_"
    file = install_with_savedvariables(beta)
    install_addon(beta)
    install_addon(live)
    config = config_for(tmp_path, Install(beta, Era.BETA), Install(live, Era.LIVE))

    run_import(config, [file])

    assert read_recommendations(beta)["lastImported"] == {
        "Classic Beta PvP": {"Alliance": 1790001200}
    }
    assert read_recommendations(live)["lastImported"] == []


def test_an_install_without_the_addon_gets_no_file(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))

    [result] = run_import(config, [file])

    assert result.error is None
    assert not (install / "Interface").exists()


# --- Scan Archive and rebuild (ADR-0005) ---


def dump(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as conn:
        return list(conn.iterdump())


def test_import_archives_every_scan_in_the_file(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))

    run_import(config, [file])

    archived = sorted(s["requestedAt"] for _, s in ScanArchive(config.archive_dir).scans())
    assert archived == [1790000000, 1790001200]


def test_rebuilding_from_the_archive_gives_the_same_history_as_importing(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    run_import(config, [file])
    imported = dump(config.history_path)

    report = run_rebuild(config)

    assert report.scans_imported == 2
    assert dump(config.history_path) == imported
    assert not list(tmp_path.glob("*.rebuild*"))


def test_rebuild_replaces_a_history_that_has_drifted_from_the_archive(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    run_import(config, [file])
    imported = dump(config.history_path)
    with closing(sqlite3.connect(config.history_path)) as conn, conn:
        conn.execute("DELETE FROM partial_sale")

    run_rebuild(config)

    assert dump(config.history_path) == imported


def test_rebuild_refuses_an_empty_archive_rather_than_wipe_the_history(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    run_import(config, [file])
    imported = dump(config.history_path)
    shutil.rmtree(config.archive_dir)

    with pytest.raises(RebuildError, match="no Scans"):
        run_rebuild(config)

    assert dump(config.history_path) == imported


def test_rebuild_tells_the_addon_what_is_in_the_rebuilt_history(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    install_addon(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    run_import(config, [file])
    (addon_folder(Install(install, Era.BETA)) / FILE_NAME).unlink()

    run_rebuild(config)

    assert read_recommendations(install)["lastImported"] == {
        "Classic Beta PvP": {"Alliance": 1790001200}
    }
