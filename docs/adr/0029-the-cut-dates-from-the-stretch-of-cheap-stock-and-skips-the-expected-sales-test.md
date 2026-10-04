# The demand cut dates from the stretch of cheap stock and no longer waits for expected sales

Amends ADR-0028. After it, the Brain still said to buy all 3895 Lesser Magic Essence at up to 3s 33c and post at 5s 96c (#135). Every Sale Event at that price was from Sep 27–30. Cheap stock had been up in every Scan since 10-02, but each wall sold at 20c or came down and a new one went up, so the wall being bought was first seen that day. ADR-0028's cutoff, the earliest first seen among the Listings in the run, dated the crash two days late. Even at the right date, the expected-sales test said 2.5 Sale Events an hour before, times 0.84 Observation Window hours since, was 2.1, under the minimum of 3, so the old demand was left whole.

So the cut changes in two ways:

- **Cutoff = the start of the stretch.** Walking back from the latest Scan, the earliest Scan from which every Scan up to the latest had at least one other player's Listing under the post price. A buyer at the old price has to get through whatever cheap stock is up, not one particular wall. One Scan with none ends the stretch: buyers cleared it. Scans far apart count as continuous, since stock up in both wasn't bought out in between.
- **Trigger:** a stretch that is only the latest Scan is never cut (a Listing too new to judge). Otherwise, if any Observation Window hours came after the cutoff, cut: only the Sale Events and window hours after it count. The expected-sales test is gone. With no window hours since, the whole range counts until the stretch is 24 hours old (`UNWATCHED_STRETCH_SECONDS`), and then nothing sells at that price.

The readers are ADR-0028's: Flip to Sell, a Hold buy's Max Loss, and `brain recommend --why-not`. `--why-not` gives the stretch's start and says "(not watched since)" when no window hours came after it.

## Considered options

- **Cut whenever the stretch is older than the latest Scan, even with no window hours since.** On the 2026-10-04 Beta data this dropped 29 of 49 Shopping List rows. Those Scans were 2 hours apart, so every cheap Listing seen twice that day lost all its demand, while the Market as a whole was buying more per watched hour than in September.
- **Keep the expected-sales test with the new cutoff:** LME still passes (2.1 < 3).
- **Measure the time since in wall-clock hours:** the rate before comes from watched hours, mostly peak play, so wall-clock hours overstate what was expected overnight.
- **Cap run size** (the issue's second proposal): the demand behind LME wasn't inflated, it was out of date. The Flip priors already shrink it to about 4300 a day, and a median-size cap gives about the same. Not done.

## Consequences

- Thin Item Keys lose ADR-0028's grace. A cheap Listing that sat through any watched hours with no Sale Event at or above the post price since loses its Flip until 3 come.
- A crash seen only in Scans more than an hour apart is trusted for up to a day. That's the cost of not killing every Flip in a Market scanned every couple of hours.
- On the 2026-10-04 17:54 Beta Scan, 10 Flips drop out (10938 among them), all with cheap stock up since 10-03 or earlier and nothing sold at or above the post price since. The rest of the list is unchanged.
