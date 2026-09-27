# One Sale Event per Item Key per Observation Window

A Sale Event used to be one Partial Sale or one Probable Sale: one Listing's drop between two Scans. Units that don't stack are one Listing each, so a single buyer sweeping them showed up as one Sale Event per unit. Recipe: Minor Cleric's Elixir (250366) had 117 Sale Events that were really two bulk Disappearances in two windows (69 at 1s swept, 47 at 49s cancelled, #72). The Sale Size Prior only shrinks an Item Key's average Sale Event size, and 117 events of 1 unit each is already "typical", so it couldn't tell one buyer from 117, and the Brain said buy 90.

A Sale Event is now every Partial Sale and Probable Sale of one Item Key whose Observation Window ends at the same Scan, whatever their prices. Its size is the total units, and its price is the dearest unit, so Max Sale Price doesn't move. This applies to every Item Key, stacking or not. Sell Rate (units per day) doesn't change; only the event count does, which lets the Sale Size Prior shrink a one-buyer sweep and makes `flip_min_sale_events` (still 3) mean sales seen in 3 separate windows. `SaleEvent` drops `own` and `kind`: nothing read them, and a merged event can mix both.

Replayed at the Scan of 1790537588, 250366 goes from 117 Sale Events to 3 and its Flip room (units that should sell within the Sale Horizon under the Flip priors) from 701 to 274.

## Considered Options

- Merge only Listings at the same price: a buyer on Forever takes the cheapest units across price points, so one sweep still splits into several events.
- Merge only Item Keys that don't stack: "doesn't stack" is only guessed from how items get listed, and a buyer sweeping stacks has the same shape. One rule is simpler.

## Consequences

- Two unrelated buyers in one window count as one Sale Event. That undercounts demand, which is the safe direction for a Flip.
- The Market's usual Sale Event size (the Sale Size Prior's typical size) gets bigger. It's still capped by the Item Key's usual Listing quantity, so non-stacking items still shrink toward 1.
- A cancel relisted one Scan too late for Repost pairing still counts as sales (#74); this only fixes how they're counted.
