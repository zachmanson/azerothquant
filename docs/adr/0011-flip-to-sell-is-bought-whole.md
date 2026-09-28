# A Flip to Sell is bought whole, or as the best run the gold covers

The Shopping List used to rank a Flip to Sell one unit at a time, most profit per gold first. But a unit's profit isn't its own: it's priced under the Listing left once the whole run is bought, so it only exists if the rest of the run is bought too. On real data (#70) almost every Flip to Sell clears the Flip margin only as its full run: 51 of 54 Item Keys had no shorter run that did. The cheap units of three big runs (250366, 2555, 4233) took the gold, each run was cut short, ADR-0010 repriced and dropped all three, and 1g 43s of 13g 42s was spent.

The Shopping List now ranks each Item Key's Flip to Sell as one pick, by the profit per gold of its whole run. When its turn comes it buys the whole run if the gold left covers it; otherwise the most profitable run of the cheapest Listings the gold left covers whose every unit still clears the Flip margin (under the Listing left after that run); otherwise nothing. On the same data the Shopping List spends 13g 42s of 13g 42s, 250366 bought whole (84 units, 10g 34s, 17g 58s profit). A longer run that clears the margin never posts lower and every unit it adds pays, so the most profitable run that fits is always the longest one that fits. Flips to Vendor stay per unit, since each unit under the Vendor Price pays on its own, and Flips to Craft were already bought whole or not at all.

ADR-0010's one-pass repricing stands. Since a kept Flip to Sell is already priced on the run it buys, and other buys of the same Item Key only take dearer Listings, its drop step should no longer fire; it stays as a safety net. Past Scans' Best Exit Value uses the same rule.

## Considered Options

- Keep ranking per unit and hand a dropped Flip's gold to the next pick: a partial settle, which ADR-0010 rejected, and the next pick is often another run that gets cut short.
- Whole runs only, skipped when they don't fit: simpler, but misses a shorter run that does pay (1 unit of 4566:12919 instead of 3).
- Every margin-clearing run as its own candidate, one per Item Key: a short run with a better ratio blocks a far more profitable long one (250988: 1 unit at 0.42 per gold ahead of 6 units at 0.34).

## Consequences

- Greedy by ratio over indivisible picks is not the best possible fill (a knapsack); a big run can still be skipped for smaller ones that together profit less. Same trade as ADR-0008: one step, explainable, close enough.
- A shorter run is ranked by its whole run's ratio, not its own.

Superseded in part by ADR-0017 (#86): the run choice stands (the most profitable run that fits, now within the Budget), but there's no greedy fill by profit per gold: each Flip to Sell is its own option.
