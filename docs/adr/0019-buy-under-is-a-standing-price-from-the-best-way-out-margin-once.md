# Buy Under is a standing price from the best way out, margin once

A Scan runs every 15 minutes or so, and a cheap Listing is often bought within minutes, so the Shopping List never sees many of the best buys. A Buy Under (#88) is worked out ahead of time instead: the most one unit of an Item Key is worth paying, so the player can buy a Listing at or under it on sight. The Addon only flags such Listings; the player buys (ADR-0003).

`way_out_value(k)` is the best per-unit value of k's ways out:

- **Vendor**: the Vendor Price.
- **Sell**: posted as a Flip would post it, under the latest Scan's other Listings and never above a Merchant Cost, with a Sell Rate from only the Sale Events at or above that price (#107 replaced the cap at the dearest Sale Event), after the cut, the effort of posting a non-stacking unit and the Deposits it's expected to lose queued behind the unbound held units. It needs the minimum of Sale Events for a Flip.
- **Craft**: for each Known Recipe of any Character in the Market that takes k, the output's value (Sell or Vendor only) times its quantity, less the other reagents' cheapest current source (Merchant Cost, the cheapest other player's Listings, or a Sub-craft, as in ADR-0014) and the effort of buying them, over k's quantity in the recipe. The best recipe counts.

`Buy Under = way_out_value − the effort of buying one unit − the Flip margin`, with the margin `max(flip_min_margin_copper, flip_min_margin_share × Buy Under)` solved for the price and floored to the copper. The margin is charged once, at the top: a chain built on a Buy Under (Disenchant mats, #76) builds on `way_out_value`, never on another Buy Under.

It shows only when at least `buy_under_min_sightings` distinct Scans in the last `buy_under_window_days` (1 and 7 by default) saw another player's Listing of k at a unit buyout at or under it. Scans are counted, not Listings, so one seller's stack counts once.

## Why

- **Crafts count here, though Best Exit Value counts none (ADR-0014).** Best Exit Value is what a held unit brings by its own Actions, and a Craft of it is already a separate Action there. A Buy Under is the price to pay for a unit that isn't held yet, and for a reagent the Craft is often the only reason to buy it (a Greater Magic Wand's reagents are one example). The output is still valued by Sell or Vendor only, never crafted further, so the chain stays one step deep plus ADR-0014's Sub-crafts for the other reagents.
- **Holdings are ignored for the other reagents.** A Buy Under is a standing price. If the Thread in the bags made the Linen's Buy Under higher, it would move each time the bags changed, and the player couldn't trust it between Scans. The held units of k itself still count against its Sell room and queue, because buying more of k than will sell is a real loss. They're the units left once the Holdings' own Craft Actions are made, the same queue a Flip sees.
- **The evidence rule.** A price nobody has ever listed under is noise on the tab. Seeing it in past Scans shows such Listings do turn up. Counting Scans rather than Listings keeps one seller's 20 stacks from reading as 20 sightings.
- **It isn't graded by the replay.** The replay works from Scans, and a Buy Under exists for Listings the Scans miss. A Listing the Scans did catch is already a Flip. So there's nothing honest to grade, and the replay leaves Buy Unders out entirely.

## Consequences

- It ignores the Budget: it's a price, not a spend.
- `units` is how many units it's good for: none for a Vendor way or a Craft whose output Vendors, else the Sell Rate room within the Sale Horizon less the unbound held units, for a Craft converted to whole crafts' worth of reagent units. A way with no units left isn't a way, so a Sell way that's full falls back to the next best one, and an Item Key with no way left has no Buy Under.
- A Craft whose output binds on craft, or whose bind type is unknown, counts only its Vendor Price.
- The Buy Unders are sorted by profit per unit at the Buy Under price, best first.
- Recommendations.lua carries them as `buyUnder`, for the Addon's Buy Under tab, tooltip line and Auction House highlight (#88's later slices).

## Amendment: the Disenchant way and Disenchant source groups (#88, 2026-09-28)

- **Disenchant is a fourth way out.** For an Item Key a Character can Disenchant (ADR-0018's skill gate), `Σ expected qty × way_out_value(mat)`. A mat's way out includes a Craft it's a reagent of, so a green whose essence feeds a Craft gets that Craft's credit. It builds on the mats' `way_out_value`, never on their Buy Under, so the margin is still charged once. A Craft output is still valued by Sell or Vendor only, never Disenchanted.
- **A Disenchant source group has its own Buy Under**, by the same formula, less the effort of buying one unit (armor and weapons don't stack) and the margin. It's shown only when some Character's Enchanting skill meets the group's highest item level. Its evidence is distinct Scans that saw another player's Listing of any item in the group that can be Disenchanted, at or under it. This is the Buy Under that catches a green nobody has listed before.
- **Units:** no limit when every mat's way out has none, else the fewest Disenchants any limited mat has room for (its units over its expected qty per Disenchant).
- **The Addon matches an item by the higher of its own Buy Under and its group's.** A group entry in `buyUnder` carries its bounds (quality, class, item levels), so the Addon checks an item against it with `C_Item.GetItemInfo` and only needs `disenchantExcluded` from the data file. The spec's `disenchantBands` was dropped as a second copy nothing needed.
