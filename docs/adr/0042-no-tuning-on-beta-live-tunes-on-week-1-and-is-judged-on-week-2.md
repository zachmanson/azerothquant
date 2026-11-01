# No more tuning on Beta; Live tunes on week 1 and is judged on week 2

Decided in the grill of the 2026-11-01 independent audit (`docs/research/independent-audit-2026-11-01/pass2-audit.md`, findings 1, 7 and 9).

- No setting is chosen, and no buy-side change is kept or dropped, on Beta Scans from now on. Fixes that make a measurement more correct (per-gap exposure in Sell Rate, the Backtest no longer re-buying what it bought) are still built. They are checked on Beta for crashes and direction only.
- On Live, settings are fit on the first full week of Scans, then frozen and judged on the second week. There are no mid-week changes. A change is kept only if it wins on the held-out week.
- A bar to beat is set from noise measured on that data (for example, the spread of P&L across runs that differ only in something that shouldn't matter), not a fixed 5g.
- The primary judge is Flip Grades from mail and the calibration report built from them (predicted against realized Profit and Days to Sell). The Backtest is a sanity check, always reported with its 0.65 grader lower bound beside the central run.

## Why

Every buy-side ADR from 0034 to 0041 was chosen on the same 86 to 97 Beta Scans with 5g bars and no holdout. The audit found three problems with that:
- The Backtest's +90.7g came mostly from one item (11288) that the simulation bought again at every Scan.
- An input that should be irrelevant (`predictions.toml`, through the written-date bug) moved the Brain's P&L by 101g, so 5g wins (ADR-0035's 4.6g, ADR-0041's 4.7g) are inside the noise.
- Beta prices drifted, from about 0.5x to 5x between the first and last week.

The 18 real Flips made 48.7% of the profit the Brain expected. Beta numbers don't carry to Live.

## Considered options

- **Keep tuning on Beta with bigger bars**: still in-sample on a market unlike Live, and the noise is not known well enough to set the bar.
- **Re-tune continuously on Live**: every change would be judged on the data it was fit to, which is the same mistake again.

## Consequences

- Settings chosen on Beta (ADR-0034 to 0041) stay until the fixed Backtest has been rerun and a Live week says otherwise. The rerun re-judges them for sanity, not for tuning.
- Nothing can be tuned in Live's first week. The cancel discount on Sell Rate (measured from the player's own Live Listings) waits for week 1 and is judged on week 2.
