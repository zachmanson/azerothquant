import dataclasses
import json
import logging
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

import pytest
from fake_pool import FakePool

from brain.archive import Archive
from brain.cli import (
    LOG_MAX_BYTES,
    RebuildError,
    main,
    pool_syncer,
    run_disenchants,
    run_flips,
    run_import,
    run_rebuild,
    run_recommend,
    run_replay,
    savedvariables_files,
    watch_step,
)
from brain.config import Config, Era, Install
from brain.fair_value import FairValueCache
from brain.grades_file import (
    FlipGrade,
    NamedBuy,
    NamedCraft,
    craft_flip_name,
    freeze_craft_flip_grade,
    freeze_named,
    freeze_shown_crafts,
)
from brain.history import (
    Holding,
    KnownRecipe,
    Market,
    Reagent,
    holdings,
    import_character_reads,
    import_mailbox_reads,
    import_pooled_scans,
    import_scans,
    known_recipes,
    listings,
    merchant_costs,
    open_history,
    outcomes,
    pooled_gold,
    scan_times,
    vendor_prices,
)
from brain.instance_lock import instance_lock
from brain.lots import NamedSet
from brain.pool import PoolError, strip_scan
from brain.pool_sync import PoolSyncer, pull, push
from brain.predictions import Prediction
from brain.recommend import grades
from brain.recommendations import FILE_NAME, GLOBAL_NAME, addon_folder
from brain.savedvariables import parse_savedvariables
from brain.watch import Watcher

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


def test_watch_logs_how_long_an_import_took(tmp_path, caplog):
    # From when the file is noticed settled to when Recommendations.lua is written, so the
    # Addon's RELOAD_READY_AFTER can be tuned by it (#71).
    install_with_savedvariables(tmp_path / "wow")
    config = config_for(tmp_path, Install(tmp_path / "wow", Era.BETA))
    watcher = Watcher(settle_seconds=0)
    caplog.set_level(logging.INFO)
    readings = iter([100.0, 110.0])
    clock = lambda: next(readings, 114.2)  # noqa: E731  noticed at 110, done by 114.2

    watch_step(config, watcher, clock)  # sees the file for the first time
    watch_step(config, watcher, clock)  # it has settled: import

    assert "Import took 4.2s" in caplog.text


IMPORT_STAGES = [
    "SavedVariables",
    "Archive",
    "history ingest",
    "Fair Values",
    "Decision Engine",
    "Recommendations.lua",
]


def logged_stages(text: str) -> tuple[dict[str, float], int]:
    """The stages of the `Import stages` line in `text`, in order, and the Scans in the
    history it gives."""
    [line] = re.findall(r"Import stages: (.*)", text)
    stages, scans = line.split("; ")[0], line.split("; ")[-1]
    named = dict(stage.rsplit(" ", 1) for stage in stages.split(", "))
    return {name: float(s.removesuffix("s")) for name, s in named.items()}, int(scans.split()[0])


def test_watch_logs_how_long_each_stage_of_an_import_took(tmp_path, caplog):
    # Where the Import took time went, so the slow part of the Scan to table loop shows (#131).
    install_with_savedvariables(tmp_path / "wow")
    install_addon(tmp_path / "wow")
    config = config_for(tmp_path, Install(tmp_path / "wow", Era.BETA))
    watcher = Watcher(settle_seconds=0)
    caplog.set_level(logging.INFO)
    ticks = iter(range(1000))
    clock = lambda: float(next(ticks))  # noqa: E731  every reading a second on

    watch_step(config, watcher, clock)  # sees the file for the first time
    watch_step(config, watcher, clock)  # it has settled: import

    stages, scans = logged_stages(caplog.text)
    assert list(stages) == IMPORT_STAGES
    assert all(seconds > 0 for seconds in stages.values())
    [took] = re.findall(r"Import took (\d+\.\d)s", caplog.text)
    assert sum(stages.values()) <= float(took)
    assert scans == 2  # the fixture's


def test_import_logs_how_long_each_stage_took(tmp_path, monkeypatch, caplog):
    install_with_savedvariables(tmp_path / "wow")
    config = config_for(tmp_path, Install(tmp_path / "wow", Era.BETA))
    monkeypatch.setattr("brain.cli.load_config", lambda path: config)
    caplog.set_level(logging.INFO)

    assert main(["--config", str(tmp_path / "config.toml"), "import"]) == 0

    stages, scans = logged_stages(caplog.text)
    assert list(stages) == IMPORT_STAGES
    assert scans == 2


def test_watch_logs_no_stages_when_every_file_failed(tmp_path, caplog):
    file = install_with_savedvariables(tmp_path / "wow")
    file.write_text("AzerothQuantDB = {", encoding="utf-8")  # half written
    config = config_for(tmp_path, Install(tmp_path / "wow", Era.BETA))
    watcher = Watcher(settle_seconds=0)
    caplog.set_level(logging.INFO)

    watch_step(config, watcher)  # sees the file for the first time
    watch_step(config, watcher)  # it has settled: import, which fails

    assert "Couldn't import" in caplog.text
    assert "Import stages" not in caplog.text


def test_watch_keeps_its_fair_value_cache_from_one_pass_to_the_next(tmp_path, monkeypatch):
    # A past Scan's Fair Values are computed once per watcher, not once per pass (#105).
    install_with_savedvariables(tmp_path / "wow")
    config = config_for(tmp_path, Install(tmp_path / "wow", Era.BETA))
    watcher = Watcher(settle_seconds=0)
    cache = FairValueCache()
    passed = []

    def recommend(conn, config, predictions, fair_value_cache=None):
        passed.append(fair_value_cache)
        return []

    monkeypatch.setattr("brain.cli.recommend", recommend)

    watch_step(config, watcher, fair_value_cache=cache)  # sees the file for the first time
    watch_step(config, watcher, fair_value_cache=cache)  # it has settled: import

    assert passed == [cache]


FRIEND_SCAN_AT = 1_790_000_600  # between the fixture's two Scans


def _watching_with_a_pool(tmp_path):
    install_with_savedvariables(tmp_path / "wow")
    config = config_for(tmp_path, Install(tmp_path / "wow", Era.BETA))
    pool = FakePool()
    fixture = parse_savedvariables(FIXTURE.read_text(encoding="utf-8"))["AzerothQuantDB"]
    friend = strip_scan({**fixture["scans"][0], "requestedAt": FRIEND_SCAN_AT})
    pool.upload(Era.BETA, friend)
    return config, pool


def test_watch_pulls_the_pool_before_an_import_and_pushes_right_after(tmp_path):
    config, pool = _watching_with_a_pool(tmp_path)
    syncer = PoolSyncer(config, pool, clock=lambda: 0.0, now=lambda: FRIEND_SCAN_AT + 3600)
    watcher = Watcher(settle_seconds=0)

    watch_step(config, watcher, pool_sync=syncer)  # sees the file for the first time: sync
    watch_step(config, watcher, pool_sync=syncer)  # it has settled: pull, import, push

    assert pool.calls == ["list", "fetch", "list", "push", "push"]
    with closing(open_history(config.history_path)) as conn:
        assert scan_times(conn, MARKET) == [1790000000, FRIEND_SCAN_AT, 1790001200]


def test_watch_times_the_pool_sync_before_and_after_an_import(tmp_path, caplog):
    config, pool = _watching_with_a_pool(tmp_path)
    syncer = PoolSyncer(config, pool, clock=lambda: 0.0, now=lambda: FRIEND_SCAN_AT + 3600)
    watcher = Watcher(settle_seconds=0)
    caplog.set_level(logging.INFO)
    ticks = iter(range(1000))
    clock = lambda: float(next(ticks))  # noqa: E731  every reading a second on

    watch_step(config, watcher, clock, pool_sync=syncer)
    watch_step(config, watcher, clock, pool_sync=syncer)

    stages, scans = logged_stages(caplog.text)
    assert list(stages) == ["pool pull", *IMPORT_STAGES]
    [took] = re.findall(r"Import took (\d+\.\d)s", caplog.text)
    assert sum(stages.values()) <= float(took)
    # The push comes after the total, so it's named apart from the stages in it.
    assert re.search(r"; pool push \d+\.\ds after; ", caplog.text)
    assert scans == 3  # the fixture's two and the friend's


def test_watch_pulls_every_pool_sync_minutes_and_retries_a_failed_push(tmp_path):
    config, pool = _watching_with_a_pool(tmp_path)
    run_import(config, savedvariables_files(config))
    now = [0.0]
    syncer = PoolSyncer(config, pool, clock=lambda: now[0], now=lambda: FRIEND_SCAN_AT + 3600)
    watcher = Watcher(settle_seconds=3600)  # the file never settles here
    pool.fail = True
    watch_step(config, watcher, lambda: now[0], pool_sync=syncer)
    pool.fail = False
    pool.calls.clear()

    now[0] = config.pool_sync_seconds - 1
    watch_step(config, watcher, lambda: now[0], pool_sync=syncer)
    assert pool.calls == []
    now[0] = config.pool_sync_seconds
    watch_step(config, watcher, lambda: now[0], pool_sync=syncer)
    # The two just pushed are in the index too, so it takes two pages.
    assert pool.calls == ["push", "push", "list", "fetch", "list"]


def test_watch_imports_even_when_the_pool_is_down(tmp_path, caplog):
    config, pool = _watching_with_a_pool(tmp_path)
    pool.fail = True
    syncer = PoolSyncer(config, pool, clock=lambda: 0.0, now=lambda: FRIEND_SCAN_AT)
    watcher = Watcher(settle_seconds=0)

    watch_step(config, watcher, pool_sync=syncer)
    watch_step(config, watcher, pool_sync=syncer)

    assert "Couldn't pull from the Scan Pool" in caplog.text
    with closing(open_history(config.history_path)) as conn:
        assert scan_times(conn, MARKET) == [1790000000, 1790001200]


def test_the_addon_hears_the_pool_is_down_until_a_sync_works_again(tmp_path):
    # A guildie never sees the log, so the problem rides along in Recommendations (#115).
    config, pool = _watching_with_a_pool(tmp_path)
    install_addon(tmp_path / "wow")
    pool.fail = True
    syncer = PoolSyncer(config, pool, clock=lambda: 0.0, now=lambda: FRIEND_SCAN_AT)
    watcher = Watcher(settle_seconds=0)

    watch_step(config, watcher, pool_sync=syncer)
    watch_step(config, watcher, pool_sync=syncer)

    assert read_recommendations(tmp_path / "wow")["brain"]["problem"] == (
        "Couldn't reach the guild scan server. Using your own Scans for now."
    )

    pool.fail = False
    [file] = savedvariables_files(config)
    file.write_text(file.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    watch_step(config, watcher, pool_sync=syncer)  # sees the change
    watch_step(config, watcher, pool_sync=syncer)  # it has settled: pull, import

    assert "problem" not in read_recommendations(tmp_path / "wow")["brain"]


def test_watch_logs_what_it_pushed_pulled_rejected_and_rematched(tmp_path, caplog):
    config, pool = _watching_with_a_pool(tmp_path)
    run_import(config, savedvariables_files(config))
    caplog.set_level(logging.INFO)
    syncer = PoolSyncer(config, pool, clock=lambda: 0.0, now=lambda: FRIEND_SCAN_AT + 3600)

    syncer.sync()

    assert "Scan Pool: pushed 2, pulled 1, rejected 0, re-matched 1" in caplog.text


def test_with_no_pool_key_nothing_leaves_the_pc(tmp_path, monkeypatch, caplog):
    def no_network(*args, **kwargs):
        raise AssertionError("a network call with the pool off")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    install_with_savedvariables(tmp_path / "wow")
    config = config_for(tmp_path, Install(tmp_path / "wow", Era.BETA))
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        f"[[installs]]\npath = '{tmp_path / 'wow'}'\nera = 'beta'\n", encoding="utf-8"
    )

    assert pool_syncer(config) is None
    assert main(["--config", str(config_file), "pool", "push"]) == 1
    assert main(["--config", str(config_file), "pool", "pull"]) == 1
    assert "pool_url and pool_key" in caplog.text


def test_pool_commands_sync_by_hand(tmp_path, monkeypatch):
    config, pool = _watching_with_a_pool(tmp_path)
    run_import(config, savedvariables_files(config))
    monkeypatch.setattr("brain.cli.load_config", lambda path: config)
    monkeypatch.setattr("brain.cli.make_pool", lambda config: pool)

    assert main(["--config", str(tmp_path / "config.toml"), "pool", "push"]) == 0
    assert (
        main(["--config", str(tmp_path / "config.toml"), "pool", "pull", "--since", "2026-09-01"])
        == 0
    )

    assert len(pool.pushed()) == 2
    with closing(open_history(config.history_path)) as conn:
        assert FRIEND_SCAN_AT in scan_times(conn, MARKET)


def test_a_watcher_that_crashes_tells_the_addon_before_it_exits(tmp_path, monkeypatch):
    install_with_savedvariables(tmp_path / "wow")
    install_addon(tmp_path / "wow")
    config = config_for(tmp_path, Install(tmp_path / "wow", Era.BETA))
    monkeypatch.setattr("brain.cli.load_config", lambda path: config)

    def crash(*args, **kwargs):
        raise RuntimeError("a bug outside the per-pass guard")

    monkeypatch.setattr("brain.cli.watch_step", crash)

    assert main(["--config", str(tmp_path / "config.toml"), "watch"]) == 1
    assert read_recommendations(tmp_path / "wow")["brain"]["problem"] == (
        "The Brain stopped after an error. Start it again from the Start menu."
    )


class _FakeAdmin:
    """The Worker's /keys endpoints: bob's name is taken, and only bob has a key."""

    revoked: list[str] = []

    def __init__(self, url, secret):
        self.url, self.secret = url, secret

    def add_key(self, name):
        if name == "bob":
            raise PoolError("POST /keys: HTTP 409 name already taken")
        return f"key-for-{name}-from-{self.url}-with-{self.secret}"

    def revoke_key(self, name):
        if name != "bob":
            raise PoolError(f"DELETE /keys/{name}: HTTP 404 no such key")
        self.revoked.append(name)


def _as_pool_admin(tmp_path, monkeypatch, **pool_settings):
    config = dataclasses.replace(config_for(tmp_path), **pool_settings)
    monkeypatch.setattr("brain.cli.load_config", lambda path: config)
    monkeypatch.setattr("brain.cli.PoolAdmin", _FakeAdmin)
    _FakeAdmin.revoked = []


def test_pool_key_add_prints_the_new_member_s_key(tmp_path, monkeypatch, capsys):
    _as_pool_admin(
        tmp_path, monkeypatch, pool_url="https://pool", pool_key="k", pool_admin_secret="s3"
    )

    assert main(["--config", str(tmp_path / "config.toml"), "pool", "key", "add", "alice"]) == 0

    assert capsys.readouterr().out.strip() == "key-for-alice-from-https://pool-with-s3"


def test_pool_key_revoke_revokes_by_name(tmp_path, monkeypatch):
    _as_pool_admin(
        tmp_path, monkeypatch, pool_url="https://pool", pool_key="k", pool_admin_secret="s3"
    )

    assert main(["--config", str(tmp_path / "config.toml"), "pool", "key", "revoke", "bob"]) == 0

    assert _FakeAdmin.revoked == ["bob"]


def test_a_refused_key_command_fails_with_the_worker_s_reason(tmp_path, monkeypatch, caplog):
    _as_pool_admin(
        tmp_path, monkeypatch, pool_url="https://pool", pool_key="k", pool_admin_secret="s3"
    )

    assert main(["--config", str(tmp_path / "config.toml"), "pool", "key", "add", "bob"]) == 1
    assert main(["--config", str(tmp_path / "config.toml"), "pool", "key", "revoke", "carol"]) == 1

    assert "name already taken" in caplog.text
    assert "no such key" in caplog.text


@pytest.mark.parametrize(
    "settings",
    [{"pool_url": "https://pool", "pool_key": "k"}, {"pool_admin_secret": "s3"}],
    ids=["no admin secret", "no pool url"],
)
def test_the_key_commands_fail_clearly_without_the_admin_secret_and_url(
    tmp_path, monkeypatch, caplog, capsys, settings
):
    _as_pool_admin(tmp_path, monkeypatch, **settings)
    missing = "pool_admin_secret" if "pool_url" in settings else "pool_url"

    assert main(["--config", str(tmp_path / "config.toml"), "pool", "key", "add", "alice"]) == 1
    assert main(["--config", str(tmp_path / "config.toml"), "pool", "key", "revoke", "bob"]) == 1

    assert capsys.readouterr().out == ""
    assert missing in caplog.text


def test_import_tells_the_addon_the_latest_scan_imported_for_each_market(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    install_addon(install)
    config = config_for(tmp_path, Install(install, Era.BETA))

    run_import(config, [file])

    # The fixture holds two Alliance Scans on "Classic Beta PvP"; the later one is 1790001200.
    # Its two Mailbox Reads are Kash-Patel's; the later one is 1790001800.
    # So are its two Character Reads; the later one is 1790002000.
    written = read_recommendations(install)
    assert written["lastImported"] == {"Classic Beta PvP": {"Alliance": 1790001200}}
    assert written["lastMailboxRead"] == {"Classic Beta PvP": {"Kash-Patel": 1790001800}}
    assert written["lastCharacterRead"] == {"Classic Beta PvP": {"Kash-Patel": 1790002000}}


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
    assert read_recommendations(beta)["lastMailboxRead"] == {
        "Classic Beta PvP": {"Kash-Patel": 1790001800}
    }
    assert read_recommendations(live)["lastMailboxRead"] == []
    assert read_recommendations(live)["lastCharacterRead"] == []


def test_import_hands_the_addon_each_markets_recommendations_for_its_own_era(tmp_path):
    beta = tmp_path / "_classic_beta_"
    live = tmp_path / "_classic_"
    file = install_with_savedvariables(beta)
    install_addon(beta)
    install_addon(live)
    config = config_for(tmp_path, Install(beta, Era.BETA), Install(live, Era.LIVE))

    run_import(config, [file])

    # Valued at the later Scan, with the gold of Kash-Patel's latest Character Read.
    market = read_recommendations(beta)["recommendations"]["Classic Beta PvP"]["Alliance"]
    assert market["asOf"] == 1790001200
    assert market["gold"] == 1200000
    assert "2589" in [row["itemKey"] for row in market["holdings"]]
    assert read_recommendations(live)["recommendations"] == []


def test_a_broken_predictions_file_still_tells_the_addon_what_was_imported(tmp_path, caplog):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    install_addon(install)
    predictions = tmp_path / "predictions.toml"
    predictions.write_text("[[predictions]", encoding="utf-8")
    config = dataclasses.replace(
        config_for(tmp_path, Install(install, Era.BETA)), predictions_path=predictions
    )

    run_import(config, [file])

    # Pruning SavedVariables mustn't wait on a typo in the Predictions (#10).
    written = read_recommendations(install)
    assert written["lastImported"] == {"Classic Beta PvP": {"Alliance": 1790001200}}
    assert written["recommendations"] == []
    assert "predictions.toml" in caplog.text
    assert written["brain"]["problem"] == "Something went wrong making your recommendations."


def test_a_failed_decision_engine_joins_the_pool_problem_in_one_line(tmp_path, monkeypatch):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    install_addon(install)
    config = config_for(tmp_path, Install(install, Era.BETA))

    def broken(*args, **kwargs):
        raise RuntimeError("a Decision Engine bug")

    monkeypatch.setattr("brain.cli.recommend", broken)
    run_import(config, [file], problem="Couldn't reach the pool.")

    assert read_recommendations(install)["brain"]["problem"] == (
        "Couldn't reach the pool. Something went wrong making your recommendations."
    )


def test_an_install_without_the_addon_gets_no_file(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))

    [result] = run_import(config, [file])

    assert result.error is None
    assert not (install / "Interface").exists()


# --- Archive and rebuild (ADR-0005) ---


def dump(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as conn:
        return list(conn.iterdump())


def test_import_archives_every_scan_in_the_file(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))

    run_import(config, [file])

    archived = sorted(s["requestedAt"] for _, s in Archive(config.archive_dir).scans())
    assert archived == [1790000000, 1790001200]


def test_import_archives_every_mailbox_read_in_the_file_verbatim(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    saved = parse_savedvariables(file.read_text(encoding="utf-8"))["AzerothQuantDB"]

    results = run_import(config, [file])

    assert results[0].report.mailbox_reads_imported == 2
    archived = sorted(Archive(config.archive_dir).mailbox_reads(), key=lambda r: r[1]["readAt"])
    assert archived == [(Era.BETA, raw) for raw in saved["mailboxReads"]]
    # Kept apart from the Scans.
    assert len(list(Archive(config.archive_dir).scans())) == 2


def test_import_archives_every_character_read_in_the_file_verbatim(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    saved = parse_savedvariables(file.read_text(encoding="utf-8"))["AzerothQuantDB"]

    results = run_import(config, [file])

    assert results[0].report.character_reads_imported == 2
    archived = sorted(Archive(config.archive_dir).character_reads(), key=lambda r: r[1]["readAt"])
    # As JSON holds it: the vendorPrices keys become strings, which is all that changes.
    as_json = json.loads(json.dumps(saved["characterReads"]))
    assert archived == [(Era.BETA, raw) for raw in as_json]
    # Kept apart from the Scans and Mailbox Reads.
    assert len(list(Archive(config.archive_dir).scans())) == 2
    assert len(list(Archive(config.archive_dir).mailbox_reads())) == 2
    with closing(open_history(config.history_path)) as conn:
        # Bags from the later Read; the bank from the earlier one, the only one with a bank.
        assert holdings(conn, Era.BETA, "Classic Beta PvP", "Kash-Patel") == {
            "2589": Holding(bags=12, bank=40),
        }
        assert pooled_gold(conn, Era.BETA, "Classic Beta PvP", "Alliance") == 1200000


def test_rebuilding_from_the_archive_gives_the_same_history_as_importing(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    run_import(config, [file])
    imported = dump(config.history_path)

    report = run_rebuild(config)

    assert report.scans_imported == 2
    assert report.outcomes_found > 0
    assert report.character_reads_imported == 2
    assert dump(config.history_path) == imported
    with closing(open_history(config.history_path)) as conn:
        assert outcomes(conn, MARKET)
        # The fixture's Scans are from before #17: its own Listing has no name.
        assert [entry.item_name for entry in listings(conn, MARKET) if entry.own] == [None]
    assert not list(tmp_path.glob("*.rebuild*"))


def test_grades_come_back_the_same_from_the_archive(tmp_path):
    # Lots aren't stored (ADR-0007), so what a Prediction is graded on must be rebuilt from
    # the Archive too: here the 52 Linen held when it was written, after the fixture's Reads.
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    linen = Prediction(
        name="Linen spike",
        reason="Tailoring quests",
        item_keys=("2589",),
        catalyst="Phase 2",
        written=date(2026, 9, 22),
        lapse=date(2026, 11, 17),
        happened=date(2026, 9, 22),
    )
    now = 1_800_000_000  # long after it's due
    run_import(config, [file])
    with closing(open_history(config.history_path)) as conn:
        imported = grades(conn, config, MARKET, [linen], now)

    run_rebuild(config)

    with closing(open_history(config.history_path)) as conn:
        assert grades(conn, config, MARKET, [linen], now) == imported
    [grade] = imported
    assert grade.cost > 0


def test_vendor_prices_come_back_the_same_from_the_archive(tmp_path):
    # The Archive is JSON, which turns the itemID keys into strings, and an empty Lua
    # table reads as a list. Neither may change what the rebuilt history holds.
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    expected = {2589: 10, 2592: 25, 6948: 0, 9768: 245}
    run_import(config, [file])
    with closing(open_history(config.history_path)) as conn:
        assert vendor_prices(conn, Era.BETA) == expected

    run_rebuild(config)

    with closing(open_history(config.history_path)) as conn:
        assert vendor_prices(conn, Era.BETA) == expected


def test_known_recipes_and_merchant_costs_come_back_the_same_from_the_archive(tmp_path):
    # JSON turns the professionID and itemID keys into strings; that mustn't matter.
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))

    def tailoring(recipe_id, output, bind_type, *reagents):
        return KnownRecipe(
            character="Kash-Patel",
            profession_id=197,
            recipe_id=recipe_id,
            output_item_id=output,
            quantity_min=1,
            quantity_max=1,
            bind_type=bind_type,
            cooldown=None,
            read_at=1790000800,
            reagents=tuple(Reagent(*r) for r in reagents),
        )

    expected_recipes = [
        tailoring(2963, 2996, 0, (2589, 2)),
        # Its output's bind type wasn't cached; the Optional reagent slot isn't kept.
        tailoring(3915, 4344, None, (2996, 1), (2320, 1)),
    ]
    expected_costs = {2320: 10, 2604: 10 / 3}
    run_import(config, [file])
    with closing(open_history(config.history_path)) as conn:
        assert known_recipes(conn, MARKET) == expected_recipes
        assert merchant_costs(conn, MARKET) == expected_costs

    run_rebuild(config)

    with closing(open_history(config.history_path)) as conn:
        assert known_recipes(conn, MARKET) == expected_recipes
        assert merchant_costs(conn, MARKET) == expected_costs


def test_rebuild_includes_the_pooled_scans_in_the_archive(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    run_import(config, [file])
    [(_, own), *_] = sorted(Archive(config.archive_dir).scans(), key=lambda s: s[1]["requestedAt"])
    late = strip_scan({**own, "requestedAt": own["requestedAt"] + 60})
    with closing(open_history(config.history_path)) as conn:
        import_pooled_scans(conn, [("p1", late)], Era.BETA, config)
        before = scan_times(conn, MARKET)
    imported = dump(config.history_path)

    report = run_rebuild(config)

    assert own["requestedAt"] + 60 in before
    assert report.scans_imported == 3
    assert dump(config.history_path) == imported


def test_rebuild_keeps_what_the_scan_pool_already_has(tmp_path):
    # Only the history knows which own Scans went up and where the last pull got to;
    # losing that would push every own Scan again and list the whole pool.
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    run_import(config, [file])
    pool = FakePool()
    with closing(open_history(config.history_path)) as conn:
        pushed = push(conn, pool, config).pushed
        pull(conn, pool, config, now=1_790_000_000)

    run_rebuild(config)

    pool.listed_since.clear()
    with closing(open_history(config.history_path)) as conn:
        assert pushed == 2
        assert push(conn, pool, config).pushed == 0
        pull(conn, pool, config, now=1_790_000_000)
    assert pool.listed_since == [2]


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


def test_the_addon_is_only_told_about_the_player_s_own_scans(tmp_path):
    # The Addon deletes its stored Scans up to lastImported. A Pooled Scan newer than an
    # own Scan the Brain hasn't read yet must not get that one deleted.
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    install_addon(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    run_import(config, [file])
    [*_, (_, own)] = sorted(Archive(config.archive_dir).scans(), key=lambda s: s[1]["requestedAt"])
    newer = strip_scan({**own, "requestedAt": own["requestedAt"] + 600})
    with closing(open_history(config.history_path)) as conn:
        import_pooled_scans(conn, [("p1", newer)], Era.BETA, config)

    run_import(config, [file])

    assert read_recommendations(install)["lastImported"] == {
        "Classic Beta PvP": {"Alliance": 1790001200}
    }


def _three_linen_held(tmp_path, mailbox_reads=()):
    """3 Linen held, selling 2 an hour, with a Flip of two 7s 00c Linen to buy."""
    # One Sale Event, so the Flip minimum (#57) is lowered to let the Flip through.
    config = dataclasses.replace(
        config_for(tmp_path, Install(tmp_path / "_classic_beta_", Era.BETA)),
        flip_min_sale_events=1,
    )
    linen = "item:2589::::::::20:1490"

    def scan(at, quantity, *extra):
        rows = [
            {"itemString": linen, "quantity": quantity, "buyout": quantity * 1000, "timeLeft": 4},
            *extra,
        ]
        return {
            "requestedAt": at,
            "realm": MARKET.realm,
            "faction": "Alliance",
            "character": "Kash-Patel",
            "listings": rows,
        }

    cheap = {"itemString": linen, "quantity": 2, "buyout": 1400, "timeLeft": 4}
    read = {
        "readAt": 1_790_000_000,
        "realm": MARKET.realm,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 123456,
        "vendorPrices": {2589: 10},
        "bags": [
            {
                "bag": 0,
                "slot": 1,
                "count": 3,
                "isBound": False,
                "link": "|cffffffff|Hitem:2589::::::::20:1490|h[Linen Cloth]|h|r",
            }
        ],
    }
    with closing(open_history(config.history_path)) as conn:
        # 2 Linen sold in an hour, so the 3 held all sell within the 7-day horizon.
        import_scans(
            conn, [scan(1_790_000_000, 20), scan(1_790_003_600, 18, cheap)], Era.BETA, config
        )
        import_character_reads(conn, [read], Era.BETA, config)
        import_mailbox_reads(conn, list(mailbox_reads), Era.BETA, config)
    return config


def test_recommend_prints_holdings_and_the_shopping_list_as_tables(tmp_path):
    # A 48 h posting, so exactly one queued unit waits past it (below).
    config = dataclasses.replace(_three_linen_held(tmp_path), post_duration_hours=48)
    text = run_recommend(config)

    lines = [re.split(r"\s{2,}", line.strip()) for line in text.splitlines()]
    assert "Classic Beta PvP Alliance (beta)" in text
    # The one Observation Window every Sell Rate here rests on.
    assert "Sell Rate observed for 1.0 h in the last 14 days" in text
    # Held units are valued with nothing on the Shopping List bought (#86), so they're
    # posted at 699 under the Flip's two 700s, for 664.05 each after the cut, 654.05 more
    # than a vendor pays.
    assert ["2589", "Sell", "3", "6s 99c", "19s 92c", "6s 54c", "1"] in lines
    assert "Shopping List, options each sized on its own within 12g 34s 56c\n" in text
    # Under the Flip priors the second one, fifth in the queue, waits past a 48 h posting
    # and loses one 6c deposit (60% of the 10c Vendor Price) first (#78).
    # #98: 1 Listing bought and 1 stack posted, 2s 46c a click. Behind the 3 held, the
    # last of the 5 sells at 48 a day / 25 (the 24 h Flip prior) in 2.6 days, 1s 89c a day.
    # 4s 92c on 14s is 35.1%.
    assert [
        "Item",
        "Action",
        "Qty",
        "Max price",
        "Profit",
        "Per click",
        "Per day",
        "ROI",
        "Cost",
        "Sales",
        "Note",
    ] in lines
    assert [
        "2589",
        "Sell",
        "2",
        "7s 00c",
        "4s 92c",
        "2s 46c",
        "1s 89c",
        "35.1%",
        "14s 00c",
        "1",
    ] in lines


def test_replay_prints_each_markets_policies_with_the_brains_lead_over_each(tmp_path):
    # A 1 h Sale Horizon, so the first of the two Scans an hour apart can be graded.
    config = dataclasses.replace(_three_linen_held(tmp_path), sale_horizon_seconds=3600)

    text = run_replay(config, since=None, until=None)

    lines = [re.split(r"\s{2,}", line.strip()) for line in text.splitlines()]
    assert "Classic Beta PvP Alliance (beta): provisional, Beta never decides" in text
    assert "Replayed 1 Scan, each graded over the 1.0 h Sale Horizon after it" in text
    assert ["Policy", "Value added", "Brain over it"] in lines
    policies = [line[0] for line in lines if line and line[0].startswith(("Brain", "Auc", "TSM"))]
    assert policies == [
        "Brain",
        "Auctionator",
        "TSM",
        "Brain without Sub-crafts",
        "Brain without Flips to Craft",
        "Brain without Deposits",
        "Brain without own-Market Sell Rate",
    ]
    assert "Realized profit over the range: 0c" in text


def test_recommend_prints_the_roi_of_held_units_bought_on_the_auction_house(tmp_path):
    # 2 of the 3 held were bought for 5s each; posted at 9s 99c they net 9s 49.05c after
    # the cut, +89.8%, a good time to sell.
    won = {
        "index": 1,
        "sender": "Alliance Auction House",
        "subject": "Auction won: Linen Cloth",
        "money": 0,
        "daysLeft": 29.5,
        "firstItemQuantity": 2,
        "firstItemLink": "|cffffffff|Hitem:2589::::::::20:1490|h[Linen Cloth]|h|r",
        "invoice": {"invoiceType": "buyer", "itemName": "Linen Cloth", "bid": 1000, "count": 2},
    }
    # Arrived 10 minutes after the Scan at T0, which named Linen to buy (#55).
    mailbox_read = {
        "readAt": 1_790_000_000 + 12 * 3600 + 600,
        "realm": MARKET.realm,
        "character": "Kash-Patel",
        "shownCount": 1,
        "totalCount": 1,
        "skippedMails": 0,
        "mails": [won],
    }
    grades_path = tmp_path / "grades.toml"
    freeze_named(grades_path, MARKET, 1_790_000_000, NamedSet({"2589": 1_000_000}))
    config = _three_linen_held(tmp_path, [mailbox_read])
    text = run_recommend(dataclasses.replace(config, grades_path=grades_path))

    lines = [re.split(r"\s{2,}", line.strip()) for line in text.splitlines()]
    assert ["Item", "Action", "Qty", "Price", "Profit", "Margin", "Sales", "ROI", "Note"] in lines
    # Posted at 699 with nothing bought (#86): 664.05 after the cut on 500 paid.
    assert ["2589", "Sell", "3", "6s 99c", "19s 92c", "6s 54c", "1", "+32.8% * on 2 of 3"] in lines


def _bolts_and_linen(tmp_path, money=0):
    """Linen at 1s and Bolts at 10s, each selling 2 an hour; 2 Linen held and the Bolt's
    recipe known."""
    config = config_for(tmp_path, Install(tmp_path / "_classic_beta_", Era.BETA))

    def scan(at, quantity):
        rows = [
            {
                "itemString": f"item:{item_id}",
                "quantity": quantity,
                "buyout": quantity * unit,
                "timeLeft": 4,
            }
            for item_id, unit in ((2589, 100), (2996, 1000))
        ]
        return {
            "requestedAt": at,
            "realm": MARKET.realm,
            "faction": "Alliance",
            "character": "Kash-Patel",
            "listings": rows,
        }

    bolt = {
        "recipeID": 2963,
        "outputItemID": 2996,
        "quantityMin": 1,
        "quantityMax": 1,
        "bindType": 0,
        "reagents": [{"itemID": 2589, "quantity": 2, "reagentType": 1}],
    }
    read = {
        "readAt": 1_790_000_000,
        "realm": MARKET.realm,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": money,
        "bags": [
            {
                "bag": 0,
                "slot": 1,
                "count": 2,
                "isBound": False,
                "link": "|cffffffff|Hitem:2589::::::::20:1490|h[Linen Cloth]|h|r",
            }
        ],
        "professions": {197: {"readAt": 1_790_000_000, "professionID": 197, "recipes": [bolt]}},
        "professionList": [{"professionID": 197}],
    }
    with closing(open_history(config.history_path)) as conn:
        import_scans(conn, [scan(1_790_000_000, 20), scan(1_790_003_600, 18)], Era.BETA, config)
        import_character_reads(conn, [read], Era.BETA, config)
    return config


def test_recommend_prints_crafts_with_the_character_and_reagents(tmp_path):
    config = _bolts_and_linen(tmp_path)
    lines = [re.split(r"\s{2,}", line.strip()) for line in run_recommend(config).splitlines()]

    # Posted at 9s 99c, the Bolt Sells for 949.05 after the cut; the 2 Linen, posted at 99,
    # would have brought 188.10.
    assert ["2996", "Craft", "1", "7s 61c", "on Kash-Patel: uses 2 of 2589"] in lines
    assert ["2996", "Sell", "1", "9s 99c", "9s 49c", "1", "incl. 1 crafted"] in lines


def test_recommend_chain_prints_an_item_keys_craft_chains_as_trees(tmp_path):
    # #77: the same numbers as the Craft row above, as its Craft Chain.
    config = _bolts_and_linen(tmp_path)
    text = run_recommend(config, chain="2996")

    assert text.splitlines()[1:] == [
        "Holdings: Craft 1 of 2996",
        "  Sell 1 2996 @ 9s 99c               +9s 49c",
        "  `- Craft 1 2996 on Kash-Patel x 1  -1s 88c",
        "     `- Use 2 2589 held              -1s 88c",
        "  Profit                             +7s 61c",
    ]


def test_recommend_chain_says_when_nothing_crafts_the_item_key(tmp_path):
    config = _bolts_and_linen(tmp_path)

    assert "No Craft row of 2589." in run_recommend(config, chain="2589")


def test_recommend_labels_what_depends_on_a_prediction_and_lists_its_buys_apart(tmp_path):
    config = dataclasses.replace(
        config_for(tmp_path, Install(tmp_path / "_classic_beta_", Era.BETA)),
        predictions_path=tmp_path / "predictions.toml",
    )
    config.predictions_path.write_text(
        """
[[predictions]]
name = "Linen spike"
reason = "Tailoring quests"
item_keys = ["2589"]
catalyst = "Phase 2"
written = 2026-09-01
lapse = 2027-01-01
""",
        encoding="utf-8",
    )
    linen = {
        "itemString": "item:2589::::::::20:1490",
        "quantity": 20,
        "buyout": 2000,
        "timeLeft": 4,
    }
    scan = {
        "requestedAt": 1_790_000_000,  # 2026-09-21
        "realm": MARKET.realm,
        "faction": "Alliance",
        "character": "Kash-Patel",
        "listings": [linen],
    }
    read = {
        "readAt": 1_790_000_000,
        "realm": MARKET.realm,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 10000,
        "vendorPrices": {2589: 95},
        "bags": [
            {
                "bag": 0,
                "slot": 1,
                "count": 3,
                "isBound": False,
                "link": "|cffffffff|Hitem:2589::::::::20:1490|h[Linen Cloth]|h|r",
            }
        ],
    }
    with closing(open_history(config.history_path)) as conn:
        import_scans(conn, [scan], Era.BETA, config)
        import_character_reads(conn, [read], Era.BETA, config)

    text = run_recommend(config)

    lines = [re.split(r"\s{2,}", line.strip()) for line in text.splitlines()]
    assert ["2589", "Hold", "3", "unknown", "under Linen spike"] in lines
    # The 3 held tie up 95c each of the 15s cap; 12 Linen at 1s can each lose 5c.
    assert "Buy to Hold under a Prediction, upside unknown: 12s 00c in total" in text
    assert ["2589", "Linen spike", "12", "1s 00c", "60c", "12s 00c"] in lines


def test_recommend_shows_the_record_of_graded_predictions_and_the_brake(tmp_path):
    config = dataclasses.replace(
        config_for(tmp_path, Install(tmp_path / "_classic_beta_", Era.BETA)),
        predictions_path=tmp_path / "predictions.toml",
    )
    # Written the day after the Read with 3 Linen held, its Catalyst the same day: graded
    # 7 days on, when the 3 are still worth the 95c each a vendor pays.
    config.predictions_path.write_text(
        """
[[predictions]]
name = "Linen spike"
reason = "Tailoring quests"
item_keys = ["2589"]
catalyst = "Phase 2"
written = 2026-09-22
happened = 2026-09-22
""",
        encoding="utf-8",
    )
    linen = {
        "itemString": "item:2589::::::::20:1490",
        "quantity": 20,
        "buyout": 2000,
        "timeLeft": 4,
    }

    def scan(at):
        return {
            "requestedAt": at,
            "realm": MARKET.realm,
            "faction": "Alliance",
            "character": "Kash-Patel",
            "listings": [linen],
        }

    read = {
        "readAt": 1_790_000_000,  # 2026-09-21
        "realm": MARKET.realm,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 10000,
        "vendorPrices": {2589: 95},
        "bags": [
            {
                "bag": 0,
                "slot": 1,
                "count": 3,
                "isBound": False,
                "link": "|cffffffff|Hitem:2589::::::::20:1490|h[Linen Cloth]|h|r",
            }
        ],
    }
    with closing(open_history(config.history_path)) as conn:
        import_scans(
            conn, [scan(1_790_000_000), scan(1_790_000_000 + 10 * 86400)], Era.BETA, config
        )
        import_character_reads(conn, [read], Era.BETA, config)

    text = run_recommend(config)

    lines = [re.split(r"\s{2,}", line.strip()) for line in text.splitlines()]
    # Breaking even is not a profit.
    assert "Graded Predictions: 1 graded, 0 profitable, pooled return 0.0%, caps not halved" in text
    assert ["Linen spike", "2026-09-29", "0c", "2s 85c", "2s 85c", "0.0%"] in lines


def _two_linen_flips(tmp_path) -> Config:
    """#60: 2 Linen at 1000 sell each hour from T0. At T0 + 1 h the Brain names 5 more at
    200 a Flip to Sell posted at 999, and they're bought and sold within the 3 hour Sale
    Horizon. At T0 + 2 h it names 3 at 200, bought too but not yet graded."""
    t0, hour = 1_790_000_000, 3600
    config = dataclasses.replace(
        config_for(tmp_path, Install(tmp_path / "_classic_beta_", Era.BETA)),
        grades_path=tmp_path / "grades.toml",
        sale_horizon_seconds=3 * hour,
        sell_rate_prior_hours_flips=0,
        sale_size_prior_events_flips=0,
        flip_min_sale_events=1,
    )
    link = "|cffffffff|Hitem:2589::::::::20:1490:::::::::|h[Linen Cloth]|h|r"

    def linen(quantity, unit):
        return {
            "itemString": "item:2589::::::::20:1490",
            "quantity": quantity,
            "buyout": quantity * unit,
            "timeLeft": 4,
        }

    def scan(at, *rows):
        return {
            "requestedAt": at,
            "realm": MARKET.realm,
            "faction": "Alliance",
            "character": "Kash-Patel",
            "listings": list(rows),
        }

    def mail(at, subject, invoice, **item):
        # Read 12 hours after it arrived.
        return {
            "readAt": at + 12 * hour,
            "realm": MARKET.realm,
            "character": "Kash-Patel",
            "shownCount": 1,
            "totalCount": 1,
            "skippedMails": 0,
            "mails": [
                {
                    "index": 1,
                    "sender": "Alliance Auction House",
                    "subject": f"{subject}: Linen Cloth",
                    "daysLeft": 29.5,
                    "invoice": invoice | {"itemName": "Linen Cloth"},
                    **({"money": 0} | item),
                }
            ],
        }

    def won(at, count):
        invoice = {"invoiceType": "buyer", "bid": count * 200, "count": count}
        return mail(at, "Auction won", invoice, firstItemQuantity=count, firstItemLink=link)

    read = {
        "readAt": t0,
        "realm": MARKET.realm,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 10_000,
        "vendorPrices": {2589: 10},
        "bags": [],
    }
    with closing(open_history(config.history_path)) as conn:
        import_scans(
            conn,
            [
                scan(t0, linen(20, 1000)),
                scan(t0 + hour, linen(18, 1000), linen(5, 200)),
                scan(t0 + 2 * hour, linen(16, 1000), linen(3, 200)),
                scan(t0 + 3 * hour, linen(14, 1000)),
                scan(t0 + 4 * hour + 600, linen(12, 1000)),
            ],
            Era.BETA,
            config,
        )
        import_mailbox_reads(
            conn,
            [
                # In the order they were read.
                won(t0 + hour + 600, 5),
                mail(
                    t0 + 2 * hour,
                    "Auction successful",
                    {"invoiceType": "seller", "bid": 5 * 999, "count": 5},
                    money=round(5 * 999 * 0.95),
                ),
                won(t0 + 2 * hour + 600, 3),
            ],
            Era.BETA,
            config,
        )
        import_character_reads(conn, [read], Era.BETA, config)
    return config


def test_recommend_shows_the_record_of_graded_flips(tmp_path):
    text = run_recommend(_two_linen_flips(tmp_path))

    # Sold at the Post at named, for the Profit it expected, 50 minutes after the Purchase.
    assert (
        "Graded Flips: 1 graded, 1 paid off, realized/expected Profit 100.0%, "
        "price/Post at 100.0% (median), sold within horizon 100.0%, median days to sell 0.03"
        in text
    )


def test_flips_prints_each_flip_with_its_grade_or_pending(tmp_path):
    text = run_flips(_two_linen_flips(tmp_path))

    lines = [re.split(r"\s{2,}", line.strip()) for line in text.splitlines()]
    assert "Classic Beta PvP Alliance (beta): provisional, Beta never decides" in text
    # Bought 10 minutes after the Scans at T0 + 1 h and T0 + 2 h, local time.
    first, second = (
        datetime.fromtimestamp(1_790_000_000 + h * 3600 + 600).strftime("%Y-%m-%d %H:%M")
        for h in (1, 2)
    )
    assert ["2589", first, "5", "9s 99c", "9s 99c", "0.03", "37s 45c"] in lines
    assert ["2589", second, "3", "9s 99c", "pending"] in lines  # nothing sold yet


def _bought_for_use(config: Config) -> None:
    """2 Linen bought for 20s each 10 minutes after the Scan at T0, which named nothing,
    read 20 hours after that Scan."""
    won = {
        "index": 1,
        "sender": "Alliance Auction House",
        "subject": "Auction won: Linen Cloth",
        "money": 0,
        "daysLeft": 30 - (20 * 3600 - 600) / 86400,
        "firstItemQuantity": 2,
        "firstItemLink": "|cffffffff|Hitem:2589::::::::20:1490|h[Linen Cloth]|h|r",
        "invoice": {"invoiceType": "buyer", "itemName": "Linen Cloth", "bid": 4000, "count": 2},
    }
    read = {
        "readAt": 1_790_000_000 + 20 * 3600,
        "realm": MARKET.realm,
        "character": "Kash-Patel",
        "shownCount": 1,
        "totalCount": 1,
        "skippedMails": 0,
        "mails": [won],
    }
    with closing(open_history(config.history_path)) as conn:
        import_mailbox_reads(conn, [read], Era.BETA, config)


def test_flips_counts_the_purchases_the_brain_didnt_name(tmp_path):
    config = _two_linen_flips(tmp_path)
    _bought_for_use(config)

    text = run_flips(config)

    assert "1 Purchase (40s 00c) not named by the Brain, counted as For Use" in text


def test_flips_counts_the_crafts_recorded_and_those_with_a_costed_output(tmp_path):
    # #44: the 3 Linen still open make one Bolt from 2, then another from the last 1 and
    # 1 looted, which leaves that Bolt only partly costed.
    config = _two_linen_flips(tmp_path)
    t0, hour = 1_790_000_000, 3600
    bolt = {
        "recipeID": 2963,
        "outputItemID": 2996,
        "quantityMin": 1,
        "quantityMax": 1,
        "bindType": 0,
        "reagents": [{"itemID": 2589, "quantity": 2, "reagentType": 1}],
    }
    read = {
        "readAt": t0 + 4 * hour,
        "realm": MARKET.realm,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 10_000,
        "bags": [],
        "professions": {197: {"readAt": t0 + 3 * hour, "professionID": 197, "recipes": [bolt]}},
        "crafts": [
            {"recipeID": 2963, "at": t0 + 3 * hour + 60, "quantity": 1},
            {"recipeID": 2963, "at": t0 + 3 * hour + 120},
        ],
    }
    with closing(open_history(config.history_path)) as conn:
        import_character_reads(conn, [read], Era.BETA, config)

    assert "Crafts recorded: 2 (1 with a costed output)" in run_flips(config)


def _linen_flips_to_craft(tmp_path) -> Config:
    """`_two_linen_flips`, where T0 + 1 h and T0 + 2 h also named a Flip to Craft of Bolts
    buying Linen at up to 200, frozen. The first's is graded and frozen: 2 Bolts, 1 sold at
    999 and 1 open at 500, for 400. The second's Linen make a Bolt, then another from the
    last Linen and a looted one, so it's not gradable once a Scan prices it."""
    config = _two_linen_flips(tmp_path)
    t0, hour = 1_790_000_000, 3600
    for at in (t0 + hour, t0 + 2 * hour):
        bolt = NamedCraft(
            "2996",
            2963,
            "Kash-Patel",
            3,
            (NamedBuy("2589", 6, 200.0),),
            999.0,
            1500.0,
            None,
            3 * hour,
        )
        freeze_shown_crafts(config.grades_path, MARKET, at, 3 * hour, [bolt])
    grade = FlipGrade(t0 + 4 * hour + 600, 2, 400, 1, 999.0, 949.05, 500.0, (0.5,), None, 0, 600)
    freeze_craft_flip_grade(config.grades_path, MARKET, craft_flip_name(2963, t0 + hour), grade)
    recipe = {
        "recipeID": 2963,
        "outputItemID": 2996,
        "quantityMin": 1,
        "quantityMax": 1,
        "bindType": 0,
        "reagents": [{"itemID": 2589, "quantity": 2, "reagentType": 1}],
    }
    read = {
        "readAt": t0 + 4 * hour,
        "realm": MARKET.realm,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 10_000,
        "bags": [],
        "professions": {197: {"readAt": t0 + 3 * hour, "professionID": 197, "recipes": [recipe]}},
        "crafts": [
            {"recipeID": 2963, "at": t0 + 3 * hour + 60, "quantity": 1},
            {"recipeID": 2963, "at": t0 + 3 * hour + 120, "quantity": 1},
        ],
    }
    later = {"requestedAt": t0 + 6 * hour, "realm": MARKET.realm, "faction": "Alliance"}
    with closing(open_history(config.history_path)) as conn:
        import_character_reads(conn, [read], Era.BETA, config)
        import_scans(conn, [later | {"character": "Kash-Patel", "listings": []}], Era.BETA, config)
    return config


def test_flips_prints_the_flips_to_craft_apart_with_their_record_and_those_not_gradable(tmp_path):
    text = run_flips(_linen_flips_to_craft(tmp_path))

    lines = [re.split(r"\s{2,}", line.strip()) for line in text.splitlines()]
    bought = datetime.fromtimestamp(1_790_000_000 + 3600 + 600).strftime("%Y-%m-%d %H:%M")
    # 949.05 + 500 - 400.
    assert ["2996", "2963", bought, "2", "9s 99c", "9s 99c", "0.50", "10s 49c"] in lines
    assert any(line[:2] == ["2996", "2963"] and line[-1] == "not gradable" for line in lines)
    assert "Graded Flips to Craft: 1 graded, 1 paid off" in text
    assert "1 Flip to Craft not gradable: uncosted reagents" in text


def test_recommend_shows_the_record_of_graded_flips_to_craft_apart(tmp_path):
    text = run_recommend(_linen_flips_to_craft(tmp_path))

    # Expected 1500 for 3 Bolts, so 1000 for the 2 graded.
    assert "Graded Flips to Craft: 1 graded, 1 paid off, realized/expected Profit 104.9%" in text
    # The later Scan grades both Flips to Sell, on their own line.
    assert "Graded Flips: 2 graded" in text


def test_replay_counts_the_purchases_in_its_range_the_brain_didnt_name(tmp_path):
    config = _two_linen_flips(tmp_path)
    _bought_for_use(config)

    text = run_replay(config, since=None, until=None)

    assert "1 Purchase (40s 00c) not named by the Brain, counted as For Use" in text


def test_recommend_prints_a_flip_to_crafts_reagent_buys(tmp_path):
    config = dataclasses.replace(
        _bolts_and_linen(tmp_path, money=100_000),
        sell_rate_prior_hours_flips=0,
        sale_size_prior_events_flips=0,
        flip_min_sale_events=1,
    )

    lines = [re.split(r"\s{2,}", line.strip()) for line in run_recommend(config).splitlines()]

    [craft] = [line for line in lines if line[:2] == ["2996", "Craft"] and "(buy" in line[-1]]
    assert craft[-1].startswith("on Kash-Patel: uses ") and "of 2589 (buy " in craft[-1]


def test_disenchants_prints_each_groups_mats_next_to_the_table(tmp_path):
    config = config_for(tmp_path, Install(tmp_path / "_classic_beta_", Era.BETA))
    result = {"itemLevel": 18, "quality": 2, "classID": 4, "at": 1790000000}
    read = {
        "readAt": 1790000100,
        "realm": "Classic Beta PvP",
        "character": "Bob-Patel",
        "faction": "Alliance",
        "money": 0,
        "bags": [],
        "disenchantResults": [result | {"mats": {10940: 2}}, result | {"mats": {10940: 3}}],
    }
    with closing(open_history(config.history_path)) as conn:
        import_character_reads(conn, [read], Era.BETA, config)

    text = run_disenchants(config)

    lines = [re.split(r"\s{2,}", line.strip()) for line in text.splitlines()]
    assert "Beta: 2 Disenchant Results, a group judged from 20" in text
    assert "Green armor ilvl 16-20" in text
    # Strange Dust both times: 100% (Wilson 34.2% to 100.0%) against the table's 75%,
    # and a mean of 2.5 (t-interval 2.5 ± 12.706 × 0.707 / √2) against its 2.5.
    assert [
        "10940",
        "2",
        "100.0% (34.2% to 100.0%)",
        "75.0%",
        "2.50 (-3.85 to 8.85)",
        "2.50",
        "too few Results",
    ] in lines


def test_disenchants_says_when_there_are_none(tmp_path):
    config = config_for(tmp_path, Install(tmp_path / "_classic_beta_", Era.BETA))
    open_history(config.history_path).close()

    assert run_disenchants(config) == "No Disenchant Results yet.\n"


def _near_misses(tmp_path):
    """Linen, selling 2 an hour at 4s, with one at 2s 80c: 1c over what clears the margin.
    Two Copper Ore at 20c that a vendor buys for 25c, over the 10c Budget. A Bolt of Linen
    Cloth at 9s that never sold. The player's own Linen and Bolt Listings name them."""
    config = dataclasses.replace(
        config_for(tmp_path, Install(tmp_path / "_classic_beta_", Era.BETA)),
        flip_min_sale_events=1,
        sell_rate_prior_hours_flips=0,
        sale_size_prior_events_flips=0,
    )
    linen, ore = "item:2589::::::::20:1490", "item:2770::::::::20:1490"
    bolt = "item:2996::::::::20:1490"

    def listing(item, quantity, unit, **extra):
        return {
            "itemString": item,
            "quantity": quantity,
            "buyout": quantity * unit,
            "timeLeft": 4,
        } | extra

    own = [
        listing(linen, 1, 2000, own=True, name="Linen Cloth"),
        listing(bolt, 1, 5000, own=True, name="Bolt of Linen Cloth"),
    ]

    def scan(at, *rows):
        return {
            "requestedAt": at,
            "realm": MARKET.realm,
            "faction": "Alliance",
            "character": "Kash-Patel",
            "listings": [*own, listing(bolt, 2, 900), *rows],
        }

    read = {
        "readAt": 1_790_000_000,
        "realm": MARKET.realm,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 123456,
        "budget": 10,
        "vendorPrices": {2770: 25},
        "bags": [],
    }
    scans = [
        scan(1_790_000_000, listing(linen, 20, 400)),
        scan(1_790_003_600, listing(linen, 18, 400), listing(linen, 1, 280), listing(ore, 2, 20)),
    ]
    with closing(open_history(config.history_path)) as conn:
        import_scans(conn, scans, Era.BETA, config)
        import_character_reads(conn, [read], Era.BETA, config)
    return config


def test_recommend_why_not_lists_the_near_misses_flip_margin_first(tmp_path):
    text = run_recommend(_near_misses(tmp_path), why_not="")

    lines = [re.split(r"\s{2,}", line.strip()) for line in text.splitlines()]
    rows = lines[lines.index(["Item", "Item Key", "Check", "Gap"]) + 1 :]
    assert rows == [
        ["Linen Cloth", "2589", "Flip margin", "ask 2s 80c, clears at 2s 79c: 1c (0.4%)"],
        ["?", "2770", "Budget", "cheapest run 20c, spend 10c"],
        ["Bolt of Linen Cloth", "2996", "Sale Events", "0/1 Sale Events"],
    ]


def test_recommend_why_not_an_item_key_shows_every_check(tmp_path):
    text = run_recommend(_near_misses(tmp_path), why_not="2589")

    lines = [re.split(r"\s{2,}", line.strip()) for line in text.splitlines()]
    assert lines[1:] == [
        ["Linen Cloth (2589): Flip margin"],
        ["Sale Events", "pass", "1/1 Sale Events"],
        ["Room", "pass", "room for 336 at 3s 99c, needs 0 held + 1"],
        ["Flip margin", "fail", "ask 2s 80c, clears at 2s 79c: 1c (0.4%)"],
        ["Budget", "-"],
        ["Row cap", "-"],
    ]


@pytest.mark.parametrize(
    ("scan_gap", "note"),
    [
        (1, ""),  # #132: watched hourly since, nothing sold
        (2, " (not watched since)"),  # #135: Scans too far apart to watch
    ],
)
def test_recommend_why_not_a_flip_cut_to_the_sales_since_its_cheap_run_says_since_when(
    tmp_path, scan_gap, note
):
    # Linen sold 2 an hour at 10s for 10 h, then a 1s showed up and stayed, and nothing
    # sold since, so only the Sale Events since it count at 9s 99c.
    config = dataclasses.replace(
        config_for(tmp_path, Install(tmp_path / "_classic_beta_", Era.BETA)),
        flip_min_sale_events=3,
    )
    t0, hour, cheap_at = 1_790_000_000, 3600, 1_790_000_000 + 10 * 3600

    def scan(at, *rows):
        return {
            "requestedAt": at,
            "realm": MARKET.realm,
            "faction": "Alliance",
            "character": "Kash-Patel",
            "listings": [
                {
                    "itemString": "item:2589::::::::20:1490",
                    "quantity": q,
                    "buyout": q * u,
                    "timeLeft": 4,
                }
                for q, u in rows
            ],
        }

    scans = [scan(t0 + n * hour, (40 - 2 * n, 1000)) for n in range(10)]
    scans += [scan(cheap_at + n * scan_gap * hour, (20, 1000), (1, 100)) for n in range(25)]
    read = {
        "readAt": t0,
        "realm": MARKET.realm,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 123456,
        "bags": [],
    }
    with closing(open_history(config.history_path)) as conn:
        import_scans(conn, scans, Era.BETA, config)
        import_character_reads(conn, [read], Era.BETA, config)

    text = run_recommend(config, why_not="2589")

    since = datetime.fromtimestamp(cheap_at).strftime("%Y-%m-%d %H:%M")
    lines = [re.split(r"\s{2,}", line.strip()) for line in text.splitlines()]
    expected = f"0/3 Sale Events since cheaper Listings went up {since}{note}"
    assert ["Sale Events", "fail", expected] in lines


def test_recommend_why_not_an_item_key_on_the_shopping_list_shows_its_row(tmp_path):
    # The two 7s 00c Linen are a Flip to Sell (above).
    text = run_recommend(_three_linen_held(tmp_path), why_not="2589")

    assert "2589: made the list\n  Sell 2 up to 7s 00c: " in text


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ("BOLT", "Bolt of Linen Cloth (2996): Sale Events"),
        (
            "linen",
            "2 Item Keys match 'linen':\n  Bolt of Linen Cloth (2996)\n  Linen Cloth (2589)\n",
        ),
        ("silk", "No Item Key on sale matches 'silk'."),
    ],
)
def test_recommend_why_not_finds_an_item_by_part_of_its_name(tmp_path, item, expected):
    assert expected in run_recommend(_near_misses(tmp_path), why_not=item)


def test_recommend_prints_the_buy_unders(tmp_path):
    # Linen Vendors for 10s, but 2 of them make a Bolt that Vendors for 50s: 25s a Linen,
    # less 20% of the Buy Under, is 20s 83c. A 5s Listing was seen in the one Scan.
    config = config_for(tmp_path, Install(tmp_path / "_classic_beta_", Era.BETA))
    scan = {
        "requestedAt": 1_790_000_000,
        "realm": MARKET.realm,
        "faction": "Alliance",
        "character": "Kash-Patel",
        "listings": [
            {"itemString": "item:2589", "quantity": 20, "buyout": 20 * 500, "timeLeft": 4}
        ],
    }
    bolt = {
        "recipeID": 2963,
        "outputItemID": 2996,
        "quantityMin": 1,
        "quantityMax": 1,
        "bindType": 0,
        "reagents": [{"itemID": 2589, "quantity": 2, "reagentType": 1}],
    }
    read = {
        "readAt": 1_790_000_000,
        "realm": MARKET.realm,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 0,
        "bags": [],
        "vendorPrices": {2589: 1000, 2996: 5000},
        "professions": {197: {"readAt": 1_790_000_000, "professionID": 197, "recipes": [bolt]}},
        "professionList": [{"professionID": 197}],
    }
    with closing(open_history(config.history_path)) as conn:
        import_scans(conn, [scan], Era.BETA, config)
        import_character_reads(conn, [read], Era.BETA, config)

    lines = [re.split(r"\s{2,}", line.strip()) for line in run_recommend(config).splitlines()]

    assert ["Buy Under"] in lines
    assert ["Item", "Buy Under", "Way out", "Units", "Seen"] in lines
    assert [
        "2589",
        "20s 83c",
        "Craft 2996 (Kash-Patel)",
        "no limit",
        "1 Scan / 7d, listed now",
    ] in lines


def test_recommend_prints_the_disenchant_buy_unders(tmp_path):
    # A green armor piece of item level 18 Disenchants into mats worth 2675 at their Vendor
    # Prices, less the 5s effort of buying it and the margin: 18s 12c. Its group's is the
    # same, seen through the same Listing.
    config = config_for(tmp_path, Install(tmp_path / "_classic_beta_", Era.BETA))
    scan = {
        "requestedAt": 1_790_000_000,
        "realm": MARKET.realm,
        "faction": "Alliance",
        "character": "Kash-Patel",
        "listings": [{"itemString": "item:9999", "quantity": 1, "buyout": 1000, "timeLeft": 4}],
        "itemInfo": {
            9999: {"itemLevel": 18, "quality": 2, "classID": 4, "equipLoc": "INVTYPE_CHEST"}
        },
    }
    read = {
        "readAt": 1_790_000_000,
        "realm": MARKET.realm,
        "character": "Bob",
        "faction": "Alliance",
        "money": 0,
        "bags": [],
        "vendorPrices": {9999: 50, 10940: 1000, 10939: 2000, 10978: 4000},
        "professions": {
            333: {"readAt": 1_790_000_000, "professionID": 333, "skillLevel": 90, "recipes": []}
        },
        "professionList": [{"professionID": 333}],
    }
    with closing(open_history(config.history_path)) as conn:
        import_scans(conn, [scan], Era.BETA, config)
        import_character_reads(conn, [read], Era.BETA, config)

    lines = [re.split(r"\s{2,}", line.strip()) for line in run_recommend(config).splitlines()]

    seen = "1 Scan / 7d, listed now"
    assert ["9999", "18s 12c", "Disenchant (Bob)", "no limit", seen] in lines
    assert ["Green armor ilvl 16-20", "18s 12c", "Disenchant (Bob)", "no limit", seen] in lines


def test_recommend_prints_a_flip_to_disenchant_by_its_group(tmp_path):
    # As above, with 1g to spend: the mats' 2675 less the 5s effort nets 2175 on the 10s
    # Listing, 11s 75c profit.
    config = config_for(tmp_path, Install(tmp_path / "_classic_beta_", Era.BETA))
    scan = {
        "requestedAt": 1_790_000_000,
        "realm": MARKET.realm,
        "faction": "Alliance",
        "character": "Kash-Patel",
        "listings": [{"itemString": "item:9999", "quantity": 1, "buyout": 1000, "timeLeft": 4}],
        "itemInfo": {
            9999: {"itemLevel": 18, "quality": 2, "classID": 4, "equipLoc": "INVTYPE_CHEST"}
        },
    }
    read = {
        "readAt": 1_790_000_000,
        "realm": MARKET.realm,
        "character": "Bob",
        "faction": "Alliance",
        "money": 10000,
        "bags": [],
        "vendorPrices": {9999: 50, 10940: 1000, 10939: 2000, 10978: 4000},
        "professions": {
            333: {"readAt": 1_790_000_000, "professionID": 333, "skillLevel": 90, "recipes": []}
        },
        "professionList": [{"professionID": 333}],
    }
    with closing(open_history(config.history_path)) as conn:
        import_scans(conn, [scan], Era.BETA, config)
        import_character_reads(conn, [read], Era.BETA, config)

    lines = [re.split(r"\s{2,}", line.strip()) for line in run_recommend(config).splitlines()]

    assert ["Green armor ilvl 16-20", "Disenchant", "1", "10s 00c", "11s 75c"] in [
        line[:5] for line in lines
    ]


def test_recommend_why_not_leaves_the_checks_after_the_first_failed_one_unreached(tmp_path):
    text = run_recommend(_near_misses(tmp_path), why_not="2996")

    lines = [re.split(r"\s{2,}", line.strip()) for line in text.splitlines()]
    assert lines[2:] == [
        ["Sale Events", "fail", "0/1 Sale Events"],
        ["Room", "-"],
        ["Flip margin", "-"],
        ["Budget", "-"],
        ["Row cap", "-"],
    ]


def _linen_early_in_live(tmp_path, weight=0.5) -> Config:
    """#110: Live's first Scan of Linen (5 at 1s, 10 at 1s 20c; Fair Value 1s) under a
    Prediction, and a Beta Market whose Fair Value is 2s and whose stack at 2s 40c sold a
    unit every half hour: 3 Sale Events in 1.5 h. As in test_beta_sell_rate, the Beta
    Sell Rate makes room for 6 at the 1s 19c post price."""
    live_start = 1_795_000_000  # 2026-11-18
    config = dataclasses.replace(
        config_for(tmp_path, Install(tmp_path / "_classic_", Era.LIVE)),
        predictions_path=tmp_path / "predictions.toml",
        sale_horizon_seconds=3 * 3600,
        sell_rate_prior_hours_flips=0,
        sale_size_prior_events_flips=0,
        flip_min_sale_events=1,
        beta_sell_rate_weight=weight,
    )
    config.predictions_path.write_text(
        """
[[predictions]]
name = "Linen spike"
reason = "Tailoring quests"
item_keys = ["2589"]
catalyst = "Phase 2"
written = 2026-11-01
lapse = 2027-01-01
""",
        encoding="utf-8",
    )

    def linen(quantity, unit):
        return {
            "itemString": "item:2589::::::::20:1490",
            "quantity": quantity,
            "buyout": quantity * unit,
            "timeLeft": 4,
        }

    def scan(at, realm, *rows):
        return {
            "requestedAt": at,
            "realm": realm,
            "faction": "Alliance",
            "character": "Kash-Patel",
            "listings": list(rows),
        }

    beta = [
        scan(1_790_000_000 + n * 1800, MARKET.realm, linen(5, 200), linen(10 - n, 240))
        for n in range(4)
    ]
    live = [scan(live_start, "Forever", linen(5, 100), linen(10, 120))]
    read = {
        "readAt": live_start,
        "realm": "Forever",
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 1_000_000,
        "vendorPrices": {},
        "bags": [],
    }
    with closing(open_history(config.history_path)) as conn:
        import_scans(conn, beta, Era.BETA, config)
        import_scans(conn, live, Era.LIVE, config)
        import_character_reads(conn, [read], Era.LIVE, config)
    return config


def test_recommend_prints_the_beta_live_fair_value_ratios_when_borrowing(tmp_path):
    text = run_recommend(_linen_early_in_live(tmp_path))

    lines = [re.split(r"\s{2,}", line.strip()) for line in text.splitlines()]
    assert "Beta/Live Fair Value of the Predictions' Item Keys (Beta Sell Rate x0.5)" in text
    assert ["2589", "2.00"] in lines


def test_recommend_prints_the_ratios_when_asked_even_with_no_weight(tmp_path):
    config = _linen_early_in_live(tmp_path, weight=0)

    assert "Beta/Live Fair Value" not in run_recommend(config)
    assert "Beta/Live Fair Value of the Predictions' Item Keys (Beta Sell Rate off)" in (
        run_recommend(config, beta_ratios=True)
    )


def test_recommend_why_not_a_prediction_buy_says_how_much_of_its_room_is_from_beta(tmp_path):
    text = run_recommend(_linen_early_in_live(tmp_path), why_not="2589")

    assert "2589: Prediction buy of 6 under Linen spike" in text
    assert "room for 6 at 1s 19c, 6 of it from Beta" in text


def _config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(f"[[installs]]\npath = '{tmp_path / 'wow'}'\nera = 'beta'\n", encoding="utf-8")
    return path


def test_watch_refuses_to_start_while_another_brain_runs(tmp_path, caplog):
    config_file = _config_file(tmp_path)

    with instance_lock(tmp_path):
        assert main(["--config", str(config_file), "watch"]) == 1

    assert "already running" in caplog.text


def test_logs_to_a_file_next_to_the_config(tmp_path):
    config_file = _config_file(tmp_path)

    assert main(["--config", str(config_file), "import"]) == 1

    assert "No AzerothQuant.lua found" in (tmp_path / "brain.log").read_text(encoding="utf-8")


def test_the_log_file_rotates_once_it_reaches_its_size_cap(tmp_path):
    config_file = _config_file(tmp_path)
    full = "x" * LOG_MAX_BYTES
    (tmp_path / "brain.log").write_text(full, encoding="utf-8")

    main(["--config", str(config_file), "import"])

    assert (tmp_path / "brain.log.1").read_text(encoding="utf-8") == full
    assert "No AzerothQuant.lua found" in (tmp_path / "brain.log").read_text(encoding="utf-8")


def test_without_a_config_option_uses_the_one_setup_wrote(tmp_path, monkeypatch):
    app_folder = tmp_path / "LocalAppData" / "AzerothQuant"
    app_folder.mkdir(parents=True)
    _config_file(app_folder)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.chdir(tmp_path)

    assert main(["import"]) == 1

    assert "No AzerothQuant.lua found" in (app_folder / "brain.log").read_text(encoding="utf-8")


def test_says_where_it_looked_when_there_is_no_config(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.chdir(tmp_path)

    assert main(["import"]) == 2

    assert str(tmp_path / "LocalAppData" / "AzerothQuant" / "config.toml") in caplog.text


def test_a_config_option_in_a_missing_folder_is_a_clean_error(tmp_path, caplog):
    assert main(["--config", str(tmp_path / "nowhere" / "config.toml"), "import"]) == 2

    assert "Can't load the config" in caplog.text
