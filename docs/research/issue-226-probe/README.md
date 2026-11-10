# #226 step 1: dropped-row probe

`AQProbe226/` is a dev-only addon that answers why Live Scans drop rows for "missing item data" when the client already knows most of those items (#226). It reads the AH replicate list itself, the same moment `Scanner.lua` does, and for each row whose link is nil records:

- `GetReplicateItemInfo` return 18 (`hasAllInfo`) and whether return 1 (the name) was there,
- whether `GetItemInfo(itemID)` is non-nil (`infoKnown`) and `C_Item.IsItemDataCachedByID`,
- whether another row of the same item read in the same pass (and one such link),
- when its link came back: on the item's `Item:CreateFromItemID(id):ContinueOnItemLoad` callback, or on a re-read at 2, 5, 10 or 30 s, or never.

Each run's tally (`Tally.lua`, specced in `spec/`) and up to 40 never-read rows go to `AQProbe226DB.runs`, with the login time, so runs before and after a full client restart can be compared. It never buys, bids, posts or cancels, and only calls `ReplicateItems` itself on `/aqp226 run` when no list is loaded.

Specs: from this folder, `..\..\..\.lua\bin\busted.bat`.

## Install

On the dev PC, `_forever_/Interface/AddOns/AQProbe226` is a junction to `docs/research/issue-226-probe/AQProbe226`. Remove the junction (not the folder it points to) once #226 is done.

## Steps (in game)

1. Log in (a fresh client start, so AQProbe226 loads). At the AH, when the Scan button is ready: `/aqp226 note first after restart`, `/aqp226 arm`, then click Scan. Keep the AH open ~40 s, until both the AzerothQuant line and the `AQProbe226: run 1 done` line are in chat.
2. Right away, still at the AH: `/aqp226 note same list again`, `/aqp226 run`. Wait for `run 2 done` (~35 s). This re-reads the same list now that the client has had time to load items.
3. `/reload` (Claude reads `WTF/Account/<account>/SavedVariables/AQProbe226.lua` and the Scan).
4. Restart check: next play session, or now if it's cheap, exit the game fully, relaunch, and do step 1 again with the note `second restart`. Compare its dropped count with the last Scans before the restart.

## Questions it answers

- Do dropped rows of items `GetItemInfo` knows ever come back, and how long does that take?
- Does `ContinueOnItemLoad` fire for them, and does the link read after it?
- Is `hasAllInfo` false on exactly the dropped rows (so it could be the wait signal)?
- Are the never-read rows a particular kind (suffixed, bonus IDs, one item ID with many Item Keys)?
- Does a full client restart reset the count?
