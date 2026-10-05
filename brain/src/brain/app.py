"""AzerothQuantBrain.exe, what a guildie runs (#115): setup on a first run, update when
it's a newer copy, `--uninstall`, and otherwise watching, hidden.

Thin glue: the popups, the registry, shortcut files and starting processes. The logic is in
`brain.installer`, which is tested. Everything a guildie reads here is short and plain.
"""

import argparse
import os
import subprocess
import sys
import tkinter
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

from brain import __version__, cli
from brain.config import APP_FOLDER, CONFIG_FILE
from brain.installer import (
    Launch,
    Places,
    Shortcut,
    brain_running,
    delete_data,
    game_installs,
    install,
    launch_action,
    stop_running_brain,
    uninstall,
    update,
    wow_folder,
)

TITLE = "AzerothQuant Brain"
# The Scan Pool every guildie's Brain syncs with.
POOL_URL = "https://azerothquant-pool.zachmanson9.workers.dev"
_REGISTRY_KEY = r"SOFTWARE\WOW6432Node\Blizzard Entertainment\World of Warcraft"
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
_DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
_CANT_STOP = "Couldn't stop the running Brain. Restart your PC and try again."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="AzerothQuantBrain")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)

    tkinter.Tk().withdraw()  # the popups' parent, never shown itself
    if not getattr(sys, "frozen", False):
        # From source, sys.executable is python.exe, which setup would copy in as the Brain.
        messagebox.showerror(TITLE, "Run the built AzerothQuantBrain.exe, not the source.")
        return 2
    places = _places()
    try:
        if args.uninstall:
            return _uninstall(places)
        action = launch_action(Path(sys.executable), places)
        if action is Launch.WATCH:
            return _watch(places)
        return _setup(places) if action is Launch.SETUP else _update(places)
    except Exception as e:  # there's no console to show a traceback in
        messagebox.showerror(
            TITLE,
            "Something went wrong. Send a screenshot of this to whoever gave you the Brain."
            f"\n\n{type(e).__name__}: {e}",
        )
        return 1


def _watch(places: Places) -> int:
    if brain_running(places.app_dir):
        messagebox.showinfo(TITLE, "AzerothQuant Brain is already running.")
        return 1
    return cli.main(["--config", str(places.app_dir / CONFIG_FILE), "watch"])


def _setup(places: Places) -> int:
    wow = wow_folder(_registry_install_path())
    if wow is not None and not messagebox.askyesno(
        TITLE, f"Found World of Warcraft at {wow}. Use this?"
    ):
        wow = None
    while True:
        if wow is None:
            picked = filedialog.askdirectory(title="Pick your World of Warcraft folder")
            if not picked:
                return 1
            wow = Path(picked)
        installs = game_installs(wow)
        if installs:
            break
        messagebox.showwarning(TITLE, f"Couldn't find the game in {wow}. Pick another folder.")
        wow = None
    key = simpledialog.askstring(
        TITLE,
        "Paste the code you were given to share scans with the guild.\n(Leave empty to skip.)",
    )
    if key is None:
        return 1
    install(places, Path(sys.executable), _bundled_addon(), installs, POOL_URL, key, _shortcut)
    _start_brain(places)
    messagebox.showinfo(
        TITLE,
        "All set. The Brain runs in the background and starts with Windows.\n"
        "Open WoW and do a Scan.",
    )
    return 0


def _update(places: Places) -> int:
    if not stop_running_brain(places.app_dir):
        messagebox.showerror(TITLE, _CANT_STOP)
        return 1
    update(places, Path(sys.executable), _bundled_addon(), POOL_URL, _shortcut)
    _start_brain(places)
    messagebox.showinfo(TITLE, f"Updated to v{__version__}.")
    return 0


def _uninstall(places: Places) -> int:
    if not stop_running_brain(places.app_dir):
        messagebox.showerror(TITLE, _CANT_STOP)
        return 1
    in_use = uninstall(places)
    remove_folder = messagebox.askyesno(TITLE, "Also delete your saved data?")
    if remove_folder:
        in_use = sorted(set(in_use + delete_data(places)))
    # Last, so the wait before deleting this exe starts as it exits.
    messagebox.showinfo(TITLE, "AzerothQuant Brain is uninstalled.")
    _delete_after_exit(in_use, places.app_dir if remove_folder else None)
    return 0


def _places() -> Places:
    programs = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return Places(
        app_dir=Path(os.environ["LOCALAPPDATA"]) / APP_FOLDER,
        start_menu=programs,
        startup=programs / "Startup",
    )


def _bundled_addon() -> Path:
    """The Addon the exe carries (slice 4 bundles it)."""
    return Path(sys._MEIPASS) / "AzerothQuant"


def _registry_install_path() -> Path | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REGISTRY_KEY) as key:
            return Path(winreg.QueryValueEx(key, "InstallPath")[0])
    except OSError:
        return None


def _shortcut(shortcut: Shortcut) -> None:
    """Write a .lnk through Windows' own shortcut maker, so nothing extra gets bundled."""

    def quoted(text: str) -> str:
        return "'" + text.replace("'", "''") + "'"

    shortcut.link.parent.mkdir(parents=True, exist_ok=True)
    script = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({quoted(str(shortcut.link))});"
        f" $s.TargetPath = {quoted(str(shortcut.target))};"
        f" $s.Arguments = {quoted(shortcut.arguments)};"
        f" $s.WorkingDirectory = {quoted(str(shortcut.target.parent))};"
        " $s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        creationflags=_NO_WINDOW,
    )


def _start_brain(places: Places) -> None:
    subprocess.Popen([str(places.exe)], cwd=places.app_dir, creationflags=_DETACHED)


def _delete_after_exit(files: list[Path], folder: Path | None) -> None:
    """Delete what's still in use (this exe) a few seconds after it exits."""
    if not files and folder is None:
        return
    steps = ["ping -n 6 127.0.0.1 >nul"] + [f'del /f /q "{f}"' for f in files]
    if folder is not None:
        steps.append(f'rmdir /s /q "{folder}"')
    subprocess.Popen(f'cmd /s /c "{" & ".join(steps)}"', creationflags=_DETACHED)


if __name__ == "__main__":
    sys.exit(main())
