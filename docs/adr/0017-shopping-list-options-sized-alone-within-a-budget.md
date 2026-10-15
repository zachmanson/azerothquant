# The Shopping List shows options, each sized on its own within a Budget

Amended by ADR-0034 (#170): each option is also sized within two risk caps, its Unsold Loss and the gold tied up in posts, each a share of the Stake.

The Shopping List used to be one basket: a greedy fill of every Flip by profit per gold until the pooled gold ran out (ADR-0010, ADR-0011). After playing with it, the player raised two problems (#86):

1. They aren't always willing to spend all their gold on the Auction House.
2. The basket put one big, profitable Flip at the top and then a long tail of Flips worth a few copper or silver. Once the top pick had taken the gold, other big Flips fell off the list, even though the player might have picked one of them instead. They want to see the best options and choose. Thin margins aren't worth their time: farming mobs pays that.

**Budget.** The Recommendation Table has a Budget box, saved per Market (realm and faction) in `AzerothQuantDB.budgets`. Each Character Read carries its Market's Budget (`budget`, copper), so it's archived and survives `brain rebuild`. The Market's latest Character Read says what the Budget is, and a blank box (nil) means all the gold. The Brain sizes within `min(pooled gold, Budget)`. The Addon folds away options that cost more than the Budget at once, and the Brain re-sizes them at the next /reload.

**Options.** Each Item Key's Flip to Sell, each Item Key's Flip to Vendor and each recipe's Flips to Craft is one option, sized as if it were the only buy:

- A Flip to Sell is the most profitable run that fits (ADR-0011's run choice stands).
- A Flip to Vendor is the cheapest units that fit.
- A Flip to Craft is the greedy loop over that recipe alone, with fresh reagent sources and a fresh outlet.

Each option is priced after only its own buys. They're sorted by profit and cut to `shopping_list_rows` (50 by default). There is no ranking by profit per gold and no minimum total profit beyond each Flip's own margin.

**Nothing is assumed bought.** Holdings, Craft Actions and Best Exit Value (at past Scans too) are valued with nothing on the Shopping List bought. So:

- A held unit is posted under the cheapest Listing even when a Flip to Sell of that Item Key would buy it.
- A held reagent a Flip to Craft would use keeps its Holdings row (the craft row still lists it under Use).
- A Sub-craft's leftovers from a Flip to Craft aren't Holdings.

ADR-0010's one-pass repricing (`_buy_what_fits`) is gone.

**Prediction buys** spend up to `min(gold, Budget)` within the ADR-0006 caps, which stay shares of the pooled gold. They no longer get only what the Shopping List leaves.

**Replay (#80).** The Brain policy takes the options in profit order while they fit the gold left, skipping any that buys, uses or makes an Item Key one already taken does. A taken Flip to Craft's held reagents come off the least profitable Holdings rows of their Item Key. The Prediction buys then get what's left.

## Considered Options

- **Keep the basket and add a Budget**: fixes the first problem only.
- **Also mark a combined pick** (the greedy basket) among the independent rows: more to read, and the player said they'd rather choose.
- **A minimum total profit per row** (say 1g): the player asked for the top 50 by profit instead, which drops the thin tail when there's enough else.
- **Holdings priced after the shown Flips of their Item Key**: closer to what happens if the player takes that Flip, but Holdings would then depend on a choice not made yet.

## Consequences

- The table no longer says what to buy together. Two options can compete for the same asks, held reagents or Sell room, and each assumes it's alone.
- A held unit's Sell price can sit under a Flip to Sell's Post at for the same Item Key. If the player takes the Flip, they post both at the Flip's price.
- A Flip to Craft per recipe runs its own greedy loop, and several can walk the same Sub-craft chains. Watch `brain recommend` speed on real data.
- Grades frozen before this keep their numbers. Later ones value held units with nothing bought.

## Amendment: Flips to Craft get their own cap and tab (#87)

With one cut, Flips to Craft (often tens of silver) fell off a busy Scan's list behind big Flips to Sell, though the player wants to see them. Now the Flips to Sell and to Vendor are sorted by profit and cut to `shopping_list_rows` (50), and the Flips to Craft apart to `craft_list_rows` (25). `shopping` stays one list, the two cuts together, most profit first. The Addon shows the Flips to Craft (the rows with `buys`) in their own **Flips to Craft** tab after the Shopping List, with the same columns. Each tab folds its own options over the Budget.

Replay's `_taken` is unchanged: it goes through the (now longer) list in profit order while the gold lasts, so it grades what the player is shown. Replay numbers from before this change aren't comparable to later ones, since up to 75 options can now be taken.

## Amendment: the cut keeps the top options by clicks and wait too (#98)

The player would rather buy 2 staffs for 10g than 400 potions for 22g: the potions take far more clicks, and have to sell. Each Shopping List row (Flips to Sell and Flips to Vendor) now carries `listings` (the Listings it buys, counted before same-price Listings are merged), `posts` (stacks posted, at the usual Sale Event size; none for a Flip to Vendor) and `days` (until its last unit sells, behind the unbound held units; none for a Flip to Vendor, which sells now). From them and Profit and Cost come **Per click**, **Per day** and ROI.

The cut keeps a Flip to Sell or Flip to Vendor that's in the top `shopping_list_rows` (50) on any of Profit, Per click, Per day or ROI, ties going to the most profit. Per day ranks the Flips to Sell alone: every Flip to Vendor ties there at "now", and 50 of them would crowd every Flip to Sell out. The list can reach four times that, but the four usually overlap a lot. The Flips to Craft are still cut by Profit alone, and their tab is unchanged.

Not changed: how each option is sized (profit per gold within the Budget), the Sale Horizon (7 days stays "how long I'll wait": risk is ranked by Per day, not by a shorter horizon), and the replay, which doesn't grade these measures. Replay's `_taken` takes only the top `shopping_list_rows` Flips to Sell and to Vendor by Profit, so the longer list leaves its numbers as they were and comparable across the checkpoints (#83). The Addon shows sortable Per click, Per day and ROI columns on the Shopping List tab, opens it sorted by Profit until the player clicks another sort, which is saved per tab in `AzerothQuantDB.recommendationSorts`, and sums a row up in its tooltip, e.g. `12 Listings + 3 posts, sells in ~2.5 days`.

## Amendment: the fold runs on the gold left once a row is marked Bought (#97)

Options are still sized alone, so buying one doesn't re-size the rest, but the player's gold does go down. Once the player marks a buy-side row **Bought** (right-click in the Recommendation Table), the Shopping List and Flips to Craft tabs fold the options that cost more than the **gold left**: the lesser of the Budget less what the marks spent and the gold on hand (all the gold on hand with no Budget set). A manual mark spends the row's Cost. The fold only hides options, never re-sizes one, and never hides a marked row. With nothing marked it's the Budget, as before. Re-sizing is still the next Brain run's job.

## Amendment: Flips to Disenchant: one option per Disenchant source group, own tab (#89)

A **Flip to Disenchant** buys other players' Listings of a Disenchant source group's items on the current Scan, Disenchants them, and takes the mats' way out. It is sized alone within the Budget like any option, and nothing else assumes it bought.

**Per group, not per item.** Every item in a group yields the same expected mats, so buying five of one group fills the same mats' Sell room. Sized apart, each item's option would count on room the others take. One greedy loop per group, like a recipe's Flips to Craft: take the cheapest Listing left, value one more Disenchant's expected mats at the margin (held mats take the room first, as in ADR-0018, then the option's own earlier Disenchants), and buy it if that, less the effort of buying a unit that doesn't stack, clears the Flip margin on its buyout and fits the gold left. Stop at the first Listing that doesn't. The Disenchanter is the group's: a Character whose skill covers its highest item level. With none, there's no option.

**Only where Disenchant is best.** A Listing is a candidate only if Disenchant is its item's best way out for one unit. Otherwise the tab would show a worse alternative to a Flip to Sell or Vendor of the same Listing, and the two would compete for the same buy.

**No Craft chaining.** A mat that feeds a Craft is valued by its way out, which already gives it the Craft's credit, with the Flip margin charged once, as in a Buy Under. The option never buys the Craft's other reagents: once the mats are held, the Holdings Craft Action takes over. One gap: a Craft way's room doesn't shrink as the option's own Disenchants add mats, so a big option can overcount it.

**Output.** The rows are cut by Profit to `disenchant_list_rows` (10) and merged into the one `shopping` list, most profit first, as Flips to Craft are (#87). A row's `disenchant` field (its group and the Listings it buys) marks it, as `buys` marks a craft row. The Addon shows them in a **Flips to Disenchant** tab after Flips to Craft, labelled by group, with Way out, Listings, Profit and Cost, and the Listings bought in the tooltip. It folds over the Budget like the others. #55's named set names each Item Key it bought, up to its dearest Listing of that Item Key, but not the group, whose Buy Under names it at the standing price.

**Replay.** It takes a Flip to Disenchant like any option, in profit order while the gold lasts, and skips one that buys or makes an Item Key an option already taken does (its expected mats count as made). Its units are held to the horizon, valued at their Best Exit Value, which is their Disenchant worth then. It gets no Flip Grade: only Flips to Sell are graded.
