# #97 slice 2: AH buy-event probe

`AQProbe97/` is a dev-only addon that answers the questions in the probe comment on #85: which events fire on an AH buy, in what order, and what they carry. #97 slice 2 (automatic Bought marks) is built from the answers.

It only listens. It registers events and post-hooks `C_AuctionHouse.StartCommoditiesPurchase`, `ConfirmCommoditiesPurchase`, `CancelCommoditiesPurchase` and `PlaceBid` with `hooksecurefunc`, which runs after Blizzard's call and can't change it. It calls no buy, bid, post or cancel function. It logs to its own `AQProbe97DB`, so the Brain's import never sees it. It's named apart from the old #39 `AQProbe`, whose save file is still in the game folders.

Each entry has `GetTime()`, `GetServerTime()`, `GetMoney()` and every arg. AH events are logged while the AH is open; `CHAT_MSG_SYSTEM` and `PLAYER_MONEY` at any time. On `AUCTION_HOUSE_PURCHASE_COMPLETED` and the `PlaceBid` hook it also logs what the client still knows about the auction: `GetAuctionInfoByID`, and the matching row of the last item search. Their `itemLink` is where gear's suffix and bonus IDs show, which tells us whether an item buy can be tied to an Item Key. The first entry after each load lists the events and hooks this client doesn't have. Past 3000 entries the oldest go.

## Install

On the dev PC, `_forever_/Interface/AddOns/AQProbe97` is a junction to `docs/research/issue-97-probe/AQProbe97`. Remove the junction (not the folder it points to) once the probe is done.

## Steps (in game)

1. Open the AH and `/aqp clear`.
2. `/aqp note commodity`, then buy part of a commodity stack (some cloth, fewer than the cheapest Listing has).
3. `/aqp note item`, then buy out one gear Listing, ideally one with a suffix ("of the Bear").
4. `/aqp note failed`, then try for a failed buy: start a commodity buy and wait on the confirm until the price changes, or buy a Listing someone may beat you to. Skip it if nothing fails within a few tries, and say so.
5. Wait ~10 seconds, close the AH, `/reload`. Claude reads `WTF/Account/<account>/SavedVariables/AQProbe97.lua`.

## Questions it answers

- Which events fire for each buy type, and in what order?
- What does each carry: itemID, suffix or bonus IDs for gear, count, unit or total price?
- If none carries the price: does the `PLAYER_MONEY` drop line up with a single buy?
- Does a failed buy fire anything that would be mistaken for a success?
