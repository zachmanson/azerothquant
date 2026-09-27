# Post at is priced after what the Shopping List buys, in one pass

Every Sell price is posted just under the cheapest other player's Listing left once the Flips of that Item Key are bought (#62, #64). Until #68 "the Flips" meant every Flip the Scan offered, before the Shopping List was cut down to the gold the player has. With 609g of Flips on offer and 14.7g to spend, Post at assumed walls were bought that never would be: 250366 posted at 34s 99c with other Listings from 12s up still there.

The Shopping List is chosen by profit, profit depends on Post at, and Post at depends on what the Shopping List buys. That loop is broken in one pass: the Shopping List is chosen as before, on the optimistic prices, then a final Valuer removes only the units the list actually buys (Flip to Sell, Flip to Vendor and Flip to Craft reagents) and everything shown at that Scan is repriced against it: held Sell rows, the Flip rows' Post at and profit, and Hold costs and Max Loss. A Flip to Sell that no longer clears the Flip margin once repriced is dropped, and its gold isn't handed to another Flip; it's left for Prediction buys, which already get what the Shopping List doesn't spend. The final Valuer is built after the drops. There is one Sell row per Item Key, so a drop only puts back that Item Key's Listings and can't cascade. What to craft from held reagents and which outlet a Flip to Craft uses stay as the first pass chose them.

At a past Scan (Best Exit Value for Grades and for units held when a Prediction is written) there is no Shopping List to reuse, so that Scan's plain Flips are cut down to the gold the Characters had then, from their latest Character Reads up to that Scan, most profit per gold first as the Shopping List does. Flips to Craft aren't considered there, so a past Scan's Best Exit Value can differ slightly from the one the Recommendation Table showed at that Scan.

## Considered Options

- Settling: re-choose the Shopping List on the repriced numbers until it stops changing. Closer to the best list, but greedy picks can swing back and forth, so it needs an iteration cap, and every round reruns crafting and the outlets. Same trade as ADR-0008: greedy and one step, explainable, close enough.
- Cutting the plain Flips to gold before anything else is valued. Simpler, but Flips to Craft still take gold from the same list afterwards, so the gap shrinks without closing.
- Keeping a repriced Flip that no longer clears the margin and showing its thin or negative profit: honest, but the Shopping List would recommend a losing buy.
- Refilling a dropped Flip's gold with the next pick: a partial settle, with the same problems.
- No Flips at all at past Scans (price against the Listings as they were): simpler, but it gives Best Exit Value two definitions, one for today and one for the past.

## Consequences

- The Shopping List is not always the best one possible under the real prices: a Flip left out on the optimistic numbers might have beaten one that got in. The error is far smaller than pricing against walls nobody buys.
- A dropped Flip's gold can end up unspent when no Prediction buy wants it.
- A Flip cut short by gold now posts under the first Listing it didn't buy, not the one the full Flip would have reached.

Superseded in part by ADR-0011: a Flip to Sell is no longer cut short by gold, since the Shopping List buys it whole or as the best run the gold covers.
