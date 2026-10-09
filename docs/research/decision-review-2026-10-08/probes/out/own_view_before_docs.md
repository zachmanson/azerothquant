# My view before reading design-docs-read-last/ (written 2026-10-08, mid-review)

From code/ and probes p1-p3 only:

1. The binding constraint is evidence, not the margin. 69 Scans over 294 h, but only
   14.1 h count as Observation Windows (gaps <= 60 min), and only 1.2 h in the last 7 days
   (p2). Every gate that asks "how many Sale Events at or above this price" is starved.
2. The Sale Events minimum (3 at/above the post price, recommend.py:3710) is the first
   failure for 5379 of 6213 Item Keys on sale (p1); 4808 of them have zero at that price.
3. The cheap-stock cutoff (since_cheap, sell_rate.py:59) is the next big one: turning it
   off alone takes Sell rows from 2 to 23 on the latest Scan (p1), because it cuts demand to
   the hours watched since cheaper stock appeared, and almost no hours were watched lately.
4. 3200 Item Keys have no price to post at (one price level only, so nothing to post
   1c under). The post rule can't price them at all (recommend.py:3771).
5. The 60-minute window rule throws away unambiguous evidence: 13.5k Partial Sales (stacks
   that shrank) in longer gaps, plus 58.6k disappearances in 1-12 h gaps whose time-left
   bucket rules out expiry (p3).
6. Framing: each gate is a hard pass/fail, so "not enough evidence" reads as "can't
   sell" and the answer is no trade. An expected-value rule with a demand estimate shrunk
   toward zero, plus small per-item and total caps, would turn "unknown" into "small bet",
   which is also how the history gets evidence about prices nobody has tested.
7. Guess to test: relaxing gates alone (without sizing) will lose money; EV + caps won't.
