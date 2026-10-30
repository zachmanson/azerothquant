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

## Amendment: no Sell way (#173, 2026-10-29)

The "isn't graded by the replay" reasoning above no longer holds: the Backtest (ADR-0032) grades Buy Unders as standing orders. At each Scan, the `buyunder` policy takes the previous Scan's Sell and Vendor ways, buys other players' Listings at or under them up to their units and its gold, and posts what a Sell way bought 1c under the cheapest Listing left, never over the price it was valued at (that already has the Merchant Cost ceiling and the demand behind it). A Listing a Scan caught stands in for the ones it missed.

The outside review (`docs/research/decision-review-2026-10-08/REVIEW.md` §5) found 45 of 78 fully sold lots lost money and blamed adverse selection: a Listing turns up under a standing price mostly as the market falls. So the Sell way got a **price-moved test**: buy only while the cheapest Listing left once it's bought is at or above the price the Buy Under was valued at (`post_at`, exported as `postAt`). That's the Flip's "has the price moved" question asked live, since the cheap-stock cutoff can't ask it: a Buy Under buys nothing at its Scan, so no stock is ever under its post price.

Backtest, 87-Scan Beta copy, 40g start, Sell-way lots at the vendor mark:

| Policy | Sell way P&L | Sell buys |
|---|---|---|
| `buyunder_unchecked` | -50.4g on 136.9g spent | 128 |
| `buyunder` (price-moved test) | -50.0g on 70.7g spent | 55 |
| `buyunder` + post at or under the Recent Price (ADR-0041) | -53.4g on 75.9g spent | 57 |

The test halves the buying but not the loss: the crash comes after the buy, not before it (one bought at 5g against an 8.48g market with nothing cheaper up, relisted at 2.2g a week later). The Recent Price check barely bit: these items sold high all week before they fell. The must-pass (reported, not a veto) failed: Troll's Bane Leggings, the player's real winner, wasn't bought in any run.

**Decision: a Buy Under has no Sell way.** An Item Key falls back to its next best way (Vendor, Craft, Disenchant). On the latest Beta Scan that's 154 Buy Unders down to 19 (13 Disenchant, 3 Vendor, 3 Craft). A Craft way's output may still Sell, and a Disenchant way's mats likewise: neither is simulated, so neither is judged here. A cheap Listing a Scan sees is still a Flip to Sell's, with the cutoff and the risk caps.

The Sell way stays in the code behind `buy_under_sell_way` (off, not in config.toml), with `post_at` and the price-moved test (`take_under`), so the `buyunder` and `buyunder_unchecked` policies can grade it again, on Live for one. Bringing it back needs its Sell-way P&L at or over 0 there.
