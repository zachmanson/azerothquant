-- Whether a Listing on the Auction House is at or under a Buy Under (#88), so the AH
-- frames can flag it for the player to buy. Scans every 15 minutes miss short-lived
-- Listings, so this is how a Buy Under gets used.
--
-- Plain Lua with no WoW API calls, so it runs under busted. The Addon never buys (ADR-0003).
local _, ns = ...
ns = ns or {}

-- In game TooltipLines.lua loads first (see the .toc), so require, which WoW lacks, isn't reached.
local TooltipLines = ns.TooltipLines or require("TooltipLines")
local RecommendationTable = ns.RecommendationTable or require("RecommendationTable")
local DisenchantGroup = ns.DisenchantGroup or require("DisenchantGroup")

local BuyUnderMatch = {}

-- A Listing with a link (in an item's own list) is its Item Key. A browse row or a
-- commodity Listing has only an itemID: that's the plain Item Key, or, for a suffixed item
-- whose browse row groups its Item Keys by name (#96), those with the row's name by nameOf.
-- A Disenchant source group's Buy Under matches any item in the group (#88).
local function matches(b, listing, nameOf, excluded)
  if b.group then
    local itemID = listing.itemID or (listing.link and tonumber(listing.link:match("|Hitem:(%d+)")))
    return DisenchantGroup.contains(b.group, itemID, listing.info, excluded)
  end
  if listing.link then
    return b.itemKey == TooltipLines.itemKey(listing.link)
  end
  local id = tostring(listing.itemID)
  if b.itemKey == id then
    return true
  end
  return b.itemKey:match("^(%d+)") == id and listing.name ~= nil
    and nameOf(RecommendationTable.itemString(b.itemKey)) == listing.name
end

-- listing: { link } or { itemID, name? }, with info ({ quality, itemLevel, classID,
-- equipLoc }, nil until the client has it) for its Disenchant source group, and unitPrice,
-- the copper per unit it can be bought for (nil for a bid-only Listing). excluded is the
-- Brain's disenchantExcluded. Gives the highest Buy Under it's at or under (its Item Key's
-- or its group's), or nil.
function BuyUnderMatch.under(recommendations, realm, faction, listing, nameOf, excluded)
  local entry = recommendations and recommendations[realm] and recommendations[realm][faction]
  if not entry or not listing.unitPrice then
    return nil
  end
  local best
  for _, b in ipairs(entry.buyUnder or {}) do
    if listing.unitPrice <= b.price and (not best or b.price > best.price) and matches(b, listing, nameOf, excluded) then
      best = b
    end
  end
  return best
end

ns.BuyUnderMatch = BuyUnderMatch
return BuyUnderMatch
