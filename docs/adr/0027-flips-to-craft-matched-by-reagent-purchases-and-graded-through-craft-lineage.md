# Flips to Craft are matched by reagent Purchases and graded through craft lineage

ADR-0023 grades the Flips to Sell the player made. A Flip to Craft (#114) is harder to grade: the player buys reagents, crafts, and sells the output, and the Brain sees those as separate events. The Purchases are in the mail, the crafts are Craft Results (#44), and the sales are Sold Outcomes of a different Item Key.

**Matching is by the reagent Purchases.** A Purchase not under a Prediction matches a Flip to Craft row of the Market's last Scan before it when its Item Key is one of the row's Auction House buys, at a unit price at or under that reagent's most to pay. That includes a Sub-craft's reagents, which are in the row's buys. A merchant reagent's Purchase never matches, since the row named no Auction House buy of it. All the Purchases matched to one row (recipe, Scan) are one Flip to Craft, the same way a run that straddles two Scans is two Flips to Sell. A craft from held reagents only has no matched Purchase, so it's never a Flip to Craft.

**Output is found through craft lineage.** Each crafted Lot records the Lots its craft used up and how many units of each, as they stood then (`Lot.lineage`). The Flip's output is the output Lots of crafts **of its row's recipe**, by its grading moment, that used up any unit of its Purchases' Lots, directly or through a Sub-craft's output Lot (followed transitively). A craft counts whole if it used any of the Flip's units, with no split by share. Sub-craft leftovers aren't graded. Lots stay derived (ADR-0007), and nothing about which units close changes.

**Some Flips can't be graded.** When a craft used uncosted reagent units (looted or For Use), #44 opens no output Lot. If such a craft of the row's recipe used the Flip's units, the Flip is skipped as "uncosted reagents" (#130 is the later fix). If none of its units went into a craft of its recipe by the horizon, it's skipped as "not crafted by the horizon". `brain flips` counts both.

**The grade** is a Flip Grade (ADR-0023) on the output: the clock starts at the first matched Purchase, and a Sale Horizon later the output units Sold by then after the Auction House cut, plus open output units at their Best Exit Value then, are set against the output Lots' cost. Vendored output stays open at its Best Exit Value, so a Vendor-exit row needs no special case. Expected Profit is the row's Profit × (output units graded ÷ the row's output units). It also records `crafted_after`, the seconds from the first Purchase to the first craft that used its units, a Sub-craft included. It's worked out and frozen at the same moments as a Flip to Sell's grade.

**Frozen rows.** Each Scan's Flip to Craft rows (output Item Key, recipe, Character, output units, Auction House buys, Post at, Profit, days, Sale Horizon) are frozen the first time the Scan is worked out, under `[shown_crafts...]` in `grades.toml`, and grades under `[craft_flips...]`, keyed `<recipe>@<Scan>`. Scans frozen before #114 have no craft rows. Such a Scan is worked out again only when a Purchase after it was named (not For Use) and matched none of its Flip to Sell rows, since only such a Purchase could be a Flip to Craft. Once worked out, it's marked even when it named none.

**Reported apart.** `brain flips` lists Flips to Craft in their own section, and `brain recommend` sums them on their own line. The two records are never merged: the units differ (bought units against crafted output), and so does what they test.

## Considered options

- **Match by the output's sales**: a Sold Bolt doesn't say whether its Linen was bought on the Brain's word or looted.
- **Split a craft's output by the share of the Flip's units it used**: more exact for mixed held/bought crafts, but it adds fractional units everywhere for a rare case.
- **Cost uncosted reagents now**: that's #130. Until then those Flips are counted, not graded.

## Consequences

- A purchase of a reagent that's in two rows of the same Scan matches both. Each counts only the output of its own recipe.
- A Sub-craft whose own reagents were uncosted breaks the chain, so its Flip shows as not crafted rather than uncosted. So does a craft whose output was under a Prediction standing then, which opens no Lot (ADR-0009).
- Output a later craft used up has no Sold Outcome, so it stays open at its Best Exit Value (ADR-0007), as for a Flip to Sell.
