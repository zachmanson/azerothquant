# Observation Windows run up to 12 hours

Amends ADR-0004 (#169, parent #166). The Observation Window cap goes from 60 minutes to 12 hours (`observation_window_max_minutes` default 720). Nothing else changes. A Disappearance in a window is a Probable Sale candidate only if its time-left bucket rules out expiry over that gap, as before. That test already works per Listing, so over a long gap only Listings in a bucket that outlasts it can count. The hours still count Market-wide, for every Item Key alike, and gaps over 12 hours still add nothing to Sell Rate, sales or hours.

## Why

The outside review (`docs/research/decision-review-2026-10-08/REVIEW.md` §1.3, §2.3, §8) found the 60-minute cap throws away most of the sales the history has. On a copy of the live history (87 Beta Scans, 439 h, to 2026-10-14 23:41):

| Gap | Hours, all history | Hours, last 14 days | Units seen sold per hour | Cheapest Listing of an Item Key can't expire over it |
|---|---|---|---|---|
| ≤1 h | 18.1 | 5.7 | 63k | |
| 1-2 h | 18.6 | 10.2 | 29k | 61% |
| 2-12 h | 78.8 | 50.3 | 4.3k | 10% |
| >12 h | 324 | 275 | 0.6k (Partial Sales only) | |

The Sell Rate went from 5.7 watched hours to 66. Over a gap longer than 2 hours only bucket 4 (12-24 h left) can't expire, and an Item Key's cheapest Listing is rarely in it, so most sales in those gaps aren't seen while their hours still count. Rates fall about 3.5x Market-wide (median among Item Keys with sales at the latest Scan: 4.2 → 0.7 units a day), but more Item Keys reach 3 Sale Events (671 → 2,478), so the Shopping List doesn't shrink. That leans Sell Rate low, the safe side, and partly offsets the prime-time lean ADR-0004 accepts.

Judged by the Backtest (ADR-0032), 40g start, with the ADR-0034 caps on (what ships) and off:

| | P&L vendor / market | Grader x0.65 vendor / market | Worst trade | Drawdown | Relisted |
|---|---|---|---|---|---|
| `brain` (60 min) | 44.7g / 118.3g | 47.7g / 106.4g | −17.7g | 9% | −120.4g |
| **12 h** | **84.6g** / 115.7g | **56.8g** / 89.4g | **−16.2g** | 9% | **−75.6g** |
| 12 h, hours per Item Key | 80.0g / 122.9g | 45.4g / 78.0g | −18.0g | 11% | −94.3g |
| 2 h | 60.3g / 99.9g | 49.4g / 82.6g | −16.2g | 13% | −94.3g |
| `uncapped` (60 min) | −49.6g / 104.3g | −11.0g / 111.7g | −48.9g | 11% | −176.4g |
| 12 h, uncapped | −25.6g / 86.5g | −32.1g / 54.4g | −30.4g | 6% | −108.4g |

12 hours wins on the vendor mark (central and both bounds), worst trade and drawdown, mostly through fewer losing relists. It's judged on the vendor mark: unsold stock at what a vendor pays is gold made, while the market mark leans on unsold stock being worth its ask. The market mark's x0.65 bound fell 17g (106.4g → 89.4g; 57g uncapped). The bounds are noisy (`brain`'s own x0.65 vendor run beats its central one), but #171 should watch it.

## Considered options

- **Hours per Item Key** (the review's "exposure only for buckets that can't have expired"): a gap over an hour counts toward an Item Key only if its cheapest Listing at the gap's start can't expire over it. It keeps the rate near today's instead of diluting it, but capped it lost to the plain 12 h on 4 of 6 lines, its uncapped drawdown was the worst (16%), and `window_hours` would stop being one number per Market (`SellRate`, `since_cheap`, Beta pooling, the CLI and Addon lines).
- **A 2-hour cap**: 61% of 1-2 h gaps can still see the cheapest Listing, but it lost to 12 h on every line.
- **Partial Sales from gaps of any length** (the issue's first ask): a shrinking stack is a certain sale, but over 12 h gaps they come to 0.6k units an hour. Counting the hours drags every rate down, and counting the sales without them is the two-denominator split ADR-0004 rejected.

## Consequences

- One rule now decides both Sell Rate's evidence and the Backtest's Sale Records (12 h, can't have expired, not a Repost), so the Backtest grades the Brain on the same kind of sale it learns from. Sale Records still count Partial Sales over any gap.
- About a third of what both rules call sales are cancels (`p6`, unchanged here). That belongs in #171's expected value, not in a pass/fail.
- A Sale Event is still one per Item Key per window (ADR-0012), so a 12 h window can fold several buyers into one. Sale Events in 2-12 h gaps averaged 41 units vs 34 in ≤1 h ones, so it's slight.
- The cheap-stock cutoff (ADR-0029, ADR-0033) counts windows ending after the cutoff, so a 12 h window that straddles it now counts whole.
