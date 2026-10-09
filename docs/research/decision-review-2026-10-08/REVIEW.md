# Review: is the Recommendation logic too cautious to make money?

Outside review of the azerothquant Brain's buy-side Recommendations, on the 69-Scan Beta
history in `data/history.sqlite`. I read `code/` first, wrote my own view down
(`probes/out/own_view_before_docs.md`), then read `design-docs-read-last/`. Every number
below comes from a probe in `probes/` (its saved output is in `probes/out/`) or from a
file:line in `code/brain/src/brain/`. Guesses are marked **(guess)**.

---

## Summary in plain language

**Is the pass/fail "can't lose" design the problem?** Partly. Each check asks for proof
that a trade can't lose, and the proof it wants is "I've seen people buy at this price".
The Brain only counts sales it saw between two Scans less than an hour apart. In this
12-day history that's 14 of 294 hours, and about 1 hour in the last week. So most items
don't fail because they're bad trades. They fail because nobody was watching, and
"no proof" is read as "no". On the latest Scan, 5,379 of 6,213 items fail the first check
(fewer than 3 sales seen at the price) and 2 make the list.

**Why only 2 rows?** It's mostly one check, the "cheap stock" rule. When you come back
after a day away, it decides from the few minutes you've watched since that nothing sells
any more. The list had 20–32 rows on most Scans from Oct 3 to 7, and fell to 2–5 each
time you'd been away for a day. On the latest Scan, 492 items were judged on a single
21-minute window with zero sales in it.

**What should replace it?** Think like a trader placing many small bets:

- For each buy, estimate **how likely it is to sell, and at what price, within a few
  days**.
- Put a number on the **average outcome**: the wins times what they make, minus the
  losses times what they cost. That's the "expected value". Buy only if it's clearly
  positive.
- **Bet small.** At most 10% of your gold in one item. At most 5% lost if that buy never
  sells. Keep 40% of your gold free. Halve all of that if you're 20% down from your best.
  You *will* lose some trades; the caps make sure no single one hurts.

The Brain already does exactly this for Predictions. It just doesn't do it for Flips.

**Did I prove it makes more than it loses?** No, and I won't pretend otherwise. I ran a
backtest over the 69 Scans: start with 40g, trade, and grade every post against sales
that really happened later. **No policy made more than it lost** on this history:

| | Gold after the test, vs the 40g start (unsold stock at vendor price → at market price) |
|---|---|
| The Brain as it is | −10.5g → +1.1g |
| The Brain with its checks loosened | **−37.7g → −27.5g**, one trade lost 21.8g |
| The expected-value rule with the caps | −9.4g → −0.2g, worst trade −2.5g |
| Buy Unders as standing orders | −18.0g → −16.8g |

What that tells you:

- **Loosening the checks without sizing is the worst choice.**
- **The expected-value rule earns about what the Brain does, with much less risk:** its
  worst trade is a third of the size, and it never runs out of gold.
- **The money is all in items that sell within the first week.** Trades that sold in
  week 1 made +61%. Trades that didn't lost *more than they cost*, mostly to listing
  deposits. Each day an item sits unsold costs about 60% of its vendor price.

**Why can't this history prove it?** Only 5 of the 12 days can carry a buy that gets a
week to sell. Prices fell 6% in the last week. And the history misses about 4 in 10 real
sales because of when Scans happen.

**What to change first:**

1. Build the backtest into `brain replay`, so every change is judged by real sales and
   gold, not row counts (§7).
2. Fix the cheap-stock rule so a few minutes of watching can't zero an item. That's the
   quick fix for the empty list.
3. Count the sales the history already records: shrinking stacks in any gap, and
   vanished listings in gaps up to 12 hours. That's 78 watched hours instead of 14.
4. Add the caps.
5. Replace the "3 sales" and margin checks with expected value, aimed at "sells within
   3 days", and stop reposting things that don't sell.

**Flips to Craft and Flips to Disenchant:**

- **Craft: mostly reality.** Your 36 recipes mostly make things worth less than their
  materials, often less than a vendor pays.
- **Disenchant: mostly a setting.** The Brain charges 5s of "hassle" per item, and that
  alone wipes out the cheap greens, whose materials are worth 2–4s more than the item.
  At 1s there'd be 4 rows; at 0, 7.

---

## 1. What the Brain decides, and which checks remove the candidates

### 1.1 What a Flip to Sell has to pass

For each item other players have listed, `_flips` (`recommend.py:3436`) tries buying the
cheapest 1, 2, 3, … listings and re-posting 1c under the cheapest listing left
(`_undercut`, `recommend.py:3771`). A run is kept only if **every** check passes:

| Check | Where | Default here |
|---|---|---|
| **Sale Events minimum**: at least 3 sales seen (in different Observation Windows) at or above the post price, or the room is 0 | `_flip_room`, `recommend.py:3710`; `config.py:84` | 3 |
| **Cheap-stock cutoff**: once cheaper listings have been up for a while, only sales seen *since* they appeared count; with no watched hours since, after 24 h "nothing sells" | `_demand_at`, `recommend.py:3662`; `SellRate.since_cheap`, `sell_rate.py:60-81` | on |
| **Room / Days to Sell**: units bought ≤ what the shrunk Sell Rate sells in 7 days, after held units | `_room_at`, `recommend.py:3681`; priors `config.py:76,81` (24 h of no sales and 5 typical-size events added) | 7 days |
| **Margin**: resale after the 5% cut, deposits and effort ≥ max(10% of price, 1s) per unit, judged on the **last** (dearest) unit | `_resells`, `recommend.py:3931`; `config.toml` sets 10% | 10% / 1s |
| **Deposits** expected lost while queued | `_Queue.lost`, `recommend.py:506` | on |
| **Effort**: 5s per non-stacking unit bought and again per unit posted | `config.py:121`, `recommend.py:3508` | 5s |
| **Dropped rows**: items the Scan dropped rows of aren't options | `recommend.py:710-711` | on |
| **Budget / row cap** | `_options`, `recommend.py:3950` | gold, 50 rows |

Flips to Craft (`_flips_to_craft`, `recommend.py:3133`) and Flips to Disenchant
(`_flip_to_disenchant`, `recommend.py:1137`) reuse the same margin, and value their
outputs/mats through the same Sell Rate room, which needs the same 3 Sale Events.

### 1.2 Counts per check on the latest Scan (probe `p1_funnel.py`, output `probes/out/p1_funnel.txt`)

6,213 Item Keys have other players' Listings. The Brain's own why-not verdict (first check
failed, `recommend.py:876`):

| First check failed | Item Keys |
|---|---|
| Sale Events (fewer than 3 at or above the post price) | **5,379** (4,808 of them have **zero** at that price) |
| Flip margin | 832 |
| Made the list | **2** |

Each check on its own (an item can fail several):

- 3,200 items have **no price to post at at all**: only one price level is listed, so there's nothing to post "1c under".
- 495 had their demand cut by the cheap-stock cutoff.
- Only 6 items clear the margin at the cheapest ask; 3 of those then fail Sale Events and room.
- Only 3 Item Keys' best run is a wall (`needs > 1`): the maintainer's "walls" are real but small in count.

Re-running the whole Shopping List with **one** gate relaxed at a time (rows, and the expected profit the Brain itself claims):

| Variant (latest Scan) | Flips to Sell | Flips to Craft | Flips to Disenchant |
|---|---|---|---|
| As is | 2 (1.0g) | 2 (0.5g) | 2 (0.8g) |
| Sale Events minimum 3 → 1 | 7 | 2 | 4 |
| **Cheap-stock cutoff off** | **23** (90.8g claimed) | 2 | 2 |
| Flip priors → Holdings priors | 2 | 2 | 2 |
| Margin 10%/1s → 0 | 5 | 6 | 2 |
| Deposits off | 2 | 2 | 2 |
| Dropped rows ignored | 2 | 2 | 2 |
| Post at the next ask instead of 1c under | 2 | 2 | 2 |
| Effort 5s → 1s per non-stacking unit (`p9_effort.py`) | 4 | 3 | 4 (11.2g claimed) |
| Effort 5s → 0 | 4 | 4 | 7 (56.0g claimed) |
| Everything above at once (`p1`) | 98 (710g claimed) | 6 | 4 |

So on this Scan the binding gates are, in order: **Sale Events minimum + cheap-stock cutoff
(both are "not enough recent sales seen")**, then the **effort charge** for gear and
Disenchanting, then the margin. Deposits, dropped rows and the 1c undercut barely matter.
Lowering the margin from 20% to 10% adding nothing (the maintainer's finding) is
consistent with this: the margin isn't what's binding.

### 1.3 Why "not enough sales seen" is the real bottleneck (probes `p2_evidence.py`, `p3_sales.py`)

- The history spans 294 hours. Sell Rate only counts **Observation Windows**, gaps between
  Scans of 60 minutes or less (`observation.py:44`, ADR-0004). They add up to **14.1 h, 4.8% of the time**, by day:
  09-27 6.3 h, 09-28 3.0 h, 09-29 3.0 h, 09-30 0.5 h, 10-03 0.8 h, **10-08 0.4 h**. The last
  7 days have 1.2 watched hours.
- So "3 Sale Events at this price" mostly means "3 sales seen on Sep 27–29". As the
  market moved on, items lost their evidence, and the cheap-stock cutoff then zeroes
  whatever demand they had (its 24 h grace ends, `sell_rate.py:68`). That's why the
  Shopping List shrank from 10–24 Flip to Sell rows per Scan in late September
  (`probes/out/p5_craft_de.txt`, per-Scan table) to 2 now.
- The data already holds much more evidence than the Brain uses. In gaps of 1–12 hours
  (78 h of the history, vs 14 h), 58,635 Listings vanished that their time-left bucket says
  **couldn't have expired**, and 13,571 stacks visibly shrank (Partial Sales, 478k units)
  in gaps over an hour. A shrinking stack is a certain sale; the Brain drops all of them
  because of the gap length (`p3_sales.txt`).
- Is a "vanished, couldn't have expired" Listing really a sale? Checked on the owner's own
  Listings, whose fate the mail says (`p6_own_truth.py`): in ≤1 h gaps 7 of 12 matched
  were sold (58%), in 1–12 h gaps 20 of 27 (74%). Small samples, but the longer gaps are
  no worse. Either way, roughly a third of "sales" are cancels, for both rules.

---

## 2. Is the framing wrong? Yes. What to replace it with

### 2.1 What's wrong with "can't lose"

Every check is a yes/no on one trade, and each one turns *uncertainty* into *no*:

- "Fewer than 3 sales seen at this price" doesn't mean "won't sell". With 1.2 watched
  hours in the last week it mostly means "nobody was looking". 4,808 of 6,213 items have
  zero sales *seen* at their post price (§1.2).
- The cheap-stock cutoff on the latest Scan judged 495 items on the 21 minutes watched
  between the two 10-08 Scans, the only watched time after their cheap stock showed up.
  492 of them had no sale in those 21 minutes, so their demand went to zero
  (`probes/out/p1_why_not.json`, `cheap_since`/`watched_since`).
- The list collapses **every time the owner comes back after a day away**, then recovers
  (Flip to Sell + Vendor rows per Scan, `probes/out/p5_craft_de.txt`):

  | Scan | Rows | | Scan | Rows |
  |---|---|---|---|---|
  | 10-04 13:46 – 20:28 (5 Scans) | 28–32 | | 10-06 17:51 – 21:45 (3 Scans) | 20–28 |
  | **10-05 18:17** (after a 22 h gap) | **5** | | **10-07 21:33** (after a 24 h gap) | **2** |
  | 10-05 22:50 | 23 | | **10-08 18:02 / 18:23** (after a 20 h gap) | **4 / 2** |

  After a long gap the cheap stretch is over 24 h old with no watched hours, so "nothing
  sells" (`sell_rate.py:68-69`); the first short watched window after it then cuts demand
  to what sold in those minutes. Over all 69 Scans the Brain averaged 14.2 Flip to
  Sell/Vendor rows (max 54). The owner's "2 rows" is the worst moment of a cycle, not the
  typical state.
- And the checks still don't make trades safe. Graded on what really sold afterwards, the
  Brain's own picks lost money on 24 of 82 buys, −10.5g overall at the vendor mark (§6). "Can't lose"
  was never true; it just isn't priced.

Stacked hard checks also can't trade a small, likely loss against a large, likely win.
A trade that sells 70% of the time at +50% and otherwise loses 20% is worth taking
(0.7 × 50 − 0.3 × 20 = +29% on average), but it fails "can't lose" every time.

### 2.2 The replacement: expected value, sized small, with a loss limit

For each possible buy (a run of the cheapest listings, and a post price, §3):

1. **Chance it sells.** Count the sales seen at or above the post price in the last 14
   days, over the hours watched, with the existing Flip prior (24 extra watched hours with
   no sales) pulling thin evidence toward zero. That gives sales per hour `r` and an
   average sale size `s`. Over a week, the number of buyers is roughly Poisson with mean
   `r × 168 h × κ`, where `κ` (0.5 here, **guess**) discounts for prime-time watching and
   being undercut. Your units sell after any cheaper units already listed are gone.
2. **Expected value.**
   `EV = (expected units sold) × (post price × 0.95 − effort) − deposits for each day a unit
   waits − cost + (expected units unsold) × (what you get back if it doesn't sell)`.
   For "what you get back" I used the Vendor Price, the worst case, so the EV is honest
   about losses.
3. **Take it if** EV ≥ 10% of the cost (a cushion for the model being wrong, **guess**).
4. **Size it.** Best EV per gold first, while:
   - **per item**: cost ≤ 10% of your bankroll (gold + what open posts cost);
   - **worst case per buy**: if nothing sells, the loss (cost − vendor value + a week of
     deposits) ≤ 5% of bankroll;
   - **total**: at most 60% of the bankroll tied up in posts, 40% kept in gold;
   - **brake**: if the bankroll falls 20% below its peak, halve the caps (the Brain already
     does this for Predictions, `recommend.py:3296-3311`, ADR-0006).

In words for the owner: *every buy is a small bet. The Brain says how often it expects
the bet to pay and how much; it only takes bets that pay on average, and never so big
that one loser hurts.* The risk rule replaces the certainty rule: you accept losing
trades, but you cap what any one loss and all of them together can cost.

This is the shape the Brain already uses for Predictions (Max Loss share, a per-Prediction
cap, a total cap, a brake): it just isn't applied to Flips, which are sized "as if the
only buy" (ADR-0017) with no total limit. In the backtest the Brain-as-is policy spent its
gold down to under 1g on 16 of the 69 Scans (`probes/out/p4_brain_wide_lb.json`, `curve`).

### 2.3 Feed it the evidence you already have

The EV rule only works if the "chance it sells" has data behind it. Use the sales the
history already contains: Partial Sales from every gap (they're certain), and vanished
Listings from gaps up to 12 hours whose time-left bucket rules out expiry (the Brain's own
test, `observation.py:92`), with the gap hours as the exposure. That's 78 watched hours
instead of 14 (`p2_evidence.txt`). The one-third cancel rate (§1.3) applies to both rules;
fold it into `κ` rather than into a pass/fail.

---

## 3. The post price: is "1c under the cheapest ask left" too narrow?

Yes, for two reasons.

- **It can't price 3,200 of the 6,213 items at all** (§1.2): with one price level listed,
  there's no "next ask" to go under, so `post_at` is None and the item is skipped
  (`recommend.py:3497`).
- **Buyers don't only buy the cheapest listing.** Over every sale-like record in the
  history (`p8_post_price.py`), weighted by units: 64% sold at the cheapest ask then up,
  15% within 5% above it, 15% at 5–20% above, 6% more than 20% above. 21% of units were
  bought by a buyer who first went through 2 or more cheaper price levels. So a post that
  sits *above* some other listings still sells, as long as there's enough demand at that
  price to get through the cheaper stock first.

What to do instead: treat the post price as a choice, not a rule. For a run, try a few
prices: 1c under each of the next 3–4 price levels left, and (for single-level items) the
recent sale prices. For each, the EV of §2.2 already accounts for the units listed below
it ("sell after cheaper units are gone"). Pick the price with the best EV. That covers
both the maintainer's example ("buy the cheap tail and post where the Sell Rate supports
it") and the Copper Tube case: with 88 units at 1s 20c listed and no sale at or above 1s
39c seen while that wall was up, the demand above the wall is near zero and the EV says
no, for the right reason (the price, not a missing check).

Caveat: Probable Sales are capped at 1.2 × Fair Value (`observation.py:338`), so dear
"sales" are dropped as likely cancels. That only removes 931 of 29,989 Sale Events (3%,
`p2_evidence.txt`), so it doesn't hide much demand, but it does cap how far above the
wall any evidence can reach. Keep it; it's the right direction given §1.3.

---

## 4. Flips to Craft and Flips to Disenchant: reality or the checks?

Probe `p5_craft_de.py` (output `probes/out/p5_craft_de.txt`) re-traces each one's first
step on the latest Scan; `p9_effort.py` varies the effort charge.

### Flips to Craft: mostly reality

The account knows 36 recipes (Tailoring 119, Enchanting 150, Cooking, all Kash-Patel).
On the latest Scan:

- 2 made the list (4315, 4305), for 3s and 1s profit a craft.
- 24 fail the margin with the output **worth more at a vendor than on the AH**: the
  output's post price after the cut doesn't beat its Vendor Price, so the Brain vendors
  it, and the reagents cost more than the vendor pays. That's the low-level Tailoring
  market, not a gate.
- 8 fail the margin on the AH: the best near misses (Woolen/Linen bolts 2997/2996,
  279981, 279967) make **under 1s a craft**, so they fail the 1s floor. Even at margin 0
  the tab only grows to 6 rows (§1.2).
- The big-ticket recipes (253895, 253907, 253919, 253931, 253943, 253955: 7–16g of
  reagents) have **no other listing and no sale** of the output, so there's no price at all.
  An EV rule wouldn't fund them either: no evidence of a buyer.

So the near-empty tab is what this character's recipes are worth. More rows needs more
recipes (or higher skill), not looser checks. One gate does bite: the outlet uses the
same Sale Events minimum at the post price (`_outlet`, `recommend.py:3101`), so a
recipe whose output sells, but rarely at *that* price, is valued at Vendor. Under the EV
rule that becomes a probability, not a cliff.

### Flips to Disenchant: mostly the effort charge

Enchanting 150 can Disenchant 16 groups that have listings where Disenchant is the best
way out. For the cheap, plentiful greens (thousands of listings at 3–8s, ilvl 5–25), the
expected mats are worth about 2–4s more than the item, and the **5s effort per item**
(`config.py:121`, charged in `recommend.py:1158`) wipes that out. Examples (latest Scan):

| Group | Listings | Cheapest | Expected mats | After 5s effort |
|---|---|---|---|---|
| green armor ilvl 16–20 | 1,523 | 3s | 7s | −1s |
| green weapon ilvl 6–15 | 365 | 3s | 7s | −1s |
| green armor ilvl 21–25 | 1,292 | 8s | 10s | −3s |
| green armor ilvl 36–40 | 233 | 34s | 64s | **bought 5** |

The higher-level groups are priced above their mats: that's reality. With the effort at
1s the tab has 4 rows (11.2g of claimed profit), at 0 it has 7 (56.0g claimed,
`p9_effort.txt`), but most of that 56g leans on the mats' own Sell room, which the
Brain already shrinks per extra Disenchant (`_mats_value`, `recommend.py:1182`).

The effort charge is a real cost of the player's time (ADR #73), not a market fact, and
the owner should set it. 5s per green is about what a level-25 player earns in a minute or
two of farming (**guess**); if a Disenchant takes 5 seconds of clicking, 1s is closer to
fair. I'd make it a setting in game and default it to 1–2s for Disenchanting, separately
from gear Flips to Sell (where it's charged twice, buy and post).

---

## 5. Buy Unders: do they cover what the Shopping List misses?

**They share most of its blind spots, and they lose money in the backtest.**

What they share and don't (`_buy_unders`, `recommend.py:975`; `_sell_way`, `recommend.py:1287`):

| | Shopping List Flip to Sell | Buy Under (Sell way) |
|---|---|---|
| 3 Sale Events at or above the post price | yes | yes (`_flip_room` via `_sell_way`) |
| Post 1c under the cheapest other ask | yes | yes, the *current* cheapest, nothing bought |
| Flip priors, Days to Sell room, margin | yes | yes, margin once (`_under_margin`, `recommend.py:1303`) |
| Cheap-stock cutoff | yes | **no** (`_demand_at` called without `cheap`, `recommend.py:1294`) |
| Walls / runs, Budget, row cap, dropped rows | yes | no |

So a Buy Under exists only where the Shopping List already has 3+ Sale Events at the
price; it can't reach the 4,808 items with none. That's why 195 Buy Unders exist but
only 9 were "listed now" on the latest Scan (`p1_funnel.txt`).

Backtest as standing orders (`p4_backtest.py buyunder`): at each Scan, buy every listing
at or under the previous Scan's Buy Under price (up to its units), post 1c under the
cheapest other ask left. 112 buys, 91% of units sold, but **45 of the 78 fully sold lots
still lost money**, median return −5% (`out/p4_buyunder_wide.json`). A listing appears
under a standing price mostly when the market is falling, so by the time it's bought the
resale price has fallen too (adverse selection). The Buy Under is priced off the Scan
before; it needs the same "has the price moved since" test as a Flip, which is exactly
the cheap-stock cutoff it skips.

The owner's one big real winner was a Buy Under, though: Troll's Bane Leggings (13114),
bought 2 at 15.6g + 12.6g on 10-04 and 2 at 10g each on 10-06, all 4 sold at 15.9–16g
(mail in `history.sqlite`). That's about +12g, with **99% of the gold in one item**
(gold 0.39g on 10-04). It worked; the EV-plus-caps rule would have allowed one at a time.
Note `brain flips` still shows both buys as "pending" (`probes/out/brain_flips.txt`)
although the mail shows all four sold, which looks like a linking bug worth a look.

---

## 6. Backtest over the 69 Scans

**Short version: I could not show a policy that made more than it lost on this history.**
Not the Brain as it is, not the Brain with gates loosened, not the Buy Unders, and not my
expected-value policy. What the backtest *does* show is below. I'd rather say that
plainly than tune until one number turns green on 12 days of Beta.

### 6.1 How it works (`probes/p4_backtest.py`)

- Every policy starts with **40g** at the first Scan and trades on its own simulated gold
  and inventory, Scan by Scan, in time order.
- **Buys only through Scan 49 (Sep 30 21:12)**, so every buy gets at least a week before
  the data ends (Oct 8). Without that cutoff, the last week's buys are still unsold at the
  end and their valuation dominates the result (§6.4).
- **Fills come from real later sales**, never from the Brain's own Sell Rate: a later
  sale-like record (`p3`) of the item at price q fills up to its units of our posts priced
  ≤ q, cheapest first. A buyer takes the cheapest first, so our cheaper unit would have
  gone instead. The record must come from after we posted. A sold unit brings
  price × 0.95, less a deposit for each 24 h posting it waited through.
- **Unsold after 7 days:** relisted once at the lower of its price and 1c under the
  cheapest ask, for 7 more days. Still unsold, it's vendored after losing a deposit per
  day posted. "Vendor mark" values anything left at the end at Vendor Price; "market mark"
  at the cheapest ask then, after the cut, capped at its post price. The truth is between
  the two.
- **Grader bounds:** on own Listings, the sale records catch about 57% of real sales
  (27 of 47 Sold mails matched) and about 69% of what they call sales are real (27 of 39,
  `p6`). Runs at 0.65× and 1.2× each record's units bracket that.
- The 5s effort is a policy input only; the grade counts gold. Flips to Disenchant are
  left out of the Brain's options (their mats aren't simulated).

Policies:

- `brain`: `recommend_market` at each Scan with the simulated gold, its Shopping List
  taken like `brain replay` does (`replay._taken`).
- `brain_relaxed`: the same, but with no cheap-stock cutoff, 1 Sale Event, Holdings priors
  and margin 0.
- `buyunder`: the previous Scan's Buy Unders as standing orders (§5).
- `ev`: §2.2.
- `ev v2`: §2.2 plus three changes I made **after seeing v1 lose**, so it's in-sample:
  sales and watched hours lose half their weight every 3 days, prices are projected to
  keep falling at the past 3 days' market-wide rate for half a week, and κ 0.5 → 0.35
  (the 69% classifier precision × 0.5).

### 6.2 Results (buys through Sep 30, graded to Oct 8)

| Policy | P&L, vendor mark | P&L, market mark | Grader ×0.65 / ×1.2 (vendor; market) | Buys | Units sold | Won / lost | Worst trade | Max drawdown | Gold low |
|---|---|---|---|---|---|---|---|---|---|
| Brain as is | −10.5g | +1.1g | −12.5 / −8.2g; −8.6 / −4.9g | 82 | 651 of 685 | 58 / 24 | −6.6g | 26% | 0.0g (under 1g on 16 Scans) |
| Brain, gates loosened | **−37.7g** | **−27.5g** | | 86 | 940 of 1,159 | 47 / 39 | **−21.8g** | 27% | 0.0g |
| Buy Unders | −18.0g | −16.8g | | 70 | 683 of 714 | 26 / 44 | −6.6g | 37% | |
| EV v1 | −19.9g | −7.9g | −25.6 / −18.1g; −10.9 / −3.2g | 387 | 7,660 of 8,213 | 262 / 125 | −2.3g | 19% | |
| **EV v2** (in-sample) | **−9.4g** | **−0.2g** | | 407 | 8,862 of 9,274 | 285 / 122 | **−2.5g** | **17%** | 19.9g |

Other runs, same setup: no relist, vendor at day 7: Brain −17.1g / +2.5g, EV v2
−11.3g / +2.6g, loosened −44.6g / −21.9g. Brain with Days to Sell 3 days: identical to as-is.
With 2 days: −10.5g / −5.7g. Brain with 12 h Observation Windows (full-period run, buys
to the end): −43.3g / −2.5g vs the Brain's −46.7g / +15.2g. Files:
`probes/out/p4_*_lb*.json`, `p4_*_wide.json`.

**Noise:** the Brain at the 1.2× bound came out *worse* at the market mark than at 1.0×,
because each run's buys depend on its own gold path. Treat differences under about 5g as
noise.

### 6.3 What it shows

1. **Loosening the gates is the worst option tested.** Same Brain, no cutoff, minimum 1,
   margin 0: it loses 3–4× more than the Brain as is, with a single −21.8g trade (half
   the starting gold). The owner's instinct ("we can't assume every trade works out") is
   right, but just "taking more risk" without sizing is how you lose.
2. **Expected value + caps matches the Brain on money, with far less risk per trade.**
   EV v2 lands where the Brain does (−9.4g vs −10.5g at the vendor mark, −0.2g vs +1.1g at
   the market mark: noise). But it spreads the gold over 5× as many trades, never risks
   more than 5% of the bankroll on one (the Brain risked up to 25%), its worst trade is
   −2.5g instead of −6.6g, and it never ran out of gold. That's what sizing buys: the
   same average with a much narrower spread.
3. **The money is in what sells in the first week, and the losses are in what doesn't.**
   EV v2: lots that sold out in week 1 made +40.9g on 66.7g spent (+61%); lots that needed
   the relist lost 47.2g on 36.7g. Brain: +18.5g on 73.5g vs −29.9g on 36.4g. EV v2's
   unsold units lost **20.1g in deposits** from being reposted daily, about 5.5× their
   vendor value (the 24 h deposit is 60% of the Vendor Price, `config.py:126`). So the
   number that decides profit is "chance it sells within a few days", and a non-seller
   must be cut quickly. The no-relist runs show the exit rule alone doesn't fix it,
   though: the entry has to predict speed better.
4. **Big tickets lost, small ones won**, for both policies: buys costing 1–4g lost 10.5g
   (EV v2) and 7.0g (Brain); buys under 20s made +1.5g in total for each policy (284 and 25 lots). The Brain's 6 buys over 4g
   lost 7.2g.
5. **Buy Unders lose as standing orders** (§5).

### 6.4 Why this history can't settle it

- **12 days, and only 5 of them can carry a buy with a week to sell.**
- **The market fell:** the median Fair Value dropped 6% from Sep 30 to Oct 8 over 2,080
  items. EV v1's losses were on items whose price ended under its cost (−15.1g, 77 lots)
  or that vanished from the AH (−11.2g, 65 lots). On items whose price held it made
  +6.4g (245 lots). Beta prices drift down as supply grows; Live after launch will drift
  too, likely faster.
- **The grader is blind most of the time.** 216 of 294 hours are in gaps over 12 h, where
  only shrinking stacks show sales. It catches about 57% of real sales.
- **Without the buy cutoff** (buys to the end), every policy has 30–64g of inventory open
  at the end, and the vendor vs market mark swings each result by 40–60g
  (`p7_backtest_table.md`).

The owner's real gold went from 17.5g (Sep 26) to 40.4g (Oct 8), from the Character
Reads (gold summed per day), about 12g of it the 13114 trade (§5); the rest is play and other sales (**guess**: I didn't separate them). That's real money,
made by a concentrated bet that happened to work.

---

## 7. What to change, in what order, and how to check it worked

Ordered by what unblocks what. Each step has a check. Run it as a walk-forward backtest
like `probes/p4_backtest.py`: buys stop a week before the data ends, it grades against
later sale records, and it reports P&L at both the vendor and the market mark, at the
0.65× and 1.2× grader bounds, plus the worst trade and the drawdown. Row counts don't
count as a check.

1. **Build the yardstick first.** Port the backtest's grader into `brain replay`, or
   replace the replay's grader with it: per-Listing sale records from every gap (§2.3),
   your posts filled only by later sales at or above their price, one markdown relist,
   then vendor. Calibrate it on your own Listings against the mail (`p6`) and report the
   two bounds. *Check:* the 6 policies here reproduce within noise. Without this step,
   every later change is judged by the Brain's own optimistic Sale Events.
2. **Stop the cheap-stock cutoff from zeroing demand on almost no evidence** (§8, first
   bullet): bring back a power test (only cut once the watched hours since the cheap stock
   appeared would have *expected* about 2 or more sales at the old rate), and replace "after
   24 h unwatched, nothing sells" with a discount. *Check:* the list no longer collapses
   after a day away (rows per Scan, `p5`), and the backtest P&L for `brain` doesn't fall.
   This is the cheapest fix for the owner's "2 rows".
3. **Feed the Sell Rate the evidence you have:** Partial Sales from every gap, and
   vanished Listings from gaps up to 12 h whose bucket rules out expiry, with per-gap
   exposure (§2.3, §8). *Check:* watched hours go from 14 to about 78 on this history; the
   classifier accuracy on own Listings (`p6`) holds up; the backtest doesn't get worse.
4. **Add the risk caps to the Shopping List** (§2.2): per item 10% of the bankroll, worst
   case per buy 5%, 60% at most tied up, and the brake. Show them as a fold or warning, so
   the owner still chooses. *Check:* the worst trade and the drawdown in the backtest
   shrink, and P&L holds.
5. **Replace the Sale Events minimum and the margin with expected value** (§2.2), keeping
   a 10% EV cushion. Price each run at a few post prices and keep the best (§3). *Check:*
   compare against the step-4 Brain on the same backtest, both bounds. Adopt only if it
   wins at the vendor mark *and* the market mark at the 1.0 bound and isn't worse at 0.65.
   **What to aim the EV at:** the backtest says profit comes from units that sell in the
   first few days and losses from the rest, mostly deposits (§6.3). So make the EV's
   key number "chance of selling within 3 days" and rank by it; charge the full
   deposit stream for unsold days; and when a post expires unsold twice, the Brain should
   say Vendor or cut the price, not repost. Weigh recent sales more than old ones and
   project a falling market forward (EV v2).
6. **Make the effort charge a visible setting** (default 1–2s for Disenchanting) (§4).
   *Check:* Flips to Disenchant rows appear on most Scans. Grade them in the backtest
   once mats are simulated (not done here).
7. **Grade the Buy Unders before showing them**, and give them the "has the price moved"
   test (§5). *Check:* their backtest P&L turns non-negative, or show fewer of them.
8. **After Live opens (Nov 4), re-fit the guesses** (κ, the 10% cushion, the caps) on the
   first Live weeks, with a held-out week. On Live, don't change parameters within a week.

The order matters: 1 makes the rest measurable. 2 is the quick win. 3 is what lets 5
work. 4 limits the damage while 5 is tuned.

---

## 8. Where I disagree with past decisions

- **ADR-0029 removed the power check from the cheap-stock cutoff.** ADR-0028 only cut
  demand when enough hours had been watched since the cheap stock appeared to *expect* 3
  sales at the old rate. ADR-0029 dropped that test because Lesser Magic Essence slipped
  through it (2.1 expected < 3). Without it, a 21-minute window decides 495 items (§2.1),
  and the list collapses after every day away. A statistician would say the test has no
  power: zero sales in 21 minutes is what you'd see whether the price crashed or not.
  Keep the cutoff's idea (old demand at the old price is stale once cheap stock sits),
  but weigh it: count the sales before the cutoff at a discount that grows with the
  watched hours since and with how cheap the new stock is, instead of keeping all or
  none. The LME case is still caught, because a thick item gets many watched sale-free
  hours quickly. Also don't zero demand after 24 h unwatched (`sell_rate.py:68-69`);
  unwatched means unknown, so shrink and size down instead.
- **ADR-0004's 60-minute cap is too tight for this player's pattern.** Its worry is that
  long gaps undercount sales while the hours still pass. That's a bias toward fewer sales,
  the safe side, and the time-left bucket already filters expiries. On own Listings, 1–12 h
  gaps classified as well as ≤1 h ones (74% vs 58% sold, §1.3), and Partial Sales are
  certain in any gap. Using gaps up to 12 h gives 78 watched hours instead of 14. The
  "two denominators" objection goes away if each gap's hours count as exposure only for
  the buckets that can't have expired over it (a bucket-4 Listing is watchable for 12 h).
  In the backtest, giving the Brain 12 h windows alone (`brain_wide` policy) didn't make it profitable (−43.3g / −2.5g vs −46.7g / +15.2g, full-period runs)
  (§6), so this is a *data* fix that the EV rule needs, not a fix by itself.
- **ADR-0017 sizes every option "as if the only buy", with no total limit.** That was the
  owner's request (see options, choose), and it's fine for display. But nothing then
  limits how much of the gold is at risk at once. In the backtest the Brain policy spent
  down to under 1g of gold repeatedly, and the owner's real 13114 trade put 99% of gold in
  one item. Keep options, add the caps of §2.2 as a fold or a warning ("this would put 40%
  of your gold in one item").
- **ADR-0006 is the right model, applied too narrowly.** Predictions already get Max Loss,
  per-item and total caps, and a brake on a losing record. Flips should get the same,
  with expected value on top (Flips, unlike Predictions, have market data for the upside).
- **ADR-0019 says Buy Unders can't be graded honestly by a replay.** They can, as standing
  orders against later Scans (§5), and graded that way they lose. Grade them before
  showing 195 of them.
- **ADR-0015's replay grades with the Brain's own Sale Events** (also the previous
  review's finding 5). My backtest grades with a wider, per-Listing sale record and a
  calibration on own Listings (§6); I'd make that, or something like it, the yardstick.
- **The 5s effort per non-stacking unit (#73)** is a preference, not a market fact, and
  it silently decides the Flips to Disenchant tab (§4). Make it visible and settable.

I agree with: the cheap-stock idea itself, the 1.2× Fair Value cap (cheap, small, right
direction), merging Sale Events per window for *counting*, Days to Sell as a buy cap,
the Prediction brake, and refusing to price Predictions' upside.

---

## 9. What's measured and what's a guess

**Measured** (probe outputs in `probes/out/`): the per-check counts (§1.2); the watched
hours and the evidence the 60-minute rule drops (§1.3); classifier accuracy on own
Listings (small samples: 12 and 27 matched Listings); the rows-per-Scan collapse after
long gaps; where sales sit in the book (§3); the Flip to Craft and Disenchant traces (§4);
the Buy Under, Brain and EV backtests and their breakdowns (§5, §6); the 6% price drop.

**Guesses:**

- κ = 0.5 (v1) / 0.35 (v2), the demand discount for prime-time watching and being
  undercut. The previous review estimated prime time at maybe 2× the daily average; nobody
  has measured it here.
- The 10% EV cushion; the 10% / 5% / 60% caps and the 20% brake. They're conventional
  sizes for many small bets with an uncertain model, not fitted.
- EV v2's 3-day half-life and "half a week" of drift: picked once, after seeing v1, not
  searched over. It's in-sample.
- "Vendor if it doesn't sell" as the EV's fallback, and the backtest's one-relist rule:
  real players do something in between.
- That 1–2s is a fair effort charge for a Disenchant.
- That the power test I propose for the cheap-stock cutoff (about 2 expected sales)
  catches the LME case. I checked the logic against ADR-0029's numbers (2.5 Sale Events
  an hour before, so under an hour of watching is enough), not by rerunning it.
- Whether Live will look like Beta. Beta prices fell 6% in a week; Live after launch
  likely falls faster, which hurts any buy-and-hold more than flips that sell fast.

**Known limits of my backtest:** fills come from other players' sales, so it can't see
our post being undercut by a seller who then sells first at a lower price (that would make
it optimistic), and it misses about 43% of real sales (pessimistic). Bought listings stay
in the later Scans, so a real buyer of the cheap listings we "bought" isn't removed from
demand; that only matters if they'd also have paid our higher price. Flips to
Disenchant aren't simulated. Deposits are charged when a lot closes, not when posted, so
the simulated gold can dip below zero.

---

## 10. Probes

All run with `Z:\vibing\azerothquant\.venv\Scripts\python.exe probes\<name>.py` (from `probes/`).
They import `code/brain/src` (identical to the live venv's code, modulo line endings) and
work on a private copy of the history in `probes/_work/` (`common.py`), so nothing in
`data/` is written. Outputs are in `probes/out/`.

| Probe | What it does | Output |
|---|---|---|
| `p1_funnel.py` | Why-not verdicts and each check alone on the latest Scan; Shopping List with one gate relaxed at a time | `p1_funnel.txt`, `p1_*.json` |
| `p2_evidence.py` | Observation Window hours by day; Disappearances by gap and expiry; Sale Events with and without the 1.2× cap | `p2_evidence.txt` |
| `p3_sales.py` | Table of every sale-like record over every gap (Partial Sales; vanished Listings that can't have expired, Reposts paired off) | `p3_sales.txt`, `_work/sales.pkl` |
| `p4_backtest.py` | Walk-forward backtest over the 69 Scans with its own gold and inventory (policies `brain`, `brain_relaxed`, `brain_wide`, `buyunder`, `ev`, `ev_nosize`) | `p4_*.json` |
| `p5_craft_de.py` | Flips to Craft and to Disenchant traced on the latest Scan; rows per Scan for all 69 | `p5_craft_de.txt` |
| `p6_own_truth.py` | Accuracy of the sale classifier on own Listings, against the mail | `p6_own_truth.txt` |
| `p7_report.py` | Backtest table | `p7_backtest_table.md` |
| `p8_post_price.py` | Where in the book sales happen (price over cheapest ask, levels swept) | `p8_post_price.txt` |
| `p9_effort.py` | Shopping List with the non-stacking effort at 5s, 2s, 1s, 0 | `p9_effort.txt` |

Also `probes/out/brain_flips.txt` (`brain flips` on the work copy) and
`probes/out/own_view_before_docs.md`.
