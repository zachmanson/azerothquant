# Shopping List options are capped by their Unsold Loss and the gold tied up

Amends ADR-0017 (#170, parent #166). Options are still sized alone and the player still picks. But each is now sized within two risk caps as well as `min(gold, Budget)`, both shares of the **Stake** (the pooled gold plus the player's own Listings up, at what they cost):

- **Unsold Loss** at most 5% of the Stake (`flip_unsold_loss_share`). An option's Unsold Loss is what it loses if none of it sells: its cost, less what its units vendor for (a Flip to Craft's output, a Flip to Disenchant's mats), plus one posting's Deposits.
- **Tied up** at most 60% of the Stake (`flip_tied_up_share`). An option costs at most the room: 60% of the Stake less the own Listings up at cost.

Both are settings. Neither has a floor.

The caps are applied inside sizing, as the Budget is. A Flip to Sell takes the most profitable run that fits them (ADR-0011), so a shorter run posts 1c under the cheapest Listing it leaves, not at the longer run's price. If no run fits and clears the Flip margin, the option drops off. The Flip to Craft and Flip to Disenchant greedy loops stop at the first step that would break a cap. A Flip to Vendor's Unsold Loss is about nothing, so only the room touches it. Buy Unders, Holdings and Prediction buys (ADR-0006) aren't touched.

A row the caps shrank carries `capped` (its units before the cap), and the Addon says why in the tooltip, in plain words. The Bought-mark fold (#97) takes marked costs off the room as well as the gold left. The replay's `options_taken` tracks the room alongside the gold.

## Why

The Cured Medium Hide row on 2026-10-12 (Scan 85) said to buy 241 for 17.77g and post at 14s 49c. The player had 60.5g, bought 501 for 38.66g, and a day later 767 units were back up from 6s 42c. The cheap-stock cutoff can't catch a buy that takes every unit under its post price (ADR-0033). Turning the cutoff off made things worse. So the guard has to be on size.

In the Backtest on the 86-Scan copy (ADR-0032), `brain`'s three worst trades were dear buys with almost no vendor floor, each 15-22% of the Stake: 12987 (−23.0g at the vendor mark), Lil Timmy's Peashooter (−22.2g) and 264016 (−15.5g). Its biggest buys by share that won were things that sell now, or cheap stock with a vendor floor (11288 +28.1g, 251525 156 units sold out). Gold was under 1g on 21 of 86 Scans, and up to all of the Stake was tied up in posts. An Unsold Loss cap hits the first group and spares the second. A cap on cost wouldn't.

## Considered options

- **A warning or fold, rows left full size** (the review's §8 suggestion): the hide row would still say 241, and the Backtest, which takes rows as sized, couldn't show a change.
- **Per-item cost cap** (10% of the Stake): would shrink the winning cheap-commodity buys as much as the losing dear ones.
- **A brake** (halve the caps 20% below the peak Stake, as ADR-0006 does on a losing record): needs a remembered peak the Brain doesn't keep. Filed separately.
- **A floor** ("never cap under 1g"): would keep the list fuller early in Live, when one bad buy hurts most. Revisit after the first Live week.
- **Caps as shares of the gold, or of the Budget**: the gold shrinks as you post, so a good buying session would cap the next one hardest. The Budget is what the player will spend, not what a loss is measured against.

## Consequences

- With a small Stake (day 1 of Live), most rows are small or gone. That's intended.
- Taking two options can still go over the room, as with the Budget. The Bought-mark fold is the guard.
- The Backtest gains an `uncapped` policy, so the change and later ones (#171) can be measured against the Brain without it. Its Stake is the simulated gold plus unsold units at cost, passed in, not read from Scans, which show the real player's posts.
- The Cured Medium Hide buy is outside the Backtest (no buys in the last 7 days). It's checked by `brain recommend` as of Scan 85.
