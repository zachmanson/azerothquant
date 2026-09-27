"""The `brain` command.

    brain import     import every SavedVariables file once
    brain watch      import each SavedVariables file whenever the client rewrites it
    brain rebuild    recreate the history database from the Archive (ADR-0005)
    brain recommend  print what to do with Holdings, and the Shopping List

All of them only read the Addon's SavedVariables and write the Brain's own files; nothing
here touches the game process (ADR-0003).
"""

import argparse
import dataclasses
import logging
import os
import sqlite3
import sys
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from brain.archive import Archive
from brain.config import Config, ConfigError, Era, load_config
from brain.history import (
    ImportFileError,
    ImportReport,
    import_character_reads,
    import_file,
    import_mailbox_reads,
    import_scans,
    open_history,
)
from brain.predictions import PredictionsError, load_predictions
from brain.recommend import Action, MarketRecommendations, Row, recommend
from brain.recommendations import write_recommendations
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
        _write_recommendations(conn, config)
    return results


class RebuildError(Exception):
    """The history can't be rebuilt, and the existing one was left as it was."""


def run_rebuild(config: Config) -> ImportReport:
    """Recreate the history database from every Scan, Mailbox Read and Character Read in
    the Archive.

    The new database is built beside the old one and only replaces it once complete, so
    a failed rebuild leaves the history as it was. An empty archive is refused rather
    than turned into an empty history. Stop `brain watch` first: it holds the history
    open, and on Windows an open file can't be replaced.
    """
    if config.archive_dir is None:
        raise RebuildError("no archive folder configured")
    archive = Archive(config.archive_dir)
    scans_by_era: dict[Era, list[dict]] = {}
    for era, raw in archive.scans():
        scans_by_era.setdefault(era, []).append(raw)
    reads_by_era: dict[Era, list[dict]] = {}
    for era, raw in archive.mailbox_reads():
        reads_by_era.setdefault(era, []).append(raw)
    character_reads_by_era: dict[Era, list[dict]] = {}
    for era, raw in archive.character_reads():
        character_reads_by_era.setdefault(era, []).append(raw)
    if not scans_by_era and not reads_by_era and not character_reads_by_era:
        raise RebuildError(
            f"no Scans, Mailbox Reads or Character Reads in the archive at {config.archive_dir}"
        )

    config.history_path.parent.mkdir(parents=True, exist_ok=True)
    rebuilt = config.history_path.with_name(config.history_path.name + ".rebuild")
    rebuilt.unlink(missing_ok=True)
    # Everything read here is already archived, so don't archive it again.
    from_archive = dataclasses.replace(config, archive_dir=None)
    total = ImportReport()
    try:
        with closing(open_history(rebuilt)) as conn:
            for era, raws in scans_by_era.items():
                _add_report(total, import_scans(conn, raws, era, from_archive))
            for era, raws in reads_by_era.items():
                import_mailbox_reads(conn, raws, era, from_archive, total)
            for era, raws in character_reads_by_era.items():
                import_character_reads(conn, raws, era, from_archive, total)
        os.replace(rebuilt, config.history_path)
    except BaseException:
        rebuilt.unlink(missing_ok=True)
        raise

    with closing(open_history(config.history_path)) as conn:
        _write_recommendations(conn, config)
    return total


def _add_report(total: ImportReport, report: ImportReport) -> None:
    for f in dataclasses.fields(ImportReport):
        if f.name == "warnings":
            total.warnings.extend(report.warnings)
        else:
            setattr(total, f.name, getattr(total, f.name) + getattr(report, f.name))


def _write_recommendations(conn: sqlite3.Connection, config: Config) -> None:
    """Rewrite every install's Recommendations.lua from the history.

    Every install, not only those just imported: it is cheap, and it also fixes a file
    a previous write couldn't replace (say the client had it open).
    """
    for install in config.installs:
        try:
            path = write_recommendations(conn, install)
        except (OSError, sqlite3.Error) as e:
            log.error("Couldn't write Recommendations for %s: %s", install.path, e)
            continue
        if path is None:
            log.warning("The Addon isn't installed in %s; no Recommendations written", install.path)


def _log_results(results: list[FileResult]) -> None:
    for r in results:
        if r.error is not None:
            log.error("Couldn't import %s: %s", r.path, r.error)
        else:
            log.info(
                "Imported %s: %d new Scans, %d already imported, %d rejected;"
                " %d new Mailbox Reads, %d already imported, %d unreadable;"
                " %d new Outcomes, %d new Purchases;"
                " %d new Character Reads, %d already imported, %d unreadable",
                r.path,
                r.report.scans_imported,
                r.report.scans_already_imported,
                r.report.scans_out_of_order + r.report.scans_unreadable,
                r.report.mailbox_reads_imported,
                r.report.mailbox_reads_already_imported,
                r.report.mailbox_reads_unreadable,
                r.report.outcomes_found,
                r.report.purchases_found,
                r.report.character_reads_imported,
                r.report.character_reads_already_imported,
                r.report.character_reads_unreadable,
            )


def _import_once(config: Config) -> int:
    files = savedvariables_files(config)
    if not files:
        log.error("No %s found in any configured install folder", SAVEDVARIABLES_FILE)
        return 1
    results = run_import(config, files)
    _log_results(results)
    return 1 if any(r.error is not None for r in results) else 0


def _recommend(config: Config) -> int:
    if not config.history_path.exists():
        log.error("No history at %s yet; run `brain import` first", config.history_path)
        return 1
    try:
        text = run_recommend(config)
    except sqlite3.Error as e:
        log.error("Couldn't read the history: %s", e)
        return 1
    except PredictionsError as e:
        log.error("Can't load the Predictions: %s", e)
        return 1
    print(text, end="")
    return 0


def _rebuild(config: Config) -> int:
    try:
        report = run_rebuild(config)
    except (RebuildError, OSError, sqlite3.Error, ValueError) as e:
        log.error("Couldn't rebuild the history: %s", e)
        return 1
    log.info(
        "Rebuilt %s from %s: %d Scans, %d rejected; %d Mailbox Reads with %d Outcomes"
        " and %d Purchases; %d Character Reads",
        config.history_path,
        config.archive_dir,
        report.scans_imported,
        report.scans_out_of_order + report.scans_unreadable,
        report.mailbox_reads_imported,
        report.outcomes_found,
        report.purchases_found,
        report.character_reads_imported,
    )
    return 0


def run_recommend(config: Config) -> str:
    """The Recommendations for every Market the player has Characters in, as text."""
    predictions = load_predictions(config.predictions_path)
    with closing(open_history(config.history_path)) as conn:
        markets = recommend(conn, config, predictions)
    if not markets:
        return "No Character has a Market with a Scan yet.\n"
    range_days = config.sell_rate_range_seconds // 86400
    return "\n".join(_render_market(m, range_days) for m in markets)


def _render_market(m: MarketRecommendations, range_days: int) -> str:
    as_of = datetime.fromtimestamp(m.as_of).strftime("%Y-%m-%d %H:%M")
    holdings = _table(
        ["Item", "Action", "Qty", "Price", "Profit", "Margin", "Sales", "Note"],
        [
            [
                r.item_key,
                _action(r),
                str(r.quantity),
                _money(r.price),
                "unknown" if r.action is Action.HOLD else _money(r.profit),
                _money(r.margin),
                _count(r.sale_events),
                f"under {r.prediction}" if r.prediction else r.note,
            ]
            for r in m.holdings
        ],
    )
    shopping = _table(
        ["Item", "Action", "Qty", "Max price", "Profit", "Cost", "Sales"],
        [
            [
                r.item_key,
                _action(r),
                str(r.quantity),
                _money(r.price),
                _money(r.profit),
                _money(r.cost),
                _count(r.sale_events),
            ]
            for r in m.shopping_list
        ],
    )
    prediction_buys = _table(
        ["Item", "Prediction", "Qty", "Max price", "Max Loss", "Cost"],
        [
            [
                r.item_key,
                r.prediction,
                str(r.quantity),
                _money(r.price),
                _money(r.max_loss),
                _money(r.cost),
            ]
            for r in m.prediction_buys
        ],
    )
    graded = _table(
        ["Prediction", "Graded", "Proceeds", "Open value", "Cost", "Return"],
        [
            [
                g.prediction,
                datetime.fromtimestamp(g.graded_at).strftime("%Y-%m-%d"),
                _money(g.proceeds),
                _money(g.open_value),
                _money(g.cost),
                _percent(g.return_),
            ]
            for g in m.grades
        ],
    )
    if m.pooled_return is None:
        record = "Graded Predictions: none yet"
    else:
        brake = "halved" if m.pooled_return < 0 else "not halved"
        record = f"Graded Predictions: pooled return {_percent(m.pooled_return)}, caps {brake}"
    market = f"{m.market.realm} {m.market.faction} ({m.market.era.value})"
    return (
        f"{market}, as of the Scan at {as_of}\n"
        f"Sell Rate observed for {m.window_hours:.1f} h in the last {range_days} days\n"
        f"Sold Outcomes not linked to an Item Key by name: {m.unlinked_sales}\n\n"
        f"Holdings\n{holdings}\n"
        f"Shopping List: {_money(m.gold)} to spend, {_money(m.shopping_cost)} in total\n"
        f"{shopping}\n"
        f"Buy to Hold under a Prediction, upside unknown: {_money(m.prediction_cost)} in total\n"
        f"{prediction_buys}\n"
        f"{record}\n"
        f"{graded}"
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "  (nothing)\n"
    widths = [max(len(cell) for cell in column) for column in zip(headers, *rows, strict=True)]
    return "".join(
        "  "
        + "  ".join(cell.ljust(w) for cell, w in zip(line, widths, strict=True)).rstrip()
        + "\n"
        for line in (headers, *rows)
    )


def _action(row: Row) -> str:
    return "-" if row.action is None else row.action.value


def _count(n: int | None) -> str:
    return "" if n is None else str(n)


def _percent(share: float | None) -> str:
    return "" if share is None else f"{share:.1%}"


def _money(copper: float | None) -> str:
    """Copper as the game shows it: 12g 03s 05c, 3s 05c or 5c."""
    if copper is None:
        return ""
    sign, copper = ("-" if copper < 0 else ""), abs(round(copper))
    gold, rest = divmod(copper, 10000)
    silver, copper = divmod(rest, 100)
    if gold:
        return f"{sign}{gold}g {silver:02d}s {copper:02d}c"
    if silver:
        return f"{sign}{silver}s {copper:02d}c"
    return f"{sign}{copper}c"


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
    commands.add_parser("rebuild", help="recreate the history database from the Archive")
    commands.add_parser("recommend", help="print what to do with Holdings, and what to buy")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    try:
        config = load_config(args.config)
    except (ConfigError, OSError) as e:
        log.error("Can't load the config: %s", e)
        return 2

    if args.command == "import":
        return _import_once(config)
    if args.command == "rebuild":
        return _rebuild(config)
    if args.command == "recommend":
        return _recommend(config)
    return _watch(config)


if __name__ == "__main__":
    sys.exit(main())
