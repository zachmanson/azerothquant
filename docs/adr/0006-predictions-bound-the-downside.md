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
