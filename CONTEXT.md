# azerothquant

A personal Auction House trading system for World of Warcraft: Forever. An in-game addon collects market and personal data, and an offline program analyzes it and sends back per-item recommendations that the player carries out by hand.

## Components

**Addon**:
The in-game half. It records market and personal data and shows the Recommendation Table. It acts only on the row the player selected, one protected action per click (post or cancel), and never buys, bids or takes mail (ADR-0016).
_Avoid_: bot, automation

**Brain**:
The offline half. It imports what the Addon collected into a persistent history and runs the Decision Engine over it.
_Avoid_: backend, server

**Decision Engine**:
The part of the Brain that scores every Action for each Candidate Item and ranks them.
_Avoid_: model, AI

## Market data

**Era**:
Which economy data comes from: Beta or Live. The Live economy starts from zero at launch, so data from the two Eras is never mixed.
_Avoid_: season, phase

**Market**:
One Auction House in one Era, identified by realm, faction (Alliance, Horde or Neutral) and Era. Every price and quantity only means something within its own Market.
_Avoid_: server, AH (when you mean the data scope)

**Beta Prior**:
Relative value learned from Beta (price ratios, turnover rank) that the Decision Engine uses early in Live, while Live history is still thin. It stops being used a few weeks after launch.

**Scan**:
One full pass over every Listing on the Auction House, as it stood at the moment the Scan was requested.
_Avoid_: snapshot, dump

**Mailbox Read**:
The Auction House mail in one Character's inbox (sales, purchases, cancellations, expiries), exactly as it stood when the player opened the mailbox. Other mail, such as COD and player letters, is left out. Mail stays until the player takes it, so the same mail shows up in every Mailbox Read until then.
_Avoid_: mail scan (a Scan is only ever the Auction House)

**Archive**:
Every Scan, Mailbox Read and Character Read exactly as the Addon recorded it, one file each, kept forever. It is the Brain's source of truth: the history database, and anything else the Brain stores, can be rebuilt from it.
_Avoid_: Scan Archive (it holds more than Scans), backup, raw dump

**Item Key**:
The identity used for pricing: itemID plus random suffix, so "of the Monkey" and "of the Eagle" versions are different Item Keys.
_Avoid_: item (when you mean the priced identity), itemID

**Listing**:
One auction on the Auction House: an Item Key, a remaining quantity and a unit buyout, tracked across the Scans it appears in. The game shows no seller or auction ID, so a Listing is recognized by Item Key, unit buyout and whether it is own, and identical Listings are interchangeable. Own means posted by the Character that did the Scan: the game hides every other seller, including the player's other Characters. Its quantity can only go down. Bids are ignored; buyout is the only price.
_Avoid_: auction, post, order, stack (a Listing can hold more than one stack)

**Disappearance**:
A Listing that was in one Scan and missing from the next. It was sold, cancelled or expired, and the game doesn't say which.

**Partial Sale**:
A drop in a Listing's quantity between two Scans. It is always a sale, since cancelling and expiring remove the whole Listing.

**Repost**:
A Disappearance that could not have expired, explained by a new Listing in the same Observation Window with the same Item Key, quantity and own flag, at the same or a lower unit buyout: most likely a seller cancelling to undercut or relist. Whenever such a pairing exists it is taken, so a Repost is never counted as a sale. The two Listings stay separate.
_Avoid_: relist, undercut (those are why a Repost happens, not the event)

**Coincidence Rate**:
The share of real sales that Repost pairing wrongly calls Reposts, because an unrelated new Listing happened to fit. It is measured on the player's own Disappearances that an Outcome shows were Sold, and it depends on how busy the Market is, not on who the seller is.
_Avoid_: error rate, false-positive rate (too generic to say which mistake)

**Probable Sale**:
A Disappearance treated as a sale because it could not have expired (the time between the two Scans was shorter than the least time its time-left bucket allows), it is not a Repost, and it was priced near or below the Fair Value of both Scans: the one it was last seen in and the one it went missing in (or only the first, if it sold the Item Key out). Cancellations without a Repost still can't be told apart.

**Sale Event**:
Every unit of one Item Key seen to sell in one Observation Window: all its Partial Sales and Probable Sales between those two Scans, whatever their prices. On Forever a buyer takes units cheapest-first across Listings and price points, and units that don't stack are one Listing each, so one buyer's sweep shows up as many drops; counted apart, they'd make one buyer look like many. A Sale Event is usually one buyer but can be several, and Scans can't tell which (ADR-0012). Its size is the units that went, and its price is the dearest of them.
_Avoid_: sale, purchase (a Purchase is the player's own buy)

**Outcome**:
What happened to one stack the player posted: Sold (with its price), Cancelled or Expired, read from a Mailbox Read. Unlike a Disappearance it is known, not inferred. It covers one stack, and a Listing can hold several, so an Outcome and a Listing don't map one to one. A Sold Outcome's mail names the item but doesn't carry it, so its Item Key is found by that name from own Listings and other Auction House mail; one whose name matches no Item Key, or more than one, is Unlinked and closes no Lot.
_Avoid_: result, receipt, invoice (an invoice is one kind of mail)

**Purchase**:
One stack the player bought on the Auction House, with its price, read from a Mailbox Read. It is how an Auction House Lot starts, as an Outcome is how one ends. Only Auction House buys arrive by mail, so crafting, merchant buys and loot start Lots some other way.
_Avoid_: buy, win

**Observation Window**:
The time between two consecutive Scans of a Market, when it is short enough that almost no sale goes unseen. Only Observation Windows count toward Sell Rate; longer gaps still track Listings but add nothing to it.
_Avoid_: gap (when you mean one that counts), interval

**Fair Value**:
The price an Item Key can realistically be sold at in its Market, based on the cheapest part of the supply in the latest Scan rather than the single lowest Listing. Units priced far below the rest of that cheap part are left out: they are Flips, not the price. It judges whether a Disappearance was a Probable Sale; it is not what anything is posted or valued at, since every Sell prices through the same undercut (see Sell).
_Avoid_: market value, price, min buyout

**Sell Rate**:
Units sold per day for an Item Key in a Market: the Partial Sales and Probable Sales inside Observation Windows, divided by the total time of those Observation Windows. The Decision Engine's measure of liquidity.
_Avoid_: volume, velocity

**Sell Rate Prior**:
Hours of Observation Window with no sales that the Decision Engine adds to a Market's real ones before Sell Rate becomes a quantity, so a sale or two in a short window doesn't read as a fast seller. Its effect fades as real window hours build up. Holdings get a small one and Flips a large one, since overrating a Flip spends gold on stock that sits. Sell Rate itself stays the raw measurement.
_Avoid_: pseudo-hours, thin-data discount, confidence bound

**Sale Size Prior**:
Sale Events of a typical size that the Decision Engine adds to an Item Key's real ones before taking their average size, so one big buyer doesn't make an Item Key look like it sells in bulk. The typical size is the smaller of the Market's usual Sale Event size among items that stack and the Item Key's usual Listing quantity. Its effect fades as real Sale Events build up. Holdings get a small one and Flips a large one, for the same reason as the Sell Rate Prior.
_Avoid_: stack-size cap, median sale

**Vendor Price**:
The fixed gold an NPC merchant pays for one unit of an item. It belongs to the itemID, so every random suffix of an item has the same one, and it is read from the game rather than taken from Classic, since Forever changed some.
_Avoid_: sell price, vendor value

**Merchant Cost**:
The gold an NPC merchant charges for one unit of an item it sells, such as thread or vials. It is read from the merchant window while it's open, only for items sold for gold in unlimited stock, and belongs to the Character that saw it, since reputation discounts differ. The Decision Engine uses the lowest latest-seen one across a realm and faction's Characters.
_Avoid_: vendor price, buy price

**Deposit**:
The copper the Auction House charges to post a unit, refunded when it sells and lost each time a posting expires unsold. Per unit, it's the deposit on the Item Key's latest Sold invoice divided by its count, else `ah_deposit_share` (0.60, the 24 h rate) of its Vendor Price, or nothing without one. The Decision Engine charges each unit it would post the deposits it expects that unit to lose: an Item Key's units sell in queue order (unbound held units, then the one Shopping List option's Flip to Sell or Flip to Craft outputs, each option queued as if it were the only buy, ADR-0017), and unit i of the queue waits i / (units per hour) and loses one deposit per `post_duration_hours` (24) that wait covers (ADR-0013).
_Avoid_: posting fee, AH fee, cut

## Crafting

**Known Recipe**:
A recipe the player already has, read from the profession window, with its output item, output quantity, reagents, cooldown and whether its output binds on pickup. The output quantity is a range for recipes that make a variable amount. Enchanting counts as a profession, even though most of its outputs are enchants rather than items; Beast Training does not. Only the Character's own profession windows count: a linked, guild or NPC crafting window shows someone else's recipes.

**Learnable Recipe**:
A recipe the player doesn't have yet but could get, and which costs something to acquire.

## Personal history

**Character Read**:
One Character's gold, faction and bag contents as they stood at logout or `/reload`, plus its bank if the player opened it that session (the bank can only be read while it's open, and can't change while it's closed), the Merchant Costs of any merchant it visited that session, the Known Recipes of each profession whose window was opened that session (read the same way, only while open), and which professions the Character has, so a dropped profession's old recipes can be told apart. Kept in the Archive like Scans and Mailbox Reads.
_Avoid_: snapshot, inventory

**Disenchant Result**:
The materials the player actually got from disenchanting one specific item.

## Decisions

**Candidate Item**:
An item the Decision Engine evaluates for a Recommendation.

**Action**:
One way out of a Candidate Item the player holds: Vendor, Sell, Craft, Disenchant or Hold. Buying is never an Action (see Flip).
_Avoid_: strategy, play

**Sell**:
The Action of posting an item on the Auction House for other players to buy. Held units are posted just under the cheapest other player's Listing (matching an own Listing that's cheaper), never above the highest price among its Sale Events or its Merchant Cost, with nothing on the Shopping List assumed bought, since its options are alternatives (ADR-0017). A Flip to Sell is posted the same way once its own run is bought. With no Listing left there is no Sell price, and held units go to Vendor. Best Exit Value values Sell the same way, at a past Scan too. A held unit Sells only while its price after the cut, less the Deposits it's expected to lose waiting its turn, beats the Vendor Price, so a slow seller's tail goes to Vendor.
_Avoid_: post, list, flip (a Flip is a buy)

**Craft**:
The Action of turning held reagents into a Known Recipe's output. A craft is worth doing when the output Holding's exit value with the crafted units added gains more than the consumed reagents' exit value loses. Missing merchant reagents are bought at their Merchant Cost, reagents Held under a Prediction are never used, and output is counted at the recipe's minimum quantity. The reagents are pooled across a realm and faction, and the Recommendation names the Character that knows the recipe. Enchants that make no item are not Crafts. Buying reagents on the Auction House to craft is a Flip, not this Action. A short reagent can be crafted first with another Known Recipe, a Sub-craft, so a Craft can be a chain (ADR-0014).
_Avoid_: make, produce

**Sub-craft**:
Crafting a reagent a Craft or Flip to Craft is short of, with another Known Recipe, whose own reagents are sourced the same way, down to `craft_chain_depth` crafts deep counting the top one. Each reagent comes from held units first, then a merchant (never Sub-crafted), then one source for the rest: a Sub-craft or, in a Flip to Craft, the Auction House, whichever costs less. A Sub-craft never uses an Item Key already on its path, and a Craft Action's Sub-craft surplus joins the crafted Holdings (a Flip to Craft's doesn't, since it's only an option, ADR-0017). It isn't a row of its own: the top Craft row lists it under `via` and carries its reagents and profit (ADR-0014).
_Avoid_: intermediate craft, chain step

**Flip**:
Buying on the Auction House because the price is below that Item Key's Best Exit Value after costs, whether the way out is Sell (buy cheap and repost), Vendor (buy under Vendor Price) or Craft (buy the reagents a Known Recipe is missing, then Sell or Vendor its output). A Flip is a Shopping List Recommendation, not an Action. A Flip to Craft buys only what held reagents don't cover, on the Auction House or as the reagents of a Sub-craft, whichever costs less, and its output is valued with a Flip's priors (ADR-0009). A Flip to Sell is posted just under the cheapest other player's Listing left once its own run is bought, so it sells first (matching an own Listing that's cheaper). It buys whichever run of the cheapest Listings makes the most profit with every unit clearing the Flip margin; with no Listing left it isn't a Flip to Sell. The Shopping List shows a Flip to Sell whole, or else the most profitable run the Budget covers that still clears the Flip margin, never part of a run priced as if the rest were bought (ADR-0011). Its resale is never priced above the highest price among the Sale Events behind its Sell Rate, and a way out through Sell needs a minimum number of those Sale Events (3 by default, so sales in 3 separate Observation Windows), since with fewer a single cancel could be the whole story. That holds for a Flip to Craft's output and for the resale a Hold buy's Max Loss assumes too; short of it, the way out is Vendor or nothing. Nor is any Sell price, a held unit's included, ever above an Item Key's Merchant Cost: nobody pays more on the Auction House than a merchant charges, so that's the ceiling, with the undercut of other Listings still applying under it. A Flip also pays an effort cost (`non_stacking_effort_copper`, 5s by default) on Item Keys that don't stack, ones no Listing was ever seen with more than one unit of: once for each unit it buys and once for each unit it posts, since each is its own buy and its own post. So a Flip to Sell pays it twice a unit and must clear the Flip margin after that, a Flip to Craft pays it on each such reagent bought on the Auction House and each such output that Sells, and a buy to Vendor only on the buy. Holdings never pay it: those units are held already. Each unit a Flip posts also pays the Deposits it's expected to lose, queued behind the held units. The last unit of a run waits longest, so it's the one that must clear the Flip margin.
_Avoid_: snipe, arbitrage

**Prediction**:
A call the player writes down from game knowledge that a group of Item Keys will be worth much more after a Catalyst, with the reason. It names no target price: the Decision Engine never estimates the upside, it only allows buying and Holding those Item Keys while the Max Loss stays small. Units of those Item Keys the player already holds are Held under it too, costed at their Best Exit Value on the day it was written, since that is the gold given up by not letting them go. It ends when the player marks its Catalyst as happened, or when it Lapses. Its units are the ones held when it was written (as of the start of that day) plus every Purchase of its Item Keys from then until it ends. It is graded by the realized return on the gold it tied up, from Outcomes, never by the player's own judgment: once a Sale Horizon has passed after it ended, its Sold units at their price after the Auction House cut, plus its still-open units at their Best Exit Value at that moment, against their cost. A Grade never changes afterwards: the Brain freezes it, and the held units' cost at writing, in `grades.toml` the first time it works them out.
_Avoid_: thesis, tip, hunch, bet

**Catalyst**:
The game event a Prediction waits for, such as a raid release or a new phase. The player marks it as happened; the Brain never guesses it from prices.
_Avoid_: trigger, event (too generic)

**Lapse**:
A Prediction ending because its Catalyst wasn't marked as happened by its lapse date. Its units go back to their best Action without the Prediction. Without it, a wrong Prediction would hold gold forever and never be graded as wrong.
_Avoid_: expiry (that's what happens to a Listing), invalidation

**Max Loss**:
For a unit bought or held under a Prediction, what it cost minus its Best Exit Value without the Prediction: what is lost if the Prediction turns out wrong and the unit is let go at today's prices.
_Avoid_: risk, downside

**Lot**:
A quantity of one Item Key acquired together at one cost, tracked until it is sold. Realized profit is measured per Lot. Lots belong to a realm and faction, not a Character, since units move between Characters by mail the Brain doesn't see. There are two kinds: one per Purchase, at its price, and the units already held when a Prediction is written, at their Best Exit Value that day. Writing a Prediction ends the open Lots of its Item Keys and folds their units into that second kind. Only a Sold Outcome closes units, from the oldest Lot first; a unit that leaves without one (vendored, disenchanted, crafted away, mailed off) stays open, because the Brain can't tell which of those happened. Loot, crafting and merchant buys don't start Lots.
_Avoid_: position, stack (a stack is an in-game bag concept)

**Paid**:
What a held Item Key's units cost, per unit, from its open Purchase Lots not tied to a Prediction, with how many units that covers. Held units take the newest open Lots first: open Lot units beyond the held ones are taken to be the oldest, gone without a Sold Outcome (crafted away, vendored, mailed off). Looted, farmed and crafted units have no cost, so a Paid can cover only some of the held units. A Holdings Sell or Vendor row's ROI is what one unit nets by its Action after the cut against its Paid; a Sell whose ROI reaches `roi_hint` is hinted at as a good time to sell, a hint only (ADR-0003).
_Avoid_: cost basis, buy price

**Best Exit Value**:
The most one unit of an Item Key is worth via its best Action, where Disenchant values its outputs at those outputs' own Best Exit Value. Craft chains backward instead: a Craft's short reagents can be Sub-crafted, but its output is valued by Sell and Vendor only, never by crafting it further (ADR-0014). Best Exit Value itself counts no crafts, and takes nothing on the Shopping List as bought (ADR-0017).
_Avoid_: value, worth

**Recommendation**:
The best Action for one Candidate Item, with quantity, price ceiling, the full Action path, expected profit and return per day.
_Avoid_: signal, tip

**Recommendation Table**:
The Addon's in-game view of one Market's Recommendations (Holdings, Shopping List, with its Flips to Craft in their own tab, and Prediction buys) as of the Scan the Brain last valued. It shows them, and posts or cancels only the row the player selects, one click per action (ADR-0016). It shows the Market of the Character's own faction, the only one the Brain recommends for.
_Avoid_: UI, window, panel

**Sale Horizon**:
How long the player is willing to wait for held units to sell. Only the units Sell Rate says will sell within it are worth Selling; the rest go to the next best Action, and a Flip never buys more than will sell within it. Held units take it first: a Flip to Sell gets only the room left after the held units that aren't bound (after the Craft Actions), even ones that end up Vendored, since their gold is already spent and a Flip is optional. Best Exit Value follows the same rule.
_Avoid_: timeout, patience

**Shopping List**:
The Recommendations for things to buy on the Auction House, as options: each Item Key's Flip to Sell and Flip to Vendor, and each recipe's Flips to Craft, sized as if it were the only buy within the Budget and priced after only its own buys. The most profitable options are shown first, Flips to Sell and Flips to Vendor in the top `shopping_list_rows` (50) by any of Profit, Per click, Per day or ROI, and Flips to Craft up to `craft_list_rows` (25) by Profit, in their own tab. Taking two may need more than the Budget, and the player picks (ADR-0017).
_Avoid_: buy list, snipes, basket

**Per click**:
A Flip to Sell's or Flip to Vendor's Profit for each click it takes: each Listing it buys (in Era every Listing is its own buyout) and each stack it posts, at the Item Key's usual Sale Event size. A Flip to Vendor posts nothing.
_Avoid_: profit per action, effort

**Per day**:
A Flip to Sell's Profit for each day until its last unit sells: the unbound held units ahead of it and its own units, at the Sell Rate under the Flip priors, the same queue the Deposits use. A Flip to Vendor sells now, so it comes before any Flip to Sell.
_Avoid_: profit per hour, velocity

**Budget**:
The most gold the player will spend in a Market, set in the Recommendation Table and carried to the Brain in each Character Read. Each Shopping List option, and the Prediction buys, spend up to the lesser of it and the pooled gold. None set means all the gold. The Prediction caps stay shares of the pooled gold (ADR-0006).
_Avoid_: bankroll, allowance

**Holdings**:
Every Item Key the player's Characters own in bags and banks, each with its Recommendation. Built from each Character's latest Character Read, taking the bank from the latest Read that has one. Keyring, equipped gear and unclaimed mail are not Holdings. Held units a Craft Action uses show only on that craft's row, not as their own Holdings row. Held units a Shopping List Flip to Craft would use keep their Holdings row too, since that Flip is only an option (ADR-0017). Recommendations pool the Characters of a Market, but the Recommendation Table shows which Characters hold each Item Key, and what to mail a crafter (ADR-0009).
_Avoid_: inventory (that's only bags), stock

**Character**:
One of the player's in-game characters, identified by realm and name. Known Recipes, Holdings and gold belong to a Character. Gold is pooled for sizing across the Characters on one realm and faction, since mail can't move it any further.
_Avoid_: toon, alt, account
