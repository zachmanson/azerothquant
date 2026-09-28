# The Shopping List shows options, each sized on its own within a Budget

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

The cut keeps a Flip to Sell or Flip to Vendor that's in the top `shopping_list_rows` (50) on any of Profit, Per click, Per day or ROI, ties going to the most profit. The list can reach four times that, but the four usually overlap a lot. The Flips to Craft are still cut by Profit alone, and their tab is unchanged.

Not changed: how each option is sized (profit per gold within the Budget), the Sale Horizon (7 days stays "how long I'll wait": risk is ranked by Per day, not by a shorter horizon), and the replay, which doesn't grade these measures. Replay's `_taken` still walks the list in profit order, so a longer list can change its numbers. The Addon shows sortable Per click, Per day and ROI columns on the Shopping List tab, opens it sorted by Profit, and sums a row up in its tooltip, e.g. `12 Listings + 3 posts, sells in ~2.5 days`.
