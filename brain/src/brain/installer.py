"""Setting the Brain up on a guildie's PC, updating it and taking it off again (#115).

This is the logic, tested against temp folders. The popups that drive it are in
`brain.app`, and stay thin.
"""

import json
import os
import shutil
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from brain.config import CONFIG_FILE, Era, Install, load_config
from brain.instance_lock import LOCK_FILE, instance_lock
from brain.recommendations import (
    FILE_NAME,
    addon_folder,
    create_data_slots,
    data_slot_folders,
    old_data_addon_folder,
)

EXE_NAME = "AzerothQuantBrain.exe"
DEFAULT_WOW_FOLDER = Path(r"C:\Program Files (x86)\World of Warcraft")
# The game folders the Brain reads, by Era. Only these: `_classic_` is MoP Classic and
# `_classic_era_` is Classic Era, different games whose Scans must never mix with Live's
# (#199).
GAME_FOLDERS = {"_classic_beta_": Era.BETA, "_forever_": Era.LIVE}


def wow_folder(registry_path: Path | None, default: Path = DEFAULT_WOW_FOLDER) -> Path | None:
    """The WoW folder, the one holding the game folders (`_forever_`, `_retail_`, ...).
    Blizzard's registry InstallPath names one of the game folders (then it's its parent),
    or the WoW folder itself. None when neither the registry's nor the default folder is
    there."""
    if registry_path is not None and registry_path.is_dir():
        if _is_game_folder(registry_path.name):
            return registry_path.parent
        return registry_path
    return default if default.is_dir() else None


def _is_game_folder(name: str) -> bool:
    return len(name) > 2 and name.startswith("_") and name.endswith("_")


def game_installs(wow: Path) -> list[Install]:
    """The installs under the WoW folder to read from, each with its Era. A game folder
    with neither WTF nor Interface has never been played, so it's left out."""
    installs = []
    for name, era in GAME_FOLDERS.items():
        game = wow / name
        if (game / "WTF").is_dir() or (game / "Interface").is_dir():
            installs.append(Install(game, era))
    return installs


def render_config(installs: list[Install], pool_url: str, pool_key: str) -> str:
    """The config.toml setup writes. An empty pool key leaves the pool off."""
    lines = ["# Written by AzerothQuant Brain setup. Running a newer Brain rewrites it.", ""]
    pool_key = pool_key.strip()
    if pool_key:
        lines += [
            f"pool_url = {_toml_string(pool_url)}",
            f"pool_key = {_toml_string(pool_key)}",
            "",
        ]
    for install in installs:
        lines += [
            "[[installs]]",
            f"path = {_toml_string(str(install.path))}",
            f"era = {_toml_string(install.era)}",
            "",
        ]
    return "\n".join(lines)


def _toml_string(text: str) -> str:
    # A JSON string is a TOML basic string, as long as non-ASCII is left as is (TOML has no
    # surrogate-pair escapes).
    return json.dumps(text, ensure_ascii=False)


@dataclass(frozen=True)
class Places:
    """Where setup puts things: the app folder (%LOCALAPPDATA%/AzerothQuant: the copied
    Brain, its config and its data), and the user's Start menu Programs and Startup
    folders."""

    app_dir: Path
    start_menu: Path
    startup: Path

    @property
    def exe(self) -> Path:
        return self.app_dir / EXE_NAME


@dataclass(frozen=True)
class Shortcut:
    """A Windows shortcut (.lnk) at `link`, starting `target` with `arguments`."""

    link: Path
    target: Path
    arguments: str = ""


def shortcuts(places: Places) -> list[Shortcut]:
    """Starts with Windows, can be started and uninstalled from the Start menu, and its log
    found from there."""
    return [
        Shortcut(places.startup / "AzerothQuant Brain.lnk", places.exe),
        Shortcut(places.start_menu / "AzerothQuant Brain.lnk", places.exe),
        Shortcut(places.start_menu / "Uninstall AzerothQuant Brain.lnk", places.exe, "--uninstall"),
        Shortcut(places.start_menu / "AzerothQuant Brain log.lnk", places.app_dir),
    ]


def install(
    places: Places,
    exe: Path,
    addon: Path,
    installs: list[Install],
    pool_url: str,
    pool_key: str,
    make_shortcut: Callable[[Shortcut], None],
) -> None:
    """Set the Brain up: copy `exe` into the app folder, install the bundled `addon` and
    its Data slots into each install, write the config and make the shortcuts."""
    places.app_dir.mkdir(parents=True, exist_ok=True)
    _copy_brain(exe, places.exe)
    for game in installs:
        # A linked-in Addon is the dev setup's (the repo's folder), never to be replaced.
        if _is_link(addon_folder(game)):
            continue
        _install_addon(addon, game)
        create_data_slots(game)
        _remove_folder(old_data_addon_folder(game))
    (places.app_dir / CONFIG_FILE).write_text(
        render_config(installs, pool_url, pool_key), encoding="utf-8"
    )
    for shortcut in shortcuts(places):
        make_shortcut(shortcut)


def _copy_brain(exe: Path, to: Path, timeout: float = 10.0) -> None:
    """Copy the Brain's exe, waiting for a stopped one to let go of the old copy: a frozen
    Brain is two processes, and the outer one exits a moment after the inner one, whose PID
    the lock holds, is stopped."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            shutil.copyfile(exe, to)
            return
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.2)


def _install_addon(addon: Path, game: Install) -> None:
    """Replace the install's Addon with the bundled one, all but its Recommendations: the
    Brain's latest stay until it next writes, rather than going back to the stub."""
    target = addon_folder(game)
    recommendations = target / FILE_NAME
    kept = recommendations.read_bytes() if recommendations.is_file() else None
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(addon, target)
    if kept is not None:
        recommendations.write_bytes(kept)


def _remove_folder(folder: Path) -> None:
    # A linked-in folder is the dev setup's (the repo's), never to be deleted.
    if folder.is_dir() and not _is_link(folder):
        shutil.rmtree(folder)


def _is_link(folder: Path) -> bool:
    return folder.is_symlink() or folder.is_junction()


class Launch(StrEnum):
    """What running the exe does."""

    SETUP = "setup"
    UPDATE = "update"
    WATCH = "watch"


def launch_action(exe: Path, places: Places) -> Launch:
    """What running `exe` does: set up on a first run, watch when it's the installed Brain,
    and update the installed Brain when it's any other copy (a newer download)."""
    if not (places.app_dir / CONFIG_FILE).is_file():
        return Launch.SETUP
    if exe.resolve() == places.exe.resolve():
        return Launch.WATCH
    return Launch.UPDATE


def update(
    places: Places,
    exe: Path,
    addon: Path,
    pool_url: str,
    make_shortcut: Callable[[Shortcut], None],
) -> None:
    """Install `exe` over the Brain set up before, without asking anything again: same key,
    and the game folders looked for again in the same WoW folder, so a game folder that
    came since (Live launching) gets the Addon too. The data is left as it is."""
    old = load_config(places.app_dir / CONFIG_FILE)
    installs = game_installs(old.installs[0].path.parent) or list(old.installs)
    install(places, exe, addon, installs, pool_url, old.pool_key or "", make_shortcut)


def brain_running(data_dir: Path) -> bool:
    """Whether a Brain is watching this data folder: one holds its lock. The PID in the lock
    file alone can't tell, since it's left behind by a crash."""
    with instance_lock(data_dir) as held:
        return not held


def stop_running_brain(data_dir: Path, timeout: float = 5.0) -> bool:
    """Stop the Brain watching this data folder, if one is. False if it still holds the
    lock after `timeout` seconds."""
    if not brain_running(data_dir):
        return True
    pid = (data_dir / LOCK_FILE).read_text(encoding="ascii").strip()
    if pid:
        try:
            os.kill(int(pid), signal.SIGTERM)  # TerminateProcess on Windows
        except OSError:
            pass  # stopped on its own since (Windows raises a plain OSError for that)
    # Windows frees a killed process's lock a moment after it's gone.
    deadline = time.monotonic() + timeout
    while brain_running(data_dir):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)
    return True


def uninstall(places: Places) -> list[Path]:
    """Take off the shortcuts, the copied Brain, and the Addon and its Data slots from each
    install, leaving the config and the data. Returns what couldn't be deleted because it's
    in use: the running Brain's own exe, when it uninstalls itself."""
    in_use = []
    config = places.app_dir / CONFIG_FILE
    installs = load_config(config).installs if config.is_file() else ()
    for game in installs:
        folders = [addon_folder(game), *data_slot_folders(game), old_data_addon_folder(game)]
        for folder in folders:
            _remove_folder(folder)
    for path in [s.link for s in shortcuts(places)] + [places.exe]:
        try:
            path.unlink(missing_ok=True)
        except PermissionError:
            in_use.append(path)
    return in_use


def delete_data(places: Places) -> list[Path]:
    """Delete the whole app folder: config, data, log. Returns the files that couldn't be
    deleted because they're in use; the folder stays until they're gone."""
    in_use: list[Path] = []

    def skip_file_in_use(_function: object, path: str, error: BaseException) -> None:
        if isinstance(error, PermissionError) and Path(path).is_file():
            in_use.append(Path(path))
        # The app folder can't go while a file in it is in use: expected, not an error.
        elif not (Path(path) == places.app_dir and in_use):
            raise error

    if places.app_dir.exists():
        shutil.rmtree(places.app_dir, onexc=skip_file_in_use)
    return in_use
