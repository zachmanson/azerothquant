# Risky rows for Flips to Sell with too few Sale Events

Amends ADR-0037 (#224). A Flip to Sell that passes every check except the Sale Events minimum (`flip_min_sale_events`, 3) is no longer dropped. It comes back on the Shopping List as a **Risky row for too few Sale Events**:

- It must still clear the Flip margin on its last unit, fit the gold and the Budget, and count its Sale Events after the cheap-stock cutoff. 0, 1 or 2 of them at its post price is too few.
- It posts just under the next other Listing once its cheap units are bought, as any Flip to Sell does. There's no cap on that price: whatever it posts at, the most it loses is its cost less the Vendor Price, plus a Deposit.
- It's sized like an ADR-0037 Risky row: no Unsold Loss cap, but within the gold, the Budget and the room, and no more than `risky_max_units` (5) units. If the room drops it, it isn't shown.
- Only Flips to Sell, and only for an Item Key with no other Flip to Sell run. No Flips to Craft, to Disenchant or to Vendor, no Buy Unders, no Loot Alert values, no Prediction buys.
- These rows sit inline, ranked by Profit, and take no place from the rest. They have their own cap, `risky_no_sales_rows` (10), and must make the Minimum Profit. 0 turns them off, as does `risky_max_units` 0 or the risk caps off.
- A held unit of such an Item Key gets a Holdings Sell row at the price a Flip would post at, tagged the same way, when it beats the Vendor Price. Before, Holdings said "no data" or Vendor for what a Risky row had just bought. This row is only shown: what held units are worth to the Stake, Disenchant and Craft is unchanged.
- The Lua row has `risky = true`, `salesSeen` (0, 1 or 2), `nextListing` (the Listing it posts under, which the Addon names rather than working it out from the post price, since the undercut and the player's own Listings change it) and, on the Shopping List, `unsoldLoss`. It has no `days`. The Addon tags it Risky and says "Risky: nobody's been seen buying this yet." (or "only N sales seen"), where the next Listing is, and what it loses if it never sells. Its wait and Per day show "?".
- A buy from one starts a Lot and gets a Flip Grade. grades.toml writes `risky = "noSales"`, so its P&L splits from ADR-0037's Risky rows (`risky = true`).
- The Backtest and the replay (`options_taken`) never take one. `--why-not` says "shown as Risky (no sales)" instead of failing it at Sale Events.

## Why

The 2026-11-07 Live Scan (about 52 h of Observation Windows) gave an empty Shopping List. 7,294 of 7,508 Item Keys stopped at Sale Events. 557 of those had a post price whose net beat the ask by more than 10%: nearly all random-enchant BoE gear, 1 unit each, never seen sold (4827: 16s ask, next Listing 70g). The player wants to see these and take the risk on the cheap ones. Lowering `flip_min_sale_events` isn't the answer: at 1 it let through just one +15s Flip, and it would size normal rows on one Disappearance.

A sticker price (70g on a 16s item) can't be capped well without Sale Events: the Beta price, sibling suffixes and a multiple of the Vendor Price each fail on some of these items. The loss is bounded by the cost anyway, and a row of at most 5 units costs little when the ask is cheap. So the gap is shown, not capped.

## Considered options

- **Lower `flip_min_sale_events`**: turns every thin Sell Rate into a normal row that the Backtest takes and sizes by its room.
- **Cap the post price** (Beta price, sibling suffixes, a Vendor Price multiple): no source covers these items reliably, and the downside doesn't depend on it.
- **Change `_sell_way`**: it feeds Buy Unders, the Loot Alert and the Flips to Disenchant and Craft, which this keeps out. Holdings rows don't go through it.

## Consequences

- No conflict with ADR-0042: this adds a row the Backtest never takes and tunes nothing.
- How these rows do is judged by their Flip Grades, split out by `risky = "noSales"`.
- A held unit with no sales may still be Disenchanted, since Disenchant compares against its unchanged worth.

## Amendment: the post price is capped at a markup over cost (#225)

Live proved the "no cap" call wrong. On 2026-11-07 all 10 of these rows posted at 5x to 437x their buy price under a never-sold sticker (6413: buy 2g 38s, post 80g, +372g claimed). The loss bound held, but the claimed profit was fiction and ranked the rows. The player: "there's a line between hey this is a little risky and just something terrible like this."

- A Risky row for too few Sale Events posts at the lower of its usual price (under the next Listing) and `risky_no_sales_markup` (3) times its run's average unit cost. Profit, the Flip margin and the Minimum Profit all use that price, so a cheap item capped low (4827: 16s, now posted at 48s) can fall out on the Minimum Profit. The row is never dropped for being over the cap.
- Its held units' Risky Sell row in Holdings is capped the same way on their Paid (ADR-0007's average cost of the newest open Lots), when there is one. Units with no Paid (looted, say) keep the uncapped price: there's no cost to anchor to, and the worst case on held units is a Deposit, not gold spent.
- The markup is a sanity line, not a price estimate. The cost is the only number these items have that someone actually accepted. `nextListing` still names the sticker, so the player sees the room above the capped price.
