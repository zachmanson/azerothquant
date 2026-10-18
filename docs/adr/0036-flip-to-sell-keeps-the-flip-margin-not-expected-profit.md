# Flip to Sell keeps the Flip margin, not Expected Profit

Tried and lost (#171 slice A). Flip to Sell stays as it is: the Sale Events minimum, the Sell room cap, the last-unit Flip margin, and the #170 caps on top (ADR-0011, ADR-0034).

The idea was to gate Flip to Sell on the run's expected profit instead. Buyers in t hours are Poisson, with a mean of the prior-shrunk Sale Events per hour × t × κ, and each takes the prior-shrunk average sale size. A unit sells within the horizon if enough buyers come to reach it in the queue. A unit that sells is worth post × 0.95 less effort and the deposits it lost first. One that doesn't is worth its Vendor Price less every deposit. The run length was the one with the best sum of those, less cost. It was taken if that cleared max(10% of cost, 1s), with no Sale Events minimum. Buying also stopped once the next unit's chance to sell was under 1%, which wasn't in the spec.

## Why

Judged by the Backtest (ADR-0032) against the capped `brain` (ADR-0034, ADR-0035), on a copy of the live history (87 Beta Scans, to 2026-10-14 23:41, 40g start). The bar was: vendor-mark central more than 5g higher, the vendor grader bounds not lower, worst trade and drawdown no worse, and market x0.65 no more than 5g lower.

| | `brain` | 3 d, κ 0.5 | 3 d, κ 1 | 7 d, κ 0.5 | 7 d, κ 1 |
|---|---|---|---|---|---|
| P&L, vendor / market mark | **84.6g / 115.7g** | 68.6g / 132.5g | 25.4g / 73.4g | 31.7g / 87.8g | −28.1g / −2.9g |
| Grader x0.65 / x1.2, vendor | **56.8g / 88.1g** | 51.6g / 67.4g | −6.2g / 29.3g | 14.4g / 38.6g | −54.0g / −47.4g |
| Grader x0.65, market | 89.4g | 116.7g | 31.1g | 58.5g | −33.6g |
| Buys (units) | 555 (910) | 767 (11,679) | 611 (8,666) | 605 (5,485) | 487 (5,313) |
| Relisted: made on spent | −75.6g on 62.9g | −134.0g on 82.0g | −134.7g on 83.9g | −124.5g on 88.6g | −95.3g on 52.3g |
| Worst trade / max drawdown | −16.2g / 9% | −21.1g / 17% | −16.8g / 23% | −15.8g / 23% | −3.6g / 60% |

Every variant lost at the vendor mark by 16g or more and broke the drawdown bar. Each bought several times the units `brain` does, and what didn't sell in the first week lost far more. A longer horizon or more buyers per Sale Event (κ 1) made Expected Profit more sure a unit sells, and both made it worse. The Sell Chance overrates demand on this history, as every loosening of the cheap-stock rules did (ADR-0033).

## Considered options

- **Sale Events minimum 2 on top** (the spec's fallback for a worse worst trade): not run. The best variant was 16g short of `brain`, and the minimum cuts the thin-evidence buys, not the overstock that lost the money.

## Consequences

- #188 (several post prices) runs on today's gate.
- The Cured Medium Hide buyout (#170: 241 units posted at 14s 49c, back at 6s 42c a day later) is still left to #170's caps.
- The code was never committed. Its diff is described on #171.
