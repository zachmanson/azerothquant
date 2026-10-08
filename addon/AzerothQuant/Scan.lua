-- Shapes one full Scan (the rows read from C_AuctionHouse's replicate list) into
-- the table stored in SavedVariables.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for
-- the namespace fallback.
local _, ns = ...
ns = ns or {}

local Scan = {}

-- "|cnIQ1:|Hitem:2680::::::::20:1490:::::::::|h[...]|h|r" -> "item:2680::::::::20:1490".
-- Trailing empty fields are dropped; they carry nothing and there are ~58k rows per Scan.
local function itemString(link)
  local s = link and link:match("|H(item:[^|]+)|h")
  return s and (s:gsub(":+$", ""))
end

-- "...|h[Scouting Belt of Nature Protection]|h|r" -> "Scouting Belt of Nature Protection".
-- The suffix is part of the name, as the sale mail spells it.
local function itemName(link)
  return link:match("|h%[(.-)%]|h")
end

-- NPC IDs of the neutral (goblin) auctioneers, from Wowhead Classic. Still to be
-- confirmed on the Forever client (issue #3); add any missing ones here.
local NEUTRAL_AUCTIONEERS = {
  [8661] = true, -- Auctioneer Beardo, Gadgetzan
  [9857] = true, -- Auctioneer Grizzlin, Everlook
  [9858] = true, -- Auctioneer Kresky, Booty Bay
  [15677] = true, -- Auctioneer Graves, Booty Bay
  [15681] = true, -- Auctioneer O'reely, Booty Bay
}

-- GetItemInfo's classID for weapons and armor: the only items that can be Disenchanted.
local DISENCHANTABLE_CLASSES = { [2] = true, [4] = true }

-- An item's { quality, itemLevel, classID, equipLoc } from GetItemInfo's returns, or nil
-- when the client hasn't loaded the item yet.
function Scan.fromGetItemInfo(...)
  local _, _, quality, itemLevel, _, _, _, _, equipLoc, _, _, classID = ...
  if quality == nil then
    return nil
  end
  return { quality = quality, itemLevel = itemLevel, classID = classID, equipLoc = equipLoc }
end

-- What the Brain needs to put an item in a Disenchant source group (#76), from
-- { quality, itemLevel, classID, equipLoc }, or nil for anything but an uncommon to epic
-- weapon or armor piece, which are left out to keep Scans and Reads small.
function Scan.disenchantInfo(info)
  if not (DISENCHANTABLE_CLASSES[info.classID] and info.quality >= 2 and info.quality <= 4) then
    return nil
  end
  return { itemLevel = info.itemLevel, quality = info.quality, classID = info.classID, equipLoc = info.equipLoc }
end

-- The Market's faction is the Auction House's, not the player's: a Horde player at
-- Booty Bay is trading in the Neutral Market. npcGUID is UnitGUID("npc") at the AH.
function Scan.marketFaction(npcGUID, playerFaction)
  local npcID = npcGUID and tonumber(npcGUID:match("^Creature%-%d+%-%d+%-%d+%-%d+%-(%d+)%-"))
  if npcID and NEUTRAL_AUCTIONEERS[npcID] then
    return "Neutral"
  end
  return playerFaction
end

-- request: { id, requestedAt, realm, character, faction }, captured when the Scan was requested,
-- plus firstUpdateAt (first REPLICATE_ITEM_LIST_UPDATE) and readAt (rows finished reading).
-- Those two are diagnostic only (#15): they tell a throttled or slow Scan apart afterwards,
-- but the Listings still stand as of requestedAt.
-- rows: one per replicate index, { link, count, buyout, timeLeft, owner, itemID }. itemID is
-- GetReplicateItemInfo's, there even when the link isn't.
-- Own rows also get the item name from the link.
-- playerName: UnitName("player"), to recognize the player's own Listings.
-- sellPrice(itemID): the item's Vendor Price in copper (GetItemInfo's sellPrice), or nil
-- when the client hasn't loaded the item yet.
-- itemInfo(itemID): { quality, itemLevel, classID, equipLoc } from GetItemInfo, or nil
-- when the client hasn't loaded the item yet.
-- Returns the Scan as stored in SavedVariables. buyout stays whole-auction; the Brain
-- divides by quantity for the unit buyout. The player's own rows are tables in listings,
-- { itemString, quantity, buyout, timeLeft, own = true, name }. Everyone else's are packed
-- into one string, packedListings = "itemString,quantity,buyout,timeLeft;..." (#144): one
-- string per Scan instead of ~58k tables makes the file ~4x smaller and the Brain's parse
-- ~50x faster. Item strings have no commas or semicolons; names can, so own rows stay tables.
function Scan.build(request, rows, playerName, sellPrice, itemInfo)
  -- The player's own rows, as tables. Everyone else's go in packed (#144).
  local listings, packed = {}, {}
  local droppedRows = 0
  -- Each dropped row's item, once: the Brain leaves it out of the Observation Windows
  -- this Scan touches, since a Listing missing here may not have sold (#150).
  local droppedItemIDs, droppedLooked = {}, {}
  -- Vendor Price belongs to the itemID, so every suffix of an item shares one entry.
  -- 0 means a vendor won't buy it; the Brain decides what that means.
  local vendorPrices, looked = {}, {}
  local vendorPricesMissing = 0
  local infos, infoLooked = {}, {}
  local itemInfoMissing = 0
  for _, r in ipairs(rows) do
    local item = itemString(r.link)
    local itemID = item and tonumber(item:match("^item:(%d+)"))
    if itemID and sellPrice and not looked[itemID] then
      looked[itemID] = true
      vendorPrices[itemID] = sellPrice(itemID)
      if vendorPrices[itemID] == nil then
        vendorPricesMissing = vendorPricesMissing + 1
      end
    end
    if itemID and itemInfo and not infoLooked[itemID] then
      infoLooked[itemID] = true
      local info = itemInfo(itemID)
      if info == nil then
        itemInfoMissing = itemInfoMissing + 1
      else
        infos[itemID] = Scan.disenchantInfo(info)
      end
    end
    if not item then
      -- Item data never loaded. hasAllInfo = false alone is fine as long as the link is there
      -- (the link carries the itemID too).
      droppedRows = droppedRows + 1
      if r.itemID and not droppedLooked[r.itemID] then
        droppedLooked[r.itemID] = true
        droppedItemIDs[#droppedItemIDs + 1] = r.itemID
      end
    elseif r.buyout and r.buyout > 0 then
      -- The full Scan hides every seller except the player, so own is the only one kept.
      if r.owner ~= nil and r.owner == playerName then
        listings[#listings + 1] = {
          -- Not the Item Key yet: the Brain derives that (itemID + bonus IDs) from this string.
          itemString = item,
          quantity = r.count,
          buyout = r.buyout,
          timeLeft = r.timeLeft,
          own = true,
          -- Sale mail names the item but carries no Item Key, so an Outcome can only be
          -- matched to its own Listing by name (#17).
          name = itemName(r.link),
        }
      else
        -- tostring: a missing field becomes a row the Brain can't read, not a lost Scan.
        packed[#packed + 1] = table.concat(
          { item, tostring(r.count), tostring(r.buyout), tostring(r.timeLeft) }, ",")
      end
    end
  end
  return {
    id = request.id,
    requestedAt = request.requestedAt,
    firstUpdateAt = request.firstUpdateAt,
    readAt = request.readAt,
    realm = request.realm,
    character = request.character,
    faction = request.faction,
    droppedRows = droppedRows,
    droppedItemIDs = droppedItemIDs,
    listings = listings,
    packedListings = table.concat(packed, ";"),
    vendorPrices = vendorPrices,
    vendorPricesMissing = vendorPricesMissing,
    itemInfo = infos,
    itemInfoMissing = itemInfoMissing,
  }
end

-- The itemIDs of the rows whose link didn't read, once each: what the Addon asks the game to
-- load before Scan.reread (#156).
function Scan.missingItemIDs(rows)
  local itemIDs, seen = {}, {}
  for _, r in ipairs(rows) do
    if not itemString(r.link) and r.itemID and not seen[r.itemID] then
      seen[r.itemID] = true
      itemIDs[#itemIDs + 1] = r.itemID
    end
  end
  return itemIDs
end

-- Reads the link of each row the main read dropped again, once the game has had time to
-- load their items (#156). rows are Scan.build's, in replicate order: rows[i] is replicate
-- index i - 1. readLink(index) is GetReplicateItemLink. A row whose link still doesn't read
-- stays dropped, and Scan.build records it as before. So does one whose link is now another
-- item's: the list changed under the wait, and the index is no longer this auction.
-- Returns how many dropped rows now read, and how many there were.
function Scan.reread(rows, readLink)
  local reread, dropped = 0, 0
  for i, r in ipairs(rows) do
    if not itemString(r.link) then
      dropped = dropped + 1
      local link = readLink(i - 1)
      local item = itemString(link)
      if item and r.itemID and tonumber(item:match("^item:(%d+)")) == r.itemID then
        r.link = link
        reread = reread + 1
      end
    end
  end
  return reread, dropped
end

-- How many Listings a built Scan holds, own and packed.
function Scan.listingCount(scan)
  local _, separators = scan.packedListings:gsub(";", "")
  local packed = scan.packedListings == "" and 0 or separators + 1
  return #scan.listings + packed
end

ns.Scan = Scan
return Scan
