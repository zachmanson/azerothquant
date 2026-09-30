# The Beta Sell Rate may bound a Prediction's Max Loss early in Live

A Prediction buy's Max Loss is its cost less its exit if the Prediction is wrong: a Sell at the post price, where the Live Sell Rate at that price has room, else the Vendor Price. The post price comes from Live's Listings, so it's there from the first Scan. The room isn't: at launch no Item Key has Live Sale Events, so the exit falls to the Vendor Price, Max Loss goes over `prediction_max_loss_share`, and nothing is bought in exactly the days a Prediction matters most (#110, #91). The missing number is the Sell Rate, not the price.

So for `beta_column_days` (14) from a Live Market's first Scan, the room a Prediction buy's Max Loss counts on may also count the Beta Market's Sale Events (same faction, else Alliance, as the Beta Prior). Each counts as `beta_sell_rate_weight` of a Sale Event, and each Beta Observation Window hour as that share of an hour, added to Live's. Beta's hours count even when none of its Sale Events are at the price, so a quiet Beta waters Live's rate down as well as a busy one lifts it. The rate is then a weighted average of the two, Live takes over as its hours build, and the weighted Beta Sale Events count toward `flip_min_sale_events`, as Siblings do (ADR-0022). All of Beta's history counts, not only its last 14 days. The post price stays Live's: a Beta Sale Event counts at it when priced at or above it times the Item Key's Beta/Live Fair Value ratio (Beta's latest over Live's in the Scan). No Beta price is ever an input.

This is the one exception to the Era rule (no decision reads the other Era). It is narrow on purpose: only a Prediction buy's Max Loss room (and the deposit queue at that room), never Flips, Flip to Craft, Holdings, or Buy Under, which spend gold on the estimate of an Item Key's own Market. A Beta Market never borrows from itself.

It is **off by default** (`beta_sell_rate_weight = 0`). Nothing yet says Beta's demand looks like Live's, so the player checks the Beta/Live Fair Value ratios first (`brain recommend --beta-ratios`) and turns it on (e.g. 0.5) if they're close.

## Considered options

- **A fallback cliff**, Beta only while Live has fewer than N Sale Events: a jump in the room the day the Nth Sale Event lands. Pooling fades on its own as Live's hours build.
- **A time fade**, a weight falling over the 14 days: another knob with no data to tune it. Pooling already fades with evidence, and the hard stop bounds it.
- **Raw Beta prices**, counting a Beta Sale Event at or above the Live post price itself: Beta's gold supply differs from Live's, so it would count too many or too few. Scaling by the Fair Value ratio compares like with like.
- **The Beta price as the exit**: puts a Beta price into a decision, where it's least trustworthy. Live's Listings give the price from the first Scan anyway.
- **Waiting for Nov 18** to see if Beta matched Live: the only window where this matters is Live's first 14 days, so the evidence would arrive after it's useful.

## Consequences

- The replay honours the weight and, while it's above 0, runs a `Brain without Beta Sell Rate` ablation (ADR-0015).
- A Prediction buy row carries the biggest room any of its units counted on and how much of that came from Beta; `brain recommend --why-not ITEM_KEY` shows it.
