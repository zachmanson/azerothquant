# Sub-crafts: a short reagent can be crafted, backward from the top craft

ADR-0008 and ADR-0009 crafted one step deep: an output was valued by Sell and Vendor only, and a reagent was held, bought from a merchant or bought on the Auction House, never crafted. That misses chains whose first step loses money on its own (ore → bar → part), which is where much of crafting's value is (#33).

A greedy step is still one more craft of one Known Recipe R, a Craft Action or a Flip to Craft. What changes is where its reagents come from. A reagent that's short can be covered by a **Sub-craft**: crafting it with another Known Recipe, whose own reagents are sourced the same way, recursively. The step's gain is the top output's worth with its units added (Sell room still applies) less the worth of the raw held reagents the whole chain uses, less the gold it spends.

**Reagent sources, in order**, per reagent:

1. Held units. A held reagent with no market data isn't used (it can't be valued, as a Flip to Craft already did), and neither is a crafted unit or one Held under a Prediction.
2. A merchant's, at its Merchant Cost. A merchant reagent is never Sub-crafted.
3. The rest from one source, whichever costs less: a Sub-craft, or the cheapest Auction House asks left (a Flip to Craft only). A Sub-craft costs the raw held reagents' worth it uses plus the gold spent below it, less its leftovers' worth; Auction House asks cost what they cost plus the non-stacking effort (#73). One reagent's shortfall is never split between sources.

The reagent-source function (`_Sources` in recommend.py) is where a Disenchant step would plug in (#76).

**Guards.**

- Path rule: a Sub-craft can't use a recipe whose output or any reagent is already an Item Key on its path from the top craft. That refuses lesser ↔ greater essences and A → B → A.
- `craft_chain_depth` (3 by default) is the most crafts deep a chain goes, counting the top craft.
- Reagents and outputs under an active Prediction are left out, as before.
- A Sub-craft of a cooldown recipe counts against that recipe's limit, shared with its own Craft rows and Flips to Craft.
- A Sub-craft's recipe may have an unknown bind type: its output is consumed.

**Leftovers.** A Sub-craft counts its output at the recipe's minimum quantity. Any surplus joins the crafted Holdings (shown as "incl. N crafted") and is valued in the step's gain. A surplus of unknown bind type counts as bound (Vendor only). Crafted units, leftovers included, are still never reagents for a later step, so every row stays self-contained and #69 is unchanged.

**Rows.** One Craft row per top recipe. Its `via` lists the Sub-crafts, deepest first, as `{ itemKey, crafts, character }`. `uses` and `buys` aggregate the raw held and bought reagents across the whole chain, and the profit sits on the top row: Sub-crafts aren't rows of their own. The CLI note reads `on X: uses 20 of 2770, via 10 of 2840 on Y`. The Addon shows `Craft 10 Copper Bar on Y` lines before the Use/Buy lines in both tooltips; the Note cell is unchanged.

## Considered Options

- **Forward valuation**: an output is worth max(Sell/Vendor, crafting it further). What the glossary's Best Exit Value first promised, but it breaks the marginal Sell-room valuation: an output's worth would depend on crafts that compete for the same room and reagents, and every row's reasoning would reach into other rows.
- **Mixing sources within one reagent's shortfall** (some bought, some Sub-crafted): a little better at the margin, but the options multiply and the row gets hard to read. The greedy loop already mixes across steps.
- **Leftovers as reagents for later steps**: it would chain rows together, so one row's profit would rest on another's, and a held unit could be counted twice (#69).

## Consequences

- Supersedes ADR-0008's "one step, outputs valued by Sell and Vendor only" and ADR-0009's "Outputs are still not crafted further". Outputs are still valued by Sell and Vendor only; it's the reagents that chain.
- A recipe shows a blocked row only when some reagent can't be sourced at all: a reagent with no market data blocks it only when no merchant sells it and no Known Recipe may make it for this recipe under the guards (depth, path, cooldown). A maker whose own reagents aren't there shows no row, like any recipe whose reagents aren't there.
- The search tries each source for each short reagent, so each greedy step values more Holdings than before; the Valuer memoizes what a Holding is worth.
- Best Exit Value is unchanged in code: Grades and held-at-writing never counted crafts (ADR-0010).
