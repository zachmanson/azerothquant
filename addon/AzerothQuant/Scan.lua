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
-- rows: one per replicate index, { link, count, buyout, timeLeft, owner }.
-- Own rows also get the item name from the link.
-- playerName: UnitName("player"), to recognize the player's own Listings.
-- Returns the Scan as stored in SavedVariables. buyout stays whole-auction; the Brain
-- divides by quantity for the unit buyout.
function Scan.build(request, rows, playerName)
  local listings = {}
  local droppedRows = 0
  for _, r in ipairs(rows) do
    local item = itemString(r.link)
    if not item then
      -- Item data never loaded. hasAllInfo = false alone is fine as long as the link is there
      -- (the link carries the itemID too).
      droppedRows = droppedRows + 1
    elseif r.buyout and r.buyout > 0 then
      local own = r.owner ~= nil and r.owner == playerName
      listings[#listings + 1] = {
        -- Not the Item Key yet: the Brain derives that (itemID + bonus IDs) from this string.
        itemString = item,
        quantity = r.count,
        buyout = r.buyout,
        timeLeft = r.timeLeft,
        -- The full Scan hides every seller except the player, so this is the only one kept.
        own = own or nil,
        -- Sale mail names the item but carries no Item Key, so an Outcome can only be
        -- matched to its own Listing by name (#17). Other rows skip it to keep the Scan small.
        name = own and itemName(r.link) or nil,
      }
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
    listings = listings,
  }
end

ns.Scan = Scan
return Scan
