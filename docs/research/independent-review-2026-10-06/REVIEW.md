# Independent review: azerothquant

Scope: `code/` first (README, Brain, Addon, Pool), then `design-docs-read-last/`. Brain tests: 1089 passed, 25 skipped, 1 failed. The failure is `test_instance_lock` on Windows, where a venv launcher PID differs from the child PID. That is an environment artifact, not a quant issue. Every finding marked "probe" was reproduced against the real code by a script in `review-probes/`.

---

## 1. My model of the system

**Goal.** Make gold on one player's World of Warcraft: Forever Auction House. The system decides what to do with held items (Sell, Vendor, Craft, Disenchant, Hold) and what to buy (Flips to Sell, Vendor, Craft or Disenchant; Prediction buys; standing "Buy Under" prices).

**Data.**
- **Full AH Scans.** The Addon calls `C_AuctionHouse.ReplicateItems` at most every ~15 min, only while the player stands at the AH. Each row has item string, quantity, stack buyout, time-left bucket (1–4) and an own flag. There is no auction ID and no seller.
- **Pooled Scans.** Guild members upload stripped raw scans to a Cloudflare Worker.
- **Mailbox Reads.** Sold, cancelled and expired Outcomes, and won Purchases.
- **Character Reads.** Gold, bags and bank, recipes, merchant costs, Disenchant results.
- Everything is archived raw as gzipped JSON and replayed into SQLite.

**Estimation.**
1. **Listing lifetimes.** Each scan is matched only to the previous scan of the same Market. Listings are keyed by (Item Key, unit buyout), and identical ones are interchangeable. The matching is a min-cost max-flow: fewest new listings first, then fewest units sold. A drop in quantity becomes a **Partial Sale**.
2. **Disappearance → Probable Sale.** A listing missing from the next scan counts as a sale only if four conditions hold:
   - the gap is ≤ 60 min (an **Observation Window**);
   - its time-left bucket rules out expiry;
   - no same-quantity listing at an equal or lower price appeared in the same window (a **Repost**);
   - its price ≤ 1.2 × the lower Fair Value of the two scans.
3. **Sale Events.** All sales of one Item Key in one window are merged into one event. Its price is the *dearest* unit sold.
4. **Fair Value.** For one scan: the unit-weighted mean of the cheapest 15% of units, dropping units below 0.5 × that slice's median. It is used mainly to filter Probable Sales.
5. **Sell Rate.** Units sold in windows ÷ window hours × 24, over 14 days.
   - At decision time it is restricted to events priced at or above the intended post price.
   - It is cut to events after a "stretch of cheap stock" began (ADR-0028/29).
   - It is shrunk by pseudo-hours with no sales (3 h for Holdings, 24 h for Flips) and by a sale-size prior.
   - It needs at least 3 Sale Events before any buy can rely on it.

**Decisions.**
- **Post price.** Always the cheapest *other* ask left after the planned buys, minus 1c. It is capped by a Merchant Cost, and for held units by the dearest Sale Event.
- **Room.** Units that "will sell" within 7 days (or Days to Sell) = shrunk rate × horizon.
- **Holdings.** Sell while (post × (1−cut) − expected lost deposits) > Vendor Price, up to the room; Vendor the rest.
- **Flips to Sell.** Try each prefix of the cheapest other asks, repost under the next ask, and keep the most profitable run whose last unit clears max(20%, 1s) after deposits and effort.
- **Shopping List.** Ranked options, each sized alone within a Budget.
- **Predictions.** Buy only while Max Loss (cost − exit if wrong) ≤ 10%, within gold caps.

**Evaluation.**
- `brain replay` re-decides at every past scan for the Brain, an Auctionator emulation, a TSM emulation and ablations. Each is graded against later inferred Sale Events. A go/stop verdict is set for ~Dec 2: the Brain must beat Auctionator by ≥10%.
- Flip Grades compare real Purchases against what was named, using mail.

**What everything rests on.** Every Sell, Flip, Buy Under and Max Loss depends on one inferred quantity: **demand at a price**, reconstructed from Disappearances between irregular, player-timed snapshots. Most findings below are about that inference.

---

## 2. Findings, ranked by impact on making gold

Severity reflects the expected effect on decisions. Confidence covers both the mechanism and how large the effect is. "Probe" means I reproduced it.

| # | Finding | Sev. | Conf. (mechanism / size) |
|---|---|---|---|
| 1 | The player's own and guildmates' Purchases count as market demand (feedback loop) | High | High / Med |
| 2 | Incomplete own Scans create phantom Sale Events | High | High / Med |
| 3 | One lowball ask reprices all Holdings, which can trigger dumping or Vendoring | High | High / High |
| 4 | Demand capture is assumed to be 100%, and prime-time hours are scaled to 24 h | High | High / Low (unmeasured) |
| 5 | The replay, the go/stop test, is graded by the Brain's own demand model and has no error bars | High | High / Med |
| 6 | One malformed pooled Scan freezes a Market for every member | High | High / High |
| 7 | Sale Event priced at its dearest unit inflates demand at higher prices | Med | High / Med |
| 8 | Known own cancellations and outcomes are not used, and coincidence counts are dropped | Med | High / Med |
| 9 | Holdings room uses demand at *any* price | Med | High / Med |
| 10 | Thresholds tuned in-sample on a distorted Beta and applied to the Live launch | Med | High / Med |
| 11 | Partial Sales are treated as certain, but interchangeable matching fabricates them | Low–Med | High / Low |
| 12 | Buy Under highlight ignores its unit cap and staleness | Low–Med | High / Med |
| 13 | 2-hour postings are structurally invisible to Sell Rate | Low | High / Low |
| 14 | Small look-ahead leaks in the replay | Low | High / Low |

### 1. Own and pooled Purchases count as market demand (feedback loop)
**Evidence.** `observation.py:240-245` makes every Listing whose last Scan opens a window a sale candidate. Nothing in `observation.py`, `sell_rate.py` or `fair_value.py` reads `purchases()`; I grepped for it. The Purchases are known: `history.py:1815`. Probe P2: the player buys the 3 cheapest of 10 listings and nothing else trades. Result: 1 Sale Event, 3 units, **216 units/day**.

**Failure scenario.** The player follows a Shopping List Flip and buys a run of cheap listings. That run then counts as a Sale Event in the next window.
- It feeds the whole-rate Holdings room (finding 9).
- It feeds the market's typical sale size and the `flip_min_sale_events` count.
- If anyone else buys a dearer unit in the same window, the whole run is booked at that dearer price (finding 7), which inflates Flip demand at the post price.
- With the Scan Pool, every guildmate's Brain sees the same buys and has no way to exclude them. The more the guild follows the Brain, the more demand it "observes". This is a self-reinforcing loop, and the system's own action changes its input data.

**Fix.**
- Remove own Purchases from Disappearance candidates. Match each by Item Key, unit price, count and arrival time against the window it fell in.
- For the pool, upload members' Purchase records (stripped) so every Brain can subtract them.
- Until then, at least exclude own Purchases and report how many Sale Events each member's buys explain.

### 2. Incomplete own Scans create phantom Sale Events
**Evidence.**
- `Scan.lua:108-111`: a row whose item link hasn't loaded is dropped and counted in `droppedRows`.
- `scan.py:166` and `history.py:57,817`: the count is stored. **Nothing reads it.**
- `history.py:731-740`: `_complete_enough` checks pooled scans only. Own scans always pass.
- The matcher compares each scan only with the previous one (`history.py` `_insert_scan`). A listing missing from scan N is a Disappearance. When it shows again in N+1 it is a *new* listing, so Repost pairing (same window only) can't explain it.

Probe P1: 10 listings, the middle scan misses them, nothing actually trades. Result: **1 Sale Event of 10 units, 360/day**.

**Failure scenario.** The first scan of a session often has unloaded item data, and the Addon prints "N dropped for missing item data". Every cheap listing of the affected items becomes a Probable Sale and can cross `flip_min_sale_events` on its own. Truncated replicate reads would do the same. ADR-0026 calls this "the likeliest poison" but guards only the pool path.

**Fix.**
- Apply the completeness test to own scans too.
- Exclude both windows touching any scan with `droppedRows > 0` or a row count far below its neighbours.
- Add a "resurrection" check: a Disappearance whose identical listing (same key, price and quantity, time-left not higher) reappears in the next scan was missed, not sold.

### 3. One lowball ask reprices every held unit, and can cause dumping or Vendoring
**Evidence.**
- `recommend.py:686-697`: Holdings are valued with nothing bought (ADR-0017).
- `recommend.py:1989-2001` posts 1c under the cheapest other ask. The only cap is from above (dearest Sale Event or Merchant Cost), and there is no floor.
- `recommend.py:2248-2252` then Sells while the price beats Vendor, and Vendors the rest.

Probe P4: 20 Sale Events at 1000c and a book of 20 at 1000c. The Brain says Sell 5 at 999c. Add one listing at 300c and it says **Sell 5 at 299c**. With a Vendor Price above 284c it would **Vendor all 5**, which can't be undone.

**Failure scenario.** Any single underpriced or troll listing sets the price of the player's whole stock. In the same table, the Shopping List says to buy that listing as a Flip. ADR-0017 accepts that "a held unit's Sell price can sit under a Flip's Post at" as cosmetic, but it isn't cosmetic when it flips Sell to Vendor.

**Fix.**
- Price held units against the book *after removing asks that are themselves Flips to Sell or Vendor* (they will be bought by someone within minutes).
- Floor the price at a robust reference, such as the recent Sale Event median at or above the post or a multi-scan Fair Value. Recommend Hold/wait rather than Vendor when the cheapest ask is far below that reference.
- Never Vendor because of a single listing.

### 4. Demand capture is assumed to be 100%, and prime time is scaled to 24 h
**Evidence.**
- `sell_rate.py:128`: units ÷ watched hours × 24. Scans only happen while the player is at the AH (ADR-0003/0004), so the watched hours are mostly evening prime time. Probe P7 shows 2 peak hours extrapolated to a full day.
- `recommend.py:3634-3647` (`_flip_room`) and `2003-2020` (`rows`): the whole market's demand at or above the post price is room *for the player's units*.
- No term accounts for competitors who undercut in the following hours, other sellers already at the same price, or guildmates following the same list.

**Failure scenario.** Both biases push room, "days to sell", the deposit queue (`_Queue.lost`) and therefore every Flip size and Sell-vs-Vendor split in the optimistic direction, and they multiply. Suppose prime time runs at 2× the daily average and the player captures 40% of buyers after being undercut. Then expected sales over the horizon are about 5× too high. The undercut-by-1c pricing invites exactly that competition. ADR-0004 accepts the time-of-day bias and promises to "revisit if Lots sell consistently slower", but nothing triggers that review (see §3).

**Fix.**
- Estimate rate per hour-of-day bucket and integrate over the day. Use pooled scans to cover the off-hours, and shrink empty buckets toward a global profile.
- Add a capture share. Estimate it from own Outcomes: how often the player's posted listing was undercut before selling, and how fast own listings actually sold compared with the predicted rate.
- Calibrate the priors against Flip Grades `sold_within` rather than choosing them by hand.

### 5. The replay that decides go/stop is graded by the Brain's own model and has no error bars
**Evidence.** In `replay.py:214-225, 590-628`:
- Every policy's posts sell into the *Brain's* inferred Sale Events (phantom, cancel, own-buy and dearest-unit inflation included).
- A post at or below an event's price sells with infinite priority. No competing listing or later undercut is ever ahead of it.
- Bought listings are not removed from the later market.
- Leftovers are valued with the Brain's own `exit_values` for every policy.
- Grades are *summed over every scan* with overlapping 7-day horizons, and `over()` (`replay.py:103`) returns a point ratio.
- ADR-0015 sets the binding thresholds: ≥ +10% to continue, ±5% to stop.

**Failure scenario.** The Brain optimizes against the same Sale Event model the grader uses, so any bias in that model shows up as Brain outperformance. The baselines don't use it. An inflated Sell Rate makes the Brain buy more, and the grader then "sells" those units into the same inflated events. The sum over heavily autocorrelated scans has an unknown, probably large, variance, so a +10% result could be noise. The verdict is not falsifiable as built.

**Fix.**
- Report a block-bootstrap confidence interval, resampling by day, and require the interval, not the point estimate, to clear the thresholds.
- In the grader, add queue position: count units of other listings at or below the post price that were up at sale time, and sell only after them.
- Value every policy's leftovers at one neutral price, for example 0.8 × emulated DBMarket or Vendor, and report sensitivity to that choice.
- Grade on a hold-out period not used to tune ADR-0028/29 parameters.
- Treat realized profit from mail as the primary check once it exists.

### 6. One malformed pooled Scan freezes a Market for every member
**Evidence.**
- The Worker checks only the *headers*: `pool/src/index.ts:119` rejects a `requestedAt` more than 10 minutes in the future and never opens the body.
- `pool_sync.py:141` imports the body's own realm, faction and `requestedAt` without comparing them with the index entry.
- `history.py:654-669`: any later scan older than the Market's latest by more than 48 h goes to "wait for `brain rebuild`".

Probe P5: one pooled body dated +30 days, then the player's real scan 30 min later. Result: **imported 0, waiting for rebuild 1**. A rebuild re-imports the same archived file, so the freeze survives until an admin revokes the uploader's key.

**Failure scenario.** One member's client bug, or a hostile member, stops every Brain in the guild from updating that Market. The Brain keeps recommending from frozen data with nothing in game saying so. The same gap lets one key inject fabricated listings that appear and then vanish. Those fake sales inflate Sell Rate, so guildmates' Brains recommend buying the item, and the attacker sells into them. ADR-0026 defers cross-checks between uploaders.

**Fix.**
- Reject a body whose realm, faction, era or `requestedAt` differs from its index entry.
- Reject `requestedAt` later than the upload time.
- Down-weight Disappearances supported by only one uploader once the pool has at least 2 active members per Market. ADR-0026 already names this.

### 7. Sale Event priced at its dearest unit inflates demand at higher prices
**Evidence.** `observation.py:339-352` and `sell_rate.py:50`. Probe P3: one buyer takes ten units at 100c and one at 115c. `at_or_above(114)` then reports **11 units** of demand. The truth is 1.

**Failure scenario.** A Flip that posts at 114c sees 11× the real demand at its price. ADR-0012 says merging "undercounts demand, which is the safe direction". That holds for the event *count*, but for demand *at a price* it overcounts, which is the unsafe direction.

**Fix.** Keep each event's price ladder as (price, units) pairs, and have `at_or_above` count only units priced at or above p. The event-count logic can stay as it is.

### 8. Known own cancellations and outcomes go unused, and coincidence counts are thrown away
**Evidence.**
- Own listings that disappear are candidates like any other (`observation.py:240`), yet their true Outcome (Sold, Cancelled or Expired) is in the mail (`history.py:1801`). Probe P4: an un-reposted cancel counts as a sale.
- `coincidences` and `reposts` are computed (`sell_rate.py:29,125`), but no decision reads them. I grepped for both.

**Failure scenario.**
- Own cancellations inflate Sell Rate, in the same direction as finding 1.
- More importantly, own listings are a **free labelled dataset** for measuring how accurate the Disappearance classifier is. Nobody uses it.

**Fix.**
- Drop own Disappearances that have a Cancelled or Expired Outcome.
- Compute the classifier's precision on own listings. Apply it as a multiplicative correction to Probable Sales, or at least publish it.

### 9. Holdings room uses demand at any price
**Evidence.** `recommend.py:1950-1980` and `2003-2020`. Held units use the *whole* Sell Rate, while the post price is capped only at the dearest event. CONTEXT.md states this on purpose: "gold already spent".

**Failure scenario.** An item sells 100/day at 10c and once a week at 100c. Held units posted at 99c get room for about 700 in 7 days. They are kept from Vendor, posted repeatedly, and lose deposits. The queue understates the deposit losses for the same reason.

**Fix.** Use `rate.at_or_above(post_at)` for held units too, plus the siblings, as ADR-0022 already does for them. Past spending is a sunk cost and doesn't change future demand at a price.

### 10. Thresholds tuned in-sample on a distorted Beta, applied at the Live launch
**Evidence.** These were all set on Beta data that ADR-0015 itself calls "distorted":
- `SHORT_BREAK_SCANS = 2` (`recommend.py:376`) was chosen by comparing 1 against 2 on the same scans used to show it works. ADR-0029 reports +63.83g over about 46 Item Keys, then concedes it comes out −46g per Scan through 10-04 20:28 for one setting, and +14g for the other.
- The 1.2 multiple, the 3 h and 24 h priors, `flip_min_sale_events = 3`, the 24 h grace, and the 15% / 0.5 Fair Value constants.
- Live launches Nov 4. A launch economy has steep price decay, which is exactly the regime where a 14-day equal-weight Sell Rate and history-based demand mislead.

**Fix.**
- Freeze parameters, then evaluate them on later Live data only.
- Add recency weighting, for example an exponential half-life on Sale Events.
- Re-tune on the first Live weeks with a pre-registered hold-out.

### 11. Partial Sales are treated as certain, but interchangeable matching can fabricate them
**Evidence.**
- CONTEXT.md and ADR-0002 call a quantity drop "always a sale".
- Matching maximizes matched pairs before minimizing units sold (`matching.py:85-124`). A whole 20-stack that sells, plus another seller's 5 at the same price, becomes "15 units Partial Sale" (probe P6).
- A cancelled 20 with a 5 reposted at the same price also becomes 15 units of "certain" sale.
- Partial Sales skip the price filter and the Repost test (`observation.py:327`).

The client has commodity listings, so real partial buys exist. The risk is in non-commodity stacks and in markets where many sellers sit at one price.

**Fix.**
- Treat only commodity Item Keys' drops as certain.
- For stack items, run the same price and repost tests on the implied drop.

### 12. Buy Under highlight ignores its unit cap and staleness
**Evidence.**
- `BuyUnderMatch.lua:48` flags every listing at or under the price.
- `BuyUnder.units` is shown in the table (`RecommendationTable.lua:455`) but never enforced when highlighting.
- `Freshness.lua` checks that imports are in order, not how old the data is.

**Failure scenario.** A crash in price after the last Brain run leaves green highlights on a falling item. The player buys past the room the price was derived from.

**Fix.**
- Decrement `units` per Purchase seen.
- Expire Buy Unders after N hours, or dim them by age.

### 13. 2-hour postings are invisible
**Evidence.** `observation.py:92` and the time-left buckets (bucket 2 is 30 min–2 h). Every 2-hour posting lives entirely in buckets 1 and 2. Any gap of 30 min or more makes `expiry_possible` true. Probe P5: 2 real sales, **0 counted**.

**Failure scenario.** Items whose sellers post at 2 h have systematically low Sell Rates. The bias runs opposite to the others, which makes the net error harder to reason about.

**Fix.** Use the listing's observed bucket history; for example, first seen in bucket 2 means it was posted at 2 h. Or report the share of candidates lost this way per Item Key.

### 14. Look-ahead leaks in the replay
**Evidence.** The replay at time t sees future data through:
- `non_stacking(seen)` over all listings (`recommend.py:1660`);
- deposits from the latest Sold invoice (`:1661`);
- Repost pairing against new listings' *final* quantity (documented at `observation.py:265-269`);
- latest recipes and merchant costs (ADR-0015 acknowledges these).

**Fix.** Filter by `as_of` everywhere. These are small leaks, but they feed the go/stop number.

**Also noted, not ranked:**
- Fair Value is computed from one scan. On books under 7 units it equals the cheapest ask, so the 1.2× filter is noisy for thin items.
- Prediction dates and `start_of` use local time, while Scans use server time. This is accepted in ADR-0026.
- Inexact rows (buyout not divisible by quantity) are negligible when stack prices are typed in whole silver. A probe found 0% for quantities of 5, 10 and 20.

---

## 3. Things nobody is measuring that they should

1. **Disappearance classifier accuracy.** Use own listings with mail Outcomes as ground truth: the share of own "Probable Sales" that were really Sold, Cancelled or Expired. This is the single most useful number for this system.
2. **Phantom rate.** The share of Disappearances whose identical listing reappears in the next scan, overall and for scans with `droppedRows > 0`.
3. **Own and pool purchase contamination.** The share of each Item Key's Sale Events explained by Purchases.
4. **Prediction calibration.** Predicted units sold within the horizon, per Sell and Flip, against what the player actually sold, plotted by decile of predicted rate. Flip Grades record `sold_within` but not against a predicted figure, and they exclude deposits.
5. **Time-of-day coverage.** Observation Window hours by hour of day, and the rate per bucket.
6. **Undercut and capture.** How long the player's own posts stay cheapest, and the share of the market's sales at or above their price that they got.
7. **Winner's curse.** Realized ÷ expected profit by Shopping List rank. Top-ranked flips are the ones whose noisy demand estimates came out highest.
8. **Replay uncertainty.** Bootstrap confidence intervals, and stability across sub-periods.
9. **Data quality per scan.** `droppedRows`, row count against neighbours, and the gap between `firstUpdateAt` or `readAt` and `requestedAt`. All are stored but never looked at.
10. **Regime drift.** Rolling median Fair Value and Sell Rate per Item Key at launch, to decide how much history to trust.
11. **Pool integrity.** Per uploader, the share of Disappearances that only that uploader's scans support.

---

## 4. Design docs against the code

### Per-ADR verdicts (quant-relevant ones)

| ADR | Holds up? | Covers or misses what I found |
|---|---|---|
| 0002 Listing lifetimes, interchangeable matching | Storage design holds. The claim that "a Partial Sale is the only sale the data proves for certain" does not. | Misses finding 11 |
| 0004 Observation Windows only | The core idea is sound. Its consequence "accepted, revisit if Lots sell slower" has no monitor attached. Cancellations are acknowledged. | Covers part of finding 4 (time of day) and finding 8 (cancels). Misses findings 1, 2, 13 and capture share |
| 0005 Archive is the source of truth | Holds. It is the reason fixes can be replayed. | — |
| 0006 Predictions bound the downside | Sound framing. A brake from 5–15 graded calls a year is statistically meaningless, as the ADR concedes. | — |
| 0010 superseded by 0017 | — | — |
| 0011 Flip bought whole | Holds as a heuristic. The greedy-ratio approach isn't a knapsack solution, which the ADR acknowledges. | — |
| 0012 One Sale Event per window | The count logic holds. Its "safe direction" claim is wrong for demand at a price. | Misses finding 7 |
| 0013 Deposits per expected expiry | Reasonable. It inherits the queue's optimistic rate. Flip Grades exclude deposits, so realized results look better than they are. | Partly misses finding 4 |
| 0015 Replay against Auctionator and TSM | A good idea, but as built it's a weak test: same-model grading, no error bars, no competition, summed overlapping horizons. | Misses finding 5. Acknowledges part of finding 14 |
| 0017 Options sized alone | Product decision; holds. Its "Sell under Flip post" consequence is understated. | Misses finding 3 (lowball ask → Vendor) |
| 0019 Buy Under | The formula is fine. It is "not graded" by design, so no feedback ever reaches it. | Misses finding 12 (units and age not enforced) |
| 0020 Days to Sell | Holds. | — |
| 0022 Sibling pooling, held units only | A sensible partial-pooling compromise. The 0.5 weight is untuned, but easy to switch off. | Holdings' *own* rate still ignores price (finding 9) |
| 0023 / 0025 / 0027 Flip Grades and named Lots | The right kind of measurement. It never feeds back and ignores deposits. | It is the natural home for the calibration in §3 |
| 0024 Beta Sell Rate (off by default) | Prudent default. The ratio comes from two single-scan Fair Values, so it's noisy. | — |
| 0026 Scan Pool | The raw-scan design is right. Completeness is guarded for pooled scans only, and body versus header is never checked. | Misses findings 2 and 6. Defers manipulation. Feedback loop through the pool not discussed |
| 0028 / 0029 Demand cut at the cheap stretch | Fixes a real failure (a crash read as demand). Each fix is driven by an anecdote, and parameters are tuned in-sample. | Finding 10 |
| 0003 / 0016 Addon acts only on the selected row; 0008, 0009, 0014 crafting; 0018 Disenchant tables; 0021 data addon | Mechanics. Nothing quantitatively wrong found. ADR-0018's Wilson and t-interval check is the one place the project uses a proper interval. | — |

### Where docs and code disagree
1. **Partial Sales.** CONTEXT.md and ADR-0002 say a quantity drop is always a sale. The matcher can produce a drop by pairing different sellers' listings at the same price (probe P6).
2. **Sale Event pricing.** ADR-0012 says merging errs low. `at_or_above` on the dearest unit errs high (probe P3).
3. **Truncated Scans.** ADR-0026 names them the likeliest poison, but the code guards only pooled scans. Own scans' `droppedRows` is stored and never read.
4. **Buy Under.** ADR-0019 says `units` is how many units the price is good for. The Auction House highlight flags every matching listing with no count.
5. **Coincidences.** ADR-0004 keeps them "as a baseline … in case we later switch to weighting". They are computed and discarded, and are never surfaced, not even in `--why-not`.
6. **"Revisit if Lots sell slower or faster"** (ADR-0004, twice). No code compares realized against predicted sell speed, so the trigger can never fire.
7. **Replay inputs.** ADR-0015 lists the look-ahead it accepts (recipes, merchant costs, vendor prices, deposits). It doesn't list the non-stacking test or Repost quantities.

### Performance (added on request)

Measured on synthetic data at the README's stated size: about 58k rows per Scan and 7k Item Keys, with 24 Scans 20 minutes apart. The scripts are in `review-probes/perf/`. Real histories are longer, so every cost that grows with history is understated here.

| Stage | Measured | Cause | Fix | Measured gain |
|---|---|---|---|---|
| Replay | **~50 s per replayed Scan** (7 policies) | `exit_values` (`recommend.py:1582`) runs 8× per Scan (`replay.py:225,628`). Each run builds a full `_valuer` with no cache, at the *same* horizon Scan. That is 49 of 87 s. | Build one Valuer and one cache per (Market, horizon Scan) and value every policy's leftovers with it. Pass one `FairValueCache` through `replay`, `flips` and `grades`. | Shared cache alone: −15%. The Valuer reuse should remove most of the 49 s (estimate). |
| Import | 2.2 s per Scan | `_match_group` builds a min-cost-flow graph for ~56k groups per Scan, almost all 1×1 | Pair a 1×1 group directly when `can_match` (`matching.py:85`) | **−38%**, identical history |
| SavedVariables parse | 3.3 s per Scan | Pure-Python parser running per character and per token (`savedvariables.py`) | Addon writes each Scan's rows as one packed string. Smaller tweaks (regex string and whitespace fast paths) gave only −12%. | Packed split: **0.06 s**. File 4.4 → 1.2 MB, which also speeds logout and `/reload` in game. |
| Recommend, cold | 16 s (8.6 s warm) | `supply_at` runs a full scan of `listing` with a correlated subquery, once per Scan whose Fair Values are needed | Keep first and last seen times on `listing` with an index, or compute every needed Scan's supply in one sweep over the `listings` the pass already loaded | 120 → 93 ms at 98k rows. The gain grows with history, since old listings get skipped. |
| Per-pass work grows with all history | — | `listings()`, `_ends_of_windows`, `non_stacking`, `_others_lows` and `disappearances` all walk **every Listing ever seen**, though Sell Rate needs only 14 days. There is no retention. | Load only Listings with last seen ≥ now − range (window), and keep a persisted tally for older data | Not measured. Without it, cost per pass grows without bound. |
| `_others_lows` + `cheapest_seen` | 1.6 + 1.8 s | Both compute the cheapest other ask per (Item Key, Scan): one in Python per Listing × span, the other as a scan × listing SQL join | Compute it once per pass with a sweep and share it | ~3 s per pass (estimate) |
| Flip demand lookups | ~1.8 s; 340k calls in replay | `at_or_above` and `since_cheap` filter tuples and `dataclasses.replace` on every call | Sort `sale_prices` by price with cumulative units and use bisect; memo per (Item Key, post_at) | Estimate 2–5× on this stage |
| `db_market` | 9.4 s per replay | `statistics.mean`/`pstdev` (exact arithmetic) | Plain float arithmetic | **7.6×** on that call |
| `fair_value` median | 11.5 s in replay | `median` over a generator expanding every unit | Weighted median over (price, quantity) | Not measured |
| `held_at_writing` | Full Valuer per Item Key (`recommend.py:1301`) until frozen | `_exit_value` per item | One `exit_values` call for all of a Prediction's items | — |

The `brain bench` command exists but only times `recommend`. Extend it to cover import, parse and one replayed Scan, so these numbers can be tracked.

### Bottom line
The engineering is careful and well tested. The weak point is statistical. One inferred quantity, demand at a price, drives everything. It has at least four upward biases: own and pooled buys, phantom disappearances, pricing at the dearest unit, and time-of-day plus 100% capture. Only one downward bias, 2-hour postings, partly offsets them. Nothing checks the estimate against the ground truth the system already collects in mail. The go/stop replay is graded with the same estimate, so it can't detect these errors.

Before the Dec 2 verdict I would do three things:
- Fix findings 1, 2 and 6.
- Measure classifier precision on own listings (§3.1).
- Add bootstrap confidence intervals and queue position to the replay.
