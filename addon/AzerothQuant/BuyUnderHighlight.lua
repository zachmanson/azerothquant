-- WoW glue for the live Buy Under flag on the Auction House (#88): a green wash on each
-- row priced at or under a Buy Under, in the browse results and in an item's own list of
-- Listings (items and commodities). All matching happens in BuyUnderMatch.lua; this file
-- only hooks the lists' rows. The item tooltip's Buy Under line (Tooltip.lua) doesn't need it.
--
-- Read-only: it flags a row and nothing else. The player buys (ADR-0003).
local _, ns = ...
local BuyUnderMatch = ns.BuyUnderMatch
local Scan = ns.Scan

local R, G, B, A = 0.1, 1, 0.1, 0.2

-- The Beta client has no global GetItemInfo, only C_Item's.
local getItemInfo = C_Item and C_Item.GetItemInfo or GetItemInfo
local isAddOnLoaded = C_AddOns and C_AddOns.IsAddOnLoaded or IsAddOnLoaded

local function nameOf(itemString)
  return (getItemInfo(itemString))
end

-- What its Disenchant source group needs to know of an item (#88), or nil until the client
-- has it.
local function infoOf(itemID)
  return itemID and Scan.fromGetItemInfo(getItemInfo(itemID))
end

-- A browse row: its lowest price, and the name it shows, which tells a suffixed item's Item
-- Keys apart (#96). Nil until the client has the name.
local function browseListing(data)
  local info = data.itemKey and C_AuctionHouse.GetItemKeyInfo(data.itemKey)
  local itemID = data.itemKey and data.itemKey.itemID
  return {
    itemID = itemID,
    name = info and info.itemName,
    info = infoOf(itemID),
    unitPrice = data.minPrice,
  }
end

-- One Listing of an item: its link gives the Item Key. The buyout covers the Listing's
-- quantity, which for an item (not a commodity) is nearly always 1.
local function itemListing(data)
  local itemID = data.itemKey and data.itemKey.itemID
  return {
    link = data.itemLink,
    itemID = itemID,
    info = infoOf(itemID),
    unitPrice = data.buyoutAmount and data.buyoutAmount / math.max(data.quantity or 1, 1),
  }
end

local function commodityListing(data)
  return { itemID = data.itemID, unitPrice = data.unitPrice }
end

local function flag(row, on)
  if not row.azerothQuantBuyUnder then
    if not on then
      return
    end
    row.azerothQuantBuyUnder = row:CreateTexture(nil, "BACKGROUND", nil, 7)
    row.azerothQuantBuyUnder:SetAllPoints()
    row.azerothQuantBuyUnder:SetColorTexture(R, G, B, A)
  end
  row.azerothQuantBuyUnder:SetShown(on)
end

-- Flags a row, or clears one recycled from a flagged Listing.
local function refresh(row, listingOf)
  local data = row.rowData
  local on = false
  if data then
    local saved = AzerothQuantRecommendations
    local recommendations = saved and saved.recommendations
    local excluded = saved and saved.disenchantExcluded
    local realm, faction = GetRealmName(), UnitFactionGroup("player")
    on = BuyUnderMatch.under(recommendations, realm, faction, listingOf(data), nameOf, excluded) ~= nil
  end
  flag(row, on)
end

local browseScrollBox

-- Rows are recycled as the list scrolls, so each one is refreshed on every init. The
-- callback registry keeps one callback per owner, so the owner is a table of our own, never
-- the list (which may have its own). Rows already on show (the AH open over a /reload) are
-- refreshed at once.
local function hook(list, listingOf)
  local scrollBox = list and list.ScrollBox
  if not scrollBox or not ScrollUtil or not ScrollUtil.AddInitializedFrameCallback then
    return nil
  end
  ScrollUtil.AddInitializedFrameCallback(scrollBox, function(_, row)
    refresh(row, listingOf)
  end, {}, false)
  scrollBox:ForEachFrame(function(row)
    refresh(row, listingOf)
  end)
  return scrollBox
end

local hooked = false

local function hookAuctionHouse()
  if hooked or not AuctionHouseFrame then
    return
  end
  hooked = true
  browseScrollBox =
    hook(AuctionHouseFrame.BrowseResultsFrame and AuctionHouseFrame.BrowseResultsFrame.ItemList, browseListing)
  hook(AuctionHouseFrame.ItemBuyFrame and AuctionHouseFrame.ItemBuyFrame.ItemList, itemListing)
  hook(AuctionHouseFrame.CommoditiesBuyFrame and AuctionHouseFrame.CommoditiesBuyFrame.ItemList, commodityListing)
end

-- The AH frames load on demand, the first time an Auction House opens. A browse row's name
-- can arrive after the row is drawn, so browse rows are refreshed when one does.
local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("ITEM_KEY_ITEM_INFO_RECEIVED")
events:SetScript("OnEvent", function(_, event, name)
  if event == "ADDON_LOADED" and name == "Blizzard_AuctionHouseUI" then
    hookAuctionHouse()
  elseif event == "ITEM_KEY_ITEM_INFO_RECEIVED" and browseScrollBox then
    browseScrollBox:ForEachFrame(function(row)
      refresh(row, browseListing)
    end)
  end
end)
if isAddOnLoaded and isAddOnLoaded("Blizzard_AuctionHouseUI") then
  hookAuctionHouse()
end
