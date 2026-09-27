# azerothquant

A personal Auction House trading system for World of Warcraft: Forever. An in-game addon collects market and personal data, and an offline program analyzes it and sends back per-item recommendations that the player carries out by hand.

## Components

**Addon**:
The in-game half. It records market and personal data and shows the Recommendation table. It never acts on the player's behalf.
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
A Disappearance treated as a sale because it could not have expired (the time between the two Scans was shorter than the least time its time-left bucket allows), it is not a Repost, and it was priced near or below the Fair Value of the Scan it was last seen in. Cancellations without a Repost still can't be told apart.

**Sale Event**:
One Partial Sale or Probable Sale: one drop in the units on offer seen between two Scans. On Forever a buyer can take any part of a Listing, so a Sale Event is usually one buyer but can be several, and Scans can't tell which. Its size is the units it removed.
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
The price an Item Key can realistically be sold at in its Market, based on the cheapest part of the supply in the latest Scan rather than the single lowest Listing. Units priced far below the rest of that cheap part are left out: they are Flips, not the price.
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
The gold an NPC merchant charges for one unit of an item it sells, such as thread or vials.
_Avoid_: vendor price, buy price

## Crafting

**Known Recipe**:
A recipe the player already has, read from the profession window, with its output item, output quantity and reagents. The output quantity is a range for recipes that make a variable amount. Enchanting counts as a profession, even though most of its outputs are enchants rather than items; Beast Training does not.

**Learnable Recipe**:
A recipe the player doesn't have yet but could get, and which costs something to acquire.

## Personal history

**Character Read**:
One Character's gold, faction and bag contents as they stood at logout or `/reload`, plus its bank if the player opened it that session (the bank can only be read while it's open, and can't change while it's closed). Kept in the Archive like Scans and Mailbox Reads.
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
The Action of posting an item on the Auction House for other players to buy.
_Avoid_: post, list, flip (a Flip is a buy)

**Flip**:
Buying on the Auction House because the price is below that Item Key's Best Exit Value after costs, whether the way out is Sell (buy cheap and repost) or Vendor (buy under Vendor Price). A Flip is a Shopping List Recommendation, not an Action.
_Avoid_: snipe, arbitrage

**Prediction**:
A call the player writes down from game knowledge that a group of Item Keys will be worth much more after a Catalyst, with the reason. It names no target price: the Decision Engine never estimates the upside, it only allows buying and Holding those Item Keys while the Max Loss stays small. Units of those Item Keys the player already holds are Held under it too, costed at their Best Exit Value on the day it was written, since that is the gold given up by not letting them go. It ends when the player marks its Catalyst as happened, or when it Lapses. Its units are the ones held when it was written (as of the start of that day) plus every Purchase of its Item Keys from then until it ends. It is graded by the realized return on the gold it tied up, from Outcomes, never by the player's own judgment: once a Sale Horizon has passed after it ended, its Sold units at their price after the Auction House cut, plus its still-open units at their Best Exit Value at that moment, against their cost. A Grade never changes afterwards.
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

**Best Exit Value**:
The most one unit of an Item Key is worth via its best Action, where Disenchant and Craft value their outputs at those outputs' own Best Exit Value. This is what makes chained Actions work.
_Avoid_: value, worth

**Recommendation**:
The best Action for one Candidate Item, with quantity, price ceiling, the full Action path, expected profit and return per day.
_Avoid_: signal, tip

**Sale Horizon**:
How long the player is willing to wait for held units to sell. Only the units Sell Rate says will sell within it are worth Selling; the rest go to the next best Action, and a Flip never buys more than will sell within it.
_Avoid_: timeout, patience

**Shopping List**:
The Recommendations for things to buy on the Auction House.
_Avoid_: buy list, snipes

**Holdings**:
Every Item Key the player's Characters own in bags and banks, each with its Recommendation. Built from each Character's latest Character Read, taking the bank from the latest Read that has one. Keyring, equipped gear and unclaimed mail are not Holdings.
_Avoid_: inventory (that's only bags), stock

**Character**:
One of the player's in-game characters, identified by realm and name. Known Recipes, Holdings and gold belong to a Character. Gold is pooled for sizing across the Characters on one realm and faction, since mail can't move it any further.
_Avoid_: toon, alt, account
