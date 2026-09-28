# The Addon only reads and displays; it never buys, posts or cancels

> Superseded in part by ADR-0016: the Addon may post or cancel the row the player selected, one protected action per click. Buying, bidding, mail and everything outside the game stay as below.

The Addon never calls Auction House actions (buying, bidding, posting, cancelling) or mail-looting APIs, even from a button the player clicks, and nothing in the project touches the game process, its memory, its network traffic, or simulates input. Blizzard's policy would allow one protected action per player click (TSM and similar addons do this), but we deliberately stay stricter: the player performs every trade through Blizzard's own UI, and the Addon only highlights and recommends. This keeps the account-risk surface at zero and makes the boundary easy to check: any use of those APIs is a bug.

Reading mail is allowed and taking from it is not: the Addon may read inbox headers and auction invoices (what the mailbox UI already shows) to learn what happened to the player's own auctions, but never calls `TakeInboxItem`, `TakeInboxMoney`, `AutoLootMailItem`, or anything that returns, deletes or sends mail. It also never reads a mail's body (`GetInboxText`), since that marks the mail as read; headers and invoices are enough.
