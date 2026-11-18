# The Neutral list buys Neutral Listings and values every exit at home

Reverses #40's won't-do (#231). The player now trades at Everlook, so a realm's Neutral Auction House gets a Shopping List of its own: Listings there worth buying to carry home and sell at the Character's own faction's Auction House.

- **Direction: Neutral to home only.** Home is the faction of the Character standing at the Neutral house. Selling at a Neutral house (and so home to Neutral) is out: its cut is 15%.
- **One Neutral list per home Market.** The Brain writes one for each faction the player has Characters in on the realm, under `neutral[realm][homeFaction]` in Recommendations.lua, beside `recommendations` so nothing that walks a realm's Markets meets it. The Addon shows the one for `UnitFactionGroup("player")`: a Horde alt never sees Alliance prices.
- **What's bought comes from Neutral, everything else from home.** Every Flip kind (Sell, Vendor, Craft, Disenchant) is worked out as the home Shopping List is, except that the Listings it buys are the Neutral Market's latest Scan's. Fair Value, Sell Rate, the room under home's cheapest Listing, home's cut and Deposit, held units, and the Market's youth are all home's. A Flip to Sell posts under home's cheapest other Listing, which buying at Neutral leaves where it is.
- **No extra margin** for the trip or for the age of home's prices. Margins aren't tuned before Flip Grades exist (ADR-0042).
- **Sized alone.** The Neutral list is sized against the realm and faction's gold on its own, not sharing a Budget with the home list: the two are alternatives, as Shopping List options already are (ADR-0017).
- **Only a Shopping List at the Neutral house.** The Recommendation Table opens there with the Shopping List and its Flips to Craft and Flips to Disenchant tabs: no Holdings, Predictions or Buy Under tab, no Post and no Cancel undercut (both are about the home Market). Search still works. The header reads "Buy here, sell at the Alliance AH. Alliance prices are from 3 h ago.", the age being the time since home's latest Scan.
- **Home Buy Unders highlight at the Neutral house too.** Their ways out (Vendor, Craft, Disenchant) don't depend on where the unit was bought.

Still to build under #231: a Neutral purchase mail joins the reading Character's home Market as a Purchase that starts a home Lot (sale, expired and cancelled mail from Neutral stays without a Market), and its Flip Grade matches it against the Neutral list worked out for the Neutral Market's last Scan before it, graded against home sales.

## Why

At Everlook the player sees Listings a home Market's Scan never shows, and the Brain already knows what each Item Key is worth at home. The trip home is the player's own time, like any other click, so it isn't priced in. Home's prices may be hours old by the time the player is at Everlook; the header says how old, and the player decides.

## Considered Options

- **Keep #40's won't-do.** It stood only while the player didn't trade at a Neutral house.
- **Buy and resell at the Neutral house.** Its 15% cut eats most Flips, and its Sell Rate would rest on few Scans.
- **Value the exit at the cheaper of home and Neutral.** Neutral isn't an exit here, so its prices don't bound a home sale.
- **A travel or staleness margin.** A tuning constant with no data behind it, before Flip Grades can judge one.
- **One shared Budget across both lists.** The player buys from one house at a time.
- **Key it as a Neutral Market under `recommendations`.** Every reader of `recommendations[realm]` would then meet a Market whose numbers aren't its own.

## Consequences

- A Live pass with a Neutral Scan works out each home Market's Shopping List twice, so it takes about twice as long.
- CONTEXT.md gains **Neutral list**; **Market**, **Shopping List** and **Recommendation Table** say how a Neutral house fits in. **Purchase**, **Lot** and **Flip Grade** follow once the mail and Flip Grades are built.
- At the Neutral house, rows marked Bought are kept apart from home's and cleared once a newer Neutral Scan is imported. The Budget box is home's, since it's the same gold.
- A Backtest of Neutral lists is #232, once there are more Neutral Scans.
