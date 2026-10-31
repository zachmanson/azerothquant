# Predictions bound the downside and never price the upside

The player's game-knowledge calls ("these mats will spike when the raid drops") come with a direction and a Catalyst, but no honest price target or date. Any number the Decision Engine put on the upside would be invented, and a confidently-wrong call would then look as good on the Shopping List as a Flip backed by market data (#8). So a Prediction never produces an expected profit. It only permits buying and Holding its Item Keys while each unit's Max Loss (cost minus its Best Exit Value without the Prediction, which already accounts for the Sale Horizon) stays within a small share of cost. Gold under Predictions is capped per Prediction and in total. Prediction rows sit in their own labeled section rather than competing with Sells and Flips on expected profit.

## Considered Options

- Target Fair Value by a date: grades cleanly and prices a Hold directly, but the player can't honestly name either number.
- Magnitude buckets ("up a bit / a lot / huge" mapped to multipliers): still invents the upside, just less visibly, with nothing to ground one multiplier over another.
- Learn the size from past Catalysts: no Forever history exists yet. Graded Predictions may supply it later.

## Consequences

- Trust comes from the realized return of graded Predictions, measured from Outcomes, never from the player's own judgment. With 5 to 15 graded a year the record is shown, not applied, except for one brake: caps are halved while the pooled realized return is negative.
- A Prediction with no Catalyst marked by its lapse date Lapses, so a wrong call can't hold gold forever or dodge grading.
- Predictions live in a player-edited `predictions.toml`, not only in the history database: they aren't recorded by the Addon, so they can't be rebuilt from the Archive (ADR-0005).

## Amendment: Grades and held-at-writing costs are frozen in `grades.toml` (#66)

Both were worked out again from history on every run, so any change to how Best Exit Value is priced (like #64) silently rewrote past Grades and the cost of units held when a Prediction was written. The Brain now records each one the first time it works it out, in a Brain-owned `grades.toml` next to `predictions.toml`, keyed by Market and Prediction name (a Prediction names Item Keys, not a Market, so each Market holds and grades it apart), and reads it from there from then on. Each is recorded only once the Market has a Scan after the moment it rests on (the start of the day after the written day, or the grading moment), since a Scan or Read from before then may still come in. The file is append-only: the Brain never overwrites an entry, and checks the file again right before appending in case another Brain process just froze it. The player deletes an entry by hand to have it worked out again. An entry whose Prediction was renamed or removed is left behind and never used. One whose Prediction was edited but kept its name (other Item Keys, another written or happened date) is still used, so delete it after such an edit.

- Not a table in the history database: that is rebuilt from the Archive (ADR-0005), and a Grade kept only there would be lost or recomputed on `brain rebuild`.
- Not the pricing rule versioned by date: the code would keep every old rule forever.

## Amendment: No Prediction buy above the Merchant Cost after the cut (#91)

A Prediction never looks at the upside, but an Item Key an NPC merchant sells in unlimited stock has a known one: nobody pays more on the Auction House than the Merchant Cost, so that's the ceiling on every Sell. Without a check, a Prediction on Black Lotus (50g at the Black Market's Mister Graphed) would let the player buy one at 48g, which can fetch at most 47.5g after the Auction House cut: a certain loss. So a Prediction buy is allowed only below the Item Key's Merchant Cost after the cut. There's no margin beyond that: demanding room under the ceiling would be pricing the upside, which this ADR rules out. An Item Key with no Merchant Cost seen in its Market has no cap.

- Not dropping merchant-sold Item Keys from Predictions: the player still wants to buy them cheap on the Auction House ahead of a Catalyst.
- Not a hand-kept list of which items a merchant sells: Merchant Cost is already read in game, per realm and faction.

## Amendment: The exit if wrong steps down to where it would sell (#205)

A unit's Max Loss assumed it was resold at its post price, if the Sale Events at or above that price had room for it, and otherwise Vendored. In a rising market the asks sit above every past sale, so there was never room at the post price, and the exit fell straight to the Vendor Price: Prediction buys skipped exactly the Item Keys a Prediction is right about (on the last Beta Scan, Swiftthistle's first unit had a Max Loss of 99.6%). A player whose Prediction turns out wrong doesn't vendor: they undercut until it sells. So a unit with no room at its post price is now valued at the dearest Sale Event price at or under that post price with room for it, judged as strictly as before (only the Sale Events at or above that price, at least the Flip minimum of them, less the Deposits it's expected to lose in the queue there), and never under the Vendor Price. Early in Live, Beta's Sale Event prices count too, scaled to Live's by the Fair Value ratio, as the Beta Sell Rate's demand already does (ADR-0024). It's still only the downside: the prices are past sales, never a target.

- Not raising `prediction_max_loss_share` for Predictions: a riser still has to have traded near its ask to be bought, which is the honest bound.
- Not a same-Scan dump test (buy what's far under the other Listings, with no sales behind it): with no exit there's nothing to bound the loss by without guessing a price.
- Not for Flips: a Flip earns at its post price, and loosening Flip to Sell lost in the Backtest (ADR-0036, ADR-0040).
- On Beta the risers rose with almost no trades (Swiftthistle had none at even half its last price), so this buys them only once Live trades them a little under the ask.
