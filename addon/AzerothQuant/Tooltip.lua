-- WoW glue for Recommendation lines in item tooltips ("AQ: Sell 2 @ 1g 28s"), so they
-- show in bags and on the Auction House without opening the Recommendation Table. All
-- shaping happens in TooltipLines.lua; this file only hooks the tooltips.
--
-- Read-only: it adds lines and nothing else (ADR-0003).
local _, ns = ...
local TooltipLines = ns.TooltipLines
local Scan = ns.Scan

local R, G, B = 0.4, 0.8, 1 -- light blue, apart from the game's white and green lines

-- The Beta client has no global GetItemInfo, only C_Item's.
local getItemInfo = C_Item and C_Item.GetItemInfo or GetItemInfo

-- A reagent's name, or nil until the client has loaded it.
local function nameOf(itemString)
  return (getItemInfo(itemString))
end

-- The name an AH browse row shows, e.g. "Willow Belt of the Sorcerer": from the row's
-- auction item key where the row has one, else the tooltip's title line.
local function rowName(tooltip)
  local owner = tooltip.GetOwner and tooltip:GetOwner()
  local key = owner and owner.rowData and owner.rowData.itemKey
  local info = key and C_AuctionHouse and C_AuctionHouse.GetItemKeyInfo(key)
  if info and info.itemName then
    return info.itemName
  end
  local title = tooltip.GetName and tooltip:GetName() and _G[tooltip:GetName() .. "TextLeft1"]
  return title and title:GetText()
end

local function addLines(tooltip, data)
  if not tooltip.GetItem then
    return
  end
  local saved = AzerothQuantRecommendations
  local recommendations = saved and saved.recommendations
  local excluded = saved and saved.disenchantExcluded
  local realm, faction = GetRealmName(), UnitFactionGroup("player")
  local _, link = tooltip:GetItem()
  local itemID = (link and tonumber(link:match("|Hitem:(%d+)"))) or (data and data.id)
  -- What its Disenchant source group needs to know of the item (#88).
  local info = itemID and Scan.fromGetItemInfo(getItemInfo(itemID))
  -- A suffixed item's AH browse row links the plain item (#96), so when the Market has
  -- nothing for its Item Key, try the row's name. Its group's Buy Under comes either way.
  local lines
  if #TooltipLines.forLink(recommendations, realm, faction, link, nameOf) == 0 and itemID then
    lines = TooltipLines.forItemName(recommendations, realm, faction, itemID, rowName(tooltip), nameOf, info, excluded)
  else
    lines = TooltipLines.forLink(recommendations, realm, faction, link, nameOf, info, excluded)
  end
  for _, text in ipairs(lines) do
    tooltip:AddLine(text, R, G, B)
  end
end

-- Newer clients build tooltips from tooltip data, and one post-call covers every tooltip
-- showing an item. Older ones fire OnTooltipSetItem on each tooltip instead.
if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall then
  TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, addLines)
else
  for _, tooltip in ipairs({ GameTooltip, ItemRefTooltip }) do
    tooltip:HookScript("OnTooltipSetItem", addLines)
  end
end
