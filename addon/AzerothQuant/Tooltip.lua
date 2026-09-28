-- WoW glue for Recommendation lines in item tooltips ("AQ: Sell 2 @ 1g 28s"), so they
-- show in bags and on the Auction House without opening the Recommendation Table. All
-- shaping happens in TooltipLines.lua; this file only hooks the tooltips.
--
-- Read-only: it adds lines and nothing else (ADR-0003).
local _, ns = ...
local TooltipLines = ns.TooltipLines

local R, G, B = 0.4, 0.8, 1 -- light blue, apart from the game's white and green lines

-- The Beta client has no global GetItemInfo, only C_Item's.
local getItemInfo = C_Item and C_Item.GetItemInfo or GetItemInfo

-- A reagent's name, or nil until the client has loaded it.
local function nameOf(itemString)
  return (getItemInfo(itemString))
end

local function addLines(tooltip)
  if not tooltip.GetItem then
    return
  end
  local _, link = tooltip:GetItem()
  local lines = TooltipLines.forLink(
    AzerothQuantRecommendations and AzerothQuantRecommendations.recommendations,
    GetRealmName(),
    UnitFactionGroup("player"),
    link,
    nameOf
  )
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
