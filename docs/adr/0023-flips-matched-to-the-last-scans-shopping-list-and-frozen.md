# Flips are matched to the last Scan's Shopping List and frozen at first sight

The Brain names Flips to Sell but never learned whether the ones the player made sold at the Post at it named, within the Sale Horizon (#60). A Flip Grade answers that, as a report only: nothing it finds feeds back into what the Brain recommends.

**Matching is automatic.** A Purchase not under a Prediction is a Flip made when its Item Key had a Flip to Sell on the Shopping List as of the Market's last Scan before it, and it cost no more per unit than the dearest Listing that row's run bought. There's no age limit, since the table shows the last import whatever its age. Every matched Purchase of an Item Key against the same Scan's row is one Flip, so a run straddling a new Scan is two, each against its own row. Partial runs compare per unit. The player never tags anything: tags would be forgotten, and the data is already in the mail.

**What was named is frozen per Scan, at first sight.** Finding the row means working that Scan's Shopping List out again with the replay's machinery (`recommend_market` as of the Scan), a full Decision Engine pass. So the first time a Scan is needed, its Flip to Sell rows (Item Key, units, dearest Listing, Post at, Profit, days, and the Sale Horizon in force) are appended to `grades.toml` under `[shown...]`. That's done even when it named none, so a Purchase that isn't a Flip (a reagent, a Buy Under snipe) never costs another pass. Freezing per Scan rather than per Flip also lets a Purchase from a later Mailbox Read still join its Flip. The frozen row is what the player was shown, which later pricing code must not rewrite. The Sale Horizon frozen with it is the one in the config when the Scan is first worked out: the config keeps no history, so a backfill uses today's.

**The Grade** comes a Sale Horizon after the Flip's first Purchase: its units Sold by then after the Auction House cut, closed through the Lots oldest first (the Brain's queue: held units sell ahead of a Flip's), plus its still-open units at their Best Exit Value then, less what they cost. That mirrors a Prediction's Grade. It's worked out once a Scan at or after its grading moment is in (that Scan prices the open units), and frozen (`[flips...]`, keyed `<Item Key>@<Scan>`) once a Mailbox Read at or after it is in too, so Sold mail from within the horizon that sat unread still counts. The clock starts at the Purchase, so post lag counts against the Flip; the lag to the first own Listing is recorded with the grade.

**Sold Outcomes only.** A sale counts once a Mailbox Read has seen it. Deposits are left out: an Expired or Cancelled Outcome can't be pinned to one Flip, so only the Item Key's Expired count within the horizon is recorded with the grade. Units that leave without a Sold Outcome (crafted away, vendored, mailed off) stay open (ADR-0007) and count at Best Exit Value.

**Only in `brain recommend` and `brain flips`.** The import path that writes Recommendations.lua doesn't grade Flips, so a first backfill's passes never delay a reload.

## Considered options

- **Freeze one snapshot per Flip, as first specced**: a Purchase that matched nothing would be worked out again on every run, and a Flip's units would be fixed at first sight.
- **The player tags their Flips**: forgotten in practice, and the mail already says what was bought and when.
- **Grade against today's Shopping List logic**: grades would drift with every pricing change and judge the Brain on advice it never gave.
- **Charge Deposits**: they'd be guessed, not known.

## Consequences

- Flip to Vendor (sells at once) isn't graded. Flips to Craft are graded since #114, matched by their reagent Purchases and traced through craft lineage (ADR-0027).
- Beta Markets are graded too, labelled provisional as in `brain replay`.
- To regrade, delete the entry from `grades.toml` by hand, as with a Prediction.
