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

## Amendment (#31)

Settled while building it:

- A reagent with a Merchant Cost costs that per unit whether held or bought, since it can always be bought back at that price. It needs no market data, so thread and vials don't block every recipe.
- Every craft uses at least one held reagent unit. From merchant reagents alone the greedy loop would never end whenever a vendor pays more for the output than the merchant charges, and that would be buying to craft anyway.
- Nothing is crafted into an Item Key under an active Prediction: its Hold would include units not made yet.
- Quest-bound outputs count as bound, like Bind on Pickup.
- A blocked recipe shows as a Craft row of 0 with the reason, only when one craft's reagents are on hand.
- The client seems to give no cooldown for a cooldown recipe that's ready (a spike dump shows `GetRecipeCooldown` returning nil), so the once-per-Character limit only applies when some Character's Read caught it cooling down.

## Superseded in part (#32)

ADR-0009 lets reagents be bought on the Auction House to craft, as a Flip to Craft. The Craft Action itself still starts from held reagents.

## Superseded in part (#33)

ADR-0014 lets a short reagent be crafted first with another Known Recipe (a Sub-craft), so a Craft can be a chain. Outputs are still valued by Sell and Vendor only, and a reagent with no market data now blocks a recipe only when nothing can source it.
