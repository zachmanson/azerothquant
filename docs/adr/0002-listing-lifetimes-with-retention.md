# Store raw Listing lifetimes, compact after 60 days

> The retention half (compacting after 60 days) is superseded by ADR-0005. The Listing lifetime model stands.

The Brain stores each Listing once, with the first and last Scan it was seen in, not a row per Scan. Raw Listings are kept for 60 days and then compacted into daily per-Item-Key summaries that are kept forever. We keep raw data because Fair Value and Sell Rate formulas will change, and only raw Listings let us recompute history under a new formula. Lifetimes (not per-Scan rows) keep storage in the low hundreds of MB, and "last seen at Scan N, gone at N+1" is exactly the event that Sell Rate is built on.

The full Scan gives no auction ID or seller, so Listings are matched between Scans by Item Key, unit buyout and an own-auction flag (the only seller the game shows is the player), with identical Listings treated as interchangeable. A Listing can't match one whose time-left bucket went up, or one whose bucket could not have lasted the time between the two Scans. When more than one matching fits, we pick the one with the fewest new Listings, then the one with the fewest units counted as Partial Sales, so a sale is only claimed when nothing else explains the data as well. Each Partial Sale (a drop in quantity) is stored as its own event on the Listing, because it is the only sale the data proves for certain.

## Considered Options

- Summarize at import and discard raw rows: smallest, but locks every past Scan into whatever formula existed at import time.
- One row per Listing per Scan: simplest to write, but grows several times faster for no extra information.

## Amendment: own leaves the match key (#117)

Listings are now matched by Item Key and unit buyout only. A Pooled Scan (ADR-0026) shows nothing as own, so with own in the key every switch between the player's Scan and a Pooled Scan would look like a Disappearance plus a new Listing on the player's own auctions. A Listing is own once any of the player's own Scans shows it as own, and stays own. The one cost is when the player and someone else both post the same Item Key at the same unit buyout: the own flag may land on the other Listing. Identical Listings were already interchangeable, so that's rare and harmless.
