# The Addon posts or cancels the selected row, one protected action per click

ADR-0003 kept the Addon read-only, stricter than Blizzard requires. Posting is where most of the player's clicks go, and the Brain's value is in choosing the price, so posting the Brain's price through Blizzard's UI by hand costs time and adds nothing (#81, ADR-0015's "gold per hour" gap). The Addon may now take the protected action for a row the player selected, one protected call per click, as TSM, Auctionator and Blizzard's own UI do.

**What the player does.** They select a row in the Recommendation Table and press the button:

- **Post** for a Holdings Sell row or a Flip to Sell's resale, at the row's Post at, with the row's quantity.
- **Cancel** for an own Listing the Brain says to pull.

Nothing moves on to the next row by itself. The player picks each row, so the decision is always theirs.

**Selecting a row** (built with #77, before Post and Cancel). A plain click selects a row and highlights it. A shift-click links the item in chat, which a plain click used to do. The selection survives a redraw (a sort, a tab switch, a re-import) while a row with the same Item Key and action is on show, and clears otherwise. Selecting a Craft row also opens its Craft Chain panel. Selecting takes no action by itself.

**Marking a row Bought** (#97). A right-click on a buy-side row (Shopping List, Flips to Craft, Prediction buys) toggles its Bought mark, so it isn't bought twice before the next Brain run. A Bought row greys out, sorts to the bottom of its tab and can't be selected. The mark is Addon state only (`AzerothQuantDB.bought`, per Market): the Addon still never buys, and the Brain never reads the marks.

**When the price has gone stale.** The Brain is offline, so Post at comes from the last import. If the live lowest Listing on the Sell screen is below Post at, the button still works but shows the undercut ("Lowest is now 4s 20c, below 4s 50c"). Repricing is the Brain's job on the next import, not something the Addon improvises.

**Guardrails** (what keeps the account-risk surface where TSM's has been for over a decade):

1. A protected call (`C_AuctionHouse.PostItem`, `PostCommodity`, `ConfirmPostItem`, `ConfirmPostCommodity`, `CancelAuction`) happens only inside the `OnClick` of a button the player pressed. It is never called from timers, events, `OnUpdate`, loops or macros the Addon writes.
2. One click makes at most one protected call. If posting turns out to take Post and then Confirm on Forever's build, that's two clicks, and the button's label changes between them.
3. The Addon never buys or bids (`PlaceBid`, `StartCommoditiesPurchase` and `ConfirmCommoditiesPurchase` are never called), because a stale Recommendation loses real gold there. It never takes, returns, deletes or sends mail, and never reads a mail's body. ADR-0003's mail rules stand unchanged.
4. Nothing in the project touches the game process, its memory or its network traffic, or simulates input.
5. **Checked, not promised.** An Addon test fails if any protected API name appears outside the one click handler. An in-game probe (a `/run` of `PostItem` with no click) shows `ADDON_ACTION_BLOCKED`, confirming that the game enforces rule 1 itself. The same probe finds out whether Forever's post takes a Confirm step.

**What this rests on (researched 2026-09-28).**

- Blizzard's generated API docs mark `PostItem`, `PostCommodity`, `ConfirmPost*`, `CancelAuction`, `PlaceBid` and `StartCommoditiesPurchase` as restricted, and scanning (`ReplicateItems`, `Send*Query`) as unrestricted. This comes from the Gethe/wow-ui-source mirror, `live` branch, and it isn't confirmed to be Forever's exact build.
- Warcraft Wiki (seen in search snippets only) says a protected call made without a hardware event is blocked and fires `ADDON_ACTION_BLOCKED`.
- Blizzard's rule is "one keypress = one action".
- A Blizzard rep said Forever shares Mainline's UI and API restrictions and will stay in sync with them.
- No official statement was found that an addon using only the API has caused a ban. Bans come from programs outside the game that automate input or read memory.

## Considered Options

- **Keep ADR-0003 (read-only).** Zero risk, but it leaves every post as manual work, the one place TSM clearly beats us.
- **Full parity (post, cancel, buy from the Shopping List, loot mail).** Buying from an offline Brain's Recommendation is where staleness costs gold, so it stays a deliberate manual step in Blizzard's UI.
- **Walk the table (each click posts the next row).** Faster, but the player stops choosing, and the user wants to decide row by row.
- **Block the post when undercut.** It forces a decision the player should make.

## Consequences

- Supersedes ADR-0003 on posting and cancelling. ADR-0003 still holds for buying, bidding and mail, and for everything outside the game.
- CONTEXT.md **Addon** and **Recommendation Table** now say the Addon acts only on the row the player selected, one click at a time.
- The Addon gets its first protected-API code, and the test in guardrail 5 comes with it.
- Before building, the in-game probe must settle whether Forever's post takes one step or two.
- The probe (#81) settled it: one call posts, with no Confirm, for gear and commodities alike. #81 built Post only. Cancel waits on #134, since the Brain doesn't yet name an own Listing to pull; until then `CancelAuction` is forbidden like the buy calls.
