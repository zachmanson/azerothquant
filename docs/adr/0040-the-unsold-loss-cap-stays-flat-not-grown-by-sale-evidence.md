# The Unsold Loss cap stays flat, not grown by sale evidence

Tried and lost (#195). A Flip to Sell's Unsold Loss cap stays a flat 3% of the Stake (ADR-0034), with Risky rows for the few-unit runs it drops (ADR-0037).

The idea was to let the cap grow for runs with strong sale evidence. A run's share went from 3% at the Sale Events minimum (3), in a straight line, up to a ceiling at 10 Sale Events at or above its post price, after the cheap-stock cutoff. It grew only if the units seen sold there, each Sale Event counted at no more than the typical sale size, covered the held units and the run. If they didn't, the run stayed at 3%. That gate was there to keep the Cured Medium Hide buyout out. Flips to Craft and Flips to Disenchant stayed at 3%, and the 60% room was unchanged.

## Why

Judged by the Backtest (ADR-0032) against `brain` on current main (2026-10-29), on the 87-Scan copy of the Beta history (to 2026-10-14 23:41). The bar was #171's: vendor-mark central more than 5g higher, the vendor grader bounds not lower, worst trade and drawdown no worse, and market x0.65 no more than 5g lower.

| 40g start | `brain` | ceiling 6% | 10% | 15% |
|---|---|---|---|---|
| P&L, vendor / market mark | **131.4g / 156.6g** | 65.9g / 94.4g | 90.0g / 137.4g | 86.9g / 124.1g |
| Grader x0.65 / x1.2, vendor | **99.3g / 135.3g** | 38.1g / 65.6g | 55.1g / 87.5g | 49.3g / 103.3g |
| Grader x0.65, market | **127.0g** | 69.2g | 106.3g | 89.2g |
| Buys (units sold of bought) | 92 (577 of 705) | 87 (513 of 667) | 87 (519 of 631) | 91 (560 of 696) |
| Sold out in week 1: made on spent | 176.3g on 162.3g | 116.6g on 120.6g | 141.2g on 171.9g | 134.8g on 176.2g |
| Worst trade / max drawdown | −6.4g / 8% | −5.0g / 11% | −12.7g / 6% | −5.9g / 7% |

| 15g start (launch-like, reported) | `brain` | 6% | 10% | 15% |
|---|---|---|---|---|
| P&L, vendor / market mark | **104.8g / 119.6g** | 97.3g / 113.7g | 53.8g / 69.1g | 64.5g / 82.4g |

Every ceiling lost at the vendor mark by 41g or more from 40g, and on every grader bound. From 15g, the start the change was for, it lost too. The bigger runs it allowed spent more on things that did sell, but made less on them: at 10%, 171.9g spent in the sold-out-in-week-1 group made 141.2g, against `brain`'s 176.3g on 162.3g. Even a run whose evidence covers it sells into a market that undercuts once it's posted (ADR-0034). This is the same lesson as ADR-0036: loosening Flip to Sell on the demand model's word loses on this history.

The must-pass cases held: no Cured Medium Hide row as of Scan 85 at any ceiling. Of the few-unit winners, only Redbeard Crest (10-11) changed, from a Risky row to a normal one. Steel Bar, Staff of the Friar, The 1 Ring, Redbeard Crest (09-28) and Troll's Bane Leggings (10-06) aren't named at any ceiling, the flat 3% included, so the cap isn't what keeps them off.

## Considered options

- **Sale Events alone, no coverage gate**: would bring back the hide buyout (commodities have many Sale Events). Not run.
- **An expected loss** (Unsold Loss times the chance it doesn't sell): ADR-0036's model again, which lost.

## Consequences

- On the latest Beta Scan (2026-10-20 19:52, 97g Stake) the cap shrinks nothing anyway. The Shopping List's one row is the Minimum Profit's doing (#197), not the cap's.
- At launch, with a small Stake, the few-unit dear flips come back as Risky rows (ADR-0037). Longer runs stay capped.
- The code was never committed. Its diff is in `Z:/aq-check-195/issue-195.patch`, and the spec is on #195.
