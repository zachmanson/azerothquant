"""The `brain` command.

    brain import     import every SavedVariables file once
    brain watch      import each SavedVariables file whenever the client rewrites it
    brain rebuild    recreate the history database from the Archive (ADR-0005)
    brain recommend  print what to do with Holdings, and the Shopping List
    brain profit     realized profit from own sales over a range
    brain backtest   trade the past Scans from a start gold and grade it by the sales after
    brain flips      grade the Flips to Sell and to Craft made: did they sell as named
    brain disenchants  check the Disenchant tables against the player's Disenchant Results
    brain pool push  upload the player's Scans the Scan Pool doesn't have yet
    brain pool pull [--since DATE]  download and import other members' Scans
    brain pool key add NAME     make a member key for NAME and print it (the pool admin only)
    brain pool key revoke NAME  revoke NAME's key and roll back their Scans (the pool admin only)

All of them only read the Addon's SavedVariables and write the Brain's own files; nothing
here touches the game process (ADR-0003). Only `brain watch` and `brain pool` go online, and
only with pool_url and pool_key set: to the Scan Pool, with stripped Scans (ADR-0026). `brain
pool key` needs pool_url and pool_admin_secret instead, and sends only the member's name.
"""

import argparse
import dataclasses
import logging
import math
import os
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from brain.archive import Archive, ArchivedScan
from brain.backtest import (
    AUCTIONATOR,
    BUY_UNDER_POLICIES,
    POLICIES,
    START_GOLD,
    MarketBacktest,
    Simulation,
    Trade,
    backtest,
)
from brain.beta_prior import BetaPrior, beta_prior
from brain.config import (
    APP_FOLDER,
    CONFIG_FILE,
    Config,
    ConfigError,
    Era,
    Install,
    config_candidates,
    find_config,
    load_config,
)
from brain.disenchant import Group, load_table
from brain.disenchant_check import DisenchantCheck, MatCheck, check_disenchants
from brain.fair_value import FairValueCache
from brain.flips import CraftFlip, Flip, craft_flips, flip_record, flips
from brain.grades_file import GradesError
from brain.history import (
    ImportFileError,
    ImportReport,
    Market,
    Purchase,
    character_markets,
    copy_pool_state,
    crafts,
    disenchant_results,
    import_archived_scans,
    import_character_reads,
    import_file,
    import_mailbox_reads,
    open_history,
    purchases,
    scan_times,
)
from brain.instance_lock import instance_lock
from brain.lots import happened_at, start_of
from brain.observation import Calibration
from brain.pool import HttpPool, Pool, PoolAdmin, PoolError
from brain.pool_sync import PoolSyncer, pull, push
from brain.predictions import PredictionsError, load_predictions
from brain.realized import Realized, realized
from brain.recommend import (
    Action,
    BuyUnder,
    ChainNode,
    Check,
    MarketRecommendations,
    NodeKind,
    Row,
    WhyNot,
    held_units,
    market_lots,
    per_click,
    per_day,
    recommend,
    return_on_cost,
    split_purchases,
)
from brain.recommendations import addon_folder, write_recommendations
from brain.savedvariables import SavedVariablesError
from brain.timings import Timings, timed
from brain.watch import Watcher

log = logging.getLogger("brain")

NEAR_MISSES = 20  # per Market in `brain recommend --why-not` (#108)
SAVEDVARIABLES_FILE = "AzerothQuant.lua"
LOG_FILE = "brain.log"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3
# How long a SavedVariables file must go unchanged before it is read, and how often
# the watcher checks. The client writes the whole file within a second or so.
SETTLE_SECONDS = 3.0
POLL_SECONDS = 1.0
# What the Addon tells the player when the Decision Engine wrote no Recommendations, and
# when `brain watch` stopped after an error (#115).
NO_RECOMMENDATIONS = "Something went wrong making your recommendations."
CRASHED = "The Brain stopped after an error. Start it again from the Start menu."


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


def run_import(
    config: Config,
    paths: list[Path],
    fair_value_cache: FairValueCache | None = None,
    timings: Timings | None = None,
    problem: str | None = None,
) -> list[FileResult]:
    """Import each file into the history, in order.

    A file that can't be imported (say it was read while the client was still writing
    it) is reported and skipped; it doesn't stop the others. Importing is idempotent,
    so reading a file again later is always safe. `fair_value_cache` as in `recommend`.
    Each stage is timed in `timings` (#131). `problem` is passed on to the Addon, as in
    `write_recommendations`.
    """
    config.history_path.parent.mkdir(parents=True, exist_ok=True)
    results = []
    with closing(open_history(config.history_path)) as conn:
        for path in paths:
            try:
                with timed(timings, "history ingest"):
                    report = import_file(conn, path, config, timings)
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
        _write_recommendations(
            conn, config, fair_value_cache=fair_value_cache, timings=timings, problem=problem
        )
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
    scans_by_era: dict[Era, list[ArchivedScan]] = {}
    for era, raw in archive.scans():
        scans_by_era.setdefault(era, []).append(ArchivedScan(raw))
    for era, pooled in archive.pooled_scans():
        scans_by_era.setdefault(era, []).append(pooled)
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
                _add_report(total, import_archived_scans(conn, raws, era, from_archive))
            for era, raws in reads_by_era.items():
                import_mailbox_reads(conn, raws, era, from_archive, total)
            for era, raws in character_reads_by_era.items():
                import_character_reads(conn, raws, era, from_archive, total)
            if config.history_path.exists():
                try:
                    with closing(open_history(config.history_path)) as old:
                        copy_pool_state(old, conn)
                except sqlite3.Error as e:
                    # The old history may be why it's being rebuilt. Without its pool state
                    # the next sync pushes every own Scan again and lists the whole pool,
                    # which costs time but loses nothing.
                    log.warning("Couldn't keep the Scan Pool state of the old history: %s", e)
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


def _write_recommendations(
    conn: sqlite3.Connection,
    config: Config,
    fair_value_cache: FairValueCache | None = None,
    timings: Timings | None = None,
    problem: str | None = None,
    catching_up_since: int | None = None,
) -> None:
    """Rewrite every install's Recommendations.lua from the history, with `problem` for
    the Addon to tell the player, and `catching_up_since` while a long pull runs (#159).

    Every install, not only those just imported: it is cheap, and it also fixes a file
    a previous write couldn't replace (say the client had it open).
    """
    # Recommendations failing (a typo in the Predictions, or a Decision Engine bug) must
    # not stop the file being written: the import times in it are what let the Addon prune
    # SavedVariables.
    # One cache for the pass, so the Beta Prior reuses the Fair Values recommend computed.
    if fair_value_cache is None:
        fair_value_cache = FairValueCache()
    fair_value_cache.timings = timings
    try:
        with timed(timings, "Decision Engine"):
            try:
                predictions = load_predictions(config.predictions_path)
                markets = recommend(conn, config, predictions, fair_value_cache=fair_value_cache)
            except (PredictionsError, GradesError) as e:
                log.error("No Recommendations written: %s", e)
                markets = []
                problem = _join_problems(problem, NO_RECOMMENDATIONS)
            except Exception:
                log.exception("No Recommendations written: the Decision Engine failed")
                markets = []
                problem = _join_problems(problem, NO_RECOMMENDATIONS)
            beta_priors = _beta_priors(conn, config, markets, fair_value_cache)
    finally:
        fair_value_cache.timings = None
    with timed(timings, "Recommendations.lua"):
        for install in config.installs:
            try:
                path = write_recommendations(
                    conn,
                    install,
                    markets,
                    beta_priors,
                    config.post_duration_hours,
                    problem,
                    catching_up_since,
                )
            except (OSError, sqlite3.Error) as e:
                log.error("Couldn't write Recommendations for %s: %s", install.path, e)
                continue
            if path is None:
                log.warning(
                    "The Addon isn't installed in %s; no Recommendations written", install.path
                )


def _join_problems(problem: str | None, more: str) -> str:
    """Both problems in one line: the Addon has room for one."""
    return f"{problem} {more}" if problem else more


def _beta_priors(
    conn: sqlite3.Connection,
    config: Config,
    markets: Sequence[MarketRecommendations],
    fair_value_cache: FairValueCache,
) -> dict[Market, BetaPrior]:
    """The Beta Prior of each Market's rows (#90). It's display only, so failing only loses
    the column, never the Recommendations."""
    result = {}
    for m in markets:
        rows = [*m.holdings, *m.shopping_list, *m.prediction_buys, *m.buy_under]
        item_keys = {r.item_key for r in rows if r.item_key}
        try:
            prior = beta_prior(conn, m.market, config, m.as_of, item_keys, fair_value_cache)
        except Exception:
            log.exception("No Beta Prior for %s %s", m.market.realm, m.market.faction)
            continue
        if prior is not None:
            result[m.market] = prior
    return result


def _log_results(results: list[FileResult]) -> None:
    for r in results:
        if r.error is not None:
            log.error("Couldn't import %s: %s", r.path, r.error)
        else:
            log.info(
                "Imported %s: %d new Scans (%d re-matched), %d already imported,"
                " %d waiting for rebuild, %d rejected;"
                " %d new Mailbox Reads, %d already imported, %d unreadable;"
                " %d new Outcomes, %d new Purchases;"
                " %d new Character Reads, %d already imported, %d unreadable",
                r.path,
                r.report.scans_imported,
                r.report.scans_rematched,
                r.report.scans_already_imported,
                r.report.scans_waiting_for_rebuild,
                r.report.scans_unreadable,
                r.report.mailbox_reads_imported,
                r.report.mailbox_reads_already_imported,
                r.report.mailbox_reads_unreadable,
                r.report.outcomes_found,
                r.report.purchases_found,
                r.report.character_reads_imported,
                r.report.character_reads_already_imported,
                r.report.character_reads_unreadable,
            )


# The stages of an import, in the order they run (#131). The Scan Pool's are timed only
# when it's on.
IMPORT_STAGES = (
    "SavedVariables",
    "Archive",
    "history ingest",
    "Fair Values",
    "Decision Engine",
    "Recommendations.lua",
)


def _log_stages(config: Config, timings: Timings) -> None:
    """Log how long each stage of an import took, and the Scans in the history, which is
    what the stages grow with (#131)."""
    with closing(open_history(config.history_path)) as conn:
        [scans] = conn.execute("SELECT COUNT(*) FROM scan").fetchone()
    pool_pull = ["pool pull"] if "pool pull" in timings.seconds else []
    stages = ", ".join(
        f"{name} {timings.seconds.get(name, 0.0):.1f}s" for name in [*pool_pull, *IMPORT_STAGES]
    )
    # The push comes after the Import took total, so it's kept apart from the stages in it.
    if "pool push" in timings.seconds:
        stages += f"; pool push {timings.seconds['pool push']:.1f}s after"
    log.info("Import stages: %s; %d Scans in the history", stages, scans)


def _import_once(config: Config) -> int:
    files = savedvariables_files(config)
    if not files:
        log.error("No %s found in any configured install folder", SAVEDVARIABLES_FILE)
        return 1
    timings = Timings()
    results = run_import(config, files, timings=timings)
    _log_results(results)
    if any(r.error is None for r in results):
        _log_stages(config, timings)
    return 1 if any(r.error is not None for r in results) else 0


def _recommend(
    config: Config, chain: str | None = None, why_not: str | None = None, beta_ratios: bool = False
) -> int:
    if not config.history_path.exists():
        log.error("No history at %s yet; run `brain import` first", config.history_path)
        return 1
    try:
        text = run_recommend(config, chain, why_not, beta_ratios)
    except sqlite3.Error as e:
        log.error("Couldn't read the history: %s", e)
        return 1
    except PredictionsError as e:
        log.error("Can't load the Predictions: %s", e)
        return 1
    except GradesError as e:
        log.error("Can't load the Grades: %s", e)
        return 1
    print(text, end="")
    return 0


BENCH_STAGES = ("Decision Engine", "Fair Values", "Recommendations.lua")


def run_bench(config: Config, out: Path) -> str:
    """Two `_write_recommendations` passes in one process, as a watching Brain makes them,
    timed by stage (#141): the yardstick for #116's budget. They run on a copy of the
    history in `out`, so a running Brain isn't blocked and nothing is changed, and write
    into one install per Era there, never a real one. The first pass computes every Fair
    Value; the second reuses them, as every pass after a Brain's first does."""
    out.mkdir(parents=True, exist_ok=True)
    copy = out / config.history_path.name
    live_uri = f"{config.history_path.resolve().as_uri()}?mode=ro"
    with (
        closing(sqlite3.connect(live_uri, uri=True)) as live,
        closing(sqlite3.connect(copy)) as conn,
    ):
        live.backup(conn)
    eras = sorted({install.era for install in config.installs}, key=lambda era: era.value)
    installs = tuple(Install(out / era.value, era) for era in eras)
    for install in installs:
        addon_folder(install).mkdir(parents=True, exist_ok=True)
    bench_config = dataclasses.replace(config, history_path=copy, installs=installs)
    cache = FairValueCache()
    lines = []
    with closing(open_history(copy)) as conn:
        for n in (1, 2):
            timings = Timings()
            start = time.monotonic()
            _write_recommendations(conn, bench_config, fair_value_cache=cache, timings=timings)
            took = time.monotonic() - start
            stages = ", ".join(
                f"{name} {timings.seconds.get(name, 0.0):.1f}s" for name in BENCH_STAGES
            )
            lines.append(f"Pass {n}: {stages}; total {took:.1f}s\n")
    return "".join(lines)


def _bench(config: Config, out: Path | None) -> int:
    if not config.history_path.exists():
        log.error("No history at %s yet; run `brain import` first", config.history_path)
        return 1
    try:
        with tempfile.TemporaryDirectory() as folder:
            text = run_bench(config, out if out is not None else Path(folder))
    except sqlite3.Error as e:
        log.error("Couldn't read the history: %s", e)
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
        report.scans_waiting_for_rebuild + report.scans_unreadable,
        report.mailbox_reads_imported,
        report.outcomes_found,
        report.purchases_found,
        report.character_reads_imported,
    )
    return 0


def _profit(config: Config, since: date | None, until: date | None) -> int:
    if not config.history_path.exists():
        log.error("No history at %s yet; run `brain import` first", config.history_path)
        return 1
    try:
        text = run_profit(config, since, until)
    except sqlite3.Error as e:
        log.error("Couldn't read the history: %s", e)
        return 1
    except PredictionsError as e:
        log.error("Can't load the Predictions: %s", e)
        return 1
    print(text, end="")
    return 0


def run_profit(config: Config, since: date | None, until: date | None) -> str:
    """Realized profit (ADR-0039) from the start of `since` to the end of `until` (all of
    it without), per Market, as text."""
    predictions = load_predictions(config.predictions_path)
    start = 0 if since is None else start_of(since)
    end = 2**62 if until is None else start_of(until + timedelta(days=1)) - 1
    with closing(open_history(config.history_path)) as conn:
        markets = {
            market: realized(conn, config, market, predictions, start, end)
            for market in character_markets(conn)
        }
    if not markets:
        return "No Character has a Market yet.\n"
    return "\n".join(_render_profit(market, r) for market, r in markets.items())


def _backtest(
    config: Config, since: date | None, until: date | None, policies: list[str], start_gold: int
) -> int:
    if not config.history_path.exists():
        log.error("No history at %s yet; run `brain import` first", config.history_path)
        return 1
    try:
        text = run_backtest(config, since, until, policies, start_gold)
    except sqlite3.Error as e:
        log.error("Couldn't read the history: %s", e)
        return 1
    except PredictionsError as e:
        log.error("Can't load the Predictions: %s", e)
        return 1
    print(text, end="")
    return 0


def run_backtest(
    config: Config, since: date | None, until: date | None, policies: list[str], start_gold: int
) -> str:
    """The Backtest (#167, ADR-0032) over the Scans from the start of `since` to the end
    of `until` (all of them without), per Market, as text."""
    predictions = load_predictions(config.predictions_path)
    start = None if since is None else start_of(since)
    end = None if until is None else start_of(until + timedelta(days=1)) - 1
    with closing(open_history(config.history_path)) as conn:
        markets = backtest(conn, config, predictions, start, end, policies, start_gold)
    if not markets:
        return "No Character has a Market with a Scan yet.\n"
    low, high = config.backtest_grade_low, config.backtest_grade_high
    return "\n".join(_render_backtest(m, start_gold, low, high) for m in markets)


def _render_backtest(m: MarketBacktest, start_gold: int, low: float, high: float) -> str:
    table = _table(
        [
            "Policy",
            "P&L vendor mark",
            "P&L market mark",
            "Buys",
            "Units sold",
            "Won",
            "Lost",
            "Worst trade",
            f"Grader x{low:g} / x{high:g} vendor mark",
            f"Grader x{low:g} / x{high:g} market mark",
            "Max drawdown",
            "Gold low",
        ],
        [
            [
                name,
                _money(sim.profit()),
                _money(sim.profit(market=True)),
                str(len(sim.trades)),
                f"{sum(t.sold for t in sim.trades):g} of {sum(t.units for t in sim.trades)}",
                str(sum(1 for t in sim.trades if t.profit() > 0)),
                str(sum(1 for t in sim.trades if t.profit() < 0)),
                _money(min((t.profit() for t in sim.trades), default=0)),
                _bounds(m.bounds[name], market=False),
                _bounds(m.bounds[name], market=True),
                f"{sim.max_drawdown:.0%}",
                _money(sim.gold_low),
            ]
            for name, sim in m.runs.items()
        ],
    )
    splits = []
    for name, sim in m.runs.items():
        split = sim.split()
        splits.append(
            f"{name}: sold out in week 1 {_trades_line(split.sold_out_in_week_1)}; "
            f"relisted {_trades_line(split.relisted)}; the rest {_trades_line(split.rest)}\n"
        )
        if name in BUY_UNDER_POLICIES:
            # The pass bar is on the Sell way: a Vendor way can't lose this way (#173).
            ways = [
                f"{way} {_trades_line([t for t in sim.trades if t.way is way])}"
                for way in (Action.SELL, Action.VENDOR)
            ]
            splits.append(f"{name} by way: {'; '.join(ways)}\n")
    scans = "Scan" if m.scans == 1 else "Scans"
    return (
        f"{_graded_title(m.market)}\n"
        f"Backtested {m.scans} {scans} from {_money(start_gold)}, no buys in the last 7 days\n"
        f"{table}\n"
        + "".join(splits)
        + _gap_line(m, low, high)
        + _calibration_line("Grader", "sold", m.grader_calibration)
        + _calibration_line("Sell Rate", "Probable Sales", m.sell_rate_calibration)
        + "Flips to Disenchant not simulated.\n"
    )


def _gap_line(m: MarketBacktest, low: float, high: float) -> str:
    """The number the Dec 2 checkpoint reads (ADR-0039): how far the Brain's P&L at the
    vendor mark is above Auctionator's, as a share of Auctionator's, at the 1x grade and
    the grader's bounds (x1, then low and high). To 0.1%, since its bands are at 5% and
    10%. None at a grade where Auctionator made 0c. Nothing unless both ran."""
    if "brain" not in m.runs or AUCTIONATOR not in m.runs:
        return ""
    (brain_low, brain_high), (auctionator_low, auctionator_high) = (
        m.bounds["brain"],
        m.bounds[AUCTIONATOR],
    )
    grades = [
        ("x1", m.runs["brain"], m.runs[AUCTIONATOR]),
        (f"x{low:g}", brain_low, auctionator_low),
        (f"x{high:g}", brain_high, auctionator_high),
    ]
    gaps = []
    for grade, brain, auctionator in grades:
        if not auctionator.profit():
            gaps.append(f"none at {grade}")
            continue
        gap = (brain.profit() - auctionator.profit()) / abs(auctionator.profit())
        gaps.append(f"{gap:+.1%} at {grade}")
    made_nothing = any(gap.startswith("none") for gap in gaps)
    return (
        f"Dec 2 gap, (brain - {AUCTIONATOR}) / |{AUCTIONATOR}| on P&L vendor mark: "
        f"{', '.join(gaps)}{f' ({AUCTIONATOR} made 0c)' if made_nothing else ''}\n"
    )


def _bounds(bounds: tuple[Simulation, Simulation], market: bool) -> str:
    """The P&L of the runs at the grader's low and high bounds, at one mark."""
    low, high = bounds
    return f"{_money(low.profit(market))} / {_money(high.profit(market))}"


def _calibration_line(rule: str, calls: str, c: Calibration) -> str:
    """How `rule` did on own Listings, whose mail says what became of them. `calls` is
    what it calls the ones it thinks sold."""
    if not c.matched:
        return f"{rule} checked on own Listings: no Listing it calls {calls} matched a mail.\n"
    caught = f"{c.sold / c.sold_mails:.0%}" if c.sold_mails else "none"
    return (
        f"{rule} checked on own Listings: of {c.matched} it calls {calls} that a mail matched, "
        f"{c.sold / c.matched:.0%} really sold; it caught {caught} of the {c.sold_mails} "
        "Sold mails.\n"
    )


def _trades_line(trades: Sequence[Trade]) -> str:
    """How many trades, what they made at the vendor mark, and what they cost."""
    made = sum(t.profit() for t in trades)
    spent = sum(t.cost for t in trades)
    return f"{len(trades)} made {_money(made)} on {_money(spent)} spent"


def _graded_title(market: Market) -> str:
    """A Market's name over something graded on its history: Beta's is provisional."""
    title = f"{market.realm} {market.faction} ({market.era.value})"
    if market.era is Era.BETA:
        title += ": provisional, Beta never decides"
    return title


def _render_profit(market: Market, r: Realized) -> str:
    return (
        f"{_graded_title(market)}\n"
        f"Realized profit over the range: {_money(r.profit)}\n"
        f"{_for_use_line(r.for_use)}"
    )


def _for_use_line(for_use: Sequence[Purchase]) -> str:
    """How many Purchases were For Use, and what they cost (#55): out of realized profit,
    as ADR-0007 counts the Unlinked Outcomes."""
    noun = "Purchase" if len(for_use) == 1 else "Purchases"
    cost = _money(sum(p.price for p in for_use))
    return f"{len(for_use)} {noun} ({cost}) not named by the Brain, counted as For Use\n"


def _flips(config: Config) -> int:
    if not config.history_path.exists():
        log.error("No history at %s yet; run `brain import` first", config.history_path)
        return 1
    try:
        text = run_flips(config)
    except sqlite3.Error as e:
        log.error("Couldn't read the history: %s", e)
        return 1
    except PredictionsError as e:
        log.error("Can't load the Predictions: %s", e)
        return 1
    except GradesError as e:
        log.error("Can't load the Grades: %s", e)
        return 1
    print(text, end="")
    return 0


def _disenchants(config: Config) -> int:
    if not config.history_path.exists():
        log.error("No history at %s yet; run `brain import` first", config.history_path)
        return 1
    try:
        text = run_disenchants(config)
    except sqlite3.Error as e:
        log.error("Couldn't read the history: %s", e)
        return 1
    print(text, end="")
    return 0


def run_disenchants(config: Config) -> str:
    """The Disenchant tables checked against the player's Disenchant Results (#76,
    ADR-0018), per Era, as text. Only a person changes the tables."""
    table = load_table()
    eras = dict.fromkeys(install.era for install in config.installs)
    parts = []
    with closing(open_history(config.history_path)) as conn:
        for era in eras:
            results = disenchant_results(conn, era)
            if results:
                min_results = config.disenchant_check_min_results
                check = check_disenchants(table, results, min_results)
                parts.append(_render_disenchants(era, len(results), check, min_results))
    if not parts:
        return "No Disenchant Results yet.\n"
    return "\n".join(parts)


_QUALITIES = {2: "Green", 3: "Blue", 4: "Purple"}


def _group_name(group: Group) -> str:
    """A Disenchant source group's name, e.g. "Green armor ilvl 16-20"."""
    kind = "armor" if group.kind == "armor" else "weapons"
    return f"{_QUALITIES[group.quality]} {kind} ilvl {group.min_level}-{group.max_level}"


def _render_disenchants(era: Era, count: int, check: DisenchantCheck, min_results: int) -> str:
    text = (
        f"{era.value.capitalize()}: {count} Disenchant Results, a group judged from {min_results}\n"
    )
    if check.unplaced:
        text += (
            f"{check.unplaced} of them have no group: the item wasn't known, or no band has it\n"
        )
    groups: dict[Group, list[MatCheck]] = {}
    for row in check.rows:
        groups.setdefault(row.group, []).append(row)
    for group, checks in groups.items():
        text += f"\n{_group_name(group)}\n"
        text += _table(
            ["Mat", "n", "Chance (95%)", "Table", "Qty when it drops (95%)", "Table", "Verdict"],
            [
                [
                    str(c.item_id),
                    str(c.n),
                    f"{c.chance:.1%} ({c.chance_interval[0]:.1%} to {c.chance_interval[1]:.1%})",
                    f"{c.table_chance:.1%}",
                    _mean_qty(c),
                    "-" if c.table_qty is None else f"{c.table_qty:.2f}",
                    c.verdict.value,
                ]
                for c in checks
            ],
        )
    return text


def _mean_qty(c: MatCheck) -> str:
    if c.qty is None:
        return "-"
    if c.qty_interval is None:
        return f"{c.qty:.2f}"
    low, high = c.qty_interval
    return f"{c.qty:.2f} ({low:.2f} to {high:.2f})"


def run_recommend(
    config: Config, chain: str | None = None, why_not: str | None = None, beta_ratios: bool = False
) -> str:
    """The Recommendations for every Market the player has Characters in, as text, or
    with `chain` an Item Key's Craft rows as their Craft Chains (#77), or with `why_not`
    why Item Keys on sale aren't Flips on the Shopping List: "" for each Market's near
    misses, else for the Item Key or item name it matches (#108). The Beta/Live Fair Value
    ratios are shown while the Beta Sell Rate is on, or with `beta_ratios` (#110)."""
    predictions = load_predictions(config.predictions_path)
    with closing(open_history(config.history_path)) as conn:
        markets = recommend(conn, config, predictions, why_not=why_not is not None)
        if not markets:
            return "No Character has a Market with a Scan yet.\n"
        if chain is not None:
            return "\n".join(_render_chains(m, chain) for m in markets)
        if why_not == "":
            return "\n".join(_render_near_misses(m) for m in markets)
        if why_not is not None:
            return _render_why_not(markets, why_not)
        # Now, not the Scan: a Purchase after the latest Scan is matched to it (#60).
        now = int(time.time())
        made = {m.market: flips(conn, config, m.market, predictions, now) for m in markets}
        to_craft = {
            m.market: craft_flips(conn, config, m.market, predictions, now) for m in markets
        }
    range_days = config.sell_rate_range_seconds // 86400
    weight = config.beta_sell_rate_weight
    return "\n".join(
        _render_market(m, range_days, made[m.market], to_craft[m.market])
        + (_render_beta_ratios(m, weight) if weight or beta_ratios else "")
        for m in markets
    )


def _render_market(
    m: MarketRecommendations,
    range_days: int,
    made: Sequence[Flip],
    to_craft: Sequence[CraftFlip],
) -> str:
    as_of = datetime.fromtimestamp(m.as_of).strftime("%Y-%m-%d %H:%M")
    held = held_units(m.holdings)
    holdings = _table(
        ["Item", "Action", "Qty", "Price", "Profit", "Margin", "Sales", "ROI", "Note"],
        [
            [
                r.item_key,
                _action(r),
                str(r.quantity),
                _money(r.price),
                "unknown" if r.action is Action.HOLD else _money(r.profit),
                _money(r.margin),
                _count(r.sale_events),
                _roi(r, held[r.item_key]),
                f"under {r.prediction}" if r.prediction else r.note,
            ]
            for r in m.holdings
        ],
    )
    shopping = _table(
        [
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
        ],
        [
            [
                _group_name(r.disenchant.group) if r.disenchant else r.item_key,
                _action(r),
                str(r.quantity),
                _money(r.price),
                _money(r.profit),
                *_measures(r),
                _money(r.cost),
                _count(r.sale_events),
                r.note,
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
    buy_under = _table(
        ["Item", "Buy Under", "Way out", "Units", "Seen"],
        [
            [
                _buy_under_item(b),
                _money(b.price),
                _way_out_label(b),
                "no limit" if b.units is None else str(b.units),
                _seen(b),
            ]
            for b in m.buy_under
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
        profitable = sum(g.proceeds + g.open_value > g.cost for g in m.grades)
        brake = "halved" if m.pooled_return < 0 else "not halved"
        record = (
            f"Graded Predictions: {len(m.grades)} graded, {profitable} profitable, "
            f"pooled return {_percent(m.pooled_return)}, caps {brake}"
        )
    market = f"{m.market.realm} {m.market.faction} ({m.market.era.value})"
    budget = "" if m.budget is None else f" (Budget {_money(m.budget)} of {_money(m.gold)})"
    least_profit = f", each making at least {_money(m.min_profit)}" if m.min_profit else ""
    if m.min_profit and m.min_profit_per_click:
        least_profit += f" and {_money(m.min_profit_per_click)} a click"
    return (
        f"{market}, as of the Scan at {as_of}\n"
        f"Sell Rate observed for {m.window_hours:.1f} h in the last {range_days} days\n"
        f"Sold Outcomes not linked to an Item Key by name: {m.unlinked_sales}\n\n"
        f"Holdings\n{holdings}\n"
        f"Shopping List, options each sized on its own within {_money(m.spend)}"
        f"{budget}{least_profit}\n"
        f"{shopping}\n"
        f"Buy to Hold under a Prediction, upside unknown: {_money(m.prediction_cost)} in total\n"
        f"{prediction_buys}\n"
        f"Buy Under\n{buy_under}\n"
        f"{record}\n"
        f"{graded}"
        f"{_flip_record(made)}\n"
        f"{_flip_record(to_craft, 'Flips to Craft')}\n"
    )


def _render_beta_ratios(m: MarketRecommendations, weight: float) -> str:
    """Each active Prediction Item Key's Beta/Live Fair Value ratio (#110): whether Beta's
    prices look like Live's, before the Beta Sell Rate is turned on. Nothing once it may
    no longer count."""
    if not m.beta_ratios:
        return ""
    table = _table(
        ["Item", "Beta/Live"], [[k, f"{r:.2f}"] for k, r in sorted(m.beta_ratios.items())]
    )
    on = f"x{weight:g}" if weight else "off"
    return f"Beta/Live Fair Value of the Predictions' Item Keys (Beta Sell Rate {on})\n{table}"


def _flip_record(made: Sequence[Flip] | Sequence[CraftFlip], kind: str = "Flips") -> str:
    """The graded Flips' record line (#60), of one `kind`: Flips to Sell or to Craft (#114)."""
    r = flip_record(made)
    if r is None:
        return f"Graded {kind}: none yet"
    days = "" if r.median_days is None else f"{r.median_days:.2f}"
    return (
        f"Graded {kind}: {r.graded} graded, {r.paid_off} paid off, "
        f"realized/expected Profit {_percent(r.realized_over_expected)}, "
        f"price/Post at {_percent(r.price_over_post_at)} (median), "
        f"sold within horizon {_percent(r.sold_within)}, median days to sell {days}"
    )


def run_flips(config: Config) -> str:
    """Each Market's Flips to Sell (#60) and Flips to Craft (#114) made, graded or
    pending, as text. Working out what a past Scan named is slow, so each is worked out
    once and frozen in grades.toml."""
    predictions = load_predictions(config.predictions_path)
    now = int(time.time())
    with closing(open_history(config.history_path)) as conn:
        made = {}
        to_craft = {}
        for_use = {}
        crafted = {}
        for market in character_markets(conn):
            times = scan_times(conn, market)
            if times:
                made[market] = flips(conn, config, market, predictions, now)
                to_craft[market] = craft_flips(conn, config, market, predictions, now)
                bought = [p for p in purchases(conn, market) if happened_at(p) <= now]
                for_use[market] = split_purchases(conn, config, market, predictions, bought).for_use
                costed = sum(lot.crafted for lot in market_lots(conn, config, market, predictions))
                crafted[market] = (len(crafts(conn, market)), costed)
    if not made:
        return "No Character has a Market with a Scan yet.\n"
    return "\n".join(
        _render_flips(market, f, for_use[market], crafted[market])
        + _render_craft_flips(to_craft[market])
        for market, f in made.items()
    )


def _crafts_line(recorded: int, costed: int) -> str:
    """How many Craft Results the Addon recorded, and how many opened an output Lot (#44),
    so gaps in what it records show."""
    return f"Crafts recorded: {recorded} ({costed} with a costed output)\n"


def _render_flips(
    market: Market,
    made: Sequence[Flip],
    for_use: Sequence[Purchase],
    crafted: tuple[int, int],
) -> str:
    title = _graded_title(market)
    table = _table(
        ["Item", "Bought", "Units", "Post at", "Sold at", "Days", "Grade"],
        [
            [
                f.item_key,
                datetime.fromtimestamp(f.bought_at).strftime("%Y-%m-%d %H:%M"),
                str(f.units),
                _money(f.named.post_at),
                _money(f.realized_price),
                _last_sale(f),
                "pending" if f.grade is None else _money(f.grade.realized),
            ]
            for f in made
        ],
    )
    return f"{title}\n{table}{_flip_record(made)}\n{_for_use_line(for_use)}{_crafts_line(*crafted)}"


def _render_craft_flips(made: Sequence[CraftFlip]) -> str:
    """The Flips to Craft section (#114), apart from the Flips to Sell: by its output, its
    output units graded, and what they sold at against the row's Post at."""
    table = _table(
        ["Item", "Recipe", "Bought", "Units", "Post at", "Sold at", "Days", "Grade"],
        [
            [
                f.named.item_key,
                str(f.recipe_id),
                datetime.fromtimestamp(f.bought_at).strftime("%Y-%m-%d %H:%M"),
                "" if f.grade is None else str(f.grade.units),
                _money(f.named.post_at),
                _money(f.realized_price),
                _last_sale(f),
                _craft_grade(f),
            ]
            for f in made
        ],
    )
    skipped = Counter(f.not_gradable for f in made if f.not_gradable is not None)
    lines = "".join(
        f"{n} Flip{'s' if n != 1 else ''} to Craft not gradable: {why.value}\n"
        for why, n in sorted(skipped.items())
    )
    return f"\nFlips to Craft\n{table}{_flip_record(made, 'Flips to Craft')}\n{lines}"


def _craft_grade(f: CraftFlip) -> str:
    if f.not_gradable is not None:
        return "not gradable"
    return "pending" if f.grade is None else _money(f.grade.realized)


def _last_sale(f: Flip | CraftFlip) -> str:
    """Days from the Purchase to the last sale within the horizon, if any."""
    if f.grade is None or not f.grade.sale_days:
        return ""
    return f"{f.grade.sale_days[-1]:.2f}"


def _market_title(m: MarketRecommendations) -> str:
    return f"{m.market.realm} {m.market.faction} ({m.market.era.value})\n"


def _render_near_misses(m: MarketRecommendations) -> str:
    """The Market's closest near misses (#108): those short of the Flip margin first, by
    how far short, then the rest by how close they came."""
    misses = sorted(
        (w for w in m.why_not if w.failed is not None),
        key=lambda w: (w.failed is not Check.MARGIN, _shortfall(w)),
    )[:NEAR_MISSES]
    table = _table(
        ["Item", "Item Key", "Check", "Gap"],
        [[w.name or "?", w.item_key, w.failed.value, _numbers(w, w.failed)] for w in misses],
    )
    return f"{_market_title(m)}Why not: the {NEAR_MISSES} closest near misses\n{table}"


def _render_why_not(markets: list[MarketRecommendations], item: str) -> str:
    """Every Check of the one Item Key on sale that `item` is, or else is part of the name
    of, in each Market it's on sale in (#108). Several matches are listed instead. A
    Prediction buy's Item Key, matched by Item Key only, shows its Beta room (#110)."""
    candidates = {r.item_key: None for m in markets for r in m.prediction_buys}
    candidates |= {w.item_key: w.name for m in markets for w in m.why_not}
    if item in candidates:
        found = {item: candidates[item]}
    else:
        found = {k: n for k, n in candidates.items() if item.lower() in (n or "").lower()}
    if not found:
        return f"No Item Key on sale matches '{item}'.\n"
    if len(found) > 1:
        listed = "".join(f"  {_item_label(n, k)}\n" for k, n in sorted(found.items(), key=_by_name))
        return f"{len(found)} Item Keys match '{item}':\n{listed}"
    [item_key] = found
    return "\n".join(
        [
            _market_title(m) + _render_checks(w, m)
            for m in markets
            for w in m.why_not
            if w.item_key == item_key
        ]
        + [
            _market_title(m) + _render_prediction_buy(r)
            for m in markets
            for r in m.prediction_buys
            if r.item_key == item_key
        ]
    )


def _render_prediction_buy(r: Row) -> str:
    """A Prediction buy, and how much of the room its Max Loss counted on came from the
    Beta Sell Rate (#110)."""
    head = f"{r.item_key}: Prediction buy of {r.quantity} under {r.prediction}\n"
    b = r.beta_room
    if b is None:
        return f"{head}  no Beta Sell Rate\n"
    return f"{head}  room for {b.room} at {_money(b.post_at)}, {b.from_beta} of it from Beta\n"


def _by_name(found: tuple[str, str | None]) -> tuple[str, str]:
    item_key, name = found
    return (name or "", item_key)


def _item_label(name: str | None, item_key: str) -> str:
    return item_key if name is None else f"{name} ({item_key})"


def _render_checks(w: WhyNot, m: MarketRecommendations) -> str:
    """Each Check of `w` in order, passed, failed or not reached ("-"), with its numbers,
    and its Shopping List rows if it made the list."""
    verdict = "made the list" if w.failed is None else w.failed.value
    lines = [[check.value, *_check(w, check)] for check in Check]
    listed = [
        r
        for r in m.shopping_list
        if r.item_key == w.item_key and r.action in (Action.SELL, Action.VENDOR)
    ]
    rows = "".join(
        f"  {r.action.value} {r.quantity} up to {_money(r.price)}: {_money(r.profit)} profit\n"
        for r in listed
    )
    return f"{_item_label(w.name, w.item_key)}: {verdict}\n{rows}{_lines(lines)}"


def _check(w: WhyNot, check: Check) -> tuple[str, str]:
    """Whether `w` passed `check` ("pass", "fail", or "-" if it never got that far) and
    the numbers behind it."""
    order = list(Check)
    if w.failed is not None and order.index(check) > order.index(w.failed):
        return "-", ""
    match check:
        case Check.SALE_EVENTS:
            passed = w.sale_events >= w.min_sale_events
        case Check.ROOM:
            passed = w.room >= w.held + w.needs
        case _:
            passed = check is not w.failed
    return ("pass" if passed else "fail"), _numbers(w, check)


def _shortfall(w: WhyNot) -> float:
    """How far short of its failed Check a near miss is, as a share of what it needed."""
    match w.failed:
        case Check.SALE_EVENTS:
            return (w.min_sale_events - w.sale_events) / w.min_sale_events
        case Check.ROOM:
            return (w.held + w.needs - w.room) / (w.held + w.needs)
        case Check.MARGIN:
            return math.inf if w.clear_at is None else (w.ask - w.clear_at) / w.ask
        case Check.DROPPED:
            return 0.0
        case Check.BUDGET:
            return (w.cost - w.spend) / w.cost
        case Check.MIN_PROFIT:
            return (w.min_profit - w.profit) / w.min_profit
        case Check.ROW_CAP:
            return (w.rank - w.rows) / w.rank


def _minute(at: int) -> str:
    return datetime.fromtimestamp(at).strftime("%Y-%m-%d %H:%M")


def _numbers(w: WhyNot, check: Check) -> str:
    """The numbers behind one Check of `w`."""
    match check:
        case Check.SALE_EVENTS:
            counted = f"{w.sale_events}/{w.min_sale_events} Sale Events"
            if w.cheap_since is None:
                return counted
            since = _minute(w.cheap_since)
            breaks = ", ".join(_minute(t) for t in w.cheap_breaks)
            note = f" (none at {breaks})" if breaks else ""
            return f"{counted} since cheaper Listings went up {since}{note}"
        case Check.ROOM:
            at = "" if w.post_at is None else f" at {_money(w.post_at)}"
            return f"room for {w.room}{at}, needs {w.held} held + {w.needs}"
        case Check.MARGIN:
            if w.clear_at is None:
                return f"ask {_money(w.ask)}, no way out"
            short = w.ask - w.clear_at
            return (
                f"ask {_money(w.ask)}, clears at {_money(w.clear_at)}: "
                f"{_money(short)} ({short / w.ask:.1%})"
            )
        case Check.DROPPED:
            return "the latest Scan dropped rows of it" if w.failed is check else ""
        case Check.BUDGET:
            return f"cheapest run {_money(w.cost)}, spend {_money(w.spend)}"
        case Check.MIN_PROFIT:
            by = w.min_profit_by
            if by == "clicks":
                by = f"{w.clicks} clicks x {_money(w.min_profit / w.clicks)}"
            return f"best row makes {_money(w.profit)}, needs {_money(w.min_profit)} ({by})"
        case Check.ROW_CAP:
            return f"best place {w.rank}, top {w.rows} kept"


def _render_chains(m: MarketRecommendations, item_key: str) -> str:
    market = _market_title(m)
    crafts = [
        (where, r)
        for where, rows in (("Holdings", m.holdings), ("Shopping List", m.shopping_list))
        for r in rows
        if r.item_key == item_key and r.action is Action.CRAFT
    ]
    if not crafts:
        return f"{market}No Craft row of {item_key}.\n"
    return market + "\n".join(
        _render_chain(f"{where}: Craft {r.quantity} of {item_key}", r) for where, r in crafts
    )


def _render_chain(title: str, row: Row) -> str:
    """A Craft row's Craft Chain as a tree, as the Addon's panel draws it (#77)."""
    lines: list[tuple[str, str]] = []

    def walk(nodes: Sequence[ChainNode], indent: str, connected: bool) -> None:
        for i, node in enumerate(nodes):
            last = i == len(nodes) - 1
            connector = ("`- " if last else "|- ") if connected else ""
            lines.append((indent + connector + _node_label(node), _signed(node.gold)))
            below = indent + (("   " if last else "|  ") if connected else "")
            walk(node.children, below, True)

    walk(row.chain, "", False)
    lines.append(("Profit", _signed(row.profit)))
    width = max(len(label) for label, _ in lines)
    return f"{title}\n" + "".join(
        f"  {label.ljust(width)}  {gold}".rstrip() + "\n" for label, gold in lines
    )


def _node_label(node: ChainNode) -> str:
    what = f"{node.quantity} {node.item_key}"
    label = {
        NodeKind.SELL: f"Sell {what} @ {_money(node.post_at)}",
        NodeKind.VENDOR: f"Vendor {what}",
        NodeKind.CRAFT: f"Craft {what} on {node.character} x {node.crafts}",
        NodeKind.USE: f"Use {what} held",
        NodeKind.BUY: f"Buy {what} AH <= {_money(node.max_unit_price)}",
        NodeKind.MERCHANT: f"Merchant {what}",
        NodeKind.LEFTOVER: f"Leftover {what}",
        NodeKind.DISENCHANT: f"Disenchant {what}",
    }[node.kind]
    return f"{label} (blocked: {node.blocked})" if node.blocked else label


def _signed(copper: float | None) -> str:
    if copper is None:
        return "?"
    return _money(copper) if copper < 0 else "+" + _money(copper)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "  (nothing)\n"
    return _lines([headers, *rows])


def _lines(lines: list[list[str]]) -> str:
    """Rows of cells in columns as wide as their widest cell, indented two spaces."""
    widths = [max(len(cell) for cell in column) for column in zip(*lines, strict=True)]
    return "".join(
        "  "
        + "  ".join(cell.ljust(w) for cell, w in zip(line, widths, strict=True)).rstrip()
        + "\n"
        for line in lines
    )


def _buy_under_item(buy: BuyUnder) -> str:
    """The Item Key, or a Disenchant source group's name."""
    return str(buy.item_key) if buy.group is None else _group_name(buy.group)


def _way_out_label(buy: BuyUnder) -> str:
    if buy.way is Action.CRAFT:
        return f"Craft {buy.output} ({buy.crafter})"
    if buy.way is Action.DISENCHANT:
        return f"Disenchant ({buy.disenchanter})"
    return buy.way.value


def _seen(buy: BuyUnder) -> str:
    scans = "Scan" if buy.seen == 1 else "Scans"
    now = ", listed now" if buy.listed_now else ""
    return f"{buy.seen} {scans} / {buy.window_days}d{now}"


def _action(row: Row) -> str:
    return "-" if row.action is None else row.action.value


def _count(n: int | None) -> str:
    return "" if n is None else str(n)


def _percent(share: float | None) -> str:
    return "" if share is None else f"{share:.1%}"


def _measures(row: Row) -> list[str]:
    """A Shopping List row's Per click, Per day and ROI (#98). A Flip to Craft or to
    Disenchant has none."""
    if row.listings is None or row.disenchant is not None:
        return ["", "", ""]
    day = per_day(row)
    return [
        _money(per_click(row)),
        "now" if day == math.inf else _money(day),
        _percent(return_on_cost(row)),
    ]


def _roi(row: Row, held: int) -> str:
    """A Holdings row's ROI on what its units cost (#50), `*` when it's a good time to
    sell, and how many of the Item Key's `held` units that rests on if not all."""
    if row.roi is None:
        return ""
    text = f"{row.roi:+.1%}" + (" *" if row.roi_hint else "")
    return text if row.paid_units == held else f"{text} on {row.paid_units} of {held}"


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


def _pool(config: Config, command: str, since: date | None) -> int:
    pool = make_pool(config)
    if pool is None:
        log.error("The Scan Pool is off: set pool_url and pool_key in the config to use it")
        return 1
    config.history_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(open_history(config.history_path)) as conn:
            if command == "push":
                report = push(conn, pool, config)
            else:
                start = None
                if since is not None:
                    day = datetime(since.year, since.month, since.day, tzinfo=UTC)
                    start = int(day.timestamp())
                report = pull(conn, pool, config, since=start)
                if report.pulled or report.rolled_back:
                    _write_recommendations(conn, config)
    except (OSError, sqlite3.Error) as e:
        log.error("Couldn't sync with the Scan Pool: %s", e)
        return 1
    log.info(report.summary())
    return 1 if report.failed else 0


def _pool_key(config: Config, action: str, name: str) -> int:
    if config.pool_url is None or config.pool_admin_secret is None:
        log.error(
            "Only the pool admin can add or revoke keys: set pool_url and pool_admin_secret "
            "(the Worker's ADMIN_SECRET) in the config"
        )
        return 1
    admin = PoolAdmin(config.pool_url, config.pool_admin_secret)
    try:
        if action == "add":
            key = admin.add_key(name)
            log.info("Give %s this key; the pool won't show it again:", name)
            print(key)
        else:
            admin.revoke_key(name)
            log.info("Revoked %s; their Scans leave every Brain at its next pull", name)
    except PoolError as e:
        log.error("The Scan Pool refused: %s", e)
        return 1
    return 0


def make_pool(config: Config) -> Pool | None:
    """The Scan Pool, or None when it's off (pool_url or pool_key unset)."""
    if config.pool_url is None or config.pool_key is None:
        return None
    return HttpPool(config.pool_url, config.pool_key)


def pool_syncer(
    config: Config,
    pool: Pool | None = None,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], float] = time.time,
    fair_value_cache: FairValueCache | None = None,
) -> PoolSyncer | None:
    """The watcher's PoolSyncer, which tells the Addon when a long pull starts and ends;
    None when the pool is off. `pool`, `clock` and `now` stand in for the real ones in
    tests. `fair_value_cache` is the watcher's, so the import after a long pull reuses the
    Fair Values its rewrite computed."""
    pool = pool or make_pool(config)
    if pool is None:
        return None

    def announce(catching_up_since: int | None, problem: str | None) -> None:
        started = time.monotonic()
        with closing(open_history(config.history_path)) as conn:
            _write_recommendations(
                conn,
                config,
                fair_value_cache=fair_value_cache,
                problem=problem,
                catching_up_since=catching_up_since,
            )
        # After a long pull, this is the Decision Engine's first pass over what it brought.
        log.info(
            "Told the Addon a long pull from the Scan Pool %s, in %.1fs",
            "started" if catching_up_since is not None else "ended",
            time.monotonic() - started,
        )

    return PoolSyncer(config, pool, clock=clock, now=now, announce=announce)


def watch_fair_value_cache() -> FairValueCache:
    """The watcher's cache: kept for as long as it runs, so each pass only computes the new
    Scans' Fair Values (#105), and in the history, so a restart doesn't compute them all
    again either (#145)."""
    return FairValueCache(keep_in_history=True)


def _watch(config: Config) -> int:
    watcher = Watcher(settle_seconds=SETTLE_SECONDS)
    fair_value_cache = watch_fair_value_cache()
    pool_sync = pool_syncer(config, fair_value_cache=fair_value_cache)
    folders = ", ".join(str(i.path) for i in config.installs)
    log.info("Watching %s in %s (Ctrl+C to stop)", SAVEDVARIABLES_FILE, folders)
    if pool_sync is not None:
        log.info("Syncing with the Scan Pool at %s", config.pool_url)
    try:
        while True:
            watch_step(config, watcher, fair_value_cache=fair_value_cache, pool_sync=pool_sync)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        return 0
    except Exception:
        # watch_step carries on past a bad pass, so this is a bug. A guildie only learns
        # the Brain stopped from the Addon (#115), so tell it, if the history still opens.
        log.exception("The Brain stopped after an error")
        try:
            with closing(open_history(config.history_path)) as conn:
                _write_recommendations(conn, config, problem=CRASHED)
        except Exception:
            log.exception("Couldn't tell the Addon the Brain stopped")
        return 1


def watch_step(
    config: Config,
    watcher: Watcher,
    clock: Callable[[], float] = time.monotonic,
    fair_value_cache: FairValueCache | None = None,
    pool_sync: PoolSyncer | None = None,
) -> None:
    ready: list[Path] = []
    try:
        # Re-listed every time so a newly created account folder is picked up.
        noticed = clock()
        ready = watcher.poll(savedvariables_files(config), now=noticed)
        if not ready:
            if pool_sync is not None:
                pool_sync.tick()
            return
        timings = Timings(clock)
        if pool_sync is not None:
            with timings.stage("pool pull"):
                pool_sync.before_import()
        results = run_import(
            config,
            ready,
            fair_value_cache=fair_value_cache,
            timings=timings,
            problem=pool_sync.problem if pool_sync is not None else None,
        )
        _log_results(results)
        failed = [r.path for r in results if r.error is not None]
        imported = len(failed) < len(results)
        if imported:
            # Up to Recommendations.lua written: what the Addon's RELOAD_READY_AFTER guesses
            # at (#71), less the settle time. Not logged when every file failed.
            log.info("Import took %.1fs", clock() - noticed)
        if pool_sync is not None:
            # After the total above, since the Addon doesn't wait on it.
            with timings.stage("pool push"):
                pool_sync.after_import()
        if imported:
            _log_stages(config, timings)
    except Exception:
        # A long-running watcher logs and carries on rather than exit on one bad pass.
        log.exception("Import failed; will try again")
        failed = ready
    for path in failed:
        watcher.retry(path, now=clock())


BACKTEST_POLICIES = [*POLICIES, *BUY_UNDER_POLICIES, AUCTIONATOR]


def _policies(text: str) -> list[str]:
    """`--policy`'s comma-separated Backtest policies."""
    names = [name.strip() for name in text.split(",") if name.strip()]
    unknown = [name for name in names if name not in BACKTEST_POLICIES]
    if unknown or not names:
        raise argparse.ArgumentTypeError(
            f"unknown policy {', '.join(unknown)}; pick from {', '.join(BACKTEST_POLICIES)}"
        )
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="brain", description=__doc__.splitlines()[0])
    parser.add_argument(
        "--config",
        type=Path,
        help=f"default: ./{CONFIG_FILE}, else %%LOCALAPPDATA%%\\{APP_FOLDER}\\{CONFIG_FILE}",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("import", help="import every SavedVariables file once")
    commands.add_parser("watch", help="import SavedVariables files whenever they change")
    commands.add_parser("rebuild", help="recreate the history database from the Archive")
    recommending = commands.add_parser(
        "recommend", help="print what to do with Holdings, and what to buy"
    )
    recommending.add_argument(
        "--chain", metavar="ITEM_KEY", help="print the Craft Chains of an Item Key's Craft rows"
    )
    recommending.add_argument(
        "--why-not",
        nargs="?",
        const="",
        metavar="ITEM",
        help="print why items on sale aren't Flips on the Shopping List: the near misses, "
        "or every check of one Item Key or item name; for a Prediction buy's Item Key, how "
        "much of its room came from Beta",
    )
    recommending.add_argument(
        "--beta-ratios",
        action="store_true",
        help="print the Beta/Live Fair Value ratio of each Prediction's Item Keys early in "
        "Live, even with beta_sell_rate_weight at 0",
    )
    profit = commands.add_parser("profit", help="realized profit from own sales over a range")
    profit.add_argument("--since", type=date.fromisoformat, help="first day, YYYY-MM-DD")
    profit.add_argument("--until", type=date.fromisoformat, help="last day, YYYY-MM-DD")
    backtesting = commands.add_parser(
        "backtest", help="trade the past Scans from a start gold and grade it by the sales after"
    )
    backtesting.add_argument("--since", type=date.fromisoformat, help="first day, YYYY-MM-DD")
    backtesting.add_argument("--until", type=date.fromisoformat, help="last day, YYYY-MM-DD")
    backtesting.add_argument(
        "--policy",
        action="extend",
        type=_policies,
        help=f"comma-separated or repeated, of {', '.join(BACKTEST_POLICIES)} (default brain)",
    )
    backtesting.add_argument(
        "--start-gold",
        type=float,
        default=START_GOLD / 10000,
        help="simulated gold to start from, in gold (default 40)",
    )
    commands.add_parser(
        "flips", help="grade the Flips to Sell and to Craft made: did they sell as named"
    )
    commands.add_parser(
        "disenchants", help="check the Disenchant tables against your Disenchant Results"
    )
    benching = commands.add_parser(
        "bench", help="time two Decision Engine passes on a copy of the history, by stage"
    )
    benching.add_argument(
        "--out",
        type=Path,
        help="keep the history copy and the Recommendations.lua written in this folder",
    )
    pooling = commands.add_parser("pool", help="sync with the Scan Pool by hand")
    pool_commands = pooling.add_subparsers(dest="pool_command", required=True)
    pool_commands.add_parser("push", help="upload your Scans the pool doesn't have yet")
    pulling = pool_commands.add_parser(
        "pull", help="download and import other members' Scans since the last pull"
    )
    pulling.add_argument(
        "--since",
        type=date.fromisoformat,
        help="go back to this day (YYYY-MM-DD, UTC) instead of the last pull",
    )
    keys = pool_commands.add_parser("key", help="the pool admin only: add or revoke member keys")
    key_commands = keys.add_subparsers(dest="key_command", required=True)
    key_commands.add_parser("add", help="make a member key and print it").add_argument("name")
    key_commands.add_parser(
        "revoke", help="revoke a member's key and roll back their Scans"
    ).add_argument("name")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    app_data = os.environ.get("LOCALAPPDATA")
    local_app_data = Path(app_data) if app_data else None
    config_path = find_config(args.config, Path.cwd(), local_app_data)
    if config_path is None:
        looked = config_candidates(Path.cwd(), local_app_data)
        log.error("No config found; looked for %s", " and ".join(map(str, looked)))
        return 2
    with _log_file(config_path.parent):
        return _run_command(args, config_path)


@contextmanager
def _log_file(data_dir: Path) -> Iterator[None]:
    """Also log to a file in the data folder for the duration of the block, so a guildie
    who never sees a console can still send what happened (#115). Rotated, so it can't
    grow forever. Nothing to log to when `--config` names a folder that isn't there:
    loading the config reports that."""
    if not data_dir.is_dir():
        yield
        return
    handler = RotatingFileHandler(
        data_dir / LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield
    finally:
        root.removeHandler(handler)
        handler.close()


def _run_command(args: argparse.Namespace, config_path: Path) -> int:
    try:
        config = load_config(config_path)
    except (ConfigError, OSError) as e:
        log.error("Can't load the config: %s", e)
        return 2

    if args.command == "pool" and args.pool_command == "key":
        return _pool_key(config, args.key_command, args.name)
    if args.command == "pool":
        return _pool(config, args.pool_command, getattr(args, "since", None))
    if args.command == "import":
        return _import_once(config)
    if args.command == "rebuild":
        return _rebuild(config)
    if args.command == "recommend":
        return _recommend(config, args.chain, args.why_not, args.beta_ratios)
    if args.command == "bench":
        return _bench(config, args.out)
    if args.command == "profit":
        return _profit(config, args.since, args.until)
    if args.command == "backtest":
        return _backtest(
            config,
            args.since,
            args.until,
            # Defaulted here: `extend` would add to a default list, not replace it.
            args.policy or ["brain"],
            round(args.start_gold * 10000),
        )
    if args.command == "disenchants":
        return _disenchants(config)
    if args.command == "flips":
        return _flips(config)
    # The data folder is the config's folder: the history, the Archive and grades.toml
    # already default to living next to it.
    with instance_lock(config_path.parent) as held:
        if not held:
            log.error("AzerothQuant Brain is already running.")
            return 1
        return _watch(config)


if __name__ == "__main__":
    sys.exit(main())
