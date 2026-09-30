# Pool Sibling demand, not price, for held units only

On Forever, 77% of Item Keys carry a random suffix: the Beta archive has 7,284 Item Keys over 354 itemIDs, about 20 suffixes each. Each suffix sees 0-1 Sale Events, so a held green gets a Sell Rate of 0 and goes to Vendor or Disenchant even when its item sells (#58).

So a held unit's Sell Rate adds its Siblings' Sale Events (the other suffixes of its itemID in the Market) to its own, each at `suffix_pool_weight` (0.5 by default) of a Sale Event and of its units. Only Sibling Sale Events priced at or above the held unit's post price count, the same test a Flip uses on its own Sale Events (#107): a buyer of a cheap Eagle says nothing about a Monkey posted dearer. The #41 cap on the post price is the dearest of its own and its Siblings' Sale Events, worked out first, since which Sibling Sale Events count depends on it.

Demand is pooled, never price. Price varies about 8x across suffixes of one item (IQR 4x-12x), so Fair Value stays per Item Key, and with no Listing of the Item Key itself to undercut there is still no Sell price.

Only held units pool. Flips to Sell, Flip to Craft outputs, Buy Under, Max Loss and the minimum of Sale Events for a Flip keep per-Item Key evidence: a Flip spends gold on the estimate, while a held unit's gold is already spent and the alternative is a Vendor Price.

## Considered options

- **Full pooling** (every suffix one Sell Rate): overstates the demand for any one suffix about 20-fold.
- **Stat-family groups** (Monkey with Monkey-like suffixes): needs a suffix-stats table nobody maintains, for evidence that's still thin.
- **A weight that fades as own evidence builds**, or a threshold below which to fall back to Siblings: more knobs with no data yet to tune them. A fixed weight is easy to check and to switch off (`suffix_pool_weight = 0` gives the old output).

## Consequences

- A Holdings row carries how many Sibling Sale Events it counted (`siblingSales`), and its tooltip reads `Sales N (+M other suffixes)`.
- Best Exit Value of held units, and so Prediction grades, counts Siblings too.
