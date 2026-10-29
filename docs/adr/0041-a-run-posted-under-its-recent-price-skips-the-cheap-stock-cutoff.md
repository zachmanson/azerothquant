# A run posted under its Recent Price skips the cheap-stock cutoff; big Risky rows must pass it

Amends ADR-0028, ADR-0029, ADR-0033 (the cheap-stock cutoff) and ADR-0037 (Risky rows). Decided in the #200 grill, 2026-10-29. To be judged by the Backtest when built; this ADR records the decision and its fallback.

- **Recent Price** (CONTEXT.md): an Item Key's median unit price over its Sale Events in the last 7 days, each unit counted, with at least 3 Sale Events or there's none.
- A Flip to Sell posted at or under its Recent Price skips the cheap-stock cutoff, for every row: a dump under a steady price isn't a crash. A row posted above it keeps the cutoff and isn't otherwise dropped.
- A Flip to Sell the Unsold Loss cap drops comes back as a Risky row at any size, not only up to `risky_max_units` (5). Above 5 units it must also post at or under its Recent Price, buy no more (held units included) than the units seen sold at or above its post price with each Sale Event counted at most the typical sale size (#198's clip), and lose no more than 25% of the Stake if none of it sells. Risky rows of 5 units or fewer keep ADR-0037's rules. Risky rows still stay out of the Backtest.

## Why

Steel Bar (216 bought at 8s 50c on 2026-10-11, all 216 sold within ~27 h for +13.4g) isn't a row as of its buy Scan even with the caps off. A day before, a few bars were up at 14s 99c, 3% under the 15s 49c post price. The cutoff took that as a crash, and no Sale Event at 15s 49c or more came after it, so the room was 0. In the 14 days before, 32 Sale Events (900 units) were at or above 15s 49c.

The Cured Medium Hide (row of 241 at 14s 49c on 2026-10-12, 501 bought, 34 sold) is blocked by the same cutoff, rightly: the ~15s+ price was a one-day spike on 10-11 in a market that sold at about 7s for days on both sides.

| as of the buy Scan | post at | Recent Price | units seen sold at or above post, clipped (14 d) | run |
|---|---|---|---|---|
| Steel Bar | 15s 49c | 19s 99c | 328 | 216 |
| Cured Medium Hide | 14s 49c | 7s 65c | 60 | 241 |

Profit per unit (about 6s each) and ROI (73% vs ~87%) can't tell them apart. The Recent Price can, and the clip keeps a run within the demand seen.

## Considered options

- **Only big Risky rows skip the cutoff**: the Backtest wouldn't move, but a Steel Bar-like run would show as Risky at a small Stake and vanish again as a normal row at a Stake big enough for the cap to fit it. This is the fallback if the Backtest loses.
- **Leave the cutoff alone**: no Steel Bar-like run ever shows.
- **Drop normal rows posted above their Recent Price**: a second change to the Backtest at once; a follow-up if Flip Grades show those rows losing.
- **A wall check** (cheap units left just above the post): harder to define and overlaps the cutoff.

## Consequences

- Must pass: the Backtest no worse than `brain` (131.4g vendor / 156.6g market from 40g, ADR-0040's table), else the cutoff skip is kept to big Risky rows. ADR-0036 and ADR-0040 both lost by loosening Flip to Sell on the demand model's word, so this may lose too.
- Must pass: Steel Bar as a big Risky row at the 2026-10-11 12:03 Scan; no Cured Medium Hide row at 2026-10-12 18:29.
- Reported: Shopping List rows per Beta Scan before vs after.
