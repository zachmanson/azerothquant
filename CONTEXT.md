# azerothquant

A personal Auction House trading system for World of Warcraft: Forever. An in-game addon collects market and personal data, and an offline program analyzes it and sends back per-item recommendations that the player carries out by hand.

## Components

**Addon**:
The in-game half. It records market and personal data and shows the Recommendation Table. It acts only on the row the player selected, one protected action per click (post or cancel), and never buys, bids or takes mail (ADR-0016). Cancel waits on #134.
_Avoid_: bot, automation

**Brain**:
The offline half. It imports what the Addon collected into a persistent history and runs the Decision Engine over it.
_Avoid_: backend, server

**Decision Engine**:
The part of the Brain that scores every Action for each Candidate Item and ranks them.
_Avoid_: model, AI

## Market data

**Era**:
Which economy data comes from: Beta or Live. The Live economy starts from zero at launch, so data from the two Eras is never mixed: no decision reads the other Era, with one exception. The Beta Prior only puts a Beta price on screen beside Live's. The exception is the Beta Sell Rate, which may count toward a Prediction buy's Max Loss room early in Live, when switched on (ADR-0024).
_Avoid_: season, phase

**Market**:
One Auction House in one Era, identified by realm, faction (Alliance, Horde or Neutral) and Era. Every price and quantity only means something within its own Market.
_Avoid_: server, AH (when you mean the data scope)

**Beta Prior**:
A Beta price shown next to each Recommendation Table row early in Live, as a reference the player reads and never a decision: the Decision Engine doesn't use it, though it may use the Beta Sell Rate. It is the raw price, not scaled to Live: the median Sale Event price over Beta's last 14 days where there are at least 3 Sale Events, else the median of the daily Fair Values over Beta's last 7 days, marked as listed, not sold. It comes from the Beta Market of the same faction, or else the Alliance one, and the row's side pane names that Market and its Beta Sell Rate. It shows for `beta_column_days` (14) from the Live Market's first Scan, then goes away (#90).
_Avoid_: Beta price as a prior or input (it's display only)

**Beta Sell Rate**:
The Sell Rate of the Beta Market a Live Market's Beta Prior comes from. The row's side pane shows it, and for `beta_column_days` from the Live Market's first Scan, a Prediction buy's Max Loss room may count it (`beta_sell_rate_weight`, 0 and so off by default). Each Beta Sale Event priced at or above the Live post price times the Item Key's Beta/Live Fair Value ratio counts as that share of a Sale Event, and each Beta Observation Window hour as that share of an hour, added to Live's, so Live takes over as its own hours build. Only demand is borrowed, never a price, and nothing else reads it: not Flips, Flip to Craft, Holdings or Buy Under (#110, ADR-0024).
_Avoid_: Sell Rate Prior (that's empty hours added, not events borrowed)

**Scan**:
One full pass over every Listing on the Auction House, as it stood at the moment the Scan was requested.
_Avoid_: snapshot, dump

**Mailbox Read**:
The Auction House mail in one Character's inbox (sales, purchases, cancellations, expiries), exactly as it stood at one moment of a mailbox visit. A visit saves one when the mailbox opens and another each time that mail changes, so a mail taken moments after opening is still in an earlier one. Other mail, such as COD and player letters, is left out. Mail stays until the player takes it, so the same mail shows up in every Mailbox Read until then. A mail missing from the next complete Mailbox Read was taken; one with nothing left attached is on its way out, and one the Brain can't read (a header or invoice the client hadn't loaded yet) makes the Read incomplete.
_Avoid_: mail scan (a Scan is only ever the Auction House)

**Archive**:
Every Scan, Mailbox Read and Character Read exactly as the Addon recorded it, plus every Pooled Scan as downloaded, one file each, kept forever (a Pooled Scan the pool rolls back is the one thing deleted). It is the Brain's source of truth: the history database, and anything else the Brain stores, can be rebuilt from it.
_Avoid_: Scan Archive (it holds more than Scans), backup, raw dump

**Scan Pool**:
A shared online store of Scans that several players' Brains upload to and download from, so each player gets the Scans the others took. It holds Scans only, stripped of anything that identifies the player: Mailbox Reads, Character Reads and everything tied to an account stay in each player's own Archive. Each Brain matches pooled Scans itself, as it does its own, so the pool holds raw Scans rather than a history someone else interpreted (#117).
_Avoid_: cloud, shared database, AuctionDB

**Pooled Scan**:
A Scan from the Scan Pool that another player took. It goes into the player's Archive (under `pool/`, apart from their own) and history like one of their own Scans, but nothing in it is own. One with too few Listings next to its Market's recent Scans is taken as cut short: archived, never imported. One whose body names another Market or requestedAt than its index entry is neither archived nor imported (#149). It never counts toward what the Addon may prune.
_Avoid_: remote Scan, foreign Scan

**Item Key**:
The identity used for pricing: itemID plus random suffix, so "of the Monkey" and "of the Eagle" versions are different Item Keys.
_Avoid_: item (when you mean the priced identity), itemID

**Sibling**:
Another Item Key of the same itemID in the same Market: another random suffix of the same item. Suffixes split an item's thin history, so a held unit's Sell Rate also counts its Siblings' Sale Events at a reduced weight, but never their prices or Fair Values (ADR-0022).
_Avoid_: variant, suffix group

**Listing**:
One auction on the Auction House: an Item Key, a remaining quantity and a unit buyout, tracked across the Scans it appears in. The game shows no seller or auction ID, so a Listing is recognized by Item Key and unit buyout, and identical Listings are interchangeable. Own means one of the player's own Scans showed it as posted by the Character that did that Scan: the game hides every other seller, including the player's other Characters, and a Pooled Scan shows nothing as own. Once own, a Listing stays own (#117). Its quantity can only go down. Bids are ignored; buyout is the only price.
_Avoid_: auction, post, order, stack (a Listing can hold more than one stack)

**Disappearance**:
A Listing that was in one Scan and missing from the next. It was sold, cancelled or expired, and the game doesn't say which.

**Partial Sale**:
A drop in a Listing's quantity between two Scans. It is always a sale, since cancelling and expiring remove the whole Listing.

**Repost**:
A Disappearance that could not have expired, explained by a new Listing in the same Observation Window with the same Item Key and quantity, at the same or a lower unit buyout, own or not (a Pooled Scan shows nothing as own): most likely a seller cancelling to undercut or relist. Whenever such a pairing exists it is taken, so a Repost is never counted as a sale. The two Listings stay separate.
_Avoid_: relist, undercut (those are why a Repost happens, not the event)

**Coincidence Rate**:
The share of real sales that Repost pairing wrongly calls Reposts, because an unrelated new Listing happened to fit. It is measured on the player's own Disappearances that an Outcome shows were Sold, and it depends on how busy the Market is, not on who the seller is.
_Avoid_: error rate, false-positive rate (too generic to say which mistake)

**Probable Sale**:
A Disappearance treated as a sale because it could not have expired (the time between the two Scans was shorter than the least time its time-left bucket allows), it is not a Repost, and it was priced near or below the Fair Value of both Scans: the one it was last seen in and the one it went missing in (or only the first, if it sold the Item Key out). Cancellations without a Repost still can't be told apart.

**Sale Event**:
Every unit of one Item Key seen to sell in one Observation Window: all its Partial Sales and Probable Sales between those two Scans, whatever their prices. On Forever a buyer takes units cheapest-first across Listings and price points, and units that don't stack are one Listing each, so one buyer's sweep shows up as many drops; counted apart, they'd make one buyer look like many. A Sale Event is usually one buyer but can be several, and Scans can't tell which (ADR-0012). Its size is the units that went, and its price is the dearest of them.
_Avoid_: sale, purchase (a Purchase is the player's own buy)

**Sale Record**:
Units of another player's Listing seen to sell between two Scans in any gap, not only an Observation Window: a Partial Sale, or a Disappearance over a gap of at most 12 hours that could not have expired and is not a Repost. It is priced at most 1.2x the Fair Value of the Scan before it, and an item either Scan dropped rows of has none. Only the Backtest grades with them, as its evidence of what a post would have sold; Sell Rate still reads Sale Events (ADR-0032).
_Avoid_: sale (too vague), Sale Event (that's one Observation Window's)

**Outcome**:
What happened to one stack the player posted: Sold (with its price), Cancelled or Expired, read from a Mailbox Read. Unlike a Disappearance it is known, not inferred. It covers one stack, and a Listing can hold several, so an Outcome and a Listing don't map one to one. A Sold Outcome's mail names the item but doesn't carry it, so its Item Key is found by that name from own Listings and other Auction House mail; one whose name matches no Item Key, or more than one, is Unlinked and closes no Lot.
_Avoid_: result, receipt, invoice (an invoice is one kind of mail)

**Purchase**:
One stack the player bought on the Auction House, with its price, read from a Mailbox Read. It is how an Auction House Lot starts, as an Outcome is how one ends, but only when the Brain named it or it's under a Prediction; any other is For Use. Only Auction House buys arrive by mail, so crafting, merchant buys and loot start Lots some other way.
_Avoid_: buy, win

**For Use**:
A Purchase the Brain didn't name, so it starts no Lot (ADR-0025): not under a Prediction, and the Market's last Scan before it had no Flip to Sell or Flip to Vendor row of its Item Key, no Flip to Craft buying it as an Auction House reagent, no Flip to Disenchant buying it (named up to its dearest Listing of the Item Key, never the whole group), and no Buy Under of it or its Disenchant source group, at or over its unit price. Like loot, it's out of realized profit, Flip Grades and Paid, and a later sale closes nothing of it. What each Scan named is worked out once and frozen in `grades.toml`. `brain flips` and the replay count them. A flip made with no row behind it counts as For Use too.
_Avoid_: consumable, personal buy

**Observation Window**:
The time between two consecutive Scans of a Market, when it is short enough that almost no sale goes unseen. Only Observation Windows count toward Sell Rate; longer gaps still track Listings but add nothing to it. An item that either of its Scans dropped rows of (item data not loaded yet) is left out of it, since its Listings may only have been missed.
_Avoid_: gap (when you mean one that counts), interval

**Fair Value**:
The price an Item Key can realistically be sold at in its Market, based on the cheapest part of the supply in the latest Scan rather than the single lowest Listing. Units priced far below the rest of that cheap part are left out: they are Flips, not the price. It judges whether a Disappearance was a Probable Sale; it is not what anything is posted or valued at, since every Sell prices through the same undercut (see Sell).
_Avoid_: market value, price, min buyout

**Sell Rate**:
Units sold per day for an Item Key in a Market: the Partial Sales and Probable Sales inside Observation Windows, divided by the total time of those Observation Windows. The Decision Engine's measure of liquidity. When deciding whether to buy something to Sell (a Flip to Sell, a Flip to Craft's output, a Hold buy's Max Loss, a Buy Under's Sell way), the Sell Rate is measured at the price it would post at: only the Sale Events priced at or above it count, toward both the units a day and the minimum number of Sale Events. A buy that removes the cheapest other players' Listings and posts above them (a Flip to Sell, a Hold buy's Max Loss) also counts only the Sale Events and Observation Window hours after the Scan the stretch of cheaper stock began in: the earliest Scan from which every Scan up to the latest had another player's Listing under the post price, except for breaks of up to 2 Scans with cheap stock again before them. Stock new in the latest Scan isn't cut, and with no Observation Window hours since, the whole range counts however old the stretch is: nothing watched means the demand is unknown, not zero (ADR-0028, ADR-0029, ADR-0033). Held units use the whole Sell Rate: their gold is already spent. Theirs also counts their Siblings' Sale Events at or above the price they post at, each as half a Sale Event (`suffix_pool_weight`); a buy's never does (ADR-0022). Early in Live, a Prediction buy's Max Loss may also count the Beta Sell Rate (ADR-0024).
_Avoid_: volume, velocity

**Sell Rate Prior**:
Hours of Observation Window with no sales that the Decision Engine adds to a Market's real ones before Sell Rate becomes a quantity, so a sale or two in a short window doesn't read as a fast seller. Its effect fades as real window hours build up. Holdings get a small one and Flips a large one, since overrating a Flip spends gold on stock that sits. Sell Rate itself stays the raw measurement.
_Avoid_: pseudo-hours, thin-data discount, confidence bound

**Sale Size Prior**:
Sale Events of a typical size that the Decision Engine adds to an Item Key's real ones before taking their average size, so one big buyer doesn't make an Item Key look like it sells in bulk. The typical size is the smaller of the Market's usual Sale Event size among items that stack and the Item Key's usual Listing quantity. Its effect fades as real Sale Events build up. Holdings get a small one and Flips a large one, for the same reason as the Sell Rate Prior.
_Avoid_: stack-size cap, median sale

**Vendor Price**:
The fixed gold an NPC merchant pays for one unit of an item. It belongs to the itemID, so every random suffix of an item has the same one, and it is read from the game rather than taken from Classic, since Forever changed some. Only the player's own Scans and Character Reads supply it, never a Pooled Scan (#129).
_Avoid_: sell price, vendor value

**Merchant Cost**:
The gold an NPC merchant charges for one unit of an item it sells, such as thread or vials. It is read from the merchant window while it's open, only for items sold for gold in unlimited stock, and belongs to the Character that saw it, since reputation discounts differ. The Decision Engine uses the lowest latest-seen one across a realm and faction's Characters.
_Avoid_: vendor price, buy price

**Deposit**:
The copper the Auction House charges to post a unit, refunded when it sells and lost each time a posting expires unsold. Per unit, it's the deposit on the Item Key's latest Sold invoice divided by its count, else `ah_deposit_share` (0.60, the 24 h rate) of its Vendor Price, or nothing without one. The Decision Engine charges each unit it would post the deposits it expects that unit to lose: an Item Key's units sell in queue order (unbound held units, then the one Shopping List option's Flip to Sell or Flip to Craft outputs, each option queued as if it were the only buy, ADR-0017), and unit i of the queue waits i / (units per hour) and loses one deposit per `post_duration_hours` (24) that wait covers (ADR-0013).
_Avoid_: posting fee, AH fee, cut

## Crafting

**Known Recipe**:
A recipe the player already has, read from the profession window, with its output item, output quantity, reagents, cooldown and whether its output binds on pickup. The output quantity is a range for recipes that make a variable amount. Enchanting counts as a profession, even though most of its outputs are enchants rather than items; Beast Training does not. Only the Character's own profession windows count: a linked, guild or NPC crafting window shows someone else's recipes. At a past moment (a replay, a Grade's Best Exit Value), the Known Recipes and Enchanting skill are the ones the Character Reads up to that moment show, not today's.

**Learnable Recipe**:
A recipe the player doesn't have yet but could get, and which costs something to acquire.

## Personal history

**Character Read**:
One Character's gold, faction and bag contents as they stood at logout or `/reload`, plus its bank if the player opened it that session (the bank can only be read while it's open, and can't change while it's closed), the Merchant Costs of any merchant it visited that session, the Known Recipes of each profession whose window was opened that session (read the same way, only while open), and which professions the Character has, so a dropped profession's old recipes can be told apart. Kept in the Archive like Scans and Mailbox Reads.
_Avoid_: snapshot, inventory

**Disenchant Result**:
The materials the player actually got from disenchanting one specific item. The Addon records one for each Disenchant the player casts, with the item that left the bags between the cast starting and its loot. When it can't tell which item that was, it records only the item's Disenchant source group (if the items that left were alike) or just the mats. They travel on the Character Read of the session, and `brain disenchants` checks the static tables against them; they never change the tables themselves (ADR-0018).

**Craft Result**:
One craft the player made with a Known Recipe, and how many units of its output it made. The Addon records one for each craft of a recipe the Character's profession window was read with that session, counting the output from how many more of it the bags hold than when the cast started. When it can't tell (the output took longer than a few seconds, or the bags gained more than the recipe makes), it records no count, and the Brain counts the recipe's minimum. A recipe that makes no item is recorded with no output. They travel on the Character Read of the session as `crafts` (#44).
_Avoid_: craft log, craft event

## Decisions

**Backtest**:
A policy trading a Market's past Scans in time order on its own simulated gold (40g by default), graded by the Sale Records after each buy: a post sells to a later one at or above its price, our cheapest units first; a lot unsold after a week is relisted once under the cheapest ask, then vendored. It reports gold made at the vendor mark and the market mark. It's the yardstick for buy-side changes (ADR-0032); `brain backtest` runs it, with the Brain under a config as each policy (`brain`, `relaxed`).
_Avoid_: replay (that's ADR-0015's per-Scan grade against Auctionator and TSM). What it buys aren't Lots: those come from the player's real Purchases

**Candidate Item**:
An item the Decision Engine evaluates for a Recommendation.

**Action**:
One way out of a Candidate Item the player holds: Vendor, Sell, Craft, Disenchant or Hold. Buying is never an Action (see Flip).
_Avoid_: strategy, play

**Sell**:
The Action of posting an item on the Auction House for other players to buy. Held units are posted just under the cheapest other player's Listing (matching an own Listing that's cheaper), never above the highest price among its and its Siblings' Sale Events or its Merchant Cost, with nothing on the Shopping List assumed bought, since its options are alternatives (ADR-0017). A Flip to Sell is posted the same way once its own run is bought, except that no Sale Event caps it: its Sell Rate counts only the Sale Events at or above its price instead (see Flip). With no Listing left there is no Sell price, and held units go to Vendor. Best Exit Value values Sell the same way, at a past Scan too. A held unit Sells only while its price after the cut, less the Deposits it's expected to lose waiting its turn, beats the Vendor Price, so a slow seller's tail goes to Vendor.
_Avoid_: post, list, flip (a Flip is a buy)

**Craft**:
The Action of turning held reagents into a Known Recipe's output. A craft is worth doing when the output Holding's exit value with the crafted units added gains more than the consumed reagents' exit value loses. Missing merchant reagents are bought at their Merchant Cost, reagents Held under a Prediction are never used, and output is counted at the recipe's minimum quantity. The reagents are pooled across a realm and faction, and the Recommendation names the Character that knows the recipe. Enchants that make no item are not Crafts. Buying reagents on the Auction House to craft is a Flip, not this Action. A short reagent can be crafted first with another Known Recipe, a Sub-craft, so a Craft can be a chain (ADR-0014).
_Avoid_: make, produce

**Sub-craft**:
Crafting a reagent a Craft or Flip to Craft is short of, with another Known Recipe, whose own reagents are sourced the same way, down to `craft_chain_depth` crafts deep counting the top one. Each reagent comes from held units first, then a merchant (never Sub-crafted), then one source for the rest: a Sub-craft or, in a Flip to Craft, the Auction House, whichever costs less. A Sub-craft never uses an Item Key already on its path, and a Craft Action's Sub-craft surplus joins the crafted Holdings (a Flip to Craft's doesn't, since it's only an option, ADR-0017). It isn't a row of its own: the top Craft row lists it under `via` and carries its reagents and profit (ADR-0014).
_Avoid_: intermediate craft, chain step

**Craft Chain**:
The tree of one Craft row's sources and exits, as the Brain writes it (`chain`) and the Addon's panel draws it. Its roots are the exits (Sell at the post price, Vendor, or both when the output outruns the Sale Horizon), the last over the top craft on its Character, and under each craft what feeds it: held units used, Auction House buys, merchant buys, Sub-crafts and a Sub-craft's leftover. Quantities are the row's totals. Each node's gold is what the craft's costing counted for it, so every node but a craft (which sums the sources under it) adds up to the row's Profit. A blocked Craft row's chain is one craft as it would be sourced, with no exit, and the node that blocks it marked (ADR-0014).
_Avoid_: recipe tree, breakdown

**Disenchant**:
The Action of destroying a held unit of armor or a weapon for its mats, by a Character whose Enchanting skill (from its latest Character Read that has one) meets what the unit's item level needs. What a unit yields comes from the static tables for its Disenchant source group, as expected quantities, so they come in fractions. A unit is worth Disenchanting when its expected mats gain more, added to the mat Holdings, than the unit would bring by Sell or Vendor: the same marginal rule as Craft, bound units first, and never for an Item Key Held under a Prediction (ADR-0018). A bound unit can't be mailed, so only the Character who holds it can Disenchant it; unbound units go to whoever can.
_Avoid_: DE, salvage

**Disenchant source group**:
The items that Disenchant alike: one quality (uncommon, rare or epic), armor or weapon, and one item-level band. An item that can't be equipped, a shirt, a tabard or an enchanter-made wand is in none.
_Avoid_: DE bracket, tier

**Flip**:
Buying on the Auction House because the price is below that Item Key's Best Exit Value after costs, whether the way out is Sell (buy cheap and repost), Vendor (buy under Vendor Price), Craft (buy the reagents a Known Recipe is missing, then Sell or Vendor its output) or Disenchant (buy armor or weapons to Disenchant, see Flip to Disenchant). A Flip is a Shopping List Recommendation, not an Action. A Flip to Craft buys only what held reagents don't cover, on the Auction House or as the reagents of a Sub-craft, whichever costs less, and its output is valued with a Flip's priors (ADR-0009). A Flip to Sell is posted just under the cheapest other player's Listing left once its own run is bought, so it sells first (matching an own Listing that's cheaper). It buys whichever run of the cheapest Listings makes the most profit with every unit clearing the Flip margin; with no Listing left it isn't a Flip to Sell. The Shopping List shows a Flip to Sell whole, or else the most profitable run the Budget covers that still clears the Flip margin, never part of a run priced as if the rest were bought (ADR-0011). Its Sell Rate counts only the Sale Events at or above the price it posts at, and a way out through Sell needs a minimum number of those Sale Events (3 by default, so sales in 3 separate Observation Windows), since with fewer a single cancel could be the whole story. Once cheaper stock than it posts at has been up across Scans and an Observation Window has watched it since, only the Sale Events since that stretch began count: buying out a crash doesn't bring the old price back (ADR-0028, ADR-0029, ADR-0033). So above the dearest Sale Event nothing sells, and a run that buys through to a dear Listing can lose to a shorter one that posts lower. That holds for a Flip to Craft's output, for the resale a Hold buy's Max Loss assumes and for a Buy Under's Sell way too; short of it, the way out is Vendor or nothing. Nor is any Sell price, a held unit's included, ever above an Item Key's Merchant Cost: nobody pays more on the Auction House than a merchant charges, so that's the ceiling, with the undercut of other Listings still applying under it. A Flip also pays an effort cost (`non_stacking_effort_copper`, 5s by default) on Item Keys that don't stack, ones no Listing was ever seen with more than one unit of: once for each unit it buys and once for each unit it posts, since each is its own buy and its own post. So a Flip to Sell pays it twice a unit and must clear the Flip margin after that, a Flip to Craft pays it on each such reagent bought on the Auction House and each such output that Sells, and a buy to Vendor only on the buy. Holdings never pay it: those units are held already. Each unit a Flip posts also pays the Deposits it's expected to lose, queued behind the held units. The last unit of a run waits longest, so it's the one that must clear the Flip margin. The Flips to Sell the player actually makes are graded: see Flip Grade.
_Avoid_: snipe, arbitrage

**Flip Grade**:
How a Flip to Sell the player made turned out against what the Brain named, a report that never feeds back into decisions (ADR-0023). A Purchase not under a Prediction is a Flip made when its Item Key had a Flip to Sell on the Shopping List as of the Market's last Scan before it, and its unit price is at or under the dearest Listing that row bought; every such Purchase of an Item Key matched to the same Scan's row is one Flip, so a run straddling a new Scan is two. The Brain works out each such Scan's Shopping List again once and freezes its Flip to Sell rows (Post at, Profit, units, days, the Sale Horizon then) in `grades.toml`, so the grade judges what the player was shown. A Sale Horizon after the first Purchase, it's graded like a Prediction: its units Sold by then (through its Lots, oldest first, so held units sell ahead of it, but not For Use ones, which have no Lot) at their price after the Auction House cut, plus its still-open units at their Best Exit Value then, against their cost. It Paid off when that's positive. Deposits are left out, since an Expired or Cancelled Outcome can't be pinned to one Flip; units that leave without a Sold Outcome stay open (ADR-0007). It is frozen too. `brain flips` lists them, and `brain recommend` sums them up under the graded Predictions. A Flip to Craft gets a Flip Grade too (ADR-0027): it's matched by its reagent Purchases (each of the row's Auction House buys at or under its most to pay), and graded on the output Lots that crafts of the row's recipe opened from them, found through those Lots' lineage, against the output Lots' cost. Its expected Profit is scaled by the output units graded. One whose craft used uncosted reagents, or that wasn't crafted by the horizon, is counted as not gradable. Its record is kept apart from the Flips to Sell's.
_Avoid_: trade score, flip result

**Prediction**:
A call the player writes down from game knowledge that a group of Item Keys will be worth much more after a Catalyst, with the reason. It names no target price: the Decision Engine never estimates the upside, it only allows buying and Holding those Item Keys while the Max Loss stays small. Nor does it allow buying an Item Key at or above its Merchant Cost after the Auction House cut, since no Sell can fetch more than that (ADR-0006). Units of those Item Keys the player already holds are Held under it too, costed at their Best Exit Value on the day it was written, since that is the gold given up by not letting them go. It ends when the player marks its Catalyst as happened, or when it Lapses. Its units are the ones held when it was written (as of the start of that day) plus every Purchase of its Item Keys from then until it ends. It is graded by the realized return on the gold it tied up, from Outcomes, never by the player's own judgment: once a Sale Horizon has passed after it ended, its Sold units at their price after the Auction House cut, plus its still-open units at their Best Exit Value at that moment, against their cost. A Grade never changes afterwards: the Brain freezes it, and the held units' cost at writing, in `grades.toml` the first time it works them out. A Flip to Sell's grade is a Flip Grade.
_Avoid_: thesis, tip, hunch, bet

**Catalyst**:
The game event a Prediction waits for, such as a raid release or a new phase. The player marks it as happened; the Brain never guesses it from prices.
_Avoid_: trigger, event (too generic)

**Lapse**:
A Prediction ending because its Catalyst wasn't marked as happened by its lapse date. Its units go back to their best Action without the Prediction. Without it, a wrong Prediction would hold gold forever and never be graded as wrong.
_Avoid_: expiry (that's what happens to a Listing), invalidation

**Max Loss**:
For a unit bought or held under a Prediction, what it cost minus its Best Exit Value without the Prediction: what is lost if the Prediction turns out wrong and the unit is let go at today's prices. A Hold buy's resale counts the demand at its post price as a Flip to Sell's does, only since the stretch of cheaper stock than its post price began (ADR-0028, ADR-0029).
_Avoid_: risk, downside

**Lot**:
A quantity of one Item Key acquired together at one cost, tracked until it is sold. Realized profit is measured per Lot. Lots belong to a realm and faction, not a Character, since units move between Characters by mail the Brain doesn't see. There are two kinds: one per Purchase the Brain named or bought under a Prediction (not For Use), at its price, and the units already held when a Prediction is written, at their Best Exit Value that day. Writing a Prediction ends the open Lots of its Item Keys and folds their units into that second kind. A Sold Outcome closes units, from the oldest Lot first, and so does a Craft Result for the reagent units it used up, though never a Prediction's. A craft starts a third kind: a Lot of its output at what its reagent units cost, plus the Merchant Cost of merchant reagents, but only when every reagent unit is costed, and never of an Item Key under a Prediction standing then. A crafted Lot records its lineage: the Lots its craft used up and how many units of each, so a Flip to Craft can trace its bought reagents to the output. A unit that leaves any other way (vendored, disenchanted, mailed off) stays open, because the Brain can't tell which of those happened. Loot, merchant buys, For Use Purchases and crafts from uncosted reagents don't start Lots.
_Avoid_: position, stack (a stack is an in-game bag concept)

**Paid**:
What a held Item Key's units cost, per unit, from its open Lots not tied to a Prediction (a Purchase's, or a craft's output), with how many units that covers. Held units take the newest open Lots first: open Lot units beyond the held ones are taken to be the oldest, gone without a Sold Outcome (vendored, mailed off). Looted, farmed and For Use units have no cost, nor do those crafted from any uncosted reagent unit, so a Paid can cover only some of the held units. A Holdings Sell or Vendor row's ROI is what one unit nets by its Action after the cut against its Paid; a Sell whose ROI reaches `roi_hint` is hinted at as a good time to sell, a hint only (ADR-0003).
_Avoid_: cost basis, buy price

**Best Exit Value**:
The most one unit of an Item Key is worth via its best Action, where Disenchant values its outputs at those outputs' own Best Exit Value. Craft chains backward instead: a Craft's short reagents can be Sub-crafted, but its output is valued by Sell and Vendor only, never by crafting it further (ADR-0014). Best Exit Value itself counts no crafts, and takes nothing on the Shopping List as bought (ADR-0017). Units valued together share the Disenchant mats' worth: held mats, and the mats other Item Keys yield, take the Sale Horizon first (ADR-0018).
_Avoid_: value, worth

**Flip to Disenchant**:
A Shopping List option that buys other players' Listings of one Disenchant source group's items on the current Scan, to Disenchant them and take the mats' way out (ADR-0017). It's one option per group, since its units share the mats' room. It buys the cheapest Listing left while one more Disenchant's expected mats, valued at the margin (held mats take their room first, then the option's own earlier Disenchants), less the effort of buying a unit that doesn't stack, clear the Flip margin on its buyout and the Budget covers it, and stops at the first that doesn't. A Listing only counts if Disenchant is its item's best way out, so it never repeats a better Flip to Sell or Vendor. A mat that feeds a Craft is valued by that Craft, as in a Buy Under, but the option never buys the Craft's other reagents. It needs a Character who can Disenchant the whole group. It has its own **Flips to Disenchant** tab, cut to `disenchant_list_rows` (10) by Profit, and isn't graded.
_Avoid_: DE flip, disenchant snipe

**Buy Under**:
The most one unit of an Item Key is worth paying on the Auction House, worked out ahead of the Scan from its best way out (Vendor, Sell, a Craft it's a reagent of, or Disenchant), less the Flip margin and effort cost. It exists so the player can buy short-lived Listings live, since Scans every 15 minutes miss them. Its Sell way counts only the Sale Events at or above the price it would post at, like a Flip's. It shows only if past Scans saw a Listing at or under it. A Disenchant source group has one too: the most any item in it is worth paying to Disenchant, seen through Listings of any of its items. An item is flagged by the higher of its own and its group's. It isn't an Action and isn't a Flip: the Addon only flags it, and the player buys (ADR-0003, ADR-0019).
_Avoid_: snipe, target price, max price

**Loot Alert**:
The Addon's raid-warning text, sound and chat line when the player loots a drop whose one unit is worth at least the threshold: the greater of `loot_alert_share` (10%) of the Market's pooled gold, as of the last Character Read, and `loot_alert_floor` (10g). One unit is judged, not the stack, so a pile of cheap mats never fires one, though the line still shows the quantity and total. The worth is the unit's Best Exit Value with its Action, valued alone: no held unit of the Item Key takes a way's room ahead of it, since the question is what the drop is worth, not what it adds to the bags. Only the player's own "You receive loot" lines count: not what they create, buy, get in the mail or as a quest reward, nor a Disenchant's mats. An Item Key no Scan has seen (a Bind on Pickup drop) gets none. Display only (ADR-0003).
_Avoid_: drop alert, loot popup

**Recommendation**:
The best Action for one Candidate Item, with quantity, price ceiling, the full Action path, expected profit and return per day.
_Avoid_: signal, tip

**Recommendation Table**:
The Addon's in-game view of one Market's Recommendations (Holdings, Shopping List, with its Flips to Craft and Flips to Disenchant in their own tabs, Prediction buys, and the Buy Unders) as of the Scan the Brain last valued. It shows them, and posts or cancels only the row the player selects, one click per action (ADR-0016). Only Post exists so far; Cancel waits on #134. It shows the Market of the Character's own faction, the only one the Brain recommends for. Its side pane shows the row under the mouse, or else the selected one: what to do with it, its Note and details, and any value the table is too narrow to show (#160).
_Avoid_: UI, window, panel

**Sale Horizon**:
How long the player is willing to wait for held units to sell. Only the units Sell Rate says will sell within it are worth Selling; the rest go to the next best Action, and a Flip never buys more than will sell within it (nor within the Days to Sell, if shorter). Held units take it first: a Flip to Sell gets only the room left after the held units that aren't bound (after the Craft Actions), even ones that end up Vendored, since their gold is already spent and a Flip is optional. Best Exit Value follows the same rule.
_Avoid_: timeout, patience

**Shopping List**:
The Recommendations for things to buy on the Auction House, as options: each Item Key's Flip to Sell and Flip to Vendor, each recipe's Flips to Craft, and each Disenchant source group's Flip to Disenchant, sized as if it were the only buy within the Budget and the risk caps (its Unsold Loss and the gold tied up in posts, each a share of the Stake), and priced after only its own buys. The most profitable options are shown first, Flips to Sell and Flips to Vendor in the top `shopping_list_rows` (50) by any of Profit, Per click, Per day (Flips to Sell only) or ROI, Flips to Craft up to `craft_list_rows` (25) by Profit, in their own tab, and Flips to Disenchant up to `disenchant_list_rows` (10) by Profit, in theirs. Taking two may need more than the Budget, and the player picks (ADR-0017).
_Avoid_: buy list, snipes, basket

**Per click**:
A Flip to Sell's or Flip to Vendor's Profit for each click it takes: each Listing it buys (in Era every Listing is its own buyout) and each stack it posts, at the Item Key's usual Sale Event size. A Flip to Vendor posts nothing.
_Avoid_: profit per action, effort

**Per day**:
A Flip to Sell's Profit for each day until its last unit sells: the unbound held units ahead of it and its own units, at the Sell Rate under the Flip priors, the same queue the Deposits use. The days are at least one, so a Flip that sells within a day has its Profit as its Per day: a one-off Flip that sells in an hour can't be made again all day. A Flip to Vendor sells now, so it comes before any Flip to Sell.
_Avoid_: profit per hour, velocity

**Budget**:
The most gold the player will spend in a Market, set in the Recommendation Table and carried to the Brain in each Character Read. Each Shopping List option, and the Prediction buys, spend up to the lesser of it and the pooled gold. None set means all the gold. The Prediction caps stay shares of the pooled gold (ADR-0006).
_Avoid_: bankroll, allowance

**Stake**:
What the player is trading with in a Market: their pooled gold plus their own Listings up on the Auction House, each at what it cost (Paid where known, else its Best Exit Value). Bags and bank aren't in it. The Shopping List's risk caps are shares of it (#170). It isn't the Budget: the Budget is what the player will spend, the Stake is what one bad buy is measured against.
_Avoid_: bankroll, net worth

**Unsold Loss**:
What a Shopping List option loses if none of it sells: its cost, less what its units (a Flip to Craft's output, a Flip to Disenchant's mats) vendor for, plus the Deposits of one posting. Each option is sized so its Unsold Loss stays within a share of the Stake, and so it doesn't take the gold tied up in posts past a share of the Stake (#170). A Flip to Vendor's is about nothing: it sells now. Not Max Loss, which is a Prediction's and assumes the unit still sells at today's prices.
_Avoid_: worst case, risk

**Bought mark**:
A flag the player puts on a buy-side row of the Recommendation Table (right-click) once they've bought it, so it isn't bought twice before the next Brain run (#97). The row greys out and sorts last, and its Cost counts as spent against the **gold left**: the least of the Budget less what's spent, the gold on hand, and the risk caps' room less what's spent (#170), which the table folds options over. Marks are kept per Market and cleared once an import's Scan is later than the mark. Only the Addon reads them; the Brain learns of the buy from Purchases and the next Scan.
_Avoid_: purchase (that's the stack read from mail), checked, done

**Days to Sell**:
The most days a buy that exits through Sell should take to sell, set per Market in the Recommendation Table next to the Budget and carried to the Brain in each Character Read. It caps how many units a Flip to Sell buys, a Flip to Craft's output Sells, and a Buy Under's Sell way is good for, after the held units ahead of them. None set, or more than the Sale Horizon, means the Sale Horizon. It doesn't touch Holdings, Best Exit Value, Prediction buys or grading, which stay on the Sale Horizon: that's how long the player will wait for what they already own, this is how much new stock they'll take on (ADR-0020).
_Avoid_: stock horizon, buy horizon, max stock

**Holdings**:
Every Item Key the player's Characters own in bags and banks, each with its Recommendation. Built from each Character's latest Character Read, taking the bank from the latest Read that has one. Keyring, equipped gear and unclaimed mail are not Holdings. Held units a Craft Action uses show only on that craft's row, not as their own Holdings row. Held units a Shopping List Flip to Craft would use keep their Holdings row too, since that Flip is only an option (ADR-0017). Recommendations pool the Characters of a Market, but the Recommendation Table shows which Characters hold each Item Key, and what to mail a crafter (ADR-0009).
_Avoid_: inventory (that's only bags), stock

**Character**:
One of the player's in-game characters, identified by realm and name. Known Recipes, Holdings and gold belong to a Character. Gold is pooled for sizing across the Characters on one realm and faction, since mail can't move it any further.
_Avoid_: toon, alt, account
