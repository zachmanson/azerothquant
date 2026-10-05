import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from brain.config import Era, Install, load_config
from brain.installer import (
    Launch,
    Places,
    Shortcut,
    brain_running,
    delete_data,
    game_installs,
    install,
    launch_action,
    render_config,
    stop_running_brain,
    uninstall,
    update,
    wow_folder,
)
from brain.instance_lock import LOCK_FILE

STUB = "-- the stub the Addon ships\n"


def _places(tmp_path: Path) -> Places:
    return Places(
        app_dir=tmp_path / "LocalAppData" / "AzerothQuant",
        start_menu=tmp_path / "Start Menu" / "Programs",
        startup=tmp_path / "Start Menu" / "Programs" / "Startup",
    )


def _bundled_addon(tmp_path: Path) -> Path:
    addon = tmp_path / "bundle" / "AzerothQuant"
    addon.mkdir(parents=True, exist_ok=True)
    (addon / "AzerothQuant.toc").write_text("## Interface: 16001\n## Title: AQ\n", encoding="utf-8")
    (addon / "Recommendations.lua").write_text(STUB, encoding="utf-8")
    (addon / "Scan.lua").write_text("-- new Scan\n", encoding="utf-8")
    return addon


def _downloaded_exe(tmp_path: Path, content: bytes = b"brain v0.2") -> Path:
    exe = tmp_path / "Downloads" / "AzerothQuantBrain.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(content)
    return exe


def _game(tmp_path: Path, name: str, era: Era) -> Install:
    game = tmp_path / "World of Warcraft" / name
    (game / "Interface" / "AddOns").mkdir(parents=True)
    return Install(game, era)


class FakeShortcuts:
    """Writes each shortcut as a file at its link, so taking them off again shows."""

    def __init__(self) -> None:
        self.made: list[Shortcut] = []

    def __call__(self, shortcut: Shortcut) -> None:
        shortcut.link.parent.mkdir(parents=True, exist_ok=True)
        shortcut.link.write_text(str(shortcut.target), encoding="utf-8")
        self.made.append(shortcut)


def test_the_wow_folder_is_the_parent_of_the_game_folder_the_registry_names(tmp_path):
    wow = tmp_path / "World of Warcraft"
    (wow / "_classic_").mkdir(parents=True)

    assert wow_folder(wow / "_classic_", default=tmp_path / "nowhere") == wow


def test_without_the_registry_the_default_wow_folder_is_used_when_it_is_there(tmp_path):
    default = tmp_path / "World of Warcraft"
    default.mkdir()

    assert wow_folder(None, default=default) == default
    assert wow_folder(tmp_path / "uninstalled" / "_classic_", default=default) == default


def test_no_wow_folder_when_neither_is_there(tmp_path):
    assert wow_folder(None, default=tmp_path / "World of Warcraft") is None


def test_classic_is_live_and_classic_beta_is_beta_and_every_other_game_is_left_out(tmp_path):
    for game in ("_classic_", "_classic_beta_", "_classic_era_", "_classic_era_ptr_", "_retail_"):
        (tmp_path / game / "WTF").mkdir(parents=True)

    assert game_installs(tmp_path) == [
        Install(tmp_path / "_classic_beta_", Era.BETA),
        Install(tmp_path / "_classic_", Era.LIVE),
    ]


def test_a_game_folder_never_played_is_left_out(tmp_path):
    (tmp_path / "_classic_beta_" / "Interface").mkdir(parents=True)
    (tmp_path / "_classic_").mkdir()

    assert game_installs(tmp_path) == [Install(tmp_path / "_classic_beta_", Era.BETA)]


def test_the_config_setup_writes_loads_with_the_installs_and_the_pool(tmp_path):
    installs = [
        Install(tmp_path / "World of Warcraft" / "_classic_beta_", Era.BETA),
        Install(tmp_path / "World of Warcraft" / "_classic_", Era.LIVE),
    ]
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        # Pasted with spaces and a newline around it.
        render_config(installs, "https://pool.example", ' it\'s a \\ "key"\n'),
        encoding="utf-8",
    )

    config = load_config(config_file)
    assert config.installs == tuple(installs)
    assert config.pool_url == "https://pool.example"
    assert config.pool_key == 'it\'s a \\ "key"'


def test_without_a_pool_key_the_config_leaves_the_pool_off(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        render_config([Install(tmp_path, Era.LIVE)], "https://pool.example", "  "),
        encoding="utf-8",
    )

    config = load_config(config_file)
    assert (config.pool_url, config.pool_key) == (None, None)


def test_install_copies_the_brain_installs_the_addons_writes_the_config_and_makes_shortcuts(
    tmp_path,
):
    places = _places(tmp_path)
    beta = _game(tmp_path, "_classic_beta_", Era.BETA)
    shortcuts = FakeShortcuts()

    install(
        places,
        exe=_downloaded_exe(tmp_path),
        addon=_bundled_addon(tmp_path),
        installs=[beta],
        pool_url="https://pool.example",
        pool_key="secret",
        make_shortcut=shortcuts,
    )

    brain = places.app_dir / "AzerothQuantBrain.exe"
    assert brain.read_bytes() == b"brain v0.2"
    config = load_config(places.app_dir / "config.toml")
    assert (config.installs, config.pool_key) == ((beta,), "secret")
    addons = beta.path / "Interface" / "AddOns"
    assert (addons / "AzerothQuant" / "Scan.lua").read_text(encoding="utf-8") == "-- new Scan\n"
    assert (addons / "AzerothQuant_Data" / "Recommendations.lua").read_text(
        encoding="utf-8"
    ) == STUB
    assert (
        (addons / "AzerothQuant_Data" / "AzerothQuant_Data.toc")
        .read_text(encoding="utf-8")
        .startswith("## Interface: 16001\n")
    )
    assert set(shortcuts.made) == set(
        [
            Shortcut(places.startup / "AzerothQuant Brain.lnk", brain),
            Shortcut(places.start_menu / "AzerothQuant Brain.lnk", brain),
            Shortcut(places.start_menu / "Uninstall AzerothQuant Brain.lnk", brain, "--uninstall"),
            Shortcut(places.start_menu / "AzerothQuant Brain log.lnk", places.app_dir),
        ]
    )


def test_installing_over_an_addon_keeps_its_recommendations_and_drops_files_it_no_longer_has(
    tmp_path,
):
    beta = _game(tmp_path, "_classic_beta_", Era.BETA)
    addons = beta.path / "Interface" / "AddOns"
    for folder in ("AzerothQuant", "AzerothQuant_Data"):
        (addons / folder).mkdir()
        (addons / folder / "Recommendations.lua").write_text("-- written by the Brain\n")
    (addons / "AzerothQuant" / "Gone.lua").write_text("-- dropped since\n")

    install(
        _places(tmp_path),
        exe=_downloaded_exe(tmp_path),
        addon=_bundled_addon(tmp_path),
        installs=[beta],
        pool_url="https://pool.example",
        pool_key="",
        make_shortcut=FakeShortcuts(),
    )

    for folder in ("AzerothQuant", "AzerothQuant_Data"):
        assert (addons / folder / "Recommendations.lua").read_text() == "-- written by the Brain\n"
    assert not (addons / "AzerothQuant" / "Gone.lua").exists()
    assert (addons / "AzerothQuant" / "Scan.lua").exists()


def _link_folder(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            raise
        import _winapi  # symlinks need Developer Mode on Windows; junctions don't

        _winapi.CreateJunction(str(target), str(link))


def test_an_addon_linked_in_from_elsewhere_is_left_alone(tmp_path):
    # The dev setup links the repo's Addon into the game, and setup must never wipe the repo.
    repo_addon = tmp_path / "repo" / "AzerothQuant"
    repo_addon.mkdir(parents=True)
    (repo_addon / "Mine.lua").write_text("-- being worked on\n", encoding="utf-8")
    beta = _game(tmp_path, "_classic_beta_", Era.BETA)
    _link_folder(beta.path / "Interface" / "AddOns" / "AzerothQuant", repo_addon)

    install(
        _places(tmp_path),
        exe=_downloaded_exe(tmp_path),
        addon=_bundled_addon(tmp_path),
        installs=[beta],
        pool_url="https://pool.example",
        pool_key="",
        make_shortcut=FakeShortcuts(),
    )

    assert [p.name for p in repo_addon.iterdir()] == ["Mine.lua"]


def test_a_first_run_sets_up(tmp_path):
    assert launch_action(_downloaded_exe(tmp_path), _places(tmp_path)) is Launch.SETUP


def test_the_installed_brain_watches_and_a_brain_run_from_anywhere_else_updates(tmp_path):
    places = _places(tmp_path)
    install(
        places,
        exe=_downloaded_exe(tmp_path, b"brain v0.1"),
        addon=_bundled_addon(tmp_path),
        installs=[_game(tmp_path, "_classic_beta_", Era.BETA)],
        pool_url="https://pool.example",
        pool_key="",
        make_shortcut=FakeShortcuts(),
    )

    assert launch_action(places.exe, places) is Launch.WATCH
    assert launch_action(_downloaded_exe(tmp_path), places) is Launch.UPDATE


def test_an_update_replaces_the_brain_keeps_the_key_and_picks_up_a_new_game_folder(tmp_path):
    places = _places(tmp_path)
    beta = _game(tmp_path, "_classic_beta_", Era.BETA)
    install(
        places,
        exe=_downloaded_exe(tmp_path, b"brain v0.1"),
        addon=_bundled_addon(tmp_path),
        installs=[beta],
        pool_url="https://old-pool.example",
        pool_key="secret",
        make_shortcut=FakeShortcuts(),
    )
    live = _game(tmp_path, "_classic_", Era.LIVE)  # Live launched since

    update(
        places,
        exe=_downloaded_exe(tmp_path, b"brain v0.2"),
        addon=_bundled_addon(tmp_path),
        pool_url="https://pool.example",
        make_shortcut=FakeShortcuts(),
    )

    assert places.exe.read_bytes() == b"brain v0.2"
    config = load_config(places.app_dir / "config.toml")
    assert config.installs == (beta, live)
    assert (config.pool_url, config.pool_key) == ("https://pool.example", "secret")
    assert (live.path / "Interface" / "AddOns" / "AzerothQuant" / "Scan.lua").exists()


HOLD_THE_LOCK = """
import sys, time
from pathlib import Path
from brain.instance_lock import instance_lock
with instance_lock(Path(sys.argv[1])) as held:
    print(held, flush=True)
    time.sleep(60)
"""


def test_stopping_the_running_brain_frees_its_data_folder(tmp_path):
    with subprocess.Popen(
        [sys.executable, "-c", HOLD_THE_LOCK, str(tmp_path)], stdout=subprocess.PIPE, text=True
    ) as running:
        try:
            assert running.stdout.readline().strip() == "True"
            assert brain_running(tmp_path)

            assert stop_running_brain(tmp_path) is True

            assert running.wait(timeout=5) is not None
            assert not brain_running(tmp_path)
        finally:
            running.kill()


def test_a_pid_left_by_a_crashed_brain_is_never_killed(tmp_path):
    # Windows reuses PIDs, so a stale one can name some other program by now.
    with subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]) as other:
        try:
            (tmp_path / LOCK_FILE).write_text(str(other.pid), encoding="ascii")

            assert stop_running_brain(tmp_path) is True

            assert other.poll() is None
        finally:
            other.kill()


def _set_up(tmp_path: Path, shortcuts: FakeShortcuts) -> tuple[Places, Install]:
    places = _places(tmp_path)
    beta = _game(tmp_path, "_classic_beta_", Era.BETA)
    install(
        places,
        exe=_downloaded_exe(tmp_path),
        addon=_bundled_addon(tmp_path),
        installs=[beta],
        pool_url="https://pool.example",
        pool_key="secret",
        make_shortcut=shortcuts,
    )
    (places.app_dir / "history.sqlite").write_bytes(b"the guildie's data")
    return places, beta


def test_uninstall_takes_off_the_brain_its_shortcuts_and_both_addons_but_keeps_the_data(
    tmp_path,
):
    shortcuts = FakeShortcuts()
    places, beta = _set_up(tmp_path, shortcuts)

    assert uninstall(places) == []

    assert not any(s.link.exists() for s in shortcuts.made)
    assert not places.exe.exists()
    addons = beta.path / "Interface" / "AddOns"
    assert not (addons / "AzerothQuant").exists()
    assert not (addons / "AzerothQuant_Data").exists()
    assert (places.app_dir / "history.sqlite").read_bytes() == b"the guildie's data"
    assert (places.app_dir / "config.toml").exists()


def test_deleting_the_data_too_takes_off_the_whole_app_folder(tmp_path):
    places, _ = _set_up(tmp_path, FakeShortcuts())
    uninstall(places)

    assert delete_data(places) == []

    assert not places.app_dir.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows refuses to delete open files")
def test_uninstall_names_what_it_could_not_delete_because_it_is_running(tmp_path):
    # Uninstall runs from the installed Brain itself, which can't delete its own exe.
    places, _ = _set_up(tmp_path, FakeShortcuts())

    with open(places.exe, "rb"):
        assert uninstall(places) == [places.exe]
        assert delete_data(places) == [places.exe]


def test_a_registry_path_that_is_already_the_wow_folder_is_used_as_is(tmp_path):
    wow = tmp_path / "World of Warcraft"
    (wow / "_classic_").mkdir(parents=True)

    assert wow_folder(wow, default=tmp_path / "nowhere") == wow


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows locks a running exe")
def test_an_update_waits_for_the_stopped_brains_exe_to_be_let_go(tmp_path):
    # A frozen Brain is two processes; the outer one lets go of the exe a moment after the
    # inner one (whose PID the lock holds) is stopped.
    places, _ = _set_up(tmp_path, FakeShortcuts())
    ping = Path(os.environ["SystemRoot"]) / "System32" / "PING.EXE"
    shutil.copyfile(ping, places.exe)
    still_running = subprocess.Popen(
        [places.exe, "-n", "2", "127.0.0.1"], stdout=subprocess.DEVNULL
    )

    update(
        places,
        exe=_downloaded_exe(tmp_path, b"brain v0.3"),
        addon=_bundled_addon(tmp_path),
        pool_url="https://pool.example",
        make_shortcut=FakeShortcuts(),
    )

    assert still_running.wait(timeout=5) == 0
    assert places.exe.read_bytes() == b"brain v0.3"
