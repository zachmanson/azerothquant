"""The young-Market yardstick (#147 slice 4): how full the table is after a Market's
first few Scans.

Replays the first N archived Scans (own and Pooled) of one Market into a fresh history,
with every archived Character Read (Holdings, vendor prices and item info, as Live gets
Beta's), and counts the rows the Decision Engine gives after 1, 3, 5, 10 and 20 Scans.
No Mailbox Reads: a new Market has no Purchases or Outcomes yet. Reads only the Archive
and the config; the real history is never touched.

    cd brain
    python ../scripts/yardstick.py                            # Classic Beta PvP Alliance
    python ../scripts/yardstick.py --realm "Classic Beta PvP" --faction Alliance
"""

import argparse
import dataclasses
import tempfile
from contextlib import closing
from pathlib import Path

from brain.archive import Archive, ArchivedScan
from brain.config import Config, Era, load_config
from brain.history import Market, import_archived_scans, import_character_reads, open_history
from brain.recommend import MarketRecommendations, recommend

COUNTS = (1, 3, 5, 10, 20)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--realm", default="Classic Beta PvP")
    parser.add_argument("--faction", default="Alliance")
    args = parser.parse_args()

    config = load_config(args.config)
    archive = Archive(config.archive_dir)
    market = Market(args.realm, args.faction, Era.BETA)
    scans = archive.market_scans(Era.BETA, market.realm, market.faction, since=0)
    reads = [raw for era, raw in archive.character_reads() if era == Era.BETA]
    print(f"{len(scans)} archived Scans, {len(reads)} Character Reads")

    print("| Scans | hours | Holdings | priced | blocked | Shopping List | Buy Under |")
    print("|---|---|---|---|---|---|---|")
    for n in COUNTS:
        if n > len(scans):
            break
        m = _replay(config, market, scans[:n], reads)
        first, last = scans[0].raw["requestedAt"], scans[n - 1].raw["requestedAt"]
        priced = [r for r in m.holdings if r.price is not None and r.blocked is None]
        blocked = [r for r in m.holdings if r.blocked is not None]
        print(
            f"| {n} | {(last - first) / 3600:.1f} | {len(m.holdings)} | {len(priced)} "
            f"| {len(blocked)} | {len(m.shopping_list)} | {len(m.buy_under)} |"
        )


def _replay(
    config: Config, market: Market, scans: list[ArchivedScan], reads: list[dict]
) -> MarketRecommendations:
    """The Market's Recommendations from a fresh history of `scans` and `reads` alone."""
    with tempfile.TemporaryDirectory() as tmp:
        fresh = dataclasses.replace(
            config, history_path=Path(tmp) / "history.sqlite", archive_dir=None
        )
        with closing(open_history(fresh.history_path)) as conn:
            import_archived_scans(conn, scans, Era.BETA, fresh)
            import_character_reads(conn, reads, Era.BETA, fresh)
            [found] = [m for m in recommend(conn, fresh) if m.market == market]
            return found


if __name__ == "__main__":
    main()
