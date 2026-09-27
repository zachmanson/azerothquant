-- Turns an item link into the lines the Addon adds to that item's tooltip: one per
-- Recommendation the Market has for its Item Key, e.g. "AQ: Sell 2 @ 1g 28s".
--
-- Plain Lua with no WoW API calls, so it runs under busted.
local _, ns = ...
ns = ns or {}

-- In game Money.lua loads first (see the .toc), so require, which WoW lacks, isn't reached.
local Money = ns.Money or require("Money")
local RecommendationTable = ns.RecommendationTable or require("RecommendationTable")

local TooltipLines = {}

-- Position of numBonusIDs in "itemID:enchant:gem1:gem2:gem3:gem4:suffix:unique:level:spec:
-- modifiersMask:context:numBonusIDs:bonusID1:..." (1-based; the bonus IDs follow it).
local NUM_BONUS_IDS = 13

-- The AH builds its browse-row links from an auction item key and adds bonus ID 3524,
-- which the item itself (in bags, or in a Scan's listing links) doesn't carry (#37).
local AH_ITEM_KEY_BONUS_ID = 3524

-- Splits on ":" keeping empty fields, which string.gmatch can't do reliably in Lua 5.1.
local function fields(s)
  local out = {}
  local start = 1
  while true do
    local colon = s:find(":", start, true)
    if not colon then
      out[#out + 1] = s:sub(start)
      return out
    end
    out[#out + 1] = s:sub(start, colon - 1)
    start = colon + 1
  end
end

-- The Item Key, the way the Brain derives it (brain/src/brain/scan.py ItemKey): the itemID
-- and the bonus IDs in ascending order. Level and spec belong to whoever looks, so they're
-- left out. Nil for a link that isn't an item (a battle pet, say).
local function itemKey(link)
  local itemString = link:match("|Hitem:([^|]*)|h")
  if not itemString then
    return nil
  end
  local f = fields(itemString)
  local key = { f[1] }
  local bonusIDs = {}
  for i = NUM_BONUS_IDS + 1, NUM_BONUS_IDS + (tonumber(f[NUM_BONUS_IDS]) or 0) do
    local id = tonumber(f[i])
    if id ~= AH_ITEM_KEY_BONUS_ID then
      bonusIDs[#bonusIDs + 1] = id
    end
  end
  table.sort(bonusIDs)
  for _, id in ipairs(bonusIDs) do
    key[#key + 1] = tostring(id)
  end
  return table.concat(key, ":")
end

-- A Craft has no price of its own (its note says what it uses), and a Hold's worth hangs on
-- its Prediction (ADR-0006).
local function holdingLine(r)
  local head = "AQ: " .. r.action .. " " .. r.quantity
  if r.action == "Craft" then
    return head .. " (" .. r.note .. ")"
  elseif r.action == "Hold" then
    return head .. " under " .. r.prediction
  end
  return head .. " @ " .. Money.format(r.price)
end

-- A Shopping List row is a Flip; a Prediction buy is held under its Prediction. A Flip to
-- Craft buys the output's reagents, not the output, so it has no price.
local function buyLine(r)
  if r.buys then
    local character = RecommendationTable.crafter(r)
    return "AQ: Buy reagents, Craft " .. r.quantity .. (character and (" on " .. character) or "")
  end
  local line = "AQ: Buy " .. r.quantity .. " @ max " .. Money.format(r.price)
  if r.prediction then
    line = line .. " under " .. r.prediction
  end
  return line
end

function TooltipLines.forLink(recommendations, realm, faction, link)
  local lines = {}
  local entry = recommendations and recommendations[realm] and recommendations[realm][faction]
  local key = link and itemKey(link)
  if not entry or not key then
    return lines
  end
  local function add(rows, lineOf)
    for _, r in ipairs(rows) do
      if r.itemKey == key and not RecommendationTable.lowValue(r) then
        lines[#lines + 1] = lineOf(r)
      end
    end
  end
  add(entry.holdings, holdingLine)
  add(entry.shoppingList, buyLine)
  add(entry.predictionBuys, buyLine)
  return lines
end

ns.TooltipLines = TooltipLines
return TooltipLines
