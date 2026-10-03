# A buy that takes the cheapest Listings counts demand only since they showed up

A Flip to Sell's Sell Rate at its post price counts every Sale Event at or above that price in the 14-day range (ADR-0004, #107). After a crash, nearly all of those Sale Events are from before the cheap supply showed up. Once it did, nobody paid the old price any more, but the Brain still suggested buying the whole cheap wall and reposting at the old price: 4807 Lesser Magic Essence at 47c, posted at 3.21s, "sells in 1.1 days" (#132). Buying the wall doesn't bring the old price back either. The sellers who posted at 20c will just post more at 20c.

So a buy that **takes the cheapest other players' Listings and posts above them** stops counting demand from before those Listings showed up, once enough time has passed to judge.

- **Cutoff**: the earliest Scan any other player's Listing under the post price was first seen in. The post price sits just under the cheapest other Listing left after the run, so these are exactly the Listings the run buys. The player's own Listings don't count. Each candidate run gets its own cutoff.
- **Trigger**: the Sale Events at or above the post price per Observation Window hour before the cutoff, times the Observation Window hours after it. Raw counts, with no Sell Rate Prior, and Sale Events rather than units. If that comes to at least `flip_min_sale_events` (3), the cut applies. Otherwise the whole range counts, as before.
- **When cut**: only the Sale Events after the cutoff count, over only the Observation Window hours after it. The Flip priors and the minimum of Sale Events then apply to what's left as usual. Buyers still sweeping through the cheap stock up to the post price let the Flip pass on their own.

This works because the Forever Auction House sells cheapest first. While old-price buyers are still around, cheap stock doesn't sit. A thick Item Key (LME, about 200 units a day) gets cut within an hour or two of watching. A thin one (6 Sale Events in 14 days) gets about a week, because its history can't tell a crash from a quiet week. A Flip to Sell whose Listings were first seen in the latest Scan has no hours after its cutoff, so it expects nothing and is never cut. No new setting is needed.

It covers the Flip to Sell, the resale a Hold buy's Max Loss assumes (cutoff from the Listings bought so far) and `brain recommend --why-not`, which says when cheaper Listings went up and how few Sale Events have come since. It does **not** cover a Flip to Craft's output or a Buy Under's Sell way. They buy nothing of that Item Key and post under the cheapest Listing, cheap stock included, so old demand at a lower price is fair. Nor does it cover held units, whose gold is already spent, or the Beta Sell Rate, which is another Market's supply. `BetaSellRate.pooled` pools onto whatever Live demand the cut leaves.

## Considered options

- **A hard cutoff with no trigger**: kills every Flip to Sell on a Listing new this Scan, since 0 Sale Events after it fails the minimum.
- **A one-window grace**: kills those on thin Item Keys, which can't show a sale in one window.
- **Recency weighting**: needs a decay rate tuned and still lags a crash.
- **A share-of-daily-sales cap**: shrinks the bet but doesn't fix it.

## Consequences

- A Sell Rate carries each Sale Event's time and its Observation Windows, so it can be cut at any Scan.
- How fast a cut lands depends on Observation Window hours, not wall-clock hours. Scans more than an hour apart add no hours after the cutoff, so a player who scans rarely waits longer for the cut.
- Flip Grades already frozen are unaffected (ADR-0023).
