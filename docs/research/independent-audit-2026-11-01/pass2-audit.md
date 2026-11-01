# Pass 2: independent audit of azerothquant's decisions

Date: 2026-11-01. Auditor: outside pass, code and data first, project docs last.
Data: a read-only copy of `brain/history.sqlite` (taken with the SQLite backup API on 2026-11-01 13:37), config from `brain/config.toml` (live overrides: `flip_min_margin_share = 0.1`), Predictions from `brain/predictions.toml`. All scripts and raw outputs are in the scratchpad, not the repo.

Order of writing: section 2 (and 2.7a) first, before any project doc was opened; then section 3 after reading pass1; then sections 4 to 6 after reading the project docs. This section was written last. The only later edit to section 2 was correcting a few file:line numbers that were off by a few lines; no verdict text changed.

## 1. Top findings, ranked by what they cost in gold or decision quality

1. **The Backtest that every buy-side decision since 10-08 was judged on is dominated by an artifact.** Run on today's code (97 Beta Scans, 40g, no Predictions), the Brain makes +90.7g, and its five best trades are all Flips to Vendor of one item, 11288, adding to 123.2g (136% of the total): the rest of the run lost at least 32.5g. 11288 sat on the Beta AH at 100c against a 200c Vendor Price in walls of up to 2,215 Listings for six days, and the simulation buys those same Listings again at every Scan, because a Flip to Vendor closes at once (backtest.py:236, 574) and the Scans never lose what the simulation bought. ADR-0034 cites "11288 +28.1g" as evidence for the cap it chose. Until the simulation removes what it buys, the Backtest's P&L, the "brain beats Auctionator" gap and the ADR-0034 to 0041 choices made on it are not evidence.

2. **Predictions are active before they are written, and it already moves gold.** `Prediction.active_on` (predictions.py:32) ignores `written`. Both Predictions in predictions.toml are written 2026-11-04, so today (11-01) the Brain is already moving the player's held Tin Ore, Silk, Iron and the rest to Hold, taking them out of Flips, and listing Prediction buys; on Beta Scans from September it did the same (B5). In the Backtest the bug alone swings the Brain from +90.7g to -10.5g, because it removes 20 Item Keys and their crafts from every Scan. Lots honour `written` (lots.py:212) and CONTEXT.md says a Prediction starts when written, so this is a plain bug with no test. A one-line fix.

3. **The Brain's expected profit is about twice what really happens.** On the one test that is not graded by the Brain's own inferred sales, the player's 18 real Flips graded from mail, realized Profit was 48.7% of expected and only 36.5% of units sold within the horizon the Brain priced them for (B7). The price was about right (median 95.5% of Post at); the volume was not. Days to Sell is a mean queue time (recommend.py:4060), not a percentile. ADR-0004 promised to revisit the time-of-day bias "if Lots sell consistently slower than predicted"; they do, and nothing compares the two.

4. **Most of the Shopping List is rows nobody has tested, with losses up to half the Stake.** On 10 sampled Beta Scans at 40g, 36 of 60 rows were Risky and they carried 79% of the list's expected profit (B8); the largest could lose 43% of the Stake if unsold. The Backtest never takes a Risky row (ADR-0037), and `risky_max_loss_share` was raised to 0.5 so that one remembered winner, Steel Bar, would show (ADR-0041). The record that is supposed to judge them is 18 Flips, two of which (Steel Bar +12.6g, Cured Medium Hide -8.7g) are the anecdotes the rules were written around.

5. **Sell Rate measures the player's scan schedule as much as the market.** With 12 h windows and Market-wide hours (ADR-0035), sale units seen per window hour fall 22x from 30-minute windows to 6-12 h ones (71k/h to 3.3k/h), and only about 3x of that is overnight demand: the rest is 12 h postings becoming invisible over any gap of 2 h or more while their hours still count (2.2). Sell Rate reads roughly half of real demand on this cadence, by an amount that varies by item and by when the player plays. The review that proposed 12 h windows made per-gap exposure a condition; the project dropped it partly for "one number per Market".

6. **Cancels are counted as sales, the project knows the rate, and uses it nowhere.** 76% of Sale Events rest on Disappearances alone; 24% of unpaired candidates sit next to a same-quantity higher-priced repost and still count. On the player's own Listings the Sell Rate rule is 84% right (n = 25) and the grader's rule 65% (n = 43). The correction was deferred to the expected-value design (ADR-0035), which was then rejected (ADR-0036), so the measured precision is a printed line and nothing else.

7. **Every parameter is tuned in-sample on one drifting Beta history, with bars inside the noise.** The Brain's Backtest moves 101g on an input that should be irrelevant (finding 2), yet changes are adopted or rejected on 5g bars (ADR-0036, 0040) and won by 4.6g (ADR-0035) or 4.7g (ADR-0041), on the same 86 to 97 Scans, with no holdout. Beta prices drifted (median 1.24x first week to last, 10-90% range 0.47x to 5x) and Live has no data at all. None of these numbers should be expected to carry to Live.

8. **Predictions will be close to inert at launch, and say the wrong thing about it.** With `beta_sell_rate_weight = 0` and a 3-Sale-Event minimum on the exit, every Prediction unit falls to Vendor Price in Live's first days and fails the 10% Max Loss test (ADR-0024 says so itself). "Launch week mats" lapses 2026-11-11, seven days after it is written. The Predictions tab will show "would lose 9x%", which reads as a bad trade rather than "no Live sales seen yet". By design a Prediction only buys what already resells within 10% of cost, so it never expresses the bet the player is making.

9. **The Backtest is graded by the signal it is testing.** Since ADR-0035, Sell Rate and the grader's Sale Records use the same 12 h, can't-have-expired, not-a-Repost rule; ADR-0032 had rejected exactly that ("would grade its own decisions on the evidence they were made from"). The central run believes 100% of inferred sales against a measured 65%; buys fill at the Scan's prices with no latency; Vendor Prices and item info are latest-only. It is out of sample in time, not in method.

10. **Several earlier review findings are still open in the code.** Sale Events priced at the dearest unit still overstate demand at a price (`at_or_above`, sell_rate.py:49); held units still use demand at any price (`holdings_room`); Buy Under highlights still have no unit count or age; time-of-day and capture share are still unmodelled; Partial Sales still skip the price and Repost tests in Sell Rate. The fixed ones (own Purchases, dropped-row phantoms, pool body checks, own cancels) were the data-plumbing ones; the open ones are the statistical ones.

## 2. Verdicts formed before reading project docs

Written after reading `brain/src` and `brain/tests` and querying the data, before opening CONTEXT.md, any ADR, any review, any research doc, or pass1. Nothing below was changed after Phase 2 or 3 started.

### 2.0 What the data is

- One Market only: `Classic Beta PvP / Alliance / beta` (market id 1). There is no Live (`_forever_`) Scan in the history yet. Every number below is Beta.
- 97 Scans from 2026-09-26 16:19 to 2026-10-20 23:52 UTC, all `own`, one character. Gaps between Scans: median 1.57 h, mean 6.1 h; 35 gaps are 30 min or less, 75 are 12 h or less, 21 are longer than 12 h (A1).
- 2,172,535 Listings, 19,073 distinct Item Keys, 32,671 Partial Sales, 376 auction mails (159 sold, 60 cancelled, 58 expired, 99 won).
- The 2026-10-22 anomaly: there is no Scan on 10-21 or 10-22. The anomaly only reaches the history through Character Reads: max character gold jumps from 16.9g (10-14 to 10-20) to 99.1g on 10-22 and 100.9g on 10-23, and 94 Item Keys are held on 10-22 (A2, A7). No code handles it (`grep` finds nothing for the date or for "anomal"). Effect: `pooled_gold` (history.py:1972) takes each character's latest read, so any Beta recommendation after 10-22 sizes caps, Stake and Prediction caps from ~97g of loot gold. The Backtest uses simulated gold and Scans that stop on 10-20, so it is not touched. Market prices, Sell Rates and Sale Records are not touched. Verdict: harmless to decisions that matter (Beta is over), but nothing protects against it, and the fix (exclude reads after the last Beta Scan, or a manual cutoff) does not exist.

### 2.1 Sale inference (observation.py)

How it works: a Listing that is in one Scan and missing from the next is a Disappearance. It is a Probable Sale candidate only if the gap is 12 h or less (`observation.py:102`), its time-left bucket could not have run out in the gap (`_least_time_left`, :107), the Item Key was not in a dropped-rows set (:294-303), no identical Listing reappears in the next Scan (`_missed`, :438), no Repost explains it (same Item Key, same quantity, same or lower price, new in the same Scan; `_pair_reposts`, :122), and its price is at most 1.2x the lower of the two Scans' Fair Values (:394-397). Partial Sales (a matched Listing's quantity dropped) are added. One Sale Event per Item Key per window (:592).

Numbers (B1, B2):
- 2,149,992 Disappearances. Only 226,065 (10.5%) pass the gap and expiry tests. After the dropped-rows and `_missed` filters: 182,731 candidates. 31,364 of them (17%) pair as Reposts; 151,367 remain.
- Of those 151,367, 35,931 (24%) sit next to a new Listing of the same Item Key and quantity at a higher price in the same window. The code calls these "coincidences" (observation.py:117-119) and still counts them as sales. A seller who cancels and reposts higher, or reposts a different stack size, is counted as a sale. Repost pairing requires an exact quantity match (:134, :141), so any cancel-and-restack is a sale.
- These become 55,143 Sale Events (2,019,321 units). Only 13,047 Sale Events (24%) include a Partial Sale, the one signal that cannot be a cancel. 76% of the Sale Events rest on Disappearances alone.
- Calibration on the player's own Listings, the only ground truth (B1): the Sell Rate rule calls 25 matched own Listings sold, 21 really sold (84% precision) and catches 21 of 49 Sold mails (43% recall). The Backtest's Sale Record rule calls 43, 28 really sold (65% precision), catching 28 of 49 (57%). Sample sizes are tiny (n = 25 and 43).
- The player's own behaviour: 60 Cancelled mails vs 159 Sold (A2, A7). If other sellers cancel at anything like that rate (27% of non-expired removals), the repost filter cannot catch most of it.
- Listing identity is fuzzy: there is no auction ID, and matching chains interchangeable Listings (matching.py:3-9). 81,334 Listings (3.7%) live longer than their first-seen time-left bucket allows under the configured maxima, and 1,875 live over 48 h, which no single posting can (A4). Some sales and cancels are hidden by being matched to a different, newer auction at the same price.

Verdict: the rule is careful about expiry and about rows the Scan dropped, but it has no answer to cancels. It is a disappearance counter with filters, and roughly a sixth (Sell Rate rule) to a third (grader rule) of what it calls sold on the one sample with ground truth was not sold. The project measures this (`grader_calibration`, `sell_rate_calibration`) and then does not use it anywhere: `grader_calibration` "doesn't move the grader's bounds" (observation.py:825-827). Sound in parts, not trustworthy as a demand number on its own.

### 2.2 Sell Rate (sell_rate.py) and sell-time estimates

How it works: units in Sale Events over the hours of Observation Windows in the last 14 days, times 24 (sell_rate.py:189). For Flips, discounted as if 24 more hours were watched with no sales and the sale size shrunk toward the typical size with 5 pseudo-events (recommend.py:4421-4450). A Flip needs 3 Sale Events at or above its post price (`_flip_room`, :4398). Days to sell = queue position / units per hour (:4060).

The denominator problem (B4, A6). The expiry test means a 12 h posting (time-left bucket 3, which is how 1.34M of the 2.17M Listings were first seen) can only count as sold in a gap under 2 h. In a longer gap it is invisible, but the gap's hours still count fully in `window_hours`. Measured sale units per hour of window, by window length:

| window length | windows | hours | Sale Events / h | units / h |
|---|---|---|---|---|
| 30 min or less | 35 | 11.2 | 2,075 | 71,478 |
| 0.5 to 2 h | 22 | 27.3 | 835 | 31,411 |
| 2 to 6 h | 12 | 38.6 | 142 | 5,100 |
| 6 to 12 h | 6 | 49.7 | 72 | 3,266 |

A 22x fall in units per hour. Some of that is time of day (long gaps are overnight). To separate the two I counted signals that stay visible in any gap up to 12 h: bucket-4 Disappearances fall only 3x (956/h to 319/h) and Partial Sales 8.5x. So demand falls perhaps 3x overnight, and the rest of the 22x, roughly another 7x, is the detector going blind. 39% of all window hours (49.7 of 126.8) are 6-12 h windows that see sales at a small fraction of their true rate. A rough correction (scale each window class by the bucket-4 ratio to the 30-minute class) puts true units sold over the windows at about 4.2M against the 2.0M counted, so Sell Rate on this Scan cadence reads about half of real demand, and how much it under-reads depends on how often the player happens to scan and on each item's usual posting length. On Live, with a different play pattern, the bias will be different and nothing measures it.

Verdict: Sell Rate is not a property of the market; it is a property of the market and the Scan schedule. It is biased low (safe for sizing, costly for coverage), the bias is not constant across items (items posted for 12 h are hit hardest, items posted for 48 h least), and the 24 h prior and 5-event sale-size prior are tuned on top of a biased base. The "days to sell" numbers are built on the same rate. Against the one real check, the player's own graded Flips (2.6), "sold within horizon 36.5% of units" is far below what Days to Sell promised, so the low bias in Sell Rate did not translate into conservative sell-time promises: the post-price assumption (2.4) dominates.

### 2.3 Market depth and price stability (B3, A5)

- Over 126.8 window hours: 11,039 Item Keys have at least one Sale Event, 5,313 have 3 or more (the Flip minimum), 1,235 have 10 or more, 278 have 30 or more. Median Item Key: about 0.4 Sale Events per day. 2,644 Item Keys average one or more Sale Event per day.
- The top 100 Item Keys hold 11% of Sale Events but 83% of units sold. Volume is a handful of mats; everything else is thin.
- Fair Value (fair_value.py:46) is the unit-weighted mean of the cheapest 15% of units in one Scan, no smoothing over Scans. Across the 90 Scans with stored Fair Values, the median Item Key (with 20+ Scans) has a coefficient of variation of 0.68; 19% of Scan-to-Scan moves exceed 20%.
- Beta drifted: for 3,050 Item Keys seen in both the first and last week, the median last-week/first-week Fair Value ratio is 1.24, with the 10th to 90th percentile running from 0.47 to 5.0.

Verdict: outside the top few hundred Item Keys this is a market of a few sales a week, where a 3-event gate is three disappearances, any one of which may be a cancel. Beta prices were not stable enough to tune anything on, and Beta is not Live.

### 2.4 Buy list: ranking, sizing, post price (recommend.py)

- Post price for a Flip to Sell is 1c under the cheapest other player's Listing left after the run is bought (`_undercut`, :4465; `_flips`, :4049-4060). Profit assumes every unit sells at that price within Days to Sell (:4069). It is protected by: demand counted only from Sale Events at or above the post price (:4356), at least 3 of them (:4407), sale prices capped at 1.2x Fair Value by the inference rule (so a post above 1.2x Fair Value can never have demand), a cheap-stock cutoff that counts demand only since cheaper stock appeared (#132, `_Cheap`, :426), deposits lost while queued (:4061-4068), and a 10% margin (config) or 1s floor.
- Not modelled: anyone undercutting after you post. The queue assumes you stay first until sold.
- Ranking: each option sized alone within all the gold, shown if it ranks top 50 by any of Profit, Per click, Per day or ROI (`_best_ranks`, :4762). Options are alternatives; nothing on the list says what the best combination is.
- Risk caps (`_risk_caps`, :1019): a 3% of Stake Unsold Loss cap per option and 60% of Stake as room. A Flip the loss cap drops comes back as a Risky row if it is 5 units or fewer, or a "long risky" run with up to 50% of Stake (!) as Unsold Loss (`risky_max_loss_share = 0.5`, config.py:153; `_risky`, :4746).
- Measured on 10 sampled Beta Scans at 40g (B8): 36 of 60 Shopping List rows were Risky, carrying 79% of the list's expected profit. The largest Risky row had an Unsold Loss of 43% of the Stake. The Backtest never takes a Risky row (backtest.py: `options_taken`, "Risky rows are never taken").

Verdict: the post-price rule plus the at-or-above demand filter is a reasonable heuristic, and the caps are thought through. But the list a player actually sees is mostly Risky rows, most of its expected profit is on rows nobody has ever simulated, and the 50%-of-Stake allowance on a long Risky row is not a risk cap in any useful sense. The real-trade record (2.6) says the expected profits are about twice the realized.

### 2.5 Sell/hold for holdings (recommend.py:2627-2900)

Held units post at the same undercut, capped at the dearest Sale Event seen, Wait if a Flip would buy the cheap run first, Sell as many as sell within 7 days under weak priors (3 h, 1 event), Vendor the rest. `has_data` needs only 1 Sale Event, so one disappearance (maybe a cancel) makes an item "sellable". On the last Beta Scan and on Scan 70, no Vendor row was for an item whose Fair Value after the cut was over twice its Vendor Price (B6), so the vendor-the-tail rule did not throw away value there; 30 and 26 rows had "no data". Verdict: acceptable. The low-biased Sell Rate makes Vendor-the-tail more likely than it should be, but I found no case where it mattered.

### 2.6 Real outcomes: the only independent check (B7)

The player's own trades, graded from mail (flips.py), are not built from inferred sales, so they are the one test that is not circular:
- Realized profit over all of Beta: 114g 12s 78c.
- 18 Flips to Sell made and graded: 15 paid off, but realized Profit was 48.7% of expected, the median realized price was 95.5% of Post at, only 36.5% of units bought sold within the Sale Horizon, median 0.87 days to the sales that did happen. The two largest Flips by units: 216 units of 3859 (+12g 61s) and 501 units of 4233 (-8g 67s; sold at 8s 75c against a 14s 49c Post at).
- 1 Flip to Craft, not gradable. Flips to Disenchant: none graded.

Verdict: on the only sample that does not grade the model with its own signal, the Brain's expected profit is roughly twice what happened, and two thirds of units were not sold inside the horizon the Brain priced them for. 18 Flips is too few to tune on, but it is enough to say the expected-profit number is not a calibrated forecast.

### 2.7 The Backtest (backtest.py)

- Fills: a posted unit sells to a later Sale Record at or above its price while the posting is up (`_fill`, backtest.py:241). Sale Records (observation.py:625) are Disappearances in gaps up to 12 h with the same expiry, missed and repost filters, plus Partial Sales, capped at 1.2x Fair Value. That is the same inferred signal Sell Rate is built from, with looser windowing. The Brain decides with inferred sales and is graded by inferred sales. It is out of sample in time, not in method: any cancel the rule calls a sale inflates both the decision and the grade.
- Central grade believes 100% of each record (`grade_share = 1.0`); bounds are 0.65 and 1.2 (config.py:300-301). The 0.65 low bound happens to equal the grader's measured precision, but the calibration is printed, not applied, and with 57% recall the "true" multiplier is unknowable from this sample.
- Buys happen at the Scan's prices with no latency and no competition for the cheap Listing.
- Never takes Risky rows, never simulates Flips to Disenchant, Craft outputs only as posts, and ignores Prediction buys (`_brain_policy` only uses `shopping`).
- Predictions leak into it: see 2.8. With the current predictions.toml, all 20 Prediction Item Keys are removed from Flips at every Beta Scan.

Backtest results on the copy (B9, central / x0.65 / x1.2 grades) are in the Appendix and summarized in 2.7a.

### 2.7a Backtest results (run on the copy, 97 Scans, 40g start, live config)

Added when the runs finished, still before opening pass1 or any project doc.

| run | P&L vendor mark | P&L market mark | x0.65 / x1.2 vendor mark | buys | units sold | won / lost | max drawdown |
|---|---|---|---|---|---|---|---|
| brain, current predictions.toml | -10g 45s | -1g 15s | -12g 72s / -10g 75s | 80 | 459 of 558 | 40 / 40 | 24% |
| auctionator baseline, same run | -49g 06s | -4g 36s | -48g 49s / -50g 59s | 64 | 113 of 373 | 1 / 63 | 115% |
| brain, no Predictions | +90g 70s | +175g 59s | +78g 77s / +108g 07s | 103 | 624 of 863 | 54 / 49 | 20% |

What this says:
1. The written-date bug (2.8) changes the Brain's Backtest from +90.7g to -10.5g. Removing 20 Item Keys from Flips and Crafts (it also blocks the 4305 Bolt of Silk craft, since Silk is a Prediction key) changes which buys the simulated gold reaches, and the whole path changes.
2. The +90.7g is not trading skill. Its five best trades are all Flips to Vendor of one item, 11288 (a wand, Vendor Price 200c, item level 23), summing to 123.2g, 136% of the run's total profit. So the rest of the run lost at least 32.5g. Someone listed up to 2,215 of these wands at 100c or less at once (A9; 8,856 such Listings over 10-02 to 10-08). They sat there for days below Vendor Price, which a real market does not allow; it looks like a Beta oddity, and the Vendor Price itself is only the latest read (vendor_price has one row per item, `seen_at` 10-20).
3. Worse, the Backtest buys those wands again at each Scan: a Flip to Vendor closes at once (`Buy(r.item_key, 0, ...)`, backtest.py:574; `trade.closed = not buy.units`, :236), so the "never an Item Key it still has units posted in" guard (:231) does not apply, and the Scans still show the Listings the simulation already bought. Consecutive Scans show 1,716, 1,714, 1,753 and 1,836 of the same Listings (A9). The simulation's own buys never leave the market it trades. This applies to every Flip to Vendor and, less visibly, to any Flip to Sell whose Listings outlive the posting.
4. Without that artifact, the Brain loses money on Beta in both runs, and the "brain beats Auctionator" number (Dec 2 gap +78.7%) compares two losing strategies, one of which is a straw man that buys the cheapest ask of anything with any spread.
5. The x0.65 / x1.2 bounds move P&L by a few gold either way. The grader share is not the dominant uncertainty; path dependence and data artifacts are.

### 2.8 Predictions (predictions.py, recommend.py:3859-4340)

How a Prediction becomes a buy: every Listing of its Item Keys is tried cheapest first. A unit's Max Loss is its buyout less its exit "if the Prediction is wrong": resale at the Flip post price for units with room within the 7-day Sale Horizon (needing 3 Sale Events at or above the price, as a Flip), stepped down to lower Sale Event prices, else Vendor. A unit is bought only if Max Loss is at most 10% of its buyout (`_hold_buys`, :4122). Buys go lowest Max-Loss share first (:4265) within 15% of gold per Prediction and 40% for all, halved while graded Predictions' pooled return is negative (`_Caps`, :3859). Held units of the Item Keys switch to Hold and count against the cap first (`_hold`, :3892). Upside is never estimated.

Findings:
1. Bug: a Prediction is active before it was written. `Prediction.active_on` (predictions.py:32-35) checks only `happened` and `lapse`, never `written`. `recommend_market` filters with it (recommend.py:819). Both Predictions in predictions.toml say `written = 2026-11-04`, and I confirmed `active_on` returns True for 2026-09-27, 2026-10-20 and today. On Beta Scan 60 (2026-10-04) `recommend_market` produced 7 Prediction buys and moved 27 held units to Hold under "Launch week mats" and "Weeks 2-3 mats" (B5), four weeks before they were written. Lots do respect `written` (lots.py:212), so buy advice and lot accounting disagree. No test covers a date before `written` (test_predictions.py only checks `lapse`/`happened` against `written`). In the Backtest this removes Tin Ore, Silk, Iron Bar and the other 17 Item Keys from Flips at every Scan; in the live Brain today (2026-11-01) it is already Holding and buying them three days early.
2. At Live launch, Predictions will buy nothing for a while. With `beta_sell_rate_weight = 0` (config.py:117, not overridden), there is no room at the post price until Live has 3 Sale Events at or above it, so every exit falls to Vendor and every unit fails the 10% Max Loss test. The "Launch week mats" Prediction lapses 2026-11-11, seven days after it is written. The Predictions tab will show "would lose 9x%" for these lines, which reads as "too risky" when the truth is "no Live sales seen yet" (`no_buy_reason`, :663).
3. By construction, a Prediction buy is a Flip with a negative margin allowance: it only buys units that already resell (or vendor) within 10% of their cost on current evidence. It never weighs the upside the player is betting on, so it cannot express "this is cheap now because nobody has priced the catalyst in". Speculation that requires evidence of present liquidity is not speculation. The brake (halve caps while pooled return < 0) is sound; the cap sizes are reasonable.
4. Ranking by lowest Max Loss share means the least speculative units get the cap first. Fine as risk control, but it is the opposite of what a Prediction is for.

Verdict: the plumbing (caps, brake, grading at a Sale Horizon after the catalyst, frozen grades) is careful. The decision rule makes Predictions close to inert when they matter (launch, no data) and the written-date bug makes them act when they should not.

### 2.9 Beta prior and Beta Sell Rate (beta_prior.py, beta_sell_rate.py)

The Beta Prior is display only (beta_prior.py:3-6): the median Sale Event price over Beta's last 14 days, else the median daily Fair Value. The Beta Sell Rate, the one place a decision reads Beta, is multiplied by `beta_sell_rate_weight`, default 0.0 and not set in config.toml, so `beta_sell_rate_weights` returns `{}` (beta_sell_rate.py:62). The Beta prior does nothing to any decision. Given 2.3 (median 24% drift over Beta, 10-90% range 0.47x to 5x, and prices that are not Live's), showing a Beta price next to Live rows invites anchoring on a number that has no demonstrated relation to Live. Verdict: harmless to decisions, of doubtful value as a display, and the machinery to use it is dead code at weight 0.

### 2.10 Crafting and Disenchanting

- Flip to Craft: greedy, one craft at a time, reagents at the cheapest asks left, output valued at the recipe's minimum yield (conservative), sold through the same post-price and room rule as a Flip (`_outlet`, :3645). Held reagents are costed at their way-out value. Reasonable. One Flip to Craft was made on Beta, not gradable.
- Flip to Disenchant: expected mats from a static table (`data/disenchant.toml`) valued at their marginal way out. The player's 62 Disenchant Results: no group reaches the 20-result threshold, so the table is unchecked (B7). Several cells disagree on tiny samples (e.g. Green weapons 21-25: table 75% for 10998, seen 0 of 4). Flips to Disenchant are excluded from the Backtest. Verdict: expected-value logic is right in form, but a Flip to Disenchant is a bet on an unvalidated table with no backtest and no graded real trade, and it is shown alongside validated-looking rows.

### 2.11 Smaller code-level points

- `DEFAULT_TIME_LEFT_MAX_MINUTES` ends at 24 h for bucket 4 (config.py:33), but 40,101 Listings first seen in bucket 4 lived between 24 h and 48 h (A4), so 48 h postings exist. Effect is small (only matching across gaps over 24 h and the post-duration deposit math), but the config is wrong for this client.
- `post_duration_hours = 24` assumes 24 h postings in the deposit queue; with 48 h postings available, the deposit-loss model is off by up to 2x per posting.

## 3. Checklist grades (pass1 section 6)

Graded from Phase 1 evidence. Where Phase 1 did not cover an item I read the code for it before grading, and say so.

| # | Item | Grade | Evidence |
|---|---|---|---|
| A1 | Censoring / exposure time in sell-rate | PARTIAL | Sell Rate is units over watched hours (sell_rate.py:189), so still-listed items do not bias it the way a mean-lifetime estimate would, but there is no survival model, and blind hours count as exposure (2.2: units/h fall 22x from 30-min to 6-12 h windows). |
| A2 | Sold / cancelled / expired as competing exits | PARTIAL | Expiry is ruled out by time-left bucket (observation.py:107); cancels are not modelled for other players at all, only for own Listings via mail (observation.py:496). |
| A3 | Ground truth precision and recall, published | PASS | `grader_calibration` and `sell_rate_calibration` print precision 65% / 84% and recall 57% / 43% in every Backtest (2.7a). Published but applied to nothing (observation.py:825). |
| A4 | Time-left bucket and gap used against expiry | PASS | `expiry_possible` (observation.py:103); 1.13M in-window Disappearances excluded on it (B1). Bucket-4 max is 24 h while 48 h postings exist (A4), a minor error. |
| A5 | Partial scans detected, unobserved not counted as gone | PASS | Dropped-row items left out of both ends of a window (observation.py:294-303), `_missed` (:438), pool completeness gate (config.py:43). |
| A6 | Exposure uses real timestamps | PARTIAL | Real `requested_at` gaps are used, but detection sensitivity depends on gap length, so irregular gaps do distort the rate (2.2 table). |
| A7 | Relisting handled | PARTIAL | `_pair_reposts` (observation.py:122) needs exact same quantity and an equal or lower price; 35,931 unpaired candidates (24%) sit next to a same-quantity higher-priced new Listing and still count as sales (B2). |
| A8 | Stack-quantity changes (partial buys) | PASS | Partial Sales from min-cost matching (matching.py); 32,671 recorded, in 24% of Sale Events (B2). |
| A9 | Per-unit prices, variants as separate keys | PASS | `unit_buyout` throughout; Item Keys carry suffixes (e.g. `4575:12918`, B5); sibling-suffix demand pooled at weight 0.5 for held units only (recommend.py:2551). |
| A10 | Shared scans de-duplicated, robust to bad upload | PASS (code only) | UNIQUE (market_id, requested_at), `has_pooled_scan`, `roll_back_pooled` on key revoke (history.py:937, 981). The copy has 0 Pooled Scans, so untested on data. |
| A11 | Scan-timing (peak hours) bias corrected or reported | FAIL | Nothing in sell_rate.py; window hours are reported but not by time of day. 2.2 shows the effect is large. |
| B12 | Exit price from what sold, not listing stats | PARTIAL | Post price is next ask minus 1c (recommend.py:4465), justified only by Sale Events at or above it (:4356), capped at the dearest Sale Event for holdings (:2539). Real Flips realized a median 95.5% of Post at (B7): the price held up, the volume at that price did not (36.5% sold within horizon). |
| B13 | Profit net of cut, deposits incl. repeated loss, vendor | PARTIAL | Cut, invoice-learned deposits, deposits lost while queued, Vendor alternative (recommend.py:4061-4068, 2428). `post_duration_hours = 24` while 48 h postings exist (A4); Live cut/deposit rates unverified. |
| B14 | Thin-market outlier guard at the low end | PARTIAL | Fair Value drops units under 50% of the cheap slice's median (fair_value.py:62); cheap-stock cutoff (#132). Nothing flags that a very cheap buy may be a trap beyond the margin and the 1.2x Fair Value cap on sale prices; the 11288 wand wall (2.7a) went straight into the Backtest. |
| B15 | Sweep priced, not each listing alone | PASS | Runs of the cheapest Listings with the post price recomputed after each (recommend.py:4049-4089), bought whole or not at all. |
| B16 | Undercutting assumed; floor / walk-away price | PARTIAL | Posts 1c under, Vendor is the floor (`_resells`, :4636), cheap-stock cutoff; no model of being undercut after posting. |
| B17 | Confidence reduced when last scan is old | FAIL | Checked code: Freshness.lua only says whether Recommendations.lua caught up with the last save; no Scan-age discount in the Brain. |
| B18 | Uncertainty intervals and low-sample warning | PARTIAL | Sale Events per row, Market window hours, "no data" rows, Young Market flag (recommendations.py:216); no intervals on price or rate. |
| B19 | Seller concentration check | FAIL | The data has no seller field and nothing approximates it (e.g. same-price walls like the 11288 one). |
| C20 | Hard caps per item, category, day | PARTIAL | Per option: Unsold Loss 3% of Stake, room 60% (recommend.py:1019). No category or per-day cap. Risky rows may carry Unsold Loss up to 50% of Stake (config.py:153); 36 of 60 sampled rows were Risky (B8). |
| C21 | Fractional Kelly with shrunk edge | N/A | No Kelly or edge-proportional sizing; size comes from room within Days to Sell and gold. |
| C22 | Wait constraint on a distribution, not the mean | FAIL | Days = queue / mean units per hour (recommend.py:4060); real Flips sold 36.5% of units inside the horizon (B7). |
| C23 | Correlated holdings as one position | FAIL | Caps are per option; Shopping List options are alternatives with no joint risk; a Prediction groups Item Keys only for its own cap. |
| C24 | Gold locked in unsold inventory tracked | PASS | Stake = gold + own Listings at cost; room = 60% of Stake less tied-up (recommend.py:1000-1031). |
| C25 | Realistic marks, drawdown or pause rule | PARTIAL | Holdings marked at the post price capped by the dearest Sale Event; the only pause rule is the Prediction brake (recommend.py:3863). No drawdown rule for Flips. |
| C26 | Stale inventory rule | PASS | Each Scan re-splits held units into Sell within the 7-day room or Vendor (recommend.py:2841); the Backtest reposts or vendors on expiry (backtest.py:284). |
| D27 | Max loss as loss-if-wrong, enforced as a hard cap | PASS | Max Loss = buyout less exit without the Prediction, 10% per unit, 15% of gold per Prediction, 40% total (recommend.py:4122-4205, 3859). The exits rest on inferred sales. |
| D28 | Shows what the current price already implies | FAIL | Nothing compares today's price with a pre-event baseline; the Predictions tab shows Held, buys and reasons only (recommendations.py:223). |
| D29 | Timestamp, thesis, exit trigger | PARTIAL | `written`, `reason`, `catalyst`, `lapse`, `happened` (predictions.py:23). No price stop. `written` is not enforced by `active_on` (2.8). |
| D30 | Graded afterward, failures kept | PASS | Graded a Sale Horizon after the end, frozen in grades.toml, pooled return drives the brake (recommend.py:1721). None graded yet. |
| D31 | Crowding (others hold the same bet) | FAIL | Not considered. |
| E32 | Prior weight falls with local data by a stated rule | PARTIAL | `BetaSellRate.pooled` weights Beta hours by a fixed weight so Live takes over as hours build (beta_sell_rate.py:33); not tied to variance, and with weight 0 the rule is moot. |
| E33 | Prior information visibly distinguished | PASS | Beta column separate and display only (beta_prior.py:3); a Prediction buy's room from Beta carried as `beta_room.from_beta` (recommend.py:4247). |
| E34 | Beta-to-Live mapping validated | FAIL | No Live data and no validation code. Beta's own drift (median 1.24x, 10-90% 0.47x to 5x, A5) suggests it would not hold. |
| E35 | Anomalous Beta periods excluded by date | FAIL | No date exclusion anywhere (2.0). It does not bite only because no Scan exists on 10-22; 10-22 character gold still feeds `pooled_gold`. |
| E36 | No confident recommendation from the prior alone | PASS | Weight 0 (config.py:117): no decision rests on Beta. |
| E37 | Structural Beta-vs-Live caveats recorded | FAIL | Only the generic "provisional, Beta never decides" line in output (2.7a). |
| F38 | Backtest free of lookahead | FAIL | Predictions written for 2026-11-04 act on every Beta Scan (2.8); Vendor Prices and item info are latest-only (one `vendor_price` row per item); config thresholds were chosen on the same Beta Backtest (config.toml comments). |
| F39 | Conservative fill model | FAIL | Ambiguous vanishings count as sold at the 1.0 central grade; no delay; the simulation buys the same Listings again on later Scans (2.7a point 3). Cut and deposits are included. |
| F40 | Naive baselines | PARTIAL | An Auctionator-style baseline (backtest.py:478); no vendor-only baseline; cash is only the implicit 0. The baseline buys anything with a spread, so beating it is weak. |
| F41 | Configurations tried recorded, holdout kept | FAIL | No holdout in backtest.py; config.toml records parameters picked "on the Beta Backtest" (gear click cost comment). |
| F42 | Grading independent of the inference | PARTIAL | Flip Grades use mail (flips.py); the Backtest prints own-Listing calibration and 0.65 / 1.2 bounds, but is itself graded by the inferred signal. |
| F43 | Live recommendations logged with fills | PASS | grades.toml freezes what each Scan showed and named; Flip Grades match Purchases to them (flips.py, grades_file.py). |
| F44 | CIs, sample sizes, worst case, recovery | PARTIAL | Worst trade, max drawdown, gold low, grader bounds; no confidence intervals, no time to recover. |
| F45 | Regime split | FAIL | One number per policy per Market. |
| G46 | Patch-day / event-day mode | FAIL | Checked code: no such mode; nothing in brain/src handles patches or a date range to discount. |
| G47 | Data-quality failures surfaced | PASS | dropped / inexact / unreadable rows per Scan, completeness gate for pooled Scans, `PRICE_MAY_BE_OFF` note (recommend.py:3850). |
| G48 | Append-only history with provenance, backed up | PARTIAL | Raw SavedVariables archived, DB rebuildable, Scan source and character recorded; no addon version per Scan. |
| G49 | Reproducible outputs, versioned parameters | PARTIAL | `FAIR_VALUE_VERSION`, frozen grades; recommendations do not record the config they were made under. |
| G50 | Shows why each recommendation was made | PASS | `--why-not` (recommend.py:1122), Sale Events per row, notes, a reason per Item Key on the Predictions tab. |

Counts, all 50: PASS 16, PARTIAL 18, FAIL 15, N/A 1.
The 22 MUST items alone: PASS 6 (A3, A4, A5, B15, D27, E33), PARTIAL 9 (A1, A2, A6, B12, B13, B14, C20, E32, F40), FAIL 6 (C22, D28, F38, F39, F41, G46), N/A 1 (C21).

## 4. Stated reasons tested

Read only after sections 2 and 3 were written: CONTEXT.md, the ADRs, the 2026-10-06 REVIEW.md and the 2026-10-08 REVIEW.md and BRIEF.md. One entry per decision where my Phase 1 verdict disagreed with what the project did.

### 4.1 Sell Rate counts 12 h windows with Market-wide hours (ADR-0035)

Their reason: "That leans Sell Rate low, the safe side, and partly offsets the prime-time lean ADR-0004 accepts." The per-Item-Key alternative was rejected because "capped it lost to the plain 12 h on 4 of 6 lines ... and `window_hours` would stop being one number per Market (`SellRate`, `since_cheap`, Beta pooling, the CLI and Addon lines)." The review that proposed 12 h windows made it conditional: "The 'two denominators' objection goes away if each gap's hours count as exposure only for the buckets that can't have expired over it" (decision-review §8).

Judgment: holds only partly. They measured the dilution themselves ("Rates fall about 3.5x Market-wide"), so this was a knowing choice. "Safe side" is true for sizing a single Flip, but the bias is not uniform: it is worst for items posted for 12 h and depends on when the player happens to scan, so it is not a conservative offset to the prime-time bias, it is a second uncontrolled bias of a different shape. The reviewer's condition was dropped, and the tie-breaker was partly engineering convenience ("one number per Market"). The backtest margin they chose on (84.6g vs 80.0g central, 4 of 6 lines) is inside the noise I measured (4.4), and it rests on the Backtest whose largest winner is the 11288 artifact (4.4).

### 4.2 The measured cancel rate is applied to nothing (ADR-0032, ADR-0035, ADR-0036)

Their reason: ADR-0032: the calibration line "doesn't move the bounds." ADR-0035: "About a third of what both rules call sales are cancels ... That belongs in #171's expected value, not in a pass/fail." ADR-0036 then rejected #171's expected value ("Tried and lost").

Judgment: rationalization by deferral. The correction was parked in a design that was later dropped, and nothing replaced it, so today the known cancel share lives only in a printed line. The 0.65 low grader bound is the one place it shows up, and only in the Backtest, never in Sell Rate, room, Days to Sell or Max Loss.

### 4.3 Risky rows: shown, unsimulated, up to half the Stake (ADR-0037, ADR-0041)

Their reason: ADR-0037: "Risky rows in the Backtest: it would grade a risk the player chooses as if the Brain chose it, and move the numbers ADR-0034 was judged on" and "their record comes from Flip Grades instead". ADR-0041: "At Steel Bar's buy Scan the Stake was 41g 20s and its 216 lose 17g 84s unsold (43%): 25% of the Stake hid it, so the user raised the limit to half."

Judgment: rationalization. The Brain ranks Risky rows inline with the rest and they were 60% of the rows I sampled, with 79% of the list's expected profit (B8). "The player chooses" is equally true of every row on the Shopping List; the Brain is the one putting a number on them. Keeping them out because they would "move the numbers ADR-0034 was judged on" protects a metric, not the player. The Flip Grade record they defer to is 18 graded Flips in total, of which the two big ones are the very anecdotes that set the rule (3859 Steel Bar +12.6g, 4233 Cured Medium Hide -8.7g, B7). Raising `risky_max_loss_share` from 25% to 50% so that one remembered winner would appear is fitting a cap to an anecdote. ADR-0041 does say long Risky rows are "common on Beta (several a Scan)", so the project knows the size of what is going unmeasured.

### 4.4 The Backtest as the judge of every buy-side change (ADR-0032, 0034, 0035, 0036, 0039, 0040, 0041)

Their reason: ADR-0032 rejects grading on Sale Events because "The Brain's strict evidence would grade its own decisions on the evidence they were made from." ADR-0035 then makes the two the same and lists it as a feature: "One rule now decides both Sell Rate's evidence and the Backtest's Sale Records ... so the Backtest grades the Brain on the same kind of sale it learns from." The bars are pre-registered in deltas ("vendor-mark central more than 5g higher", ADR-0036, ADR-0040).

Judgment: partly holds, mostly does not. Pre-registered bars and the grader bounds are good practice and better than what most hobby tools do. But:
- ADR-0035 reverses ADR-0032's own objection without saying so. The circularity the earlier review named (finding 5) is now by design.
- ADR-0034 cites "11288 +28.1g" as one of the Brain's winning buys and uses that to argue the Unsold Loss cap spares the right trades. 11288 is the wand that sat on the AH below Vendor Price in walls of up to 2,215 Listings and that the simulation buys again at each Scan (2.7a). The decision review listed "Bought listings stay in the later Scans" as a known limit and judged it minor ("only matters if they'd also have paid our higher price"); for a Flip to Vendor it is the whole result.
- In my runs, the Brain's P&L moves by 101g (+90.7g to -10.5g) from predictions.toml alone (2.7a). The 5g bars are an order of magnitude inside the path noise of this harness. ADR-0035's 4.6g win, ADR-0034's "3% beat 5% by more than 5g" and ADR-0041's "beats main by 4g 70s" are not distinguishable from noise. The decision review warned "Treat differences under about 5g as noise" and showed a 1.2x run doing worse than 1.0x; the project then set its bars at exactly 5g.
- No holdout. Every parameter since 10-08 was picked on the same 86 to 97 Beta Scans.

### 4.5 Predictions never price the upside, and Beta demand is off at launch (ADR-0006, ADR-0024)

Their reason: ADR-0006: "Any number the Decision Engine put on the upside would be invented." ADR-0024 states the launch problem itself: "at launch no Item Key has Live Sale Events, so the exit falls to the Vendor Price, Max Loss goes over `prediction_max_loss_share`, and nothing is bought in exactly the days a Prediction matters most," then ships the fix off: "Nothing yet says Beta's demand looks like Live's, so the player checks the Beta/Live Fair Value ratios first ... and turns it on."

Judgment: the principle holds; the operational result is acknowledged and left on the player. Refusing to invent an upside is honest and I agree with it. But the consequence, as ADR-0024 says in its own words, is that the feature does nothing when it matters, unless the player flips a switch the ADR also says there is no evidence for. The "Launch week mats" Prediction lapses 2026-11-11; nothing in the Brain tells the player that its lines read "would lose 9x%" because Live has no Sale Events yet, not because the trade is bad. The written-date bug is not a decision; CONTEXT.md is explicit that a Prediction's units start "when it was written", so the code simply disagrees with the domain model.

### 4.6 Time-of-day bias accepted until Lots sell slower than predicted (ADR-0004)

Their reason: "Scaling those hours to 'per day' likely overstates Sell Rate. Accepted for now; revisit if Lots sell consistently slower than predicted."

Judgment: the trigger has fired and nothing was revisited. Flip Grades say 36.5% of units sold within the horizon and realized Profit was 48.7% of expected (B7). The earlier review pointed out in October that no code compares realized with predicted sell speed (its "where docs and code disagree" item 6); that is still true. Now that 12 h windows dilute the rate in the other direction (4.1), the two biases are tangled and neither is measured.

### 4.7 One Sale Event per window, priced at its dearest unit (ADR-0012)

Their reason: "Two unrelated buyers in one window count as one Sale Event. That undercounts demand, which is the safe direction for a Flip."

Judgment: holds for event counts, fails for demand at a price, as the 2026-10-06 review showed (finding 7). `SellRate.at_or_above` (sell_rate.py:49) still keeps every unit of an event whose dearest unit clears the price. With 12 h windows (ADR-0035), events fold more buyers together than when the ADR was written. Only the long-Risky test clips it (`units_sold_at_or_above`, #198).

## 5. Earlier review findings: fixed, partly, or not fixed

Checked against today's code, not against what the docs say was done.

### 2026-10-06 independent review

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | Own and pooled Purchases count as demand | Partly | Own Purchases come out (`_own_purchases`, `_units_left`, observation.py:537-589, #152). Guildmates' Purchases are not uploaded or subtracted. 0 Pooled Scans so far, so it has not bitten. |
| 2 | Incomplete own Scans create phantom sales | Fixed | Dropped-row items left out of both ends of a window, `_missed` resurrection check (observation.py:294-318, 438). |
| 3 | One lowball ask reprices every held unit | Partly | Held units Wait above a run a Flip would buy (`wait_at`, recommend.py:2590, ADR-0038). No robust floor (multi-scan price or Sale Event median). |
| 4 | 100% capture, prime time scaled to 24 h | Not fixed | No capture share, no time-of-day profile (sell_rate.py). Now mixed with the 12 h dilution (4.1). |
| 5 | Grader uses the Brain's own model, no error bars | Partly | Replay retired for a Backtest with own-Listing calibration and 0.65 / 1.2 bounds (ADR-0032). No bootstrap interval, no queue position, bought Listings still stay in later Scans (2.7a), no holdout, and ADR-0035 made the grader's signal the Sell Rate's again. |
| 6 | One malformed pooled Scan freezes a Market | Fixed | Body realm, faction and requestedAt checked against the index entry (pool_sync.py:203-217). |
| 7 | Sale Event priced at its dearest unit inflates demand at higher prices | Not fixed | `at_or_above` unchanged (sell_rate.py:49-66); only the long-Risky path clips (#198). |
| 8 | Own cancellations unused; coincidences dropped | Partly | Own Cancelled / Expired Outcomes drop own Probable Sales (#153); precision is published. Not applied to other players; coincidences still computed and read by nothing that decides. |
| 9 | Holdings room uses demand at any price | Not fixed | `holdings_room` uses `held_rate`, whose own part is the whole Sell Rate; only siblings are cut at the post price (recommend.py:2551-2575, 2640). |
| 10 | Thresholds tuned in-sample on a distorted Beta | Not fixed, worse | Every ADR since (0034 to 0041) tunes on the same Beta copy; no holdout. |
| 11 | Partial Sales treated as certain | Partly | Sale Records price-check them (observation.py:675-682); Sell Rate still adds them with no price or Repost test (observation.py:404-421). |
| 12 | Buy Under highlight ignores units and staleness | Not fixed | BuyUnderMatch.lua matches any Listing at or under the price, with no unit count or age. |
| 13 | 2-hour postings invisible | Not fixed, worse | With 12 h windows, 12 h postings are invisible over any gap of 2 h or more too (2.2). |
| 14 | Small look-ahead leaks | Not fixed | `non_stacking` and deposits read all Listings and mail (recommend.py:2164; lots.py:359); Repost pairing uses a new Listing's final quantity (observation.py:333-337 docstring); Vendor Price latest only. Plus the new, larger leak: Predictions before their written date (2.8). |

### 2026-10-08 decision review (its section 7 plan and section 8)

| Recommendation | Status | Evidence |
|---|---|---|
| 1. Build the backtest yardstick, calibrated on own Listings | Fixed | backtest.py, ADR-0032; calibration line printed. Its own listed limit (bought Listings stay) not fixed, and it matters more than the review thought (2.7a). |
| 2. Cheap-stock cutoff: power test, no zeroing after 24 h unwatched | Partly | Unwatched stretch keeps its demand (`since_cheap`, sell_rate.py:100-121, ADR-0033). The discount version was built and rejected (ADR-0031); no power test. |
| 3. Feed Sell Rate 12 h gaps and Partial Sales from any gap, with per-gap exposure | Partly | 12 h windows shipped (ADR-0035) without the per-gap exposure the review made a condition; Partial Sales from longer gaps rejected. |
| 4. Risk caps: 10% per item, 5% worst case, 60% tied up, brake | Partly | 3% Unsold Loss and 60% room shipped (ADR-0034); no per-item cost cap, no brake for Flips; Risky rows (ADR-0037, 0041) reopen the loss to 50% of the Stake. |
| 5. Replace the gates with expected value | Not adopted | Tried and lost on the Backtest (ADR-0036). Given 4.4, that verdict is as weak as the wins it was compared with. |
| 6. Make the effort charge a visible setting | Fixed | `non_stacking_effort_copper` in config; config.toml records a 2s trial and a return to 5s. |
| 7. Grade Buy Unders before showing them, add a price-moved test | Partly | `buyunder` / `buyunder_unchecked` Backtest policies and `take_under`'s check exist; the Sell way is off by default (`buy_under_sell_way`); highlights still unbounded (finding 12 above). |
| 8. Refit on Live with a held-out week, no mid-week changes | Not yet due | No holdout mechanism exists in code to support it. |
| 13114 shown as pending in `brain flips` | Fixed | Both 13114 Flips grade as sold (B7). |

## 6. Revised after reading docs

My Phase 1 verdicts stand. Three notes where the docs change emphasis, not direction:

1. The Auctionator baseline. In 2.7a I called it a straw man. ADR-0039 shows it was given a fifth-of-Stake and 20-unit cap so it would not lose to its own carelessness, which is fairer than I implied. My point that it is the only baseline, and that beating a losing baseline while losing money is not a pass, stands.
2. The 12 h windows. I wrote as if the dilution was unnoticed. ADR-0035 measured it (3.5x) and chose it. So this is a known trade, not an oversight; my objection is to the reasoning (4.1), not to awareness.
3. Predictions at launch. ADR-0024 shows the project knows Predictions buy nothing at launch with the Beta weight at 0. I had read this as an unintended consequence; it is a deliberate default left to the player. The written-date behaviour, by contrast, is plainly unintended (CONTEXT.md), so it stays a bug.

## 7. What I couldn't determine, and what data would settle it

- The cancel rate of other players. Own Listings give 65% / 84% precision on n = 43 / 25, and the player's own cancel habits may not be typical. Settles with more own posts and mail, or with Pooled members' mail (their own Listings are ground truth for them).
- How much of the Sell Rate gap between short and long windows is demand and how much is blindness. My split uses bucket-4 Disappearances as the "always visible" signal, which still includes cancels. Settles with Scans spread around the clock (Pooled Scans at off-hours), or a per-bucket exposure model.
- Whether the 11288 wands were really buyable at 100c and vendorable at 200c. The Vendor Price row is from 10-20 only. Settles with one in-game check on Live, or Vendor Price history.
- The Backtest without the re-buy artifact. I did not patch the code (not allowed). Settles by removing a simulated buy's Listings from later Scans (or skipping any Listing already bought by its id) and rerunning; I expect the Brain to be negative on Beta.
- Whether Risky rows make money. Settles only with graded Risky Flips; grades.toml has none flagged yet.
- How long a bucket-4 posting really lasts on the Live client (config says 24 h; 40,101 Beta Listings lived 24 to 48 h). Settles with one Live posting at each duration.
- Any Live behaviour at all. There is no Live Scan in the history.
- I ran only the `brain` and `auctionator` policies (each run took about 90 minutes). `relaxed`, `uncapped` and the Buy Under policies are untested by me.

## 8. Appendix: queries and outputs

All against the copy at `C:\Users\zachm\AppData\Local\Temp\claude\C--vibing-azerothquant\646bd6a6-2c4a-4328-9f1d-da4bf2e6109c\scratchpad\pass2\history.sqlite`, opened `mode=ro`. "A" items are plain SQL; "B" items call the Brain's own functions on a read-only connection with the live config (`load_config(brain/config.toml)`, `grades_path=None`). Scripts are in the scratchpad `q\` folder next to it.

**A1. Markets and Scan cadence**
```sql
select * from market;
select id, requested_at, character, source, dropped_rows, readable_rows from scan order by requested_at;
```
1 market: `1 | Classic Beta PvP | Alliance | beta`. 97 Scans, 2026-09-26 16:19 to 2026-10-20 23:52, all own, character Kash-Patel. 96 gaps: median 1.57 h, mean 6.08 h; at most 0.5 h: 35; 1 h: 45; 2 h: 57; 6 h: 69; 12 h: 75; 24 h: 93; 48 h: 96.

**A2. Mail and Character Reads by day**
```sql
select kind, count(*), sum(count) from auction_mail group by kind;
select date(read_at,'unixepoch') d, count(*), max(money) from character_read group by d;
```
cancelled 60 (262 units), expired 58 (97), sold 159 (748), won 99 (988). Max character gold: 16.9g on 10-14 to 10-20, 99.1g on 10-22, 100.9g on 10-23. No mail after 10-20.

**A3. Longest time seen in each time-left bucket (no drop recorded)**
```sql
select l.time_left, count(*), max(ls.requested_at - fs.requested_at)/3600.0
from listing l join scan fs on fs.id=l.first_seen_scan_id join scan ls on ls.id=l.last_seen_scan_id
where not exists (select 1 from time_left_drop d where d.listing_id=l.id) group by l.time_left;
```
bucket 1: 76,385, max 3.09 h; 2: 253,211, 8.03 h; 3: 1,031,950, 31.5 h; 4: 198,907, 77.9 h. Longest Listing life 112.4 h; 51,484 over 24 h; 1,875 over 48 h.

**A4. Lifetimes longer than the first-seen bucket allows**
```sql
with first_bucket as (
  select l.id, coalesce((select d.time_left_before from time_left_drop d join scan s on s.id=d.scan_id
     where d.listing_id=l.id order by s.requested_at limit 1), l.time_left) b,
     (ls.requested_at - fs.requested_at)/3600.0 life_h
  from listing l join scan fs on fs.id=l.first_seen_scan_id join scan ls on ls.id=l.last_seen_scan_id)
select b, count(*),
  sum(life_h > case b when 1 then 0.5 when 2 then 2 when 3 then 12 else 24 end),
  sum(life_h > case b when 1 then 0.5 when 2 then 2 when 3 then 12 else 48 end)
from first_bucket group by b;
```
| first bucket | Listings | over config max | over max with bucket 4 = 48 h |
|---|---|---|---|
| 1 | 76,385 | 1,203 | 1,203 |
| 2 | 303,759 | 11,151 | 11,151 |
| 3 | 1,339,775 | 27,004 | 27,004 |
| 4 | 452,616 | 41,976 | 1,875 |

**A5. Fair Value stability** (from `scan_fair_values`, 90 Scans, `v1 slice 0.15 outlier 0.5`)
18,734 Item Keys; 8,678 with 20+ Scans. Median coefficient of variation 0.679 (deciles 0.264, 0.387, 0.486, 0.584, 0.679, 0.784, 0.907, 1.082, 1.384). Share of consecutive-Scan moves over 20%: 19.3%. 3,050 Item Keys in both the first and last week: median last/first 1.24, deciles 0.47, 0.67, 0.88, 1.00, 1.24, 1.61, 2.20, 3.00, 5.00.

**A6. Signals visible in any gap up to 12 h, per hour of gap**
```sql
-- per (last_seen_scan_id, time_left): count(*), sum(quantity) of other players' Listings gone,
-- grouped by the length of the gap to the next Scan; partial_sale grouped the same way
select last_seen_scan_id, time_left, count(*), sum(quantity) from listing where not own group by 1, 2;
select scan_id, count(*), sum(units_sold) from partial_sale group by scan_id;
```
| gap | gap hours | all others gone / h | bucket 4 gone / h | bucket 4 units / h | Partial Sales / h | Partial units / h |
|---|---|---|---|---|---|---|
| 0.5 h or less | 11.2 | 14,537 | 956 | 11,645 | 758 | 19,323 |
| 0.5 to 2 h | 27.3 | 10,274 | 586 | 6,364 | 394 | 11,136 |
| 2 to 6 h | 38.6 | 6,930 | 367 | 3,886 | 142 | 3,656 |
| 6 to 12 h | 49.7 | 4,725 | 319 | 2,260 | 89 | 2,917 |
| over 12 h | 456.7 | 2,636 | 300 | 2,664 | 8 | 443 |

**A7. 10-22 footprint**
```sql
select max(requested_at) from scan;                                         -- 1792540334 (2026-10-20 23:52)
select date(cr.read_at,'unixepoch') d, count(distinct ci.item_key), sum(ci.count)
from character_read cr join character_item ci on ci.character_read_id=cr.id
where d in ('2026-10-20','2026-10-22','2026-10-23') group by d;            -- 77/3,766; 94/4,173; 42/1,731
select count(*) from vendor_price where date(seen_at,'unixepoch')>='2026-10-21';  -- 106
select count(*) from item_info where date(seen_at,'unixepoch')>='2026-10-21';     -- 26
```

**A8 / A9. Item 11288**
```sql
select * from vendor_price where item_id=11288;   -- beta | 11288 | 200 | 1792540334
select * from item_info where item_id=11288;      -- ilvl 23, quality 2, class 2, INVTYPE_RANGEDRIGHT
select count(distinct id), sum(quantity) from listing where item_key like '11288%' and unit_buyout<200;  -- 8,856 / 8,856
-- Listings of 11288 under 200c up in each Scan:
select s.requested_at, count(*), sum(l.quantity), sum(l.unit_buyout*l.quantity) from scan s
join listing l on l.market_id=1 and l.item_key like '11288%' and l.unit_buyout<200 and not l.own
join scan fs on fs.id=l.first_seen_scan_id join scan ls on ls.id=l.last_seen_scan_id
where fs.requested_at<=s.requested_at and ls.requested_at>=s.requested_at group by s.id;
```
10-02 16:21: 544; 10-02 19:49: 1,157; 10-03 19:46: 1,716; 20:20: 1,714; 22:13: 1,753; 22:29: 1,836; 10-04 17:46: 1,693; ... 10-06 21:51: 2,215; ... 10-08 01:33: 1,698; 10-08 22:02: 6. Nearly all at 100c, 1 unit each.

**B1. Disappearances and calibration** (`observation.disappearances`, `sell_rate_evidence` over all Scans, `grader_calibration`, `sell_rate_calibration`, `own_outcomes`, `sale_records`)
- 2,172,535 Listings (231 own); 2,149,992 Disappearances.
- In window, expiry possible: bucket 1 206,799; 2 275,999; 3 237,154. In window, no expiry: 2 23,522; 3 145,754; 4 56,789. Long gap: 1,204,975 (all buckets).
- Candidates 226,065 (67 own, 1,853,794 units).
- Evidence: 126.8 window hours, 75 windows; 55,143 Sale Events, 2,019,321 units; 31,364 Reposts; 33,433 coincidences.
- Item Keys with 1+ Sale Event: 11,039; 3+: 5,313; 10+: 1,235; 30+: 278; listed at all: 19,073.
- Grader calibration: matched 43, sold 28, Sold mails 49. Sell Rate calibration: matched 25, sold 21, Sold mails 49. Own Outcomes matched: 49 sold, 45 expired, 28 cancelled.
- Sale Records: 169,709 (2,180,196 units). Partial Sales: 32,671 (1,009,253 units, 6 own).

**B2. Repost pairing, instrumented** (wrapping `observation._pair_reposts` over every window)
Candidates after dropped-row and `_missed` filters 182,731 (1,561,286 units); Reposts 31,364; unpaired 151,367 (1,431,342 units; 94,494 of quantity 1); coincidences before the price check 35,931; Partial Sale rows in windows 27,071 (742,172 units); Sale Events 55,143; Sale Events that include a Partial Sale 13,047.

**B3. Thinness** (from B1's Sale Events)
Sale Events per day per Item Key, deciles: 0.19, 0.19, 0.19, 0.38, 0.38, 0.57, 0.76, 1.14, 1.89. 2,644 Item Keys at 1+ a day, 313 at 5+. Top 100 Item Keys: 10.8% of Sale Events, 82.8% of units. Units per Sale Event deciles: 1, 1, 1, 1, 1, 2, 4, 10, 36.

**B4. Sale Events by window length** (table in 2.2)

**B5. One Scan, live config, current predictions.toml** (`recommend_market` at 1791056768 and the next Scan, gold 40g)
At Scan 60: 11 Shopping List rows, 8 Risky; 7 Prediction buys; "Launch week mats" Held 17, tied up 59,980c of a 60,000c cap; "Weeks 2-3 mats" Held 10. Both Predictions are `written = 2026-11-04`. `Prediction.active_on` is True on 2026-09-27, 10-20, 11-01 and 11-04 for both.

**B6. Holdings Vendor rows worth more on the AH** (latest Scan and Scan 70): none with Fair Value after the cut over twice the Vendor Price; 30 and 26 "no data" rows.

**B7. Real outcomes** (`cli.run_profit`, `run_disenchants`, `run_flips` on a second copy with a copy of grades.toml)
Realized profit 114g 12s 78c; 66 Purchases (39g 09s 84c) For Use. 62 Disenchant Results, no group at 20. Graded Flips: 18, 15 paid off, realized / expected Profit 48.7%, median price / Post at 95.5%, sold within horizon 36.5%, median days to sell 0.87. Largest: 3859 (216 units, +12g 61s 08c), 4233 (501 units, -8g 67s 27c). 1 Flip to Craft, not gradable.

**B8. Risky rows** (`recommend_market` at every 8th Scan from Scan 21, 40g, no Predictions)
60 rows, 36 Risky; expected profit 102.3g of which 80.3g on Risky rows; largest Risky Unsold Loss / Stake per Scan: 0.27, 0.02, 0.38, 0, 0.22, 0.43, 0.23, 0.17, 0.28, 0. Loss cap 1.2g, room 24g at a 40g Stake.

**B9. Backtests** (`backtest.backtest`, 97 Scans, 40g, live config; table in 2.7a)
- With predictions.toml: brain -10g 45s 47c vendor / -1g 14s 52c market; 80 buys; 459 of 558 units sold; 40 won / 40 lost; worst -3g 25s; drawdown 24%. auctionator -49g 05s 98c / -4g 36s 35c; 64 buys; 113 of 373 sold; 1 won / 63 lost; drawdown 115%. Gap +78.7% at x1.
- Without Predictions: brain +90g 69s 64c / +175g 59s 40c; x0.65 / x1.2 vendor 78g 76s 68c / 108g 07s 07c; 103 buys; 624 of 863 sold; 54 / 49; worst -15g 09s 78c (4305, a Bolt of Silk craft); drawdown 20%. Five best trades, all 11288 Flips to Vendor: +15.27g, +20.47g, +22.83g, +28.09g, +36.56g = 123.2g (136% of the total).
- At Scan 1791056768 with a fixed 40g, neither run has an 11288 row, so the artifact shows up only on gold paths that reach it.
