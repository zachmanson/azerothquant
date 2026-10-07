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

## Amendment: A short break doesn't end the stretch (#139)

On the 2026-10-06 17:51 Beta Scan the Brain said to buy 528 Waylaid Crate: Journeyman Curiosities (248689) at up to 12s to post at 15s 98c. Every Sale Event at that price was from Sep 27–29. Cheap stock had been up in every Scan from 10-02 to 10-04, but the one Scan on 10-05 18:17 had nothing under 15s 98c, so the stretch started at the next Scan, 10-05 22:50. No Observation Window came after it, so the 24 h grace left the week-old demand whole.

So walking back from the latest Scan, a break of up to 2 Scans with nothing under the post price (`SHORT_BREAK_SCANS`) doesn't end the stretch when the Scan before it had cheap stock again. The stretch starts at the earliest cheap Scan reached that way, and only longer breaks end it. Sale Events during the break are after the start, so they still count. A Scan with none of the Item Key listed at all still ends it. The trigger and the 24 h grace are unchanged, and a stretch that is only the latest Scan is still never cut. `--why-not` names the Scans it was kept through: "(none at 2026-10-05 18:17)".

Why 2 Scans: on the Beta data, breaks of every length are common (of the breaks between two cheap Scans, about 3,600 last 1 Scan, 2,200 last 2 and 1,400 last 3), and Scans are 15 minutes to 22 hours apart, so a limit in hours would have to be over a day to cover 248689. Grading each Flip to Sell alone over the Scans from 09-29 to 10-05 (40–63), every Flip that 1 or 2 Scans changes, counted once per Item Key at its first Scan:

- 1 Scan: 33 Item Keys change; of the Flips dropped, 19 lost money and 10 made it; net +32.77g.
- 2 Scans: 46 Item Keys change; 29 lost, 14 made; net +63.83g.

Scans from 10-04 on have under 3 days of Sale Horizon left in the data, so their grades lean on Best Exit Value at the end. Counted at every Scan instead of once, 1 Scan comes out −46g through 10-04 20:28. That's one false cut, 262888 at 39s 99c (dropped at four Scans in a row, and it sold), and 2 Scans has the same false cut and still comes out +14g there.

- Not an hours limit: see above.
- Not ignoring demand when every Sale Event at the post price is days old, and not a shorter grace: as in the issue, the grace is what keeps good Flips when Scans are 2 hours apart.

On the 17:51 and 19:46 Scans of 10-06, 248689 drops off the Shopping List, and 1121, 11177, 3182, 2879, 729, 12977 and 5637 drop too. Nothing is added.
