# Held units Wait out Listings a Flip to Sell would buy

Amends ADR-0017 (#151). Holdings are still valued with nothing on the Shopping List bought. But when a Flip to Sell would buy an Item Key's cheapest Listings, its held units no longer post under them. They **Wait**: kept for now, to post once those Listings are gone.

**The rule.** A held Item Key Waits when its `clearing_run` (#108) exists: a run of the cheapest other players' Listings that a Flip to Sell would clear the margin on, room aside, with at least `flip_min_sale_events` Sale Events at the price it posts at, counted only since any stretch of cheap stock began (ADR-0028, ADR-0029, ADR-0033). The units that would Sell at the price after that run is bought (`post_at` with the run taken off, still capped by the dearest Sale Event and the Merchant Cost, within the room, beating the Vendor Price less expected deposits) become one Wait row at that price, with that Sell's profit. The rest go as they would anyway: the tail a slow seller can't sell in time is Vendored, and bound units always are.

So `worth`, Best Exit Value, a Holdings Craft's or Disenchant's marginal and the Hold caps count waiting units at what they'll bring once the cheap Listings go, not at the lowball.

**Where it doesn't apply.** Under a pricer (the replay's Brain without own-Market Sell Rate, ADR-0015) there's no Sell Rate to judge a Flip by, so nothing Waits. A Valuer that has already bought some of the Item Key (the #108 Checks value a way out with the run bought) has no run left to wait out. Auctionator and the emulated TSM never price through Holdings rows, so they're unchanged.

**Output.** `Action.WAIT` ("Wait") on a Holdings row, with `price` and `profit` like a Sell. The Addon says "Keep them for now: someone's selling these cheap. Check again after the next Scan." and the tooltip `AQ: Wait 3, then post @ 9s 99c`. It's not folded away and has no Post button. ROI is shown on it (after the cut, as for a Sell), but never the hint to sell now. The replay counts Wait units as kept, like a Hold.

## Why

Probe P4 (independent review, finding 3): 20 Sale Events and 20 Listed at 1000c, plus one Listing at 300c, said Sell 5 at 299c, and with a Vendor Price over 284c, Vendor all 5. Vendor can't be undone, and guildies follow the table on day 1. Meanwhile the Shopping List says to buy that same 300c Listing as a Flip. ADR-0017 called a held unit priced under a Flip's Post at cosmetic. It isn't when it turns into a dump or a Vendor.

The clearing run is the "Sale Events at or above the post" reference the triage named. It is demand, not Listings, so it works in a thin market. And it fails safe in a crash: once cheap stock has been up across Scans and watched, the old sales stop counting, there's no run, and held units undercut (and Vendor, if that's right) as before.

## Considered Options

- **Floor at Fair Value's outlier rule** (cheapest ask under half the median of the cheapest 15% of units): already in the model, but in a thin market the slice is the lowball itself. With 6 units up, a 1-unit lowball is never an outlier, and thin markets are where gear lowballs happen.
- **The next-cheapest ask as the reference**: literally "one Listing", but two lowballs beat it.
- **A multi-Scan Fair Value**: new machinery, too much before Live (Nov 4).
- **Post held units above the lowball** (price against the book without the Listings a Flip would buy): breaks "never post above a live ask", and the unit wouldn't sell before the lowball goes anyway.
- **Only stop the Vendor, still Sell at 299c**: a sale at 30% of the price loses nearly as much as a Vendor.
- **Reuse Hold**: Hold means held under a Prediction (ADR-0006), and the Addon, `_hold` and the glossary all read it that way.

## Consequences

- Waits are more common than lowballs: any Listing cheap enough to Flip, say 20% under, makes held units Wait. Posting under a Listing that's about to be flipped is dumping too.
- A Wait is a call for one Scan. If the cheap Listings are still there next time and still flippable, the units still Wait. If nobody buys them, the cheap-stock cutoff eventually ends the run and they post under them.
- Best Exit Value and the Flip Grades from here on value lowballed held units higher. Grades frozen before this keep their numbers.
- Replay and Backtest numbers before and after aren't comparable on Markets with held units under a flippable Listing.
- One Flip to Sell per Item Key now costs a `clearing_run` for every held Item Key with other players' Listings, once per pass (cached per Valuer). Watch `brain bench`.
