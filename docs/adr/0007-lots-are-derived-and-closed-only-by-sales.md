# Lots are derived, pooled per realm and faction, and closed only by sales

Grading a Prediction (ADR-0006) needs Lots: which units it covers, what they cost and what they fetched. The Brain sees Purchases and Sold Outcomes by mail, and bag contents in Character Reads, but not vendor sales, disenchanting, crafting or mail between the player's own Characters. So a Lot closes only on a Sold Outcome, oldest Lot first, and a unit that leaves any other way stays open and is valued at its Best Exit Value when the Prediction is graded. Lots are pooled per realm and faction, the same scope as pooled gold. There are only two kinds for now: one per Purchase, and the units held when a Prediction is written (costed at that day's Best Exit Value, which ends and absorbs any open Lots of its Item Keys). Lots aren't stored. They are recomputed from Purchases, Outcomes, `predictions.toml` and Character Reads whenever they're needed, and past Best Exit Values (written day, grading moment) are recomputed as of that moment from history.

## Considered Options

- Close a vanished unit at its Vendor Price: a known floor, but it grades a Prediction on mats the player crafted with as if they were sold for pennies.
- Infer every exit (and loot, crafting and merchant buys as new Lots) from changes between Character Reads: posting, taking mail and moving items between Characters also change bag counts, so this is guesswork that `brain rebuild` would have to repeat exactly.
- Lots per Character: an item bought on one Character and sold on another would never close.
- A `lot` table filled at import: `predictions.toml` is edited by hand, and every edit would leave it stale until a rebuild. Tens to hundreds of Purchases a year are cheap to replay.
- Snapshot the written-day Best Exit Value when the Brain first sees a Prediction: lost on rebuild (ADR-0005), and wrong for a Prediction written with a past date.

## Consequences

- A Sold Outcome's mail has no Item Key, so it is linked by item name to own Listings and mail that carried the item. One that can't be linked closes nothing and is counted, so a gap shows. If that count isn't zero in practice, the Addon can record item names in Character Reads.
- Units used rather than sold are graded at market value, not what they actually earned. That's neutral rather than biased either way, and grading never has to reconcile bag counts.
- The Decision Engine needs an "as of" moment instead of always reading the latest Scan.
- A Grade is fixed at its grading moment, so the record and the brake don't move with later prices.
