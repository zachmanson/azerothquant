# Old sales count at a discount after cheap stock goes up, not all or none

**Status: rejected (2026-10-08, #168).** Built and tested, then not committed: the backtest got clearly worse and the Shopping List still empties after a day away. ADR-0029 stands. The results are under "Why it was rejected" below.

Would have amended ADR-0029 (#168). The cutoff (the start of the stretch of cheap stock, kept through short breaks) is unchanged. What happens at it changes.

Under ADR-0029, once any Observation Window hours came after the cutoff, only the Sale Events since counted, and after 24 hours with none, nothing sold at the post price. The outside review (`docs/research/decision-review-2026-10-08/REVIEW.md` §2.1, §8) found that this decides on almost no evidence. On the 10-08 18:23 Scan, 495 Item Keys were judged on the 21 minutes watched between the two 10-08 Scans, and 492 had no sale in them, so their demand went to 0. No sale in 21 minutes is what a thin Item Key shows whether its price crashed or not. After every day away the Shopping List dropped to 2–5 Flip to Sell rows, against 20–32 otherwise.

So the Sale Events and Observation Window hours from before the cutoff now count at a weight `w` between 0 and 1, and the ones after it count in full:

- **Rate** = (w × units before + units since) / (w × hours before + hours since). The rate before is kept, but the evidence behind it thins out, so the Flip Sell Rate Prior (24 hours of no sales) pulls it down. Thin, stale demand gets sized down rather than cut.
- **w = exp(−max(0, E − n)) × 0.5^(age / 24 h).**
  - E = the Sale Events per Observation Window hour at or above the post price before the cutoff, times the Observation Window hours since. It's how many Sale Events the old demand would have shown since.
  - n = the Sale Events since.
  - The first factor is the power test that ADR-0029 dropped, made smooth. When the sales since keep up with the old rate, it's 1. When they fall well short, it heads to 0. Lesser Magic Essence (#135: 2.5 an hour before, 0.84 hours since, none seen) comes to 0.12, while a thin Item Key over 21 minutes stays near 1.
  - The second factor halves the weight for every day the stretch has been up (age = latest Scan − cutoff), watched or not. Cheap stock that sits for a day without being bought through is evidence too. It replaces the 24-hour step to 0 (`UNWATCHED_STRETCH_SECONDS`) with a half-life of the same length: unwatched means unknown, so the demand shrinks.
- **The Flip minimum of Sale Events (`flip_min_sale_events`) reads the raw count** at or above the post price over the whole range, before the cutoff or after. That check is there because one or two Disappearances can be one seller cancelling (#57), which says nothing about whether the demand is stale. Staleness is `w`'s job. If the minimum read the weighted count, an Item Key with 3 Sale Events and a stretch a day old would drop to 1.5 and lose its row, and the list would still collapse after a day away.

The readers are ADR-0028's: Flip to Sell, a Hold buy's Max Loss, and `brain recommend --why-not`. `--why-not` gives the weight and where it came from: "older sales count at 12% (expected 2.1 since, saw 0; stretch 30 h old)".

## Considered options

- **ADR-0028's power test, all or none** (cut once E ≥ 2): this catches LME (2.1), but it puts a cliff at the threshold. One more watched minute flips an Item Key from full demand to none.
- **Weight the units only, not the hours:** the rate drops straight to w × the old rate, and the prior then shrinks it again, counting the same doubt twice.
- **Poisson P(N ≤ n | E) as the weight:** with n near E it comes to about 0.6, so it docks Item Keys whose sales kept up.
- **A term for how far under the post price the cheap stock is** (the review's suggestion): there's no data to fit its shape, and the post price and the room already react to it. Left for #171.
- **The minimum of Sale Events on the weighted count:** see above.
- **A hard floor that cuts LME to no rows** (w < 0.2 → 0): it brings back the cliff. LME was a problem because of its size, all 3895 units. A small buy on doubtful demand is the bet the review argues for, and each further watched hour with no sale pushes a thick Item Key's `w` toward 0 quickly.

## Why it was rejected

Checked on the outside review's history copy (69 Beta Scans) with its probes. HEAD's Brain and this rule were each run on their own copy.

- **Backtest** (`p4_backtest.py brain wide last_buy=1790818960`: buys to Sep 30, graded to Oct 8). HEAD's re-run came out at −13.1g, against the review table's −10.5g. The comparison uses the re-run.

  | | HEAD | This rule |
  |---|---|---|
  | P&L, vendor mark | −13.1g | −29.5g |
  | P&L, market mark | −1.4g | −26.2g |
  | Worst trade | −6.6g | −11.1g |
  | Won / lost | 58 / 24 | 50 / 27 |

  That's far past the review's ~5g noise band. Loosening the cutoff added buys on the Scans between gaps (10-03: 11 → 41 rows), and they lost money. That fits the review's own finding that loosening without sizing does worst.
- **Rows per Scan** (`p5`): the mean rose from 14.2 to 20.0, but the Scans after a day away barely moved: 10-05 18:17 stayed at 5, 10-07 21:33 at 2, and 10-08 18:02 / 18:23 went from 4 / 2 to 7 / 6. So the collapse after a gap isn't mainly the cutoff, as the review thought (§2.1). At 10-07 21:33 under this rule, 5,848 Item Keys fail the minimum of Sale Events on the raw count, which the cutoff doesn't touch, 949 fail the Flip margin and 14 fail on dropped rows (#156).
- **LME** (unit test only): the week's sellable units went from 3027 to 527, 17% (w = 0.119).

The weighting may still be the right shape once buys are sized by expected value and capped (#170, #171). Revisit it there, and only measured against the backtest yardstick (#167).
