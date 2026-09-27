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
