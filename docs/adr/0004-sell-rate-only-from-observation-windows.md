# Sell Rate counts only Observation Windows

Scans only happen while the player stands at an Auction House (ADR-0003), at most one every ~15 min per Market, so the time between Scans ranges from 15 minutes to days. Over a long gap every Listing that was posted and sold in between is never seen, so sales are undercounted while the hours still pass. We therefore build Sell Rate only from Observation Windows: gaps between consecutive Scans of a Market no longer than a configured cap (default 1 h). Both the sales and the hours come from those windows, so the rate isn't biased by long gaps; longer gaps still update Listing lifetimes but add nothing to Sell Rate. Within a window, a Disappearance can only be a Probable Sale if its time-left bucket rules out expiry over that gap. The routine this assumes is a Scan on arriving at the AH and a second one 15+ min later before leaving.

## Considered Options

- Count every gap: simplest and uses all data, but long gaps pull Sell Rate down in proportion to how rarely the player scans.
- Count Partial Sales from every gap and Probable Sales only from short ones: keeps more certain sales, but the two halves would need different denominators, so the rate wouldn't mean one thing.

## Consequences

- Observation Windows cluster in the hours the player plays, usually evening prime time, when buying is heaviest. Scaling those hours to "per day" likely overstates Sell Rate. Accepted for now; revisit if Lots sell consistently slower than predicted.
- Each Sell Rate keeps its evidence (Observation Window hours for the Market, sale events for the Item Key) so the Decision Engine can discount thin data later (#8).
