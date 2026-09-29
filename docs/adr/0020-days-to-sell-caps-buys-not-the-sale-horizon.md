# Days to Sell caps buys, not the Sale Horizon

Shopping List rows were buying 170-205 units: a week of Sell Rate at the post price, since a Flip's room is what sells within the Sale Horizon (#109). Some players would rather flip smaller and faster without that being forced on everyone. Shortening `sale_horizon_days` would do it, but the Sale Horizon also decides which held units are worth Selling (the rest Vendor), Best Exit Value, Craft and Disenchant room, when a Prediction's Grade comes due, and the window the replay grades over (ADR-0015). A 2-day horizon would Vendor held units that sell on day 3 and make replay grades incomparable with earlier checkpoints (#83).

So Days to Sell is a separate, per-Market player setting, carried in the Character Read like the Budget (#86). It only caps buys that exit through Sell: a Flip to Sell's run, a Flip to Craft's Sell room, and a Buy Under's Sell way units, each after the held units ahead of them. It's clamped to the Sale Horizon and defaults to it. Flip to Vendor sells at once and Prediction buys are a deliberate hold, so neither is capped.

This amends ADR-0017, which kept 7 days as "how long I'll wait" and left risk to the Per day ranking. That still holds for the Sale Horizon; ranking by Per day just can't shrink a row's quantity, and this does.

## Consequences

- The replay's Brain policy buys with the Days to Sell set at each replayed Scan (as it reads the Budget), but grades over the Sale Horizon, so it can show whether shorter buys earn more. Scans from before the setting use the Sale Horizon.
