import shutil
from contextlib import closing
from pathlib import Path

from brain.cli import run_import, savedvariables_files
from brain.config import Config, Era, Install
from brain.history import Market, listings, open_history

FIXTURE = Path(__file__).parent / "fixtures" / "AzerothQuant.lua"
MARKET = Market(realm="Classic Beta PvP", faction="Alliance", era=Era.BETA)


def install_with_savedvariables(root: Path, account: str = "ACCOUNT1") -> Path:
    """A WoW install folder with the fixture as one account's SavedVariables file."""
    folder = root / "WTF" / "Account" / account / "SavedVariables"
    folder.mkdir(parents=True)
    shutil.copy(FIXTURE, folder / "AzerothQuant.lua")
    return folder / "AzerothQuant.lua"


def config_for(tmp_path: Path, *installs: Install) -> Config:
    return Config(installs=installs, history_path=tmp_path / "history.sqlite")


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
