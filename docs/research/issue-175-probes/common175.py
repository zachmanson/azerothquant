import sqlite3, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, r"Z:\vibing\azerothquant\brain\src")
from brain.config import load_config
from brain.fair_value import FairValueCache
from brain.history import character_markets, scan_times
from brain.predictions import load_predictions
import brain.recommend as R

WORK = Path(__file__).parent / "work"

def setup():
    (WORK / "fake-wow").mkdir(exist_ok=True)
    cfg = WORK / "config.toml"
    cfg.write_text("flip_min_margin_share = 0.1\n\n[[installs]]\n"
                   f"path = '{WORK / 'fake-wow'}'\nera = \"beta\"\n")
    config = load_config(cfg)
    conn = sqlite3.connect(WORK / "history.sqlite")
    market = next(iter(character_markets(conn)))
    return conn, config, market, load_predictions(config.predictions_path), FairValueCache()

def ts(t): return datetime.fromtimestamp(t).strftime("%m-%d %H:%M")

def find(conn, market, label):
    for t in scan_times(conn, market):
        if ts(t) == label: return t
    raise KeyError(label)

def run(conn, config, market, preds, cache, now, **kw):
    cache.start_pass()
    return R.recommend_market(conn, config, market, preds, now, as_of=now, fair_value_cache=cache,
                              why_not=True, buy_under=False, paid=False, loot_alert=False, **kw)
