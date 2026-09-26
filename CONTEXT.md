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
A Disappearance treated as a sale because it could not have expired (the time between the two Scans was shorter than the least time its time-left bucket allows), it is not a Repost, and it was priced near or below Fair Value. Cancellations without a Repost still can't be told apart.

**Outcome**:
What happened to one stack the player posted: Sold (with its price), Cancelled or Expired, read from a Mailbox Read. Unlike a Disappearance it is known, not inferred. It covers one stack, and a Listing can hold several, so an Outcome and a Listing don't map one to one.
_Avoid_: result, receipt, invoice (an invoice is one kind of mail)

**Purchase**:
One stack the player bought on the Auction House, with its price, read from a Mailbox Read. It is how an Auction House Lot starts, as an Outcome is how one ends. Only Auction House buys arrive by mail, so crafting, merchant buys and loot start Lots some other way.
_Avoid_: buy, win

**Observation Window**:
The time between two consecutive Scans of a Market, when it is short enough that almost no sale goes unseen. Only Observation Windows count toward Sell Rate; longer gaps still track Listings but add nothing to it.
_Avoid_: gap (when you mean one that counts), interval

**Fair Value**:
The price an Item Key can realistically be sold at in its Market, based on the cheapest part of recent supply rather than the single lowest Listing.
_Avoid_: market value, price, min buyout

**Sell Rate**:
Units sold per day for an Item Key in a Market: the Partial Sales and Probable Sales inside Observation Windows, divided by the total time of those Observation Windows. The Decision Engine's measure of liquidity.
_Avoid_: volume, velocity

**Vendor Price**:
The fixed gold an NPC merchant pays for one unit of an item.
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
One way to extract value from a Candidate Item: Vendor, Flip, Craft, Disenchant or Hold.

**Thesis**:
A prediction the player writes down from game knowledge: an Item Key, an expected price move, a date and a reason. The Decision Engine prices it as a Hold, and it gets graded afterward.
_Avoid_: tip, hunch, bet

**Lot**:
A quantity of one Item Key acquired together at one cost, tracked until it is sold, vendored, disenchanted or crafted away. Realized profit is measured per Lot.
_Avoid_: position, stack (a stack is an in-game bag concept)

**Best Exit Value**:
The most one unit of an Item Key is worth via its best Action, where Disenchant and Craft value their outputs at those outputs' own Best Exit Value. This is what makes chained Actions work.
_Avoid_: value, worth

**Recommendation**:
The best Action for one Candidate Item, with quantity, price ceiling, the full Action path, expected profit and return per day.
_Avoid_: signal, tip

**Shopping List**:
The Recommendations for things to buy on the Auction House.
_Avoid_: buy list, snipes

**Holdings**:
Every Item Key the player's Characters own in bags and banks, each with its Recommendation. Built from each Character's latest Character Read, taking the bank from the latest Read that has one. Keyring, equipped gear and unclaimed mail are not Holdings.
_Avoid_: inventory (that's only bags), stock

**Character**:
One of the player's in-game characters, identified by realm and name. Known Recipes, Holdings and gold belong to a Character. Gold is pooled for sizing across the Characters on one realm and faction, since mail can't move it any further.
_Avoid_: toon, alt, account
