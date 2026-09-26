# Sell Rate counts only Observation Windows

Scans only happen while the player stands at an Auction House (ADR-0003), at most one every ~15 min per Market, so the time between Scans ranges from 15 minutes to days. Over a long gap every Listing that was posted and sold in between is never seen, so sales are undercounted while the hours still pass. We therefore build Sell Rate only from Observation Windows: gaps between consecutive Scans of a Market no longer than a configured cap (default 1 h). Both the sales and the hours come from those windows, so the rate isn't biased by long gaps; longer gaps still update Listing lifetimes but add nothing to Sell Rate. Within a window, a Disappearance can only be a Probable Sale if its time-left bucket rules out expiry over that gap. The routine this assumes is a Scan on arriving at the AH and a second one 15+ min later before leaving.

## Considered Options

- Count every gap: simplest and uses all data, but long gaps pull Sell Rate down in proportion to how rarely the player scans.
- Count Partial Sales from every gap and Probable Sales only from short ones: keeps more certain sales, but the two halves would need different denominators, so the rate wouldn't mean one thing.

## Consequences

- Observation Windows cluster in the hours the player plays, usually evening prime time, when buying is heaviest. Scaling those hours to "per day" likely overstates Sell Rate. Accepted for now; revisit if Lots sell consistently slower than predicted.
- Each Sell Rate keeps its evidence (Observation Window hours for the Market, sale events for the Item Key) so the Decision Engine can discount thin data. It does so with the Sell Rate Prior in `brain recommend`, leaving Sell Rate itself the raw measurement (#25).
- Sell Rate counts units, and Sale Event sizes are heavy-tailed, so one bulk buyer on thin evidence can make an Item Key read as a fast seller that the hours-based prior alone can't fix. The Decision Engine therefore splits Sell Rate into Sale Events per day times average Sale Event size, and shrinks the average size toward a typical one with the Sale Size Prior (#24). It uses the mean rather than the median because expected units sold is events times mean size: bulk buyers are real demand once there are enough Sale Events to see how often they come.
- A Disappearance that pairs with a new Listing in the same window is a Repost, not a sale, and pairs are taken wherever the data allows (#13). Some real sales will be paired with an unrelated post by coincidence, so this pulls Sell Rate low, against the prime-time bias above. Each Item Key's evidence also counts the pairs that failed only because the new Listing was priced higher, as a baseline for how often coincidences happen, in case we later switch to weighting instead.
