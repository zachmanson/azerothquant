# Flip to Craft: buy missing reagents on the Auction House, one greedy craft at a time

ADR-0008 left buying reagents out of the first Craft Action, though much of crafting's profit is there. A Flip to Craft (#32) is a Flip whose way out is Craft, then the output's Sell or Vendor: a Shopping List Recommendation, not an Action. Outputs are still not crafted further (#33).

It runs after held-only crafting, on what's left. Each step takes the single best craft across Known Recipes, as in ADR-0008. Leftover held reagents are used first, costed at their Best Exit Value; missing ones are bought at the next cheapest asks not already taken by a plain Flip, and merchant ones at their Merchant Cost. The output counts at the recipe's minimum quantity. Its units are worth Selling only within its Sell room, which is what sells within the Sale Horizon under the Flip priors, less the units already held (held crafts included) and those a Flip to Sell buys. Anything past that is valued at Vendor Price. A craft is taken only while it clears the Flip margin against the gold it spends. Each craft then joins plain Flips in the Shopping List's ranking by profit per gold. Prediction buys get what's left.

## Considered Options

- Stricter priors than a Flip's, since two markets are involved: the reagent side is priced at real asks that walk up as more are bought, so its risk is already in the cost. Only the output is a guess, and that is exactly a Flip's risk.
- Ignoring held reagents and buying everything: it would recommend buying what the player already holds.
- One joint greedy over every ask and every kind of buy, or a linear-programming solver: better when a Flip and a craft want the same cheap ask, but harder to explain. Plain Flips going first never double-books an ask, and gold cutting a Flip short leaves its asks idle, the same approximation the Shopping List already makes for a cut-short resale.
- A separate gold share for Flips to Craft: an arbitrary split. Profit per gold already ranks everything else on the Shopping List.
- Requiring at least one held or Auction House reagent (ADR-0008's amendment): the unbounded merchant-to-vendor loop it guarded against is now bounded by gold, and Sell room bounds the Auction House exit. Crafts from merchant reagents alone are real money-makers.

## Consequences

- A Flip to Craft is one Shopping List row per recipe, keyed by the output and naming the Character that knows it, with a structured list of reagent buys (Item Key, quantity, most to pay per unit, whether it's a merchant's). The Addon names the reagents, because the Brain only knows names from own Listings, and a reagent is useless to shop for by itemID.
- Amended by #49: every Craft row, a Holdings Craft or a Flip to Craft, also carries its Character as a field and a structured list of the held reagent units it uses (Item Key, quantity). The Addon names both the reagents a craft uses and the ones it buys, and reads the Character from the field, not from the note. The note stays for the `brain recommend` CLI.
- Cooldowns, blocked recipes, bind types and Predictions follow ADR-0008: reagents and outputs under an active Prediction are left out, since buying them is a Prediction buy. A blocked recipe shows no Flip to Craft row.
- Bought reagents start Lots that crafting never closes (ADR-0007), so realized profit doesn't cover Flips to Craft yet.
- Amended by #69: a held unit is recommended once. Holdings rows are built from what's left after the Craft Actions and the Flips to Craft the Shopping List buys, so a held reagent a Flip to Craft uses shows only in that Flip's `uses`, not as its own Holdings row.
