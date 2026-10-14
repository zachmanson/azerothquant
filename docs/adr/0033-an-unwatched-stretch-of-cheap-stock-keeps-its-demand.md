# An unwatched stretch of cheap stock keeps its demand

Amends ADR-0029 (#168, parent #166). The cutoff (the start of the stretch, kept through short breaks) and the trigger with Observation Window hours since are unchanged. Only the 24-hour rule goes. Under ADR-0029, a stretch with no window hours since it began counted the whole range until it was 24 hours old, and then nothing sold at the post price (`UNWATCHED_STRETCH_SECONDS`). Now a stretch with no window hours since counts the whole range however old it is. No hours watched means nothing was seen, so the demand is unknown, not zero. The cut waits for the first window hours after the cutoff, as it does for a stretch under a day old.

`--why-not` loses "(not watched since)": a cut always has window hours after the cutoff now.

## Why

The outside review (`docs/research/decision-review-2026-10-08/REVIEW.md` §2.1, §8) said the cutoff zeroes demand on minutes of watching and empties the Shopping List after a day away. #175 showed the thin Scans aren't tied to gaps. The question was then whether any part of the cutoff should go, judged by the Backtest (ADR-0032). On a copy of the live history (86 Beta Scans, to 2026-10-13 18:12, 40g start):

| | `brain` (ADR-0029) | this rule | cutoff off (`nocut`) | power test |
|---|---|---|---|---|
| P&L, vendor / market mark | −34.8g / +76.5g | **−24.3g / +78.5g** | −49.7g / −18.9g | −45.2g / −22.3g |
| Grader x0.65, vendor / market | −37.1g / +45.9g | −25.4g / +48.6g | −135.7g / −93.8g | −53.5g / −26.7g |
| Grader x1.2, vendor / market | −40.1g / +70.0g | −37.8g / +74.3g | −37.1g / −11.1g | −45.0g / −14.1g |
| Buys (units) | 424 (887) | 423 (877) | 295 (1605) | 351 (979) |
| Worst trade / max drawdown | −23.0g / 10% | −23.0g / 10% | −11.1g / 53% | −11.1g / 61% |

This rule is better or equal on every line. The change is small: one 11-unit buy (Item Key 12999, −11.7g) drops out and one 3-unit buy comes in. It's in for removing a cliff no evidence backs, not for more rows.

## Considered options

- **No cutoff** (`nocut`, the Brain with `cheap_stock_cutoff` off): about 95g worse at the market mark, drawdown 10% → 53%. It buys fewer, larger runs into crashes. Cutting on short watching is what earns money here, so the review's main claim (§2.1) doesn't hold on this history.
- **ADR-0028's power test** (cut only once the old rate would have shown 2+ Sale Events in the window hours since, and an unwatched stretch kept whole): nearly as bad as no cutoff. Short watching rarely reaches 2 expected, so it seldom cuts.
- **Old Sale Events at a discount** (ADR-0031): rejected on 2026-10-08 (−13.1g → −29.5g on p4, which the Backtest reproduces). Not re-run.

## Consequences

- A crash seen only in Scans with no Observation Window between them is trusted until a window comes, however long that takes. A player who scans once a day never gets one, so for them the cutoff only fires within a session.
- Size is the remaining risk. A buy that takes every unit under its post price leaves no cheap stock, so no stretch, and no cutoff applies (Cured Medium Hide, 2026-10-12: 241 units at up to 7s posted at 14s 49c, with 767 units back from 6s 42c a day later). That's #170's caps and #171's EV, not this rule.
