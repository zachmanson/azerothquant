# Pass 1: outside market research for a WoW Auction House trading tool

Written 2026-11-01 by an outside researcher who was told only the project description (a per-flavor AH scanner addon, a local Python "Brain" that infers sales from listing disappearances, buy lists, sell/hold calls, craft/DE arbitrage, user "Predictions", a Beta prior, and self-backtesting). I did not read the repository.

Evidence labels used below:
- **[doc]** read from an official or primary source this session.
- **[paper]** a published academic or practitioner paper; I confirmed it exists and its headline claim via search, but did not read the full text.
- **[secondary]** blog, forum, or summary page.
- **[background]** standard textbook knowledge stated from memory without a fetched citation. Verify before relying on specifics.
- **[folklore]** widely repeated among players, no measurement found.

Search tooling was weak. Several things I wanted (Undermine/Saddlebag sale-estimation methods, TSM's sale-rate computation, the market-impact square-root law) came back empty. Section 7 lists them.

---

## 1. Summary

1. **Nobody gets true sales from the live AH for free.** The Blizzard AH API gives snapshots of current listings (roughly hourly). A forum answer says snapshots contain only auctions present at dump time, and that diffing them cannot tell sales from relisting or cancels [secondary]. TSM's own sale-side numbers (DBRegionSaleAvg) come from players' TSM Accounting data uploaded through the desktop app [doc], not from snapshot diffs. The project's sale inference is unusual and has no established benchmark.
2. **A disappeared listing is an ambiguous event, not a sale.** Still-listed items are right-censored time-to-sell observations. Dropping them, or counting only the ones that vanished, biases sell time downward (too optimistic). Survival analysis (Kaplan-Meier, with competing risks for sold/cancelled/expired) is the standard fix [background, tutorials secondary].
3. **TSM's DBMarket is a listing price, not a sale price.** TSM's docs say it "shows what items are listed for, not what they sell for." It is a 14-day weighted average, with an outlier filter that only uses the lowest 30% of listings [doc]. Using a listing-based price as an exit price overstates what you will receive.
4. **Adverse selection is the main structural risk of a "cheap listing" buy list.** A listing far below market is cheap because it is a mistake, a bait item, a different stack or variant, or something the market knows is about to drop. Glosten-Milgrom is the textbook framing [paper]. Expect a fraction of the "best" picks to be traps.
5. **Min-buyout "market price" is fragile in thin markets.** One listing sets it. A price tracker (Donut.build) openly admits one cheap listing drags its tracked value down [doc].
6. **Your buying moves the price in thin markets.** If the tool recommends sweeping the bottom of a book, the post-buy price is not the pre-buy price. Kyle's lambda is the formal idea. Practical form: price the whole sweep, and assume the relist price faces your competitors' undercut [background].
7. **Size with a fraction of Kelly at most, and treat your edge estimate as an upper bound.** Overbetting is penalized more than underbetting, and estimation error pushes you toward overbetting [paper/secondary: Thorp, MacLean-Thorp-Ziemba]. With finite gold and slow, lumpy sales, hard per-item and per-category caps matter more than a clever formula.
8. **Backtests on your own sales inference are circular.** If the same inferred-sale signal creates the labels, the fills, and the grades, the test only shows the code is self-consistent. Look for ground truth (the player's own actual sales and mail receipts).
9. **Grade against a dumb baseline.** "Beats a random cheap listing" is weak. Compare against buy-cheapest-relist-at-median, vendor-only, and cash [background].
10. **Multiple testing bites hobby projects too.** Tuning thresholds on a few weeks of data and keeping the best is the selection bias that the Deflated Sharpe Ratio paper targets [paper].
11. **Regime change is the default on a fresh realm.** Price levels in the first weeks are driven by gold scarcity, leveling waves, and first clears. Early windows will not describe later weeks [folklore].
12. **A Beta prior is a shrinkage target and a structural-mismatch risk.** Shrinkage toward a related market helps when the target is plausible (Efron-Morris) [paper]. It hurts when the target is structurally different. The prior's weight must fall as local data arrives, and the tool should show when it leans on the prior.
13. **Event speculation is only "capped" if the cap is real.** Size the cap as loss-if-wrong. The usual failure is that the event was already priced in [background].
14. **Game economies have faucets, sinks, bots, and patch risk that real markets lack.** One hotfix (drop rate, vendor price, recipe) can zero an inventory. Bot supply can swamp organic supply [secondary].
15. **Small populations mean small samples.** A thin realm has noisy, manipulable prices; one seller can be most of a market. Pooling guildmate scans improves coverage, not independence.

---

## 2. WoW practice

### 2.1 TradeSkillMaster (TSM) price sources

From the TSM support pages [doc: https://support.tradeskillmaster.com/which-price-sources-can-i-use-and-what-do-they-mean, fetched this session]:

| Source | Definition as published |
|---|---|
| DBMarket | Weighted 14-day average of auctions listed on your realm, weighted toward the most recent 3 days. "Shows what items are listed for, not what they sell for." |
| DBMinBuyout | Lowest-priced auction as of the last pricing update, "may be 30+ minutes old." |
| DBHistorical | 60-day average of DBMarket on your realm. |
| DBRegionMarketAvg | Average of DBMarket across all realms in the region. |
| DBRegionHistorical | 60-day average of DBRegionMarketAvg. |
| DBRegionSaleAvg | Average sale and purchase price in the region, from TSM Accounting data sent through the desktop app. |
| DBRegionSaleRate / DBRegionSoldPerDay | My fetch did not return definitions. Search summaries say: sale rate is a decimal (0.4 = sells about 40% of the time) averaged across the region's auction houses; sold per day is average units sold per AH per day in the region [secondary summary of the TSM pages]. A TSM developer is reported to say region rates can't be broken down by realm because there isn't enough data [secondary]. |

How DBMarket's daily value is built (AuctionDB doc) [doc: https://support.tradeskillmaster.com/tsm-addon-documentation/auctiondb-market-value]:
- Only the lowest 30% of auctions are considered.
- After 15% of auctions have been passed, a jump of 20% or more from one auction to the next causes that auction and all above it to be discarded. The rest are averaged.
- Individual auctions are not stored, only one value per day. The prior 14 days plus today are blended with a half-life a little over two days.

What this tells you:
- TSM's realm price is a **listing-side, outlier-trimmed, recency-weighted** statistic. It is stable by design, so it lags regime shifts and says nothing about whether the item sells.
- TSM's only sale-side data comes from **actual sales recorded by many players' own clients**. The project has no equivalent, so its inferred sales are its only sale-side signal. That is novel and unvalidated at once.
- TSM says realm-level sale rates are too sparse to publish. The project attempts realm-level sell rates on one tiny fresh realm. Expect very wide uncertainty and demand the tool show it.
- TSM trims the high end to hedge bait listings. The same logic applies at the low end of a buy list: one absurdly cheap listing is more likely a mistake or trap than a bargain.

### 2.2 Auctionator

A dependent addon describes Auctionator's auction price as the lowest price seen at the last scan, and a TSM add-on maps it to DBMinBuyout [secondary: https://www.curseforge.com/wow/addons/price-answer, https://www.curseforge.com/wow/addons/auctionator-compainion]. I found no primary documentation of any sell-through model. Treat it as a cheapest-listing tool plus posting UX [secondary; incomplete].

### 2.3 Undermine Exchange / Undermine Journal / Oribos Exchange

- Undermine Exchange's API docs say its data comes from Blizzard's AH snapshots [doc: https://undermine.exchange/api.html]. Its collection code is reportedly open source; I did not read it, so I cannot say whether or how it estimates sales.
- A Blizzard forum Q&A says the dump holds only auctions present at that moment, typically every 60 minutes [secondary: https://us.forums.blizzard.com/en/blizzard/t/how-to-find-items-sold-on-ah-and-turnover/11022]. Replies in these threads note that diffing snapshots cannot account for delist-and-relist and that a listing can come and go inside one interval [secondary, via search summary].
- A third-party addon describes this data as listing-price history and medians, not confirmed sales [secondary: https://www.curseforge.com/wow/addons/dealscryer].
- Takeaway: mainstream tools treat snapshots as price levels and depth. I found **no published validation** of sale inference from snapshot diffs.

### 2.4 Saddlebag Exchange

I could not find its methodology; searches returned unrelated pages. I make no claim [gap].

### 2.5 Practitioner pitfalls in a price tracker

Donut.build samples up to 10 pages and about 10 usable listings per item, normalizes to per-item price (because stack totals favor small stacks), and stores the cheapest valid per-item price. It admits "one unusually cheap listing can pull the tracked value downward" and that sampling is capped [doc: https://www.donut.build/how-we-track-auction-prices]. Pitfalls: stack normalization, cheap outliers, truncated sampling, mismatched or broken listings (variants or bonus IDs under one item key).

### 2.6 How goldmakers behave (mostly folklore)

I found no measured studies. This is community consensus from general guides and background knowledge; evidence quality is **folklore** unless stated.
- Build your own price history on a fresh realm; do not import another server's prices [secondary: https://www.cgmagonline.com/guides/gold-farming-earning-wow-classic-guide, https://earlygame.com/gaming/wow-sod-how-to-make-gold].
- Diversify so one stuck inventory does not freeze capital [secondary, same sources].
- Filter flips by minimum sale rate and margin after AH cut and deposit [folklore]. A Reddit formula using sale rate and vendor value was seen, but it is not documentation.
- AH cut, deposit on expiry/cancel, and listing duration are first-order costs. Deposit is lost when an item expires unsold, so low-sale-rate items pay deposit repeatedly [background; verify rates for this realm type].
- Undercut wars: post 1 copper under the cheapest. In thin markets this erodes margin to the vendor floor. Goldmakers respond with a per-item floor price and refusal to post below it [folklore].
- Market resets (buy the book, relist higher) work on stable realms. They fail when someone has stock behind the wall, when demand is elastic, or when supply refills faster than demand [folklore].
- Patch speculation: buy known-upcoming-demand materials before the patch and sell into week one. The recurring failure is that everyone does the same trade and the price is already up at launch [folklore].
- Common ways people lose gold [folklore]: buying a mispriced listing that was a different item or stack; ignoring cut and deposit; posting at a price that never clears; holding through a patch that changes supply; buying too much of a thin market and relisting into your own undercut; trusting a stale scan.

---

## 3. Real-world analogues

### 3.1 Market making and inventory risk

**Core idea.** A market maker posts bid and ask prices and earns the spread, but ends up holding inventory that can move against them. Avellaneda-Stoikov (2008) formalizes this: shift quotes away from mid-price in proportion to inventory and volatility, so a dealer who is too long quotes lower to attract buyers of their inventory [paper: https://math.nyu.edu/~avellane/HighFrequencyTrading.pdf; record https://econpapers.repec.org/RePEc:taf:quantf:v:8:y:2008:i:3:p:217-224]. Glosten-Milgrom (1985) shows a positive spread arises from adverse selection alone: some counterparties know more than you, and each trade is a signal [paper: https://www.edegan.com/pdfs/Glosten%20Milgrom%20%281985%29%20-%20Bid%20Ask%20and%20Transaction%20Prices%20in%20a%20Specialist%20Market%20with%20Heterogeneously%20Informed%20Trades.pdf]. Empirical estimates of the adverse-selection share of the spread vary a lot by estimator (roughly 21% to 50% in one comparison) [secondary: https://eu.vlex.com/vid/determinants-of-the-components-855636437].

**Why it matters here.**
- The AH trader is a part-time market maker with slow, lumpy fills and costly inventory (deposits, cut, locked capital). "Hold" and "sell" calls are inventory decisions. Holding cost should rise with how concentrated the portfolio is in one item.
- A listing far under the book is the adverse-selection case: you may be the one who is wrong. The tool should discount apparent edge for "too good" gaps, not rank them first.
- Avellaneda-Stoikov assumes continuous liquid trading and Brownian mid-price. AH markets violate both. Use the qualitative lesson (skew price with inventory), not the formulas.

### 3.2 Pricing illiquid or rarely traded goods

**Core idea.** When an item trades rarely, last trade is a poor price. Practitioners use repeat-sales indices (Case-Shiller style), hedonic regression, and comparables. All suffer **selection bias**: unsold lots are dropped, and owners re-offer winners and hold losers [secondary: https://www.masterworks.com/academy/posts/how-reliable-are-repeat-sales-indices-for-art, a vendor page; treat with caution]. Evidence on how large the bias is is mixed; one auction study found none, others found downward bias in estimates [secondary, unverified].

**Why it matters.** A thin item's price built from the few sales is conditional on selling. The right question is "what price clears with probability p within D days," not "what was the average sale price." Items that never sell are invisible in sale-price statistics, and the tool must not conflate the two.

### 3.3 Your own trades moving the price

**Core idea.** Kyle (1985): price moves in proportion (lambda) to signed order flow; illiquid markets have high lambda [paper: https://edegan.com/pdfs/Kyle%20%281985%29%20-%20Continuous%20Auctions%20and%20Insider%20Trader.pdf; explainer https://screamer.readthedocs.io/en/stable/functions_micro/EwKyleLambda.html]. One source cautions that lambda is an equilibrium coefficient in the model, not automatically the causal effect of one trade [secondary: https://www.quantt.co.uk/resources/kyle-model-and-kyles-lambda]. I did not retrieve the empirical square-root impact law (impact scaling with the square root of order size over volume); it is commonly cited but unverified here [background; gap].

**Why it matters.** On a thin realm one buyer can clear several rungs. Two effects: (1) **buying** walks the book up, so average fill is worse than the cheapest listing; (2) **selling** the same quantity faces the undercut dynamic and your own supply depresses price. A buy list that prices each listing independently overstates profit as size grows, and a sell-rate estimate that treats you as a price taker overstates how fast you exit.

### 3.4 Position sizing

**Core idea.** Kelly maximizes long-run log growth by betting a fraction of bankroll proportional to edge over variance. It is aggressive and very sensitive to estimation error. Thorp warns that overestimating the edge overstates the Kelly fraction, and that betting above Kelly gives more risk and less return [secondary: Scribd copy of Thorp's paper, https://www.scribd.com/document/326490154/kuli-doc]. MacLean, Thorp and Ziemba recommend fractional Kelly to hedge estimation error [paper, via search summary]. A 2025 arXiv paper restates that estimation error leads to over-betting and discusses shrinking mean estimates [secondary: https://www.arxiv.org/pdf/2503.17927].

**Why it matters.**
- AH payoffs are not independent coin flips: outcomes are delayed, correlated (same patch, same category), and gold is locked while waiting. Kelly's assumptions fail.
- Edge estimates here come from noisy inferred data. Fractional Kelly (commonly a quarter to a half) plus hard caps (per item, per category, per day) and a drawdown pause is the sane engineering choice [background].
- Sizing must account for **time to sell**. The "days willing to wait" parameter is the right lever, but check that it constrains a distribution (for example a high percentile of time to sell), not a mean.

### 3.5 Event-driven speculation

**Core idea.** Traders of scheduled events (earnings, approvals, index changes) separate the event's information from what the price already embeds. The edge is mispriced expectations, not the event itself. Downside is capped with defined-risk structures or position limits [background; no primary source fetched].

**Why it matters.** A user-entered Prediction is a bet the user writes on their own belief. Key questions: what is already in the price? how many others hold the same bet? what is the maximum loss, sized as loss-if-wrong? what is the exit trigger (time stop, price stop)? Predictions should be timestamped so calibration can be graded honestly. Evidence that WoW patch speculation is profitable is **folklore only**.

### 3.6 Inferring transactions from snapshots; time to sell

**Core idea.** Survival analysis handles "time until event" when some units haven't had the event yet. Those are **right-censored**: you know they lasted at least until the last observation. Ignoring them, or reading "still listed" as "never sells," biases the estimate. Kaplan-Meier uses at-risk counts so censored items count as at risk until they leave [secondary: https://survive-python.readthedocs.io/theory.html, https://www.analyticsvidhya.com/blog/2020/12/a-brief-introduction-to-survival-analysis-and-kaplan-meier-estimator/]. The key assumption is **non-informative censoring**; if censoring depends on the outcome, estimates bias [secondary, same results]. Cancels are informative (sellers cancel because an item isn't selling or the price moved), so sold, cancelled, and expired should be treated as competing exits, not as random censoring.

Snapshot pitfalls (some from the Blizzard forum answer above; the rest are logical consequences):
- Listings created and removed between scans are invisible.
- Relisting at a new price looks like a sale plus a new listing. Check which fields the scan captures (seller, bid, buyout, time-left bucket, auction ID).
- Time-left bucket matters. A listing that vanishes when time-left was short is probably an expiry; one that vanishes with long time left was bought or cancelled.
- Irregular scan gaps mean longer gaps hide more events. The estimator must use exposure time, not scan counts.
- Partial or interrupted scans (page limits, category scope) create false disappearances.
- Stackables: a partly bought stack changes quantity, not presence.
- Different scanners see different slices (realm, connected realm, commodity vs not), and a scanner's own purchases alter the market.
- The only unbiased label is the player's own mailbox sales and gold deltas. Validate against them.

### 3.7 Priors from a related market

**Core idea.** Shrinkage: combine a noisy local estimate with a prior, weighting the prior less as local data grows. The Efron-Morris baseball example showed that shrinking early-season batting averages toward the group mean predicted end-of-season averages better in total error, though not for every player [secondary: https://philsci-archive.pitt.edu/13303/1/Philosophical%20significance%20of%20Stein%20Preprint.pdf; Efron 1977 https://Www.Gwern.net/doc/statistics/bayes/1977-efron.pdf]. This is empirical Bayes; the prior's weight should come from relative variances, not a hand-picked constant.

**Why it matters, and the risk.** A Beta prior is sensible for a fresh realm. Risks:
- **Structural difference.** Beta population, gold supply, level distribution, gold sellers, and horizon differ from live. The prior is only useful if the Beta-to-live mapping is stable. Test it on items with both histories: how well does Beta price predict live price at weeks 1, 2, 4? If weak, the prior is noise with a confident label.
- **Shrinkage helps on aggregate, not per item.** Some items will be badly wrong. Mark prior-sourced numbers and widen their uncertainty.
- **Fade rule.** Check that the weight decays with local sample size and by what rule.
- Known anomalous Beta periods must be excluded by date, not by hand.

---

## 4. How evaluations lie, and what to do instead

Standard in quantitative finance [background unless cited].

1. **Lookahead bias.** Using information not available at decision time, for example fitting parameters on the full history and replaying it. Any sell-rate or price model must be refit on data up to time t only.
2. **Survivorship bias.** Evaluating only items that still trade. Items that vanish or never sell drop out and flatter results.
3. **Multiple testing and overfitting.** Trying many thresholds and reporting the best. The Deflated Sharpe Ratio corrects for selection under many trials and non-normality [paper: https://papers.ssrn.com/abstract=2460551; overview https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio]. A companion paper reported an in-sample Sharpe of 1.59 falling to -0.18 out of sample in one example [secondary: https://www.cxoadvisory.com/big-ideas/backtest-overfitting-the-movies/]. Record how many configurations were tried. With weeks of data and many knobs, assume the best-looking setting is partly luck.
4. **Regime change.** A fresh economy is not stationary. A strategy tested across a boom week can look great because prices rose, not because picks were good.
5. **Optimistic fills.** Assuming you buy at the listed price, sell at the median, immediately, in unlimited size, with zero deposit. Needs sweep cost, partial fills, a delay between buy and relist, AH cut, deposit on expiry/cancel, and undercut after you list.
6. **Circular labels.** Grading picks on inferred sales produced by the same engine. Needs at least a small real-sales ground-truth sample.
7. **Weak baseline.** Beating "random listing" is meaningless. Compare to naive strategies (cheapest-listing flip, vendor-only, cash).
8. **Simulator assumptions.** A "typical player" grade depends on the simulator. If it uses the tool's own sale model, model errors validate themselves.
9. **Reporting only the optimized metric.** Also report worst case and time to recover.

**What practitioners do instead [background]:**
- **Walk-forward testing:** fit on window A, test on the next window B, roll forward; never tune on B.
- **Out-of-sample holdout:** freeze a period and look once.
- **Paper/forward trading:** log recommendations in real time and grade later. This is the one test free of lookahead. This project has an advantage: the human trades by hand, so every recommendation, whether it was taken, and the actual fill can be logged.
- **Conservative fill model:** treat ambiguity against yourself (ambiguous vanishings count as unsold; worse buy price; add delay).
- **Report uncertainty:** intervals and sample sizes, not points.
- **Pre-register parameters** before looking at the test period.

---

## 5. Game-economy gotchas

- **Gold inflation, faucets and sinks.** Gold enters through quests, drops, vendors, and bots, and leaves through repairs, AH cut, deposits. Prices tend to drift upward on a fresh realm as gold accumulates, so week-1 scarcity prices underprice later [folklore; forum complaints about bot-driven inflation on Classic Anniversary realms, e.g. https://us.forums.blizzard.com/en/wow/t/blizzard-need-to-adress-this/2294291, opinion not data].
- **Bots and gold sellers.** Players report bot farming swamping herb/material supply, for example Black Lotus on Anniversary realms [secondary: https://opera.sportskeeda.com/mmo/wow-classic-s-black-lotus-regulation-fix-wider-economy]. A news report ties a gold-making exploit to Token price [secondary: https://esports.gg/news/world-of-warcraft/wow-token-prices-spark-inflation-worries-in-wow-after-massive-gold-making-exploit]. All qualitative. Bot supply can make a market look liquid until a ban wave removes it. Limit exposure to bot-farmable goods.
- **Blizzard patches and hotfixes.** Changes to drop rates, vendor prices, recipes, or bind rules can reprice overnight. The vendor-floor arbitrage the project uses is exactly what a vendor price change breaks. Check how stale vendor data is handled and how the tool behaves on patch day.
- **Non-profit-maximizing players.** Many sellers post a fixed price once, auto-undercut, or use round numbers; buyers buy for leveling needs regardless of price. Prices cluster and rarely clear to equilibrium, so "arbitrage closes the gap" holds weakly.
- **Tiny player counts.** A few sellers can be most of a market. Buyout-and-relist manipulation is cheap, and one competitor can dominate. Sell rate reflects a handful of buyers.
- **Time-of-day and weekly cycles.** Sales concentrate in evenings and raid nights. If scans cluster at peak hours, inferred sell rates are biased [background].
- **Fresh-realm launch dynamics.** Level-cap timing, profession ramp, first clears, and alt waves create demand surges. Spreads are wide and data is thinnest at the moment opportunity is largest.
- **Shared scans from guildmates.** More coverage but shared biases (same realm, similar timing, one player's own trades visible). Check de-duplication, provenance, and that a buggy upload cannot poison history.

---

## 6. The checklist

Priority: **MUST** = a serious flaw if missing; **SHOULD** = expected of a careful tool; **NICE** = improves quality.

### A. Data and inference

1. **MUST** Does the sell-rate/time-to-sell estimate treat still-listed items as right-censored observations (using exposure time) rather than ignoring them?
2. **MUST** Are sold, cancelled, and expired treated as separate exits (competing risks) instead of one "disappeared" bucket?
3. **MUST** Is there any ground truth for sales (the player's own mail/gold receipts) used to measure the inference's precision and recall, and are those numbers published?
4. **MUST** Does the inference use the listing's last-seen time-left bucket and the scan gap to separate likely expiries from sales?
5. **MUST** Are partial or interrupted scans detected and excluded, so merely unobserved listings are not counted as gone?
6. **MUST** Does exposure time use actual scan timestamps, so irregular gaps do not distort rates?
7. **SHOULD** Is relisting handled (a listing vanishes and a similar one from the same seller appears at a new price) so it is not counted as a sale?
8. **SHOULD** Are stack-quantity changes (partial buys) handled for stackable goods?
9. **SHOULD** Are prices per-unit, and are item variants (bonus IDs, suffixes, quality) kept as separate keys?
10. **SHOULD** Are shared scans de-duplicated and attributed, and robust to a bad upload, without double-counting one market state?
11. **NICE** Is bias from scan timing (scans concentrated in peak hours) corrected or at least reported?

### B. Pricing

12. **MUST** Is the exit price based on what the item sold for (or a clearing price at a stated probability), not just listing statistics such as median or minimum?
13. **MUST** Is profit net of AH cut, deposit (including repeated deposit loss on expiry/cancel), and vendor alternatives, using the correct rates for this realm type?
14. **MUST** Are thin-market prices guarded against single-listing outliers (cheap bait or mistake listings) with a rule at the low end?
15. **MUST** Does the buy list price the sweep (walking several listings, price impact), not each listing independently?
16. **SHOULD** Does the exit price assume undercutting, and is there a floor/walk-away price per item?
17. **SHOULD** Is confidence reduced when the last scan is old?
18. **SHOULD** Are uncertainty intervals and a low-sample warning shown for price and sell rate?
19. **NICE** Is there a seller-concentration check (one seller owns most of the book)?

### C. Sizing and risk

20. **MUST** Is there a hard cap on gold per item, per category, and per day, independent of any formula?
21. **MUST** If Kelly or any edge-proportional sizing is used, is it a fraction of Kelly with the edge shrunk for estimation error?
22. **MUST** Does the "days willing to wait" constraint apply to a distribution (for example a high percentile of time to sell), not the mean?
23. **SHOULD** Are correlated holdings (same patch, material chain, category) treated as one position for risk?
24. **SHOULD** Does the tool track gold locked in unsold inventory and warn when free gold is low?
25. **SHOULD** Are holdings marked to a realistic exit (not listing median), and is a drawdown limit or pause rule defined?
26. **NICE** Is there a stale-inventory rule (old inventory gets a lower ask or is vendored)?

### D. Speculation (Predictions)

27. **MUST** Is each Prediction's maximum loss defined as loss-if-wrong and enforced as a hard size cap?
28. **MUST** Does the tool show what the current price already implies (has the item already moved before the event)?
29. **SHOULD** Does every Prediction have a timestamp, thesis, and exit trigger (time stop and/or price stop)?
30. **SHOULD** Are Predictions graded afterward for calibration across many bets, with failures kept in the record?
31. **NICE** Does the tool consider how many others likely hold the same bet (popular item, public guides)?

### E. Priors (Beta prior)

32. **MUST** Does the weight on the Beta prior fall as local observations accumulate, by a stated rule tied to relative variance?
33. **MUST** Is prior-derived information visibly distinguished from local-data information in the output?
34. **SHOULD** Has the Beta-to-live mapping been validated on items with both histories (correlation and error at weeks 1, 2, 4)?
35. **SHOULD** Are known-anomalous Beta periods excluded by date, and is the prior robust to outliers?
36. **SHOULD** Does the tool avoid confident recommendations when only the prior supports them?
37. **NICE** Are structural Beta-vs-live differences (population, gold supply, vendor and drop changes) recorded as caveats per item class?

### F. Evaluation

38. **MUST** Is the backtest free of lookahead: parameters and models fit with data up to t only?
39. **MUST** Does it use a conservative fill model (sweep cost, delay, deposit, cut, undercut, ambiguous vanishings count as unsold)?
40. **MUST** Are results compared against stated naive baselines (cheapest-listing flip, vendor-only, cash), not just random listings?
41. **MUST** Is the number of configurations or thresholds tried recorded, and is there a holdout period never used for tuning?
42. **SHOULD** Is grading independent of the inference being graded (ground-truth subset, or a sensitivity analysis over sale-inference assumptions)?
43. **SHOULD** Are live recommendations logged with timestamps, whether taken, and actual fills, for forward evaluation?
44. **SHOULD** Are results reported with confidence intervals and sample sizes, including worst case and time to recover?
45. **NICE** Is a regime split reported (by week, by market state) to show it is not one lucky stretch?

### G. Operations

46. **MUST** Is there a patch-day or event-day mode (pre-patch data flagged or discounted, vendor-price changes handled)?
47. **SHOULD** Are data-quality failures (missing scans, parse errors, SavedVariables schema changes) detected and surfaced rather than silently producing numbers?
48. **SHOULD** Is history stored append-only with provenance (who scanned, when, addon version) and backed up?
49. **SHOULD** Are recommendations reproducible (same inputs give the same outputs, versioned parameters)?
50. **NICE** Does the tool show the human why each recommendation was made (inputs and uncertainty) so errors can be caught at the point of action?

---

## 7. Open questions (not settled by sources)

- How TSM computes DBRegionSaleRate and DBRegionSoldPerDay. My fetch of the price-source page did not return definitions; only secondary summaries did.
- Whether Undermine Exchange, Oribos Exchange, or Saddlebag Exchange estimate sales from snapshots, and how.
- Any published validation of sales inference from AH snapshot diffs. I found none; it may exist privately.
- Auctionator's internal models. Only secondary descriptions found.
- Empirical market impact on tiny game markets. The real-world square-root law was not retrieved and may not transfer.
- Measured profitability of WoW patch speculation or market resets. Only anecdote.
- How strongly a Beta economy predicts a fresh live economy. No source; testable only with the project's own data.
- Current AH cut and deposit rates for this realm type. Not verified.
- Whether bot and gold-seller supply raises or lowers material prices on a fresh realm. Evidence is conflicting and partly commercial (gold-seller pages were discounted).
- I did not retrieve primary sources for event-driven speculation practice or Case-Shiller methodology; those lean on background knowledge.

---

## 8. Sources

WoW tools and community
- https://support.tradeskillmaster.com/which-price-sources-can-i-use-and-what-do-they-mean
- https://support.tradeskillmaster.com/tsm-addon-documentation/auctiondb-market-value
- https://support.tradeskillmaster.com/which-value-sources-can-i-use-and-what-do-they-mean
- https://blog.tradeskillmaster.com/tsm-4-10-new-sources/
- https://www.donut.build/how-we-track-auction-prices
- https://undermine.exchange/api.html
- https://us.forums.blizzard.com/en/blizzard/t/how-to-find-items-sold-on-ah-and-turnover/11022
- https://www.curseforge.com/wow/addons/dealscryer
- https://www.curseforge.com/wow/addons/price-answer
- https://www.curseforge.com/wow/addons/auctionator-compainion
- https://www.cgmagonline.com/guides/gold-farming-earning-wow-classic-guide
- https://earlygame.com/gaming/wow-sod-how-to-make-gold
- https://us.forums.blizzard.com/en/wow/t/blizzard-need-to-adress-this/2294291
- https://opera.sportskeeda.com/mmo/wow-classic-s-black-lotus-regulation-fix-wider-economy
- https://esports.gg/news/world-of-warcraft/wow-token-prices-spark-inflation-worries-in-wow-after-massive-gold-making-exploit

Finance and statistics
- https://math.nyu.edu/~avellane/HighFrequencyTrading.pdf
- https://econpapers.repec.org/RePEc:taf:quantf:v:8:y:2008:i:3:p:217-224
- https://www.edegan.com/pdfs/Glosten%20Milgrom%20%281985%29%20-%20Bid%20Ask%20and%20Transaction%20Prices%20in%20a%20Specialist%20Market%20with%20Heterogeneously%20Informed%20Trades.pdf
- https://econpapers.repec.org/RePEc:eee:jfinec:v:14:y:1985:i:1:p:71-100
- https://eu.vlex.com/vid/determinants-of-the-components-855636437
- https://edegan.com/pdfs/Kyle%20%281985%29%20-%20Continuous%20Auctions%20and%20Insider%20Trader.pdf
- https://screamer.readthedocs.io/en/stable/functions_micro/EwKyleLambda.html
- https://www.quantt.co.uk/resources/kyle-model-and-kyles-lambda
- https://www.scribd.com/document/326490154/kuli-doc (Thorp, secondary copy)
- https://www.arxiv.org/pdf/2503.17927
- https://www.masterworks.com/academy/posts/how-reliable-are-repeat-sales-indices-for-art (vendor page)
- https://survive-python.readthedocs.io/theory.html
- https://www.analyticsvidhya.com/blog/2020/12/a-brief-introduction-to-survival-analysis-and-kaplan-meier-estimator/
- https://philsci-archive.pitt.edu/13303/1/Philosophical%20significance%20of%20Stein%20Preprint.pdf
- https://Www.Gwern.net/doc/statistics/bayes/1977-efron.pdf
- https://papers.ssrn.com/abstract=2460551
- https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio
- https://www.cxoadvisory.com/big-ideas/backtest-overfitting-the-movies/
