# Cancel works through the Undercut Listings, one per click

Amends ADR-0016 for Cancel only (#177, supersedes #134). ADR-0016 had the player select an own Listing the Brain said to pull and press Cancel, and it turned down "walk the table" (each click acts on the next row). For cancels, the player now gets that walk-through:

- A **Cancel undercut (N)** button beside Post, shown only at a faction Auction House. Each click cancels the next Undercut own Listing, with no row selected. When N is 0 the button is disabled and reads "No undercut Listings".
- **Undercut** is checked live by the Addon, not decided by the Brain. An own Listing is Undercut when another player's Listing of the same Item Key is cheaper by any amount, or at exactly the same price. At one price the Auction House sells the newest first, and the player always posts under the cheapest other Listing, so another player at the same price posted after them. Own units never count (`lowestOther`).
- **Order:** the most gold tied up first (units × own unit price). If the player stops partway, the cancels already made freed the most.
- **Checking:** on `AUCTION_HOUSE_SHOW`, `QueryOwnedAuctions`, then one search per distinct owned Item Key, through a queue that waits for the search throttle. The button reads "Checking 3/7…" until it finishes. After each cancel (confirmed on `OWNED_AUCTIONS_UPDATED`), the next target's Item Key is searched again before the button re-enables, and a target no longer Undercut is dropped. Post's undercut search moves onto the same queue.
- **Showing the next click:** hovering the button names the next target ("Medium Hide ×20 at 4s 50c, lowest other 4s 20c"), and a chat line says what each click cancelled. There's no Listings tab.
- Only the logged-in Character's auctions, since `CancelAuction` only works on one's own. Nothing follows a cancel: the units come back by mail, become Holdings, and the Holdings Sell row offers Post at the Brain's price.

Post is unchanged: one selected row per click. Guardrails 1 to 5 of ADR-0016 hold as written. `CancelAuction` is called only in this button's `OnClick`, at most once per click, and the guardrail test allows it there and nowhere else.

## Why

A cancel risks only its Deposit, and the units come back. The rule ("someone will sell ahead of me") is mechanical, so choosing row by row adds clicks but no decision. Posting chooses a price and quantity, so it keeps the row choice. The check has to be live, because a list from the last Scan offers cancels for Listings that have since sold or become cheapest again. ADR-0016's "repricing is the Brain's job" still holds: cancelling reprices nothing, and the repost goes through the Brain's Post at.

The same-price rule rests on player reports and a Blizzard post from the 8.3 Auction House revamp saying a price point sells last in, first out (sources on #177). It isn't confirmed on Forever. Reading the order from `auctionID` would need an in-game probe, and would only improve on the rule for Listings the player posted by hand at someone else's price.

## Considered Options

- **Pull-beats-leave from the Brain (#134 as grilled 2026-10-04).** Weighs the lost Deposit against waiting, but it is only as fresh as the last Scan and needs a Leave model, a Listings tab and per-Character rows. Whether a cancel pays for its Deposit is moved to #183 (undercut wars).
- **Cheaper only.** Misses the same-price Listings that sell first.
- **An undercut gap (e.g. 1%).** A tuning constant with no data behind it. 1c matters on a commodity.
- **Keep row-by-row Cancel.** The player wants to click through quickly.
- **Read posting order from `auctionID`.** Needs a probe first, for a rare case.

## Consequences

- ADR-0016 gets "Amended by ADR-0044", and its #134 Consequences line is superseded.
- CONTEXT.md gains **Undercut**. **Addon** and **Recommendation Table** describe the button.
- The Addon checks owned Item Keys through a throttle-respecting search queue, which Post's undercut line also uses.
- In 1c undercut wars the player can lose a Deposit per round. They see each cancel and can stop. The Brain still prices held units 1c under the cheapest other; whether it should match instead (same price sells newest first) is #230.
