# Replay retired: the Dec 2 checkpoint runs on the Backtest

Supersedes ADR-0015 (#184). Its question stays: azerothquant keeps growing only if the Brain earns more than a simpler tool. What changes is the harness that answers it. `brain replay` is gone, and the Live checkpoint is read from the Backtest (ADR-0032).

**Why.** The replay grades only by Sale Events, which come from 60-minute Observation Windows, so it can't see most sales, for the Brain or the baselines (ADR-0032). Its #83 Beta read also showed the baselines losing mostly to their own carelessness: they posted every unit at every Scan and paid 7 Deposits on each unsold one (#196). Fixing them would polish a grader we no longer trust for anything else. The Backtest's Sale Records, with their 0.65x/1.2x bounds and the calibration line against the player's mail, are the grader every buy-side change already answers to.

**The Live checkpoint (around Dec 2, 4 weeks after the Nov 4 launch).** `brain backtest` over the Live Market runs the Brain and an **Auctionator** policy from the same start gold. The Auctionator policy is Flip to Sell only: all the units at the cheapest ask when it sits under the next-lowest ask by more than the cut plus the Deposit, posted 1c under that one (#196 builds it). The deciding number is **P&L at the vendor mark, at the 1x grade**, with the gap as (Brain - Auctionator) / |Auctionator|:

- **Continue** at +10% or more.
- **Stop** within ±5%: trade with Auctionator, keep the Addon for data collection, and freeze Brain features.
- **In between**, a 2-week live split decides (some Item Keys or Characters follow Auctionator, the rest the Brain).

The 0.65x and 1.2x grades are shown beside it, so a lead that only holds at 1.2x is seen. The verdict is recorded on #83.

**Realized profit** (the player's Sold Outcomes after the cut, less the cost of the Lot units they closed, ADR-0007) has its own command, `brain profit [--since DAY] [--until DAY]`, which also counts the For Use Purchases in the range (#55). It's real gold, so it's kept apart from the Backtest's simulated gold.

## Considered options

- **Keep the replay only for Dec 2, after fixing its baselines (#196).** A 3.5 h rerun and a post cap, all on a grader that misses most sales.
- **Decide Dec 2 on realized profit and gold per hour alone.** No baseline to compare with, so no answer to "would a simpler tool do as well".
- **Port the emulated TSM too.** TSM doesn't run on Forever and has no data there (ADR-0015), and most of its stand-in's strength was crafting, which the Backtest doesn't simulate. Revisit if TSM announces Forever support.
- **Market mark as the deciding number.** It counts unsold units at an ask that may never be paid. The vendor mark is what the Backtest's gold already uses.

## Consequences

- Deleted: `replay.py` (grading, the Auctionator and emulated TSM baselines, DBMarket and the ablations), `brain replay`, and their tests. `options_taken` moved to `backtest.py`.
- `recommend_market`'s `pricer` existed only for the replay's own-Market Sell Rate ablation, so it went too. ADR-0038's exception for it is gone with it.
- No ablation table any more. A feature's worth is judged by a Backtest policy with the feature off, when one is wanted.
- Crafting and how Holdings are handled aren't compared with a baseline: the Backtest's policies only buy.
- The Beta read on #83 (Brain +51.82g, Auctionator -4273.97g, TSM -5463.67g) stands as a replay result; its logs (`brain/replay-83/`) weren't kept.

## The Auctionator policy's post cap (#196)

Auctionator has no cap of its own, but the old replay stand-in posting everything is most of why it lost by thousands on #83's Beta read, and a player flipping by hand doesn't put all their gold into one Item Key. The `auctionator` policy spends at most **a fifth of its Stake** (gold plus the units still posted at cost, as the Brain's risk caps use) on one Item Key at a Scan, and **at most a stack (20 units)**, in whole Listings. It's a spread-it-out rule that needs no sale data, which Auctionator doesn't have, and it grows with the gold from 40g to Live. When the gold runs short, the last Item Key gets the Listings it still affords (smallest first), as a player would buy what they can. A Listing bigger than the cap on its own is skipped. The stack cap came from the first Beta run: with the gold cap alone it bought 528 Copper Rods at 1s and 1645 of a 20c item at the first Scan and ended at -191g from 40g, almost all of it Deposits on units that never sold. With no sale data, it can't tell those from a run that sells (the user's Steel Bars), so a careful player buys a stack; the Brain's sizing is unchanged.

- **A fixed unit cap (a stack of 20).** Simple, but 20 copper herbs and 20 epics are very different bets, and it doesn't grow with the gold.
- **No unit cap.** See the -191g run above: the baseline loses to Deposits, and Dec 2 would read "continue" without a test.
- **A tenth of the Stake.** At 40g that's 4g an Item Key, which skips most Flips worth doing, so the baseline would lose by doing too little rather than by its rule.

The buy test takes the cut on the post (1c under the next-lowest ask), not on the spread, and charges one Deposit: a hair stricter than "under by more than the cut plus the Deposit", and what a player reading Auctionator's prices would work out.

`brain backtest --policy brain --policy auctionator` (or `--policy brain,auctionator`) prints the gap line.
