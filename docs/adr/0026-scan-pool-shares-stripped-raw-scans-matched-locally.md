# The Scan Pool shares stripped raw Scans, and each Brain matches them itself

Sell Rate comes only from Observation Windows (ADR-0004), and one player Scanning while they're online leaves most of the day uncovered. A Scan Pool lets a group of players fill each other's gaps (#117). Nobody publishes Scan-level Forever data: Booty Bay Broker, AHledger and TheWoWDB are crowdsourced the same way and publish only per-item aggregates, which can't show a Disappearance (#82 comment, 2026-09-30).

The pool holds **raw Scans, stripped of whatever identifies the player**, not a derived history. Each Brain downloads Pooled Scans into its own Archive and matches them itself, like its own Scans. That keeps ADR-0005 true for pooled data: a new matching rule or Sell Rate formula replays over every Pooled Scan too. It also means no Brain has to trust another's interpretation. A claimed Sale Event can't be checked, but a raw Scan can be checked against the Scans around it.

Pooled Scans arrive late: a friend's Scan from an hour ago often lands after the player's own newer one. The importer used to reject any Scan older than its Market's latest, so a late Scan now **re-matches the Market's tail**. That Market's history is rewound to just before the late Scan and its Scans from there on are re-imported from the Archive in time order. Listings first seen in that tail are deleted, and a Listing that spans it gets back its quantity (from its Partial Sales) and time-left bucket (from a record of each bucket drop) as of the Scan before it (#118), and its own flag (from a record of the Scan where it turned own, #119). A Scan more than `pool_rematch_hours` (48) older than the Market's latest is archived but waits for the next `brain rebuild`, so a stale download can't set off a huge re-match. The Brain pulls the pool before importing its own Scan, so most Scans arrive in order anyway.

It runs on Cloudflare R2 behind a small Worker, which holds the keys and the index and does cheap shape checks. It is off by default. Only a trusted group, each member with their own key, can push and pull, and a revoked key's Scans are rolled back from every Brain on its next sync.

## Considered Options

- **Pool derived history** (Listing lifetimes, Sale Events): smaller, but it bakes one Brain's matching into everyone's data. A fake Sale Event can't be checked, and a formula change can't be replayed.
- **Only accept Pooled Scans newer than the player's latest**: nothing to build, but it drops nearly every Pooled Scan, and the ones that fill the gaps between the player's own Scans are the whole point.
- **A separate pooled-only history**: no re-matching, but that gives two Sell Rates to reconcile.
- **Supabase or a VPS**: Supabase's 5 GB egress cap and idle pausing don't fit six-MB Scans fanned out to every member, and a VPS is a box to maintain. R2's egress is free.
- **Outside aggregates** (Booty Bay Broker, AHledger, TheWoWDB): fine as a price prior or a sanity check (#82), but they can't give Sell Rate.

## Consequences

- `own` leaves a Listing's match key (ADR-0002 amendment). Otherwise every switch between the player's Scan and a Pooled Scan would look like a Disappearance plus a new Listing on the player's own auctions.
- Pooled Scans are stored as downloaded, which is already stripped, not as the Addon wrote them (ADR-0005 amendment).
- The Addon stamps Scans with the server clock (`GetServerTime()`), so everyone's Scans order on one clock.
- A truncated Scan is the likeliest poison, and it isn't malicious: a disconnect mid-Scan makes thousands of fake Disappearances. So a Pooled Scan with fewer Listings than `pool_min_completeness` (0.8) of its Market's recent median is rejected.
- Cross-checks between uploaders are left until the pool opens beyond a trusted group: down-weighting a Disappearance only one uploader's Scan supports, and reputation.
- A re-match costs time in the loop (#116). The pull-before-import order and the 48 h cap keep it rare and short.
