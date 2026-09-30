# Purchase Lots only from buys the Brain named

Not every Auction House buy is a flip. The player also buys consumables and leveling mats that get drunk or crafted away (#55). Such a buy leaves without a Sold Outcome, so its Lot stays open (ADR-0007), and since a sale closes the oldest open Lot first, later sales of that Item Key (looted units, or real flips) close the used-up Lot at its cost. That skews realized profit, Flip Grades, Paid and FIFO closure for anything that is both used and sold.

So a Purchase not under a Prediction starts a Lot only when the Brain named it as of the Market's last Scan before the Purchase, the same Scan a Flip is matched to (ADR-0023). Named means, at a unit price at or under what was named:

- a **Flip to Sell** or **Flip to Vendor** row of its Item Key on the Shopping List (up to the dearest Listing the row bought),
- a **Flip to Craft** row buying it as an Auction House reagent (up to that reagent's most to pay), or
- a **Buy Under** of its Item Key, or of its Disenchant source group (up to the Buy Under).

There is no quantity cap: buying 40 against a 30-unit row counts all 40. Every other Purchase is **For Use** and starts no Lot, the same as loot: it's out of realized profit, Flip Grades, Paid and FIFO closure. Purchases under a running Prediction are unchanged and always the Prediction's, since Prediction Lots feed Max Loss and Grades.

What each needed Scan named is worked out once, the way the replay does (#80), and frozen in `grades.toml` under `named`, next to `shown` (ADR-0023). One recompute freezes both. A past-Scan recompute skips Paid, which is display-only and the one thing that needs the named sets, so it never needs the Lots it decides. Prediction Lots don't need them either: other Lots never close a Prediction's units, since those before it was written are folded into its held Lot and those after it ended are younger.

## Considered options

- **A hand-kept For Use Item Key list**: potions and mats are sometimes flipped too, and the list goes stale.
- **Such lists with date windows**: the same, with more bookkeeping.
- **Marking single Purchases** For Use by hand: the player won't do it for every buy.
- **Addon-recorded uses**, crafts and consumption closing Lots: the right fix, but it needs in-game probes and reverses "only sales close Lots", so it's its own issue (#112).

## Consequences

- A flip made on the player's own judgment, with no row behind it, counts as For Use: its sales look free and it has no Paid. Accepted to keep it automatic.
- `brain flips` and the replay print how many Purchases were For Use and what they cost, as ADR-0007 counts the Unlinked Outcomes, so a big gap shows. If it's big, #112 is the fix.
- The first `brain recommend` after this ships works out every Scan before a Purchase, which is slow. Later runs read them from `grades.toml`.
- Holdings still recommend on For Use units (a Sell row for held potions stays, and the player ignores it).
