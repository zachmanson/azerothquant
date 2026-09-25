# Store raw Listing lifetimes, compact after 60 days

The Brain stores each Listing once, with the first and last Scan it was seen in, not a row per Scan. Raw Listings are kept for 60 days and then compacted into daily per-Item-Key summaries that are kept forever. We keep raw data because Fair Value and Sell Rate formulas will change, and only raw Listings let us recompute history under a new formula. Lifetimes (not per-Scan rows) keep storage in the low hundreds of MB, and "last seen at Scan N, gone at N+1" is exactly the event that Sell Rate is built on.

The full Scan gives no auction ID or seller, so Listings are matched between Scans by Item Key and unit buyout, with identical Listings treated as interchangeable. A Listing can't match one whose time-left bucket went up. When more than one matching fits, we pick the one with the fewest new Listings. Each Partial Sale (a drop in quantity) is stored as its own event on the Listing, because it is the only sale the data proves for certain.

## Considered Options

- Summarize at import and discard raw rows: smallest, but locks every past Scan into whatever formula existed at import time.
- One row per Listing per Scan: simplest to write, but grows several times faster for no extra information.
