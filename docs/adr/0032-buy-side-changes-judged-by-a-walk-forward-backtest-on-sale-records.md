# Buy-side changes are judged by a walk-forward backtest graded on Sale Records

Amends ADR-0015 (#167, parent #166). The replay stays as it is, but it no longer judges whether a change to how the Brain buys should go in. The **Backtest** does: `brain backtest`, ported from the outside review's `p4_backtest.py` (`docs/research/decision-review-2026-10-08/`, §6.1 and §7.1).

**Why not the replay.** It grades each Scan apart, from the player's real Holdings and gold, over one Sale Horizon, and only by Sale Events, which come from 60-minute Observation Windows. On the review's history, 14 of 294 hours were watched, so most of what a post would have sold is invisible to it, and nothing carries from one Scan to the next: a bad buy never ties up the gold the next buy needed. Row counts on the Shopping List aren't a check either. More rows can mean more losing buys.

**What the Backtest does.** Per Market, each policy starts with simulated gold (40g by default, `--start-gold`, not the player's real gold) at the first Scan in `--since`/`--until`, and at every Scan, in time order:

1. **Fills.** A post sells to a later Sale Record of its Item Key at or above its price, up to the record's units, our cheapest units first. Only a record whose Listing was still up at or after the Scan we posted in counts. A sold unit brings its price after the cut, less a Deposit for each 24 hours of posting it waited through.
2. **Week out.** A lot unsold 7 days after posting is relisted once, for 7 more days, at the lower of its price and 1c under other players' cheapest ask then, if that still beats the Vendor Price after the cut. Unsold after that, it's vendored after losing a Deposit for each day posted.
3. **Buys.** The policy buys with the gold it has, never in an Item Key it still has units posted in (the real Scans don't show our simulated posts), and nothing in the last 7 days of the data, so every buy gets its week.

Units still posted at the end are marked two ways: the **vendor mark** (Vendor Price, less the Deposits lost) and the **market mark** (other players' cheapest ask less 1c, after the cut, capped at the post price, and never under the Vendor Price). As in p4, the market mark is worked out for every lot that ends with units unsold, vendored mid-run or not; the simulated gold always uses the vendor mark.

**Policies** are the Brain under a config, as overrides of the player's: `brain` (as is) and `relaxed` (no cheap-stock cutoff, 1 Sale Event enough, the Holdings' Sell Rate priors for Flips, no margin). A policy is any function from (Scan, gold, Item Keys posted) to buys, so EV (#171) and Buy Unders as standing orders (#173) can add theirs. The Brain policy takes the Shopping List options a player would take, as the replay does, sized to the simulated gold with no Budget. Flips to Disenchant are left out: their mats aren't simulated.

**Sale Records** are the grader's evidence (CONTEXT.md): other players' Partial Sales in any gap, and their Disappearances over a gap of at most 12 hours that couldn't have expired and aren't Reposts, priced at most 1.2x the Fair Value of the Scan before, with items either Scan dropped rows of left out. They don't feed the Sell Rate. Whether they should is #169.

**Grader bounds** (slice 2): a "gone" Listing may have been cancelled rather than sold. The review's own-Listing check (p6) found about 60-75% of the player's gone Listings were really sold. Each run is also graded believing 0.65x and 1.2x of each record's units (`backtest_grade_low`, `backtest_grade_high`), and prints a calibration line: the same rule tried on the player's own Listings against their mail (how many it calls sold really were, and how many Sold mails it caught). The line doesn't move the bounds. Each run also reports its max drawdown (the deepest fall of gold plus unsold units at cost from a peak) and its gold low (the least gold after a Scan's buys).

## Considered options

- **Keep the replay as the judge.** See above: it can't see most sales, and nothing compounds.
- **Grade on Sale Events (Observation Windows only).** The same blind spot. The Brain's strict evidence would grade its own decisions on the evidence they were made from.
- **Real gold as the start.** It changes as the player trades, so two runs a day apart wouldn't compare. A fixed start does.
- **No relist, vendor at a week.** Harsher than what a player does. The review ran both, and the relist is what players do.
- **Leave out the 1.2x cap.** The review's "loose" grader. A 3x Disappearance is more likely a cancel than a sale.

The ADR-0015 checkpoints (Brain vs. Auctionator and TSM on Live) still use the replay. ADR-0019 (Buy Unders) is left for #173.
