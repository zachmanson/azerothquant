# Brief: is the Recommendation logic too cautious to make money?

You're reviewing one part of azerothquant, a WoW Auction House gold-making tool, from outside the project. A local Python "Brain" (`code/brain/src/brain/`) reads Auction House Scans and writes Recommendations that an in-game Addon shows: Holdings (what to do with what you own), a Shopping List (Flips: buy cheap listings and resell, vendor, craft or disenchant), Flips to Craft, Flips to Disenchant, Prediction buys, and Buy Unders (standing "buy at X or less" prices).

## The owner's complaint, in their words (lightly edited)

> On a 69-Scan Beta history with 40g, the Shopping List had 2 rows. Flips to Craft and Flips to Disenchant are often only 1-2 rows or empty. Everything is a risk. We can't assume every trade works out. You lose some, you win some, and the wins should be more than the losses. I'm not a finance person. What we have now is definitely not correct, but I don't know what the right answer is.

## What the maintainer found before handing this to you (verify; don't trust)

- Most near misses are items where many sellers list at the same price (a wall), e.g. 14 listings at 1g 53s. Buying one and reposting 1c under the next is a loss after the 5% AH cut. The Brain rejects these, which looks right.
- Copper Tube (4361): 88 units at 1s 20c, then 1s 40c, 1s 50c, 1s 90c, 3s 20c. No sales at or above 1s 39c while the 1s 20c wall has been up (~3 days), so "room" there is 0. The only sales above 3s are a week old. The Brain skipped it.
- Lowering the minimum Flip margin from 20% to 10% added no Sell rows on the latest Scan.

So the individual rules each look defensible. The owner's point is about the *whole design*: every check is a hard pass/fail aimed at "this trade can't lose", and stacked together they may leave almost nothing. A trader thinks in expected value across many small bets, with sizing, not in per-trade certainty.

## Questions to answer

1. What does the Brain actually decide, and which gates (Sale Events minimum, room / Days to Sell, the cheap-stock cutoff, margin share and copper floor, queue/deposit losses, the 1c-undercut post price, Budget, row cap, dropped rows) remove the most candidates on this real data? Measure; give counts per gate.
2. Is the framing wrong? Would an expected-value approach do better: probability of selling at price P within T days, times profit, minus the loss when it doesn't sell (reposts, deposits, selling lower, vendoring)? How would sizing and a risk limit work (e.g. cap per item, cap total at risk, fraction of gold)? Keep it simple enough to explain to a non-finance player.
3. Post price: is "1c under the cheapest other ask left" too narrow? E.g. buying out a cheap tail and posting at a price the Sell Rate supports, not just under the next listing.
4. Flips to Craft and Flips to Disenchant: why are they 0-2 rows? Reality (few profitable recipes, little demand), or gates that are too strict for them (they reuse the Flip margin, the Sale Events minimum on outputs, etc.)?
5. Buy Unders (181 rows) are the other buying signal. Do they cover what the Shopping List misses, or do they share its blind spots?
6. A concrete recommendation: what to change, in what order, and how to check it worked (a backtest over the 69 Scans with `brain replay` or your own probe, comparing realized profit and losses, not just row counts).

## Rules

- Read `code/` first. Read `design-docs-read-last/` (domain glossary, ADRs, the previous outside review) only after you've formed your own view, then note where you disagree with a past decision and why.
- Don't edit `code/`. Put scripts in `probes/` and the report in `REVIEW.md` here.
- Every claim about what the code does or what the data shows needs a probe or a file:line. Say which of your suggestions are guesses.
- Plain language in the summary at the top. The owner is a physics grad, new to finance and to software.

## How to run the Brain on the real data

- `data/history.sqlite` is a copy of the owner's history (69 Scans, one Market: Classic Beta PvP Alliance). `data/config.toml` points at it (flip margin 10%).
- From `data/`: `Z:\vibing\azerothquant\.venv\Scripts\brain.exe recommend` (and `--why-not`, `--why-not <itemKey>`, `--chain <itemKey>`). A cold run took 9 minutes here (Fair Values plus the Decision Engine, nothing cached), so save outputs and reuse them. `data/out.txt` is one full `recommend` run from this snapshot. In a probe, run several variants in one process so the Fair Values are worked out once.
- That exe runs the live project's code, which matches `code/` as of this snapshot. To try a changed rule, monkeypatch `brain.recommend` in a probe script and call `brain.cli.main()` with `sys.argv = ["brain", "recommend"]`, run from `data/` with that venv's python.
- `data/Recommendations-2026-10-08.lua` is what the Addon was shown.
