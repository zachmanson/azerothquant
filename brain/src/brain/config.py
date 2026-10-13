"""Brain config: which WoW install folders to read, which Era each one belongs to,
and how long each Auction House time-left bucket can last.

Beta and Live data are never mixed (CONTEXT.md: Era), and the install folder a
SavedVariables file came from is what tells the Brain which Era it is.
"""

import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ConfigError(Exception):
    """The config file is missing something or contradicts itself."""


class Era(StrEnum):
    BETA = "beta"
    LIVE = "live"


@dataclass(frozen=True)
class Install:
    path: Path
    era: Era


# Longest time left in each bucket (1 = shortest), in minutes: <30m, 30m-2h, 2-12h, 12-24h.
# The labels are the Forever client's (#95); the last bucket ends at 24 h because Forever
# posts for 2, 8 or 24 h (#78), not retail's 48 h.
DEFAULT_TIME_LEFT_MAX_MINUTES = (30, 120, 12 * 60, 24 * 60)


# Longest gap between two Scans of a Market that still counts as an Observation Window
# (ADR-0004).
DEFAULT_OBSERVATION_WINDOW_MAX_MINUTES = 60

# A Scan more than this much older than its Market's latest is archived and waits for
# `brain rebuild` instead of re-matching the Market's tail (ADR-0026).
DEFAULT_POOL_REMATCH_HOURS = 48
DEFAULT_POOL_MIN_COMPLETENESS = 0.8
DEFAULT_POOL_COMPLETENESS_WINDOW = 10
DEFAULT_POOL_SYNC_MINUTES = 5
DEFAULT_POOL_BACKFILL_DAYS = 14


# Fair Value averages the cheapest this share of a Market's units of an Item Key (#21).
DEFAULT_FAIR_VALUE_SLICE_SHARE = 0.15
# Units in that slice priced under this share of its median are Flips, not the price.
DEFAULT_FAIR_VALUE_OUTLIER_SHARE = 0.5
# A Disappearance priced over this multiple of the Fair Value of the Scan it was last
# seen in is not a Probable Sale.
DEFAULT_PROBABLE_SALE_MAX_FAIR_VALUE_MULTIPLE = 1.2


# Sell Rate counts the Observation Windows that ended in this many days before now (#22).
DEFAULT_SELL_RATE_RANGE_DAYS = 14


# The Decision Engine (#23). The Auction House keeps this share of a sale: 5% at a
# faction Auction House, 15% at a neutral one.
DEFAULT_AH_CUT = 0.05
DEFAULT_NEUTRAL_AH_CUT = 0.15
# Only the held units Sell Rate says will sell within this many days are worth Selling.
DEFAULT_SALE_HORIZON_DAYS = 7
# A Flip to Sell must clear both this share of its buy price and this much copper per unit.
DEFAULT_FLIP_MIN_MARGIN_SHARE = 0.2
DEFAULT_FLIP_MIN_MARGIN_COPPER = 100
# The Sell Rate Prior: thin Sell Rate evidence is discounted as if this many more hours of
# Observation Window had been watched with no sales (#25). Lenient for Holdings, where too
# low a rate vendors what would have sold; strict for Flips, where too high a rate buys
# stock that sits.
DEFAULT_SELL_RATE_PRIOR_HOURS_HOLDINGS = 3
DEFAULT_SELL_RATE_PRIOR_HOURS_FLIPS = 24
# The Sale Size Prior: an Item Key's average Sale Event size is shrunk toward a typical
# size as if this many more Sale Events of that size had been seen (#24). Lenient and
# strict for the same reasons as the Sell Rate Prior.
DEFAULT_SALE_SIZE_PRIOR_EVENTS_HOLDINGS = 1
DEFAULT_SALE_SIZE_PRIOR_EVENTS_FLIPS = 5
# A buy is only resold on the Auction House when its Item Key's Sell Rate rests on at least
# this many Sale Events: one or two can be a single seller cancelling (#57).
DEFAULT_FLIP_MIN_SALE_EVENTS = 3
# A Flip to Sell is posted this many copper under the cheapest other player's Listing left
# once it's bought, so it sells first (#62).
DEFAULT_POST_UNDERCUT_COPPER = 1
# Predictions (ADR-0006): a unit is only bought under one while its Max Loss is at most
# this share of its cost, and the gold under Predictions is capped at these shares of the
# Market's pooled gold, per Prediction and in total.
DEFAULT_PREDICTION_MAX_LOSS_SHARE = 0.10
DEFAULT_PREDICTION_CAP_SHARE = 0.15
DEFAULT_PREDICTIONS_CAP_SHARE = 0.40
# Crafting (ADR-0008): one more craft is only made while it gains more than this many
# copper.
DEFAULT_CRAFT_MIN_GAIN = 0
DEFAULT_CRAFT_CHAIN_DEPTH = 3
# `brain disenchants` (#76, ADR-0018) judges a Disenchant source group's table only from
# this many Disenchant Results.
DEFAULT_DISENCHANT_CHECK_MIN_RESULTS = 20
DEFAULT_SHOPPING_LIST_ROWS = 50
DEFAULT_CRAFT_LIST_ROWS = 25
DEFAULT_DISENCHANT_LIST_ROWS = 10
DEFAULT_BUY_UNDER_MIN_SIGHTINGS = 1
DEFAULT_BUY_UNDER_WINDOW_DAYS = 7
# Days the Beta Prior column shows for, from a Market's first Scan (#90).
DEFAULT_BETA_COLUMN_DAYS = 14
# What each Beta Sale Event counts for in a Prediction buy's Max Loss room over those same
# days (#110, ADR-0024); off by default.
DEFAULT_BETA_SELL_RATE_WEIGHT = 0.0
# A Loot Alert (#54) fires on a drop whose one unit is worth at least this share of the
# Market's pooled gold, and never under this many gold.
DEFAULT_LOOT_ALERT_SHARE = 0.10
DEFAULT_LOOT_ALERT_FLOOR_GOLD = 10
COPPER_PER_GOLD = 10000
# Holdings ROI (#50): a Sell that nets at least this share over what its units cost is
# hinted at as a good time to sell.
DEFAULT_ROI_HINT = 0.20
# The hassle of an Item Key that doesn't stack (#73): each unit is its own buy and its own
# post, so every unit a Flip buys, and every one it posts, costs this many copper.
DEFAULT_NON_STACKING_EFFORT_COPPER = 500
# Posting on the Auction House costs a deposit, refunded on a sale and lost on each expiry
# (#78, ADR-0013). An Item Key never seen Sold is charged this share of its Vendor Price
# per unit per posting at 24 h: Classic's 5% per 2 h, checked in game 2026-09-28
# (floor(Vendor Price x 5%) x 12; 8c/32c/96c at 2/8/24 h for a 162c Vendor Price).
DEFAULT_AH_DEPOSIT_SHARE = 0.60
# How long the player posts for: a unit still unsold after it expires and loses its deposit.
# Forever offers 2, 8 or 24 h (no 48 h, checked 2026-09-28).
DEFAULT_POST_DURATION_HOURS = 24
# Held units of a random suffix count their siblings' Sale Events, the other suffixes of
# the same itemID, at this weight each (#58, ADR-0022): suffixes split a thin history.
DEFAULT_SUFFIX_POOL_WEIGHT = 0.5


DEFAULT_HISTORY_FILE = "history.sqlite"
DEFAULT_ARCHIVE_DIR = "archive"
PREDICTIONS_FILE = "predictions.toml"
GRADES_FILE = "grades.toml"


@dataclass(frozen=True)
class Config:
    installs: tuple[Install, ...]
    # Index 0 is bucket 1. Used to rule out Listing matches that couldn't have lasted
    # the time between two Scans.
    time_left_max_seconds: tuple[int, ...] = tuple(m * 60 for m in DEFAULT_TIME_LEFT_MAX_MINUTES)
    # The SQLite history. A relative path in the file is relative to the config file.
    history_path: Path = Path(DEFAULT_HISTORY_FILE)
    # Only gaps between Scans up to this long count toward Sell Rate (ADR-0004).
    observation_window_max_seconds: int = DEFAULT_OBSERVATION_WINDOW_MAX_MINUTES * 60
    # A late Scan older than its Market's latest by more than this waits for `brain rebuild`.
    pool_rematch_seconds: int = DEFAULT_POOL_REMATCH_HOURS * 3600
    # A Pooled Scan with fewer readable Listings than this share of the median of its
    # Market's last pool_completeness_window Scans is archived but not imported.
    pool_min_completeness: float = DEFAULT_POOL_MIN_COMPLETENESS
    pool_completeness_window: int = DEFAULT_POOL_COMPLETENESS_WINDOW
    # The Scan Pool's Worker and this player's member key. Unless both are set, the pool
    # is off and nothing leaves the PC.
    pool_url: str | None = None
    pool_key: str | None = None
    # The Worker's ADMIN_SECRET, for `brain pool key add/revoke`. Only the pool admin has it.
    pool_admin_secret: str | None = None
    # `brain watch` pulls this often, besides right before each import.
    pool_sync_seconds: int = DEFAULT_POOL_SYNC_MINUTES * 60
    # The first pull reaches back this far.
    pool_backfill_days: int = DEFAULT_POOL_BACKFILL_DAYS
    # The Archive folder (ADR-0005). A loaded config always has one; None, for
    # tests and for rebuilding from the archive itself, means Scans aren't archived.
    archive_dir: Path | None = None
    # Fair Value is the average of the cheapest this share of units (always at least one).
    fair_value_slice_share: float = DEFAULT_FAIR_VALUE_SLICE_SHARE
    # ...leaving out units priced under this share of the slice's median.
    fair_value_outlier_share: float = DEFAULT_FAIR_VALUE_OUTLIER_SHARE
    # Probable Sales are priced at most this multiple of Fair Value in their last Scan.
    probable_sale_max_fair_value_multiple: float = DEFAULT_PROBABLE_SALE_MAX_FAIR_VALUE_MULTIPLE
    # Sell Rate counts only the Observation Windows that ended this recently.
    sell_rate_range_seconds: int = DEFAULT_SELL_RATE_RANGE_DAYS * 24 * 3600
    # Share of a sale the Auction House keeps, at a faction and at a neutral one.
    ah_cut: float = DEFAULT_AH_CUT
    neutral_ah_cut: float = DEFAULT_NEUTRAL_AH_CUT
    # How long the player is willing to wait for held units to sell (CONTEXT.md).
    sale_horizon_seconds: int = DEFAULT_SALE_HORIZON_DAYS * 24 * 3600
    # A Flip to Sell must make at least this share of its buy price...
    flip_min_margin_share: float = DEFAULT_FLIP_MIN_MARGIN_SHARE
    # ...and at least this many copper per unit.
    flip_min_margin_copper: int = DEFAULT_FLIP_MIN_MARGIN_COPPER
    # Hours of no sales added to the Observation Windows before Sell Rate becomes a
    # quantity, for Holdings and for Flips.
    sell_rate_prior_hours_holdings: float = DEFAULT_SELL_RATE_PRIOR_HOURS_HOLDINGS
    sell_rate_prior_hours_flips: float = DEFAULT_SELL_RATE_PRIOR_HOURS_FLIPS
    # Sale Events of the typical size added to an Item Key's real ones before taking
    # their average size, for Holdings and for Flips.
    sale_size_prior_events_holdings: float = DEFAULT_SALE_SIZE_PRIOR_EVENTS_HOLDINGS
    sale_size_prior_events_flips: float = DEFAULT_SALE_SIZE_PRIOR_EVENTS_FLIPS
    # A Flip, a Flip to Craft's output or a Hold buy's Max Loss only counts on Selling
    # when the Sell Rate rests on at least this many Sale Events.
    flip_min_sale_events: int = DEFAULT_FLIP_MIN_SALE_EVENTS
    # A Flip to Sell is posted this many copper under the cheapest other player's Listing.
    post_undercut_copper: int = DEFAULT_POST_UNDERCUT_COPPER
    # The player's Predictions, always next to the config file (ADR-0006).
    predictions_path: Path = Path(PREDICTIONS_FILE)
    # Where Grades and held-at-writing costs are frozen, next to predictions.toml (#66).
    # A loaded config always has one; None, for tests, means nothing is frozen.
    grades_path: Path | None = None
    # The most a unit bought under a Prediction may lose, as a share of its cost.
    prediction_max_loss_share: float = DEFAULT_PREDICTION_MAX_LOSS_SHARE
    # The most gold under one Prediction, and under all of them, as a share of pooled gold.
    prediction_cap_share: float = DEFAULT_PREDICTION_CAP_SHARE
    predictions_cap_share: float = DEFAULT_PREDICTIONS_CAP_SHARE
    # A craft is only made while it gains more than this many copper (ADR-0008).
    craft_min_gain: float = DEFAULT_CRAFT_MIN_GAIN
    # The most crafts deep a chain of Sub-crafts goes, counting the top craft (#33).
    craft_chain_depth: int = DEFAULT_CRAFT_CHAIN_DEPTH
    # `brain disenchants` says "too few Results" for a group with fewer than this many.
    disenchant_check_min_results: int = DEFAULT_DISENCHANT_CHECK_MIN_RESULTS
    # How many options the Shopping List shows, most profit first (#86).
    shopping_list_rows: int = DEFAULT_SHOPPING_LIST_ROWS
    # How many Flips to Craft it shows besides, most profit first, in their own tab (#87).
    craft_list_rows: int = DEFAULT_CRAFT_LIST_ROWS
    # And how many Flips to Disenchant, most profit first, in theirs (#89).
    disenchant_list_rows: int = DEFAULT_DISENCHANT_LIST_ROWS
    # A Buy Under shows only once this many distinct Scans in the last
    # buy_under_window_days saw another player's Listing at or under it (#88).
    buy_under_min_sightings: int = DEFAULT_BUY_UNDER_MIN_SIGHTINGS
    buy_under_window_days: int = DEFAULT_BUY_UNDER_WINDOW_DAYS
    # The Beta Prior shows for this many days from the Market's first Scan (#90); 0 never.
    beta_column_days: int = DEFAULT_BETA_COLUMN_DAYS
    # What each Beta Sale Event and Observation Window hour counts for in the room a
    # Prediction buy's Max Loss counts on, over beta_column_days (#110); 0 never.
    beta_sell_rate_weight: float = DEFAULT_BETA_SELL_RATE_WEIGHT
    # A Loot Alert's threshold: the greater of this share of pooled gold and this floor,
    # set in gold in config.toml (#54).
    loot_alert_share: float = DEFAULT_LOOT_ALERT_SHARE
    loot_alert_floor_copper: int = DEFAULT_LOOT_ALERT_FLOOR_GOLD * COPPER_PER_GOLD
    # A Sell's ROI from which it's hinted at as a good time to sell (only a hint).
    roi_hint: float = DEFAULT_ROI_HINT
    # What a Flip is charged per unit it buys and per unit it posts of an Item Key that
    # doesn't stack.
    non_stacking_effort_copper: int = DEFAULT_NON_STACKING_EFFORT_COPPER
    # The deposit per unit per posting, as a share of the Vendor Price, for an Item Key
    # without a Sold invoice to learn it from, and how long a posting lasts.
    ah_deposit_share: float = DEFAULT_AH_DEPOSIT_SHARE
    post_duration_hours: float = DEFAULT_POST_DURATION_HOURS
    # What each sibling suffix's Sale Event counts for in a held unit's Sell Rate (#58).
    suffix_pool_weight: float = DEFAULT_SUFFIX_POOL_WEIGHT
    # Features the replay switches off one at a time to see what each is worth (#80,
    # ADR-0015). Always on outside it: not read from config.toml.
    flips_to_craft: bool = True
    deposits: bool = True
    # The cheap-stock cutoff (ADR-0028, ADR-0029): off only in the Backtest's relaxed
    # policy (#167). Not read from config.toml.
    cheap_stock_cutoff: bool = True
    # The Backtest's grader bounds (#167, ADR-0032): runs that believe this share of each
    # Sale Record's units, bracketing the own-Listing calibration. Not read from config.toml.
    backtest_grade_low: float = 0.65
    backtest_grade_high: float = 1.2
    # The Market's Days to Sell, set in game and read per Market with the Budget (#109,
    # ADR-0020); None for not set. Not read from config.toml.
    days_to_sell_seconds: int | None = None

    @property
    def days_to_sell_or_horizon_seconds(self) -> int:
        """How long a unit bought to Sell may take to sell: Days to Sell, clamped to the
        Sale Horizon, which it is when not set."""
        if self.days_to_sell_seconds is None:
            return self.sale_horizon_seconds
        return min(self.days_to_sell_seconds, self.sale_horizon_seconds)


CONFIG_FILE = "config.toml"
APP_FOLDER = "AzerothQuant"


def find_config(explicit: Path | None, cwd: Path, local_app_data: Path | None) -> Path | None:
    """The config file to load: `--config` if given, else ./config.toml (the dev setup),
    else the one setup wrote in %LOCALAPPDATA%/AzerothQuant (#115). None if there's none."""
    if explicit is not None:
        return explicit
    for candidate in config_candidates(cwd, local_app_data):
        if candidate.is_file():
            return candidate
    return None


def config_candidates(cwd: Path, local_app_data: Path | None) -> list[Path]:
    """Where `find_config` looks without `--config`, in order."""
    candidates = [cwd / CONFIG_FILE]
    if local_app_data is not None:
        candidates.append(local_app_data / APP_FOLDER / CONFIG_FILE)
    return candidates


def load_config(path: Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    raw_installs = raw.get("installs")
    if not raw_installs:
        raise ConfigError(f"{path}: needs at least one [[installs]] entry")
    if not isinstance(raw_installs, list) or not all(isinstance(e, dict) for e in raw_installs):
        raise ConfigError(f"{path}: [[installs]] must be a list of tables")

    installs = tuple(_parse_install(path, entry) for entry in raw_installs)

    seen: set[Path] = set()
    for install in installs:
        if install.path in seen:
            raise ConfigError(f"{path}: install folder {install.path} is listed more than once")
        seen.add(install.path)

    minutes = _parse_time_left(
        path, raw.get("time_left_max_minutes", DEFAULT_TIME_LEFT_MAX_MINUTES)
    )
    window_minutes = raw.get(
        "observation_window_max_minutes", DEFAULT_OBSERVATION_WINDOW_MAX_MINUTES
    )
    if (
        isinstance(window_minutes, bool)
        or not isinstance(window_minutes, int)
        or window_minutes < 1
    ):
        raise ConfigError(
            f"{path}: observation_window_max_minutes must be a positive whole number of minutes, "
            f"got {window_minutes!r}"
        )
    sell_rate_days = raw.get("sell_rate_days", DEFAULT_SELL_RATE_RANGE_DAYS)
    if (
        isinstance(sell_rate_days, bool)
        or not isinstance(sell_rate_days, int)
        or sell_rate_days < 1
    ):
        raise ConfigError(
            f"{path}: sell_rate_days must be a positive whole number of days, "
            f"got {sell_rate_days!r}"
        )
    rematch_hours = raw.get("pool_rematch_hours", DEFAULT_POOL_REMATCH_HOURS)
    if isinstance(rematch_hours, bool) or not isinstance(rematch_hours, int) or rematch_hours < 1:
        raise ConfigError(
            f"{path}: pool_rematch_hours must be a positive whole number of hours, "
            f"got {rematch_hours!r}"
        )
    pool_url, pool_key = _parse_pool_access(path, raw)
    pool_admin_secret = raw.get("pool_admin_secret")
    if pool_admin_secret is not None and (
        not isinstance(pool_admin_secret, str) or not pool_admin_secret
    ):
        raise ConfigError(f"{path}: pool_admin_secret must be the Worker's ADMIN_SECRET")
    pool_sync_minutes = _parse_whole(
        path, raw.get("pool_sync_minutes", DEFAULT_POOL_SYNC_MINUTES), "pool_sync_minutes", 1
    )
    backfill_days = _parse_whole(
        path, raw.get("pool_backfill_days", DEFAULT_POOL_BACKFILL_DAYS), "pool_backfill_days", 1
    )
    min_completeness = _parse_number(
        path,
        raw.get("pool_min_completeness", DEFAULT_POOL_MIN_COMPLETENESS),
        "pool_min_completeness",
        lambda x: 0 <= x <= 1,
        "from 0 to 1",
    )
    completeness_window = _parse_whole(
        path,
        raw.get("pool_completeness_window", DEFAULT_POOL_COMPLETENESS_WINDOW),
        "pool_completeness_window",
        3,  # the guard needs 3 Scans to compare against
    )
    history = raw.get("history_path", DEFAULT_HISTORY_FILE)
    if not isinstance(history, str) or not history:
        raise ConfigError(f"{path}: history_path must be a file path, got {history!r}")
    archive = raw.get("archive_dir", DEFAULT_ARCHIVE_DIR)
    if not isinstance(archive, str) or not archive:
        raise ConfigError(f"{path}: archive_dir must be a folder path, got {archive!r}")

    slice_share = _parse_number(
        path,
        raw.get("fair_value_slice_share", DEFAULT_FAIR_VALUE_SLICE_SHARE),
        "fair_value_slice_share",
        lambda x: 0 < x <= 1,
        "above 0 and at most 1",
    )
    outlier_share = _parse_number(
        path,
        raw.get("fair_value_outlier_share", DEFAULT_FAIR_VALUE_OUTLIER_SHARE),
        "fair_value_outlier_share",
        lambda x: 0 <= x < 1,
        "from 0 up to (not including) 1",
    )
    multiple = _parse_number(
        path,
        raw.get(
            "probable_sale_max_fair_value_multiple", DEFAULT_PROBABLE_SALE_MAX_FAIR_VALUE_MULTIPLE
        ),
        "probable_sale_max_fair_value_multiple",
        lambda x: x > 0,
        "above 0",
    )
    ah_cut, neutral_ah_cut = (
        _parse_number(
            path, raw.get(key, default), key, lambda x: 0 <= x < 1, "from 0 up to (not including) 1"
        )
        for key, default in (("ah_cut", DEFAULT_AH_CUT), ("neutral_ah_cut", DEFAULT_NEUTRAL_AH_CUT))
    )
    horizon_days = _parse_number(
        path,
        raw.get("sale_horizon_days", DEFAULT_SALE_HORIZON_DAYS),
        "sale_horizon_days",
        lambda x: x > 0,
        "of days above 0",
    )
    margin_share = _parse_number(
        path,
        raw.get("flip_min_margin_share", DEFAULT_FLIP_MIN_MARGIN_SHARE),
        "flip_min_margin_share",
        lambda x: x >= 0,
        "of at least 0",
    )
    margin_copper = _parse_copper(
        path,
        raw.get("flip_min_margin_copper", DEFAULT_FLIP_MIN_MARGIN_COPPER),
        "flip_min_margin_copper",
    )
    prior_holdings, prior_flips = (
        _parse_number(path, raw.get(key, default), key, lambda x: x >= 0, "of hours of at least 0")
        for key, default in (
            ("sell_rate_prior_hours_holdings", DEFAULT_SELL_RATE_PRIOR_HOURS_HOLDINGS),
            ("sell_rate_prior_hours_flips", DEFAULT_SELL_RATE_PRIOR_HOURS_FLIPS),
        )
    )
    size_prior_holdings, size_prior_flips = (
        _parse_number(
            path, raw.get(key, default), key, lambda x: x >= 0, "of Sale Events of at least 0"
        )
        for key, default in (
            ("sale_size_prior_events_holdings", DEFAULT_SALE_SIZE_PRIOR_EVENTS_HOLDINGS),
            ("sale_size_prior_events_flips", DEFAULT_SALE_SIZE_PRIOR_EVENTS_FLIPS),
        )
    )
    min_sale_events = raw.get("flip_min_sale_events", DEFAULT_FLIP_MIN_SALE_EVENTS)
    if (
        isinstance(min_sale_events, bool)
        or not isinstance(min_sale_events, int)
        or min_sale_events < 1
    ):
        raise ConfigError(
            f"{path}: flip_min_sale_events must be a whole number of Sale Events of at least 1, "
            f"got {min_sale_events!r}"
        )
    undercut = _parse_copper(
        path, raw.get("post_undercut_copper", DEFAULT_POST_UNDERCUT_COPPER), "post_undercut_copper"
    )
    effort = _parse_copper(
        path,
        raw.get("non_stacking_effort_copper", DEFAULT_NON_STACKING_EFFORT_COPPER),
        "non_stacking_effort_copper",
    )
    max_loss_share, cap_share, total_cap_share = (
        _parse_number(path, raw.get(key, default), key, lambda x: 0 <= x <= 1, "from 0 to 1")
        for key, default in (
            ("prediction_max_loss_share", DEFAULT_PREDICTION_MAX_LOSS_SHARE),
            ("prediction_cap_share", DEFAULT_PREDICTION_CAP_SHARE),
            ("predictions_cap_share", DEFAULT_PREDICTIONS_CAP_SHARE),
        )
    )
    craft_min_gain = _parse_number(
        path,
        raw.get("craft_min_gain", DEFAULT_CRAFT_MIN_GAIN),
        "craft_min_gain",
        lambda x: x >= 0,
        "of copper of at least 0",
    )
    chain_depth = raw.get("craft_chain_depth", DEFAULT_CRAFT_CHAIN_DEPTH)
    if isinstance(chain_depth, bool) or not isinstance(chain_depth, int) or chain_depth < 1:
        raise ConfigError(
            f"{path}: craft_chain_depth must be a whole number of crafts of at least 1, "
            f"got {chain_depth!r}"
        )
    min_results = raw.get("disenchant_check_min_results", DEFAULT_DISENCHANT_CHECK_MIN_RESULTS)
    if isinstance(min_results, bool) or not isinstance(min_results, int) or min_results < 2:
        raise ConfigError(
            f"{path}: disenchant_check_min_results must be a whole number of Results of at"
            f" least 2, got {min_results!r}"
        )
    shopping_rows = raw.get("shopping_list_rows", DEFAULT_SHOPPING_LIST_ROWS)
    craft_rows = raw.get("craft_list_rows", DEFAULT_CRAFT_LIST_ROWS)
    disenchant_rows = raw.get("disenchant_list_rows", DEFAULT_DISENCHANT_LIST_ROWS)
    for key, rows in (
        ("shopping_list_rows", shopping_rows),
        ("craft_list_rows", craft_rows),
        ("disenchant_list_rows", disenchant_rows),
    ):
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
            raise ConfigError(
                f"{path}: {key} must be a whole number of rows of at least 1, got {rows!r}"
            )
    sightings = raw.get("buy_under_min_sightings", DEFAULT_BUY_UNDER_MIN_SIGHTINGS)
    window_days = raw.get("buy_under_window_days", DEFAULT_BUY_UNDER_WINDOW_DAYS)
    for key, n, unit in (
        ("buy_under_min_sightings", sightings, "Scans"),
        ("buy_under_window_days", window_days, "days"),
    ):
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ConfigError(
                f"{path}: {key} must be a whole number of {unit} of at least 1, got {n!r}"
            )
    beta_days = raw.get("beta_column_days", DEFAULT_BETA_COLUMN_DAYS)
    if isinstance(beta_days, bool) or not isinstance(beta_days, int) or beta_days < 0:
        raise ConfigError(
            f"{path}: beta_column_days must be a whole number of days of at least 0,"
            f" got {beta_days!r}"
        )
    roi_hint = _parse_number(
        path, raw.get("roi_hint", DEFAULT_ROI_HINT), "roi_hint", lambda x: x >= 0, "of at least 0"
    )

    deposit_share = _parse_number(
        path,
        raw.get("ah_deposit_share", DEFAULT_AH_DEPOSIT_SHARE),
        "ah_deposit_share",
        lambda x: x >= 0,
        "of at least 0",
    )
    post_hours = _parse_number(
        path,
        raw.get("post_duration_hours", DEFAULT_POST_DURATION_HOURS),
        "post_duration_hours",
        lambda x: x > 0,
        "of hours above 0",
    )
    pool_weight = _parse_number(
        path,
        raw.get("suffix_pool_weight", DEFAULT_SUFFIX_POOL_WEIGHT),
        "suffix_pool_weight",
        lambda x: 0 <= x <= 1,
        "from 0 to 1",
    )
    beta_weight = _parse_number(
        path,
        raw.get("beta_sell_rate_weight", DEFAULT_BETA_SELL_RATE_WEIGHT),
        "beta_sell_rate_weight",
        lambda x: 0 <= x <= 1,
        "from 0 to 1",
    )
    loot_share = _parse_number(
        path,
        raw.get("loot_alert_share", DEFAULT_LOOT_ALERT_SHARE),
        "loot_alert_share",
        lambda x: 0 <= x <= 1,
        "from 0 to 1",
    )
    loot_floor = _parse_number(
        path,
        raw.get("loot_alert_floor", DEFAULT_LOOT_ALERT_FLOOR_GOLD),
        "loot_alert_floor",
        lambda x: x >= 0,
        "of gold of at least 0",
    )
    return Config(
        installs=installs,
        time_left_max_seconds=tuple(m * 60 for m in minutes),
        history_path=path.parent / history,
        observation_window_max_seconds=window_minutes * 60,
        pool_rematch_seconds=rematch_hours * 3600,
        pool_min_completeness=min_completeness,
        pool_completeness_window=completeness_window,
        pool_url=pool_url,
        pool_key=pool_key,
        pool_admin_secret=pool_admin_secret,
        pool_sync_seconds=pool_sync_minutes * 60,
        pool_backfill_days=backfill_days,
        archive_dir=path.parent / archive,
        fair_value_slice_share=slice_share,
        fair_value_outlier_share=outlier_share,
        probable_sale_max_fair_value_multiple=multiple,
        sell_rate_range_seconds=sell_rate_days * 24 * 3600,
        ah_cut=ah_cut,
        neutral_ah_cut=neutral_ah_cut,
        sale_horizon_seconds=round(horizon_days * 24 * 3600),
        flip_min_margin_share=margin_share,
        flip_min_margin_copper=margin_copper,
        sell_rate_prior_hours_holdings=prior_holdings,
        sell_rate_prior_hours_flips=prior_flips,
        sale_size_prior_events_holdings=size_prior_holdings,
        sale_size_prior_events_flips=size_prior_flips,
        flip_min_sale_events=min_sale_events,
        post_undercut_copper=undercut,
        predictions_path=path.parent / PREDICTIONS_FILE,
        grades_path=path.parent / GRADES_FILE,
        prediction_max_loss_share=max_loss_share,
        prediction_cap_share=cap_share,
        predictions_cap_share=total_cap_share,
        craft_min_gain=craft_min_gain,
        craft_chain_depth=chain_depth,
        disenchant_check_min_results=min_results,
        shopping_list_rows=shopping_rows,
        craft_list_rows=craft_rows,
        disenchant_list_rows=disenchant_rows,
        buy_under_min_sightings=sightings,
        buy_under_window_days=window_days,
        beta_column_days=beta_days,
        beta_sell_rate_weight=beta_weight,
        loot_alert_share=loot_share,
        loot_alert_floor_copper=round(loot_floor * COPPER_PER_GOLD),
        roi_hint=roi_hint,
        non_stacking_effort_copper=effort,
        ah_deposit_share=deposit_share,
        post_duration_hours=post_hours,
        suffix_pool_weight=pool_weight,
    )


def _parse_number(
    config_path: Path, value: object, key: str, allowed: Callable[[float], bool], wording: str
) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not allowed(value):
        raise ConfigError(f"{config_path}: {key} must be a number {wording}, got {value!r}")
    return value


def _parse_whole(config_path: Path, value: object, key: str, least: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < least:
        raise ConfigError(
            f"{config_path}: {key} must be a whole number of at least {least}, got {value!r}"
        )
    return value


def _parse_pool_access(config_path: Path, raw: dict) -> tuple[str | None, str | None]:
    """pool_url and pool_key. Pushing and pulling come as one and need both set, so a
    member always gives as well as takes. pool_url alone is how the pool admin starts:
    `brain pool key add` needs it to make their own key (#128)."""
    url, key = raw.get("pool_url"), raw.get("pool_key")
    if url is None and key is None:
        return None, None
    if url is None:
        raise ConfigError(f"{config_path}: pool_key is set but pool_url isn't")
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise ConfigError(f"{config_path}: pool_url must be an http(s) URL, got {url!r}")
    if key is None:
        return url, None
    if not isinstance(key, str) or not key:
        raise ConfigError(f"{config_path}: pool_key must be the key the pool admin gave you")
    return url, key


def _parse_copper(config_path: Path, value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(
            f"{config_path}: {key} must be a whole number of copper of at least 0, got {value!r}"
        )
    return value


def _parse_time_left(config_path: Path, value: object) -> tuple[int, ...]:
    expected = len(DEFAULT_TIME_LEFT_MAX_MINUTES)
    if (
        not isinstance(value, list | tuple)
        or len(value) != expected
        or not all(isinstance(m, int) and not isinstance(m, bool) and m > 0 for m in value)
        or list(value) != sorted(set(value))
    ):
        raise ConfigError(
            f"{config_path}: time_left_max_minutes must be {expected} increasing positive "
            f"whole numbers of minutes, got {value!r}"
        )
    return tuple(value)


def _parse_install(config_path: Path, entry: dict) -> Install:
    for field in ("path", "era"):
        if field not in entry:
            raise ConfigError(f"{config_path}: an [[installs]] entry is missing '{field}'")

    try:
        era = Era(entry["era"])
    except ValueError:
        allowed = ", ".join(e.value for e in Era)
        raise ConfigError(
            f"{config_path}: unknown era '{entry['era']}' (expected one of: {allowed})"
        ) from None

    return Install(path=Path(entry["path"]), era=era)
