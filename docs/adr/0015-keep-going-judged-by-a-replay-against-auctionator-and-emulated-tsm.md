# Keep going, judged by a replay against Auctionator and emulated TSM

Should azerothquant keep going when TradeSkillMaster (TSM) exists? It exists for gold and for the craft of building it, but it has to earn its keep: if a simpler tool earns as much, the Brain stops growing.

**What TSM offers on Forever (researched 2026-09-28, mostly from search snippets, since the key sites blocked fetching).** Nothing yet. Forever is in Beta (Sept 17 to Oct 21, 2026), and Live launches Nov 4. There is no official TSM statement, no Forever flavor of TSM on CurseForge and no Forever AuctionDB data (DBMarket, DBRegion*, SaleRate). A third-party site, unconfirmed, reports that Blizzard's auction API has no Forever data, which TSM would need to build any. Auctionator (a Forever-flagged file) and community Auctioneer forks already run on Forever, and Booty Bay Broker crowdsources Forever Scans. So the opponent today is Auctionator, and the question "would a TSM price string do as well" is answered by emulating one.

**The test is a replay over the Archive.** At each past Scan of a Market, three policies choose Actions from the same Holdings and Listings: the Brain, an Auctionator baseline (post just under the lowest current Listing, buy nothing it can't resell above that) and an emulated TSM baseline (price strings over DBMarket and DBMinBuyout computed from our own Scans by TSM's published method: DBMarket is a 14-day weighted average of the lower listings). Each policy is graded by Best Exit Value against what the Market did next, as Grades already are. The one number that decides is graded value, Brain vs. each baseline.

**Ablations** rerun the Brain with one feature switched off at a time: Sub-crafts, Flip to Craft, Deposits and own-Market Sell Rate (replaced by a DBMarket-style price with no Sell Rate). They say which features pay and where the next month of work goes. The features expected to win are own-Market Sell Rate and Sale Events, Sub-crafts and Flip to Craft. Deposits and Holdings Sell vs Vendor should win by less, and Predictions are unproven.

**Checkpoints.** Beta and Live data are never mixed (Era), so there are two reads:

- **Beta, by Oct 21: provisional.** It debugs the harness and gives an early read. It can flag a bug, but it never stops the project, since the Beta economy is distorted.
- **Live, after 4 weeks (around Dec 2): binding.**
  - **Continue** if the Brain beats Auctionator by at least 10% of graded value and is no worse than emulated TSM.
  - **Stop** if it's within ±5% of Auctionator: trade with Auctionator, keep the Addon for data collection, and freeze Brain features.
  - **In between**, a 2-week live split (some Item Keys or Characters follow Auctionator, the rest the Brain) decides.

Realized profit from Lots and Sold mail is reported alongside as the confirmation. Gold per hour of the player's time is reported honestly as TSM's traditional strength. ADR-0016 narrows that gap, and it doesn't decide the verdict.

**Outside market data.** TSM's real value may be its data, so if TSM (or anyone else) publishes Forever data, it supplements ours and doesn't replace it. It's imported per Market and fills in where our own Market is thin (rare Item Keys, items with no Sell Rate, new recipes). Our own Sale Events override it wherever there are enough of them, and an ablation measures whether it helps. It may replace one of our metrics (Fair Value or Sell Rate) only if the replay shows it predicts that metric better. Revisit trigger: TSM announces Forever support or AuctionDB data. Then "real TSM" joins the replay as a third baseline and as a supplement, read from the file the TSM desktop app writes (`TradeSkillMaster_AppHelper`) as an ordinary import. Booty Bay Broker is researched now (#82), as the one Forever source that exists.

## Considered Options

- **Stop and use TSM.** It doesn't run on Forever and has no data there.
- **Point price accuracy only** (Fair Value and Sell Rate vs. DBMarket and SaleRate). Too narrow: the Brain's edge is in decisions across items (what to craft, flip or hold), not in one item's price.
- **Realized profit as the deciding metric.** It's the closest to real money, but slow and noisy, and it can only be measured on Live. It's the confirmation instead.
- **Live split only.** It costs real gold and weeks. It runs only when the replay result is close.
- **Beta data as the verdict.** The Beta economy starts from zero and is distorted, and the Era rule keeps it separate anyway.
- **Replace our data with TSM's if theirs is better.** Region-wide data blurs Markets, and our edge is seeing our own Market's Sale Events. Replacement is allowed only per metric, and only when the replay proves it.

## Consequences

- The replay harness (#80) is built before the #38 build so it runs on Beta data before Oct 21. It needs the two baseline policies, grading by Best Exit Value and ablation flags in config.
- Brain feature work after Dec 2 depends on the verdict (#83), and a stop freezes it.
- DBMarket and DBMinBuyout emulation lives in the harness as a baseline. It isn't a Brain price.
- An outside data source is a prior: it's per Market, and it gives way to Live observation.
- The Beta Prior is display only (#90): the Decision Engine never reads it, so it isn't ablated. The Beta Sell Rate is read (#110, ADR-0024), so while `beta_sell_rate_weight` is above 0 the replay also runs a `Brain without Beta Sell Rate` ablation, with the weight at 0.

## How the replay grades (#80)

`brain replay [--since DAY] [--until DAY]` grades every Scan in the range that has a whole Sale Horizon of Scans after it, per Market (so per Era).

- **Moves.** At a Scan, each policy starts from the Holdings and gold of that moment. The Brain is `recommend` as of that Scan: its Sell rows are posted, its Vendor rows vendored, its Shopping List and Prediction buys bought, and no-data, Hold and Prediction-bought units held on to. Known Recipes, Merchant Costs, Vendor Prices, Sold-invoice deposits and the Lots behind Hold costs and ROI are the latest seen, not as of the Scan.
- **Grade.** Vendor gold, plus posted units that later Sale Events of the Item Key reached (a Sale Event's dearest price at or above the post, up to its units, the policy's cheapest posts first), less the Deposits lost on the way (a sale seen at a Scan is taken to be just before it, so a posting ending right then hadn't expired; an unsold unit loses one per posting that ended by the end of the horizon, and its Best Exit Value charges only the later ones), plus what's still held at the end of the horizon at its Best Exit Value, less the gold spent. Then the same Holdings held untouched until then are subtracted, so each grade is the **value added** and the shared Holdings don't dilute the gaps. Grades are summed over the Scans, and "Brain over it" is (Brain - policy) / |policy|.
- **Auctionator.** Flip to Sell only: all the units at the cheapest ask, when it sits under the next-lowest ask by more than the cut plus the Deposit, reposted 1c under that one. Then every held unit is posted 1c under the cheapest other player's Listing left, or Vendored when that pays more.
- **Emulated TSM.** DBMarket, per Scan: the mean of the cheapest 15% of units, then more up to 30% while each is under 120% of the one before, leaving out units more than 1.5 standard deviations (population) from that mean. A day's value is its Scans' mean (days are 24 h back from the Scan being replayed, not calendar days), and DBMarket weights the last 14 days by 14 for the latest day down to 1 (our choice: TSM doesn't publish its weights exactly). DBMinBuyout is the cheapest unit in the Scan. Posts go 1c under the cheapest other player's Listing while that's between the floor (0.8 x DBMarket, or the Vendor Price if more) and the normal price (DBMarket, or the Vendor Price if more), else at the normal price, never above it even when the cheapest Listing is dearer. It crafts one level deep while one more craft's reagents (held ones at DBMinBuyout, bought ones at the asks) cost less than the output's DBMarket, with no Sell Rate and no inventory limit. Recipes with a cooldown, and outputs that bind, are left out.
- **Ablations** are Config fields the replay sets, not config.toml keys: `craft_chain_depth = 1` (no Sub-crafts), `flips_to_craft = False` and `deposits = False`. The grader charges Deposits whatever the run.
- **The own-Market Sell Rate ablation** (#84) isolates the Sell Rate inside the Brain: Sub-crafts, Flips to Craft, Holdings Sell vs Vendor, Deposits, the Flip margin, effort and the cut all stay the Brain's. `recommend_market` takes an optional pricer: (Item Key, the cheapest other player's unit price left once the buys are made) → the price to post at, or none. Only the replay builds one, from the emulated DBMarket and TSM's post rule: 1c under the cheapest other Listing while that's between the floor (0.8×DBMarket, or the Vendor Price if more) and DBMarket, else DBMarket. There's no Config field or config.toml key for it, and `recommend.py` never computes a TSM price itself. Given a pricer, it replaces the Sell Rate everywhere but the Prediction buys, the Buy Unders (a replay doesn't grade them) and the Shopping List's Per day and Per click (the replay takes Flips by Profit alone):
  - Room: unlimited, with no `flip_min_sale_events` minimum. The gold is the only limit on Flips to Sell and Flip to Craft outputs, and every unbound held unit Sells while its post after the cut beats the Vendor Price.
  - Data: an Item Key has data when the pricer has a price for it (a DBMarket at that Scan), not by our Fair Value.
  - Ceiling: no cap at the dearest Sale Event, but a Merchant Cost still caps the price.
  - Deposit queue: empty, so no expected lost Deposits are charged. The grader still charges the real ones.
  - Held units' worth in Sub-craft and Flip to Craft costing uses the same pricer.
  It's graded like every policy, by the real Brain's Best Exit Value at the end of the horizon, as the `Brain without own-Market Sell Rate` row. It runs on every `brain replay`.
- **Realized profit** is the range's Sold Outcomes after the cut, less the cost of the Lot units they closed.

## Amendments

- Amended by #167 (ADR-0032): the replay no longer judges buy-side changes. The walk-forward Backtest graded on Sale Records does (`brain backtest`). The Brain vs. Auctionator and TSM checkpoints above still use the replay.
