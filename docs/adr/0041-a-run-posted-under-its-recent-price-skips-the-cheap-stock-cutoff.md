# Only a long Risky row posted under its Recent Price skips the cheap-stock cutoff

Amends ADR-0028, ADR-0029, ADR-0033 (the cheap-stock cutoff) and ADR-0037 (Risky rows). Decided in the #200 grill, 2026-10-29; built the same day, when the Backtest sent it to its fallback (below).

- **Recent Price** (CONTEXT.md): an Item Key's median unit price over its Sale Events in the last 7 days, each unit counted (the lower middle one), with at least 3 Sale Events or there's none.
- Grilled: a Flip to Sell posted at or under its Recent Price skips the cheap-stock cutoff, for every row: a dump under a steady price isn't a crash. **Built: only a long Risky row does.** Every Flip skipping it lost the Backtest by 138g (below), so it's `recent_price_skips_cutoff`, off by default, kept for a later A/B.
- A Flip to Sell the Unsold Loss cap drops, or the cutoff leaves without a run, comes back as a Risky row at any size, not only up to `risky_max_units` (5). Above 5 units it's sized with the cutoff skipped under its Recent Price, and must post at or under its Recent Price, buy no more (held units included) than the units seen sold at or above its post price with each Sale Event counted at most the typical sale size (#198's clip), and lose no more than half the Stake if none of it sells (`risky_max_loss_share`; 25% in the grill, raised when built, below). Risky rows of 5 units or fewer keep ADR-0037's rules. Risky rows still stay out of the Backtest.
- Minimum Profit (CONTEXT.md) grows with the clicks: at least 5s (`row_min_profit_per_click`) for each Listing a row buys and stack it posts.

## Why

Steel Bar (216 bought at 8s 50c on 2026-10-11, all 216 sold within ~27 h for +13.4g) isn't a row as of its buy Scan even with the caps off. A day before, a few bars were up at 14s 99c, 3% under the 15s 49c post price. The cutoff took that as a crash, and no Sale Event at 15s 49c or more came after it, so the room was 0. In the 14 days before, 32 Sale Events (900 units) were at or above 15s 49c.

The Cured Medium Hide (row of 241 at 14s 49c on 2026-10-12, 501 bought, 34 sold) is blocked by the same cutoff, rightly: the ~15s+ price was a one-day spike on 10-11 in a market that sold at about 7s for days on both sides.

| as of the buy Scan | post at | Recent Price | units seen sold at or above post, clipped (14 d) | run |
|---|---|---|---|---|
| Steel Bar | 15s 49c | 19s 99c | 328 | 216 |
| Cured Medium Hide | 14s 49c | 7s 65c | 60 | 241 |

Profit per unit (about 6s each) and ROI (73% vs ~87%) can't tell them apart. The Recent Price can, and the clip keeps a run within the demand seen.

## Built: the Backtest (87-Scan Beta copy, `brain` policy, from 40g)

| | P&L vendor mark | P&L market mark | Buys | Max drawdown |
|---|---|---|---|---|
| main (ADR-0040's bar) | 131g 35s | 156g 60s | 92 | 8% |
| every Flip skips the cutoff under its Recent Price, + 5s a click | -7g 10s | 7g 01s | 80 | 25% |
| only long Risky rows skip it, + 5s a click (built) | 136g 04s | 161g 03s | 89 | 7% |

The skip for every row lost, as ADR-0036 and ADR-0040 lost by loosening Flip to Sell: most of the extra runs it let through were posted under a steady price and still didn't sell. The per-click floor alone beats main by 4g 70s. Risky rows stay out of the Backtest, so the built version scores as the per-click floor alone.

At Steel Bar's buy Scan the Stake was 41g 20s and its 216 lose 17g 84s unsold (43%): 25% of the Stake hid it, so the user raised the limit to half (2026-10-29). As built, Steel Bar is a Risky row of 216 up to 8s 50c posted at 15s 49c (13g 36s profit), and there's no Cured Medium Hide row at its Scan (its Recent Price is under the post).

Shopping List rows per Scan, over the 66 Scans the Backtest values at its own simulated Stake (from 40g): normal rows 1.96 a Scan on main, 1.85 after (the per-click floor). Risky rows 1.18 a Scan on main, 2.60 after (first 50 Scans; the final run was stopped for low memory there, its normal rows and gold matching the run above call for call).

## Considered options

- **Every Flip to Sell skips the cutoff under its Recent Price**: the grilled choice; lost the Backtest by 138g.
- **Leave the cutoff alone**: no Steel Bar-like run ever shows.
- **Drop normal rows posted above their Recent Price**: a second change to the Backtest at once; a follow-up if Flip Grades show those rows losing.
- **A wall check** (cheap units left just above the post): harder to define and overlaps the cutoff.

## Consequences

- A Steel Bar-like run shows as Risky whatever the Stake, never as a normal row: the cutoff still holds for those.
- Long Risky rows are common on Beta (several a Scan at a ~40g Stake, 18 to 29 units); they're named, flagged risky and not backtested, so their Flip Grades are what will say whether they pay.
- `_flips` runs twice for an Item Key with a Recent Price and cheap stock, once with the skip, for the long runs.

## Amendment: the loss limit is back to 25% of the Stake (#211)

Decided in the grill of the 2026-11-01 independent audit (`docs/research/independent-audit-2026-11-01/pass2-audit.md`, finding 4). `risky_max_loss_share` defaults to 0.25 again, the grilled value, instead of the 0.5 it was raised to so that Steel Bar would show.

On 10 sampled Beta Scans at 40g, Risky rows were 36 of 60 Shopping List rows and carried 79% of the list's expected profit, with unsold losses up to 43% of the Stake. Risky rows are never backtested, so nothing measured backs the higher limit. At 25%, a Steel Bar-like run at a ~40g Stake is hidden again; a player who wants it can set `risky_max_loss_share = 0.5` in config.toml.

Revisit once 10 Risky Flips have Flip Grades (ADR-0042: judged on Flip Grades, not the Beta Backtest).
