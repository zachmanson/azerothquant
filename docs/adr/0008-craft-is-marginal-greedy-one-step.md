# Craft is marginal, greedy, one step, and starts from held reagents

The Craft Action (#28) is the first Action that uses up several Item Keys and makes another, so it can't be decided one Item Key at a time like Sell and Vendor. Sell is also limited: only the units that will sell within the Sale Horizon count, so crafting into an output the player already holds plenty of mostly adds units that end up vendored. So a craft is valued at the margin: one more craft is worth doing when the output Holding's exit value with its units added gains more than the consumed reagents' exit value loses, both computed by the same Sell/Vendor split the Holdings rows already use. Crafts are chosen greedily, taking the single best craft across all Known Recipes each step and recomputing, until the best gain is no more than `craft_min_gain`. Outputs are valued by Sell and Vendor only, not by crafting them further, and only reagents the player already holds (plus merchant reagents at Merchant Cost) are used, never ones bought on the Auction House.

## Considered Options

- Per-unit Best Exit Value (output value times quantity against the reagents' value): simplest, but it ignores Sell capacity and recommends crafting into a saturated market.
- A linear-programming solver over all recipes at once: optimal when recipes compete for the same reagent, but adds a dependency and makes every row hard to explain. Greedy on the best step first is close enough until real Holdings show otherwise.
- Chained crafts (valuing an output by crafting it further): what the glossary's Best Exit Value promises, but recursing inside the greedy loop needs cycle guards (some recipes round-trip) and makes the reasoning behind a row hard to follow. One step already covers most of the value.
- Buying reagents on the Auction House to craft: where much of crafting's profit is, but it stacks Fair Value after buying out the reagents on top of the output's Sell Rate, and has to share the Shopping List's gold with Flips and Predictions.

## Consequences

- The guesses all lean toward crafting less: output counts at the recipe's minimum quantity, a reagent with no market data blocks the recipe (valuing it at its Vendor Price would understate what crafting it away costs), while an output with no data counts at its Vendor Price. A Bind on Pickup output is Vendor only, and one whose bind type is unknown blocks the recipe.
- A recipe with a cooldown crafts at most once per Character that knows it, and not at all while its cooldown, as of the Character Read, hasn't passed.
- Reagents Held under an active Prediction are never crafted away.
- Crafting still starts no Lots (ADR-0007): the Brain recommends a craft but never sees one happen.
- Chaining and buying reagents to craft are separate follow-ups, each able to revisit this.
