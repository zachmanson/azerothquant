"""The `brain` command.

    brain import   import every SavedVariables file once
    brain watch    import each SavedVariables file whenever the client rewrites it

Both only read the Addon's SavedVariables and write the Brain's own files; nothing
here touches the game process (ADR-0003).
"""

import argparse
import logging
import sqlite3
import sys
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from brain.config import Config, ConfigError, load_config
from brain.history import ImportFileError, ImportReport, import_file, open_history
from brain.savedvariables import SavedVariablesError
from brain.watch import Watcher

log = logging.getLogger("brain")

DEFAULT_CONFIG = Path("config.toml")  # run from brain/, or pass --config
SAVEDVARIABLES_FILE = "AzerothQuant.lua"
# How long a SavedVariables file must go unchanged before it is read, and how often
# the watcher checks. The client writes the whole file within a second or so.
SETTLE_SECONDS = 3.0
POLL_SECONDS = 1.0


@dataclass(frozen=True)
class FileResult:
    """How importing one SavedVariables file went: a report, or why it failed."""

    path: Path
    report: ImportReport | None = None
    error: str | None = None


def savedvariables_files(config: Config) -> list[Path]:
    """The Addon's SavedVariables file for every account in every configured install."""
    files = []
    for install in config.installs:
        pattern = f"WTF/Account/*/SavedVariables/{SAVEDVARIABLES_FILE}"
        files.extend(sorted(install.path.glob(pattern)))
    return files


def run_import(config: Config, paths: list[Path]) -> list[FileResult]:
    """Import each file into the history, in order.

    A file that can't be imported (say it was read while the client was still writing
    it) is reported and skipped; it doesn't stop the others. Importing is idempotent,
    so reading a file again later is always safe.
    """
    config.history_path.parent.mkdir(parents=True, exist_ok=True)
    results = []
    with closing(open_history(config.history_path)) as conn:
        for path in paths:
            try:
                report = import_file(conn, path, config)
            except (
                ImportFileError,
                SavedVariablesError,
                UnicodeDecodeError,
                OSError,
                sqlite3.Error,
            ) as e:
                results.append(FileResult(path, error=str(e)))
            else:
                results.append(FileResult(path, report=report))
    return results


def _log_results(results: list[FileResult]) -> None:
    for r in results:
        if r.error is not None:
            log.error("Couldn't import %s: %s", r.path, r.error)
        else:
            log.info(
                "Imported %s: %d new Scans, %d already imported, %d rejected",
                r.path,
                r.report.scans_imported,
                r.report.scans_already_imported,
                r.report.scans_out_of_order + r.report.scans_unreadable,
            )


def _import_once(config: Config) -> int:
    files = savedvariables_files(config)
    if not files:
        log.error("No %s found in any configured install folder", SAVEDVARIABLES_FILE)
        return 1
    results = run_import(config, files)
    _log_results(results)
    return 1 if any(r.error is not None for r in results) else 0


def _watch(config: Config) -> int:
    watcher = Watcher(settle_seconds=SETTLE_SECONDS)
    folders = ", ".join(str(i.path) for i in config.installs)
    log.info("Watching %s in %s (Ctrl+C to stop)", SAVEDVARIABLES_FILE, folders)
    try:
        while True:
            _watch_step(config, watcher)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        return 0


def _watch_step(config: Config, watcher: Watcher) -> None:
    ready: list[Path] = []
    try:
        # Re-listed every time so a newly created account folder is picked up.
        ready = watcher.poll(savedvariables_files(config), now=time.monotonic())
        if not ready:
            return
        results = run_import(config, ready)
        _log_results(results)
        failed = [r.path for r in results if r.error is not None]
    except Exception:
        # A long-running watcher logs and carries on rather than exit on one bad pass.
        log.exception("Import failed; will try again")
        failed = ready
    for path in failed:
        watcher.retry(path, now=time.monotonic())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="brain", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG, help=f"default: {DEFAULT_CONFIG}"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("import", help="import every SavedVariables file once")
    commands.add_parser("watch", help="import SavedVariables files whenever they change")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    try:
        config = load_config(args.config)
    except (ConfigError, OSError) as e:
        log.error("Can't load the config: %s", e)
        return 2

    if args.command == "import":
        return _import_once(config)
    return _watch(config)


if __name__ == "__main__":
    sys.exit(main())
