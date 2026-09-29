-- Turns an item link into the lines the Addon adds to that item's tooltip: one per
-- Recommendation the Market has for its Item Key, e.g. "AQ: Sell 2 @ 1g 28s", then its Buy
-- Under (#88), then one per Character holding it.
--
-- Plain Lua with no WoW API calls, so it runs under busted.
local _, ns = ...
ns = ns or {}

-- In game Money.lua loads first (see the .toc), so require, which WoW lacks, isn't reached.
local Money = ns.Money or require("Money")
local RecommendationTable = ns.RecommendationTable or require("RecommendationTable")
local DisenchantGroup = ns.DisenchantGroup or require("DisenchantGroup")

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

TooltipLines.itemKey = itemKey

-- A Craft has no price of its own: it names its Character, and its reagents follow as
-- lines of their own. One that can't be made says why. A Disenchant is the same, with its
-- expected mats (#76). A Hold's worth hangs on its Prediction (ADR-0006).
local function holdingLine(r, nameOf)
  local head = "AQ: " .. r.action .. " " .. r.quantity
  if r.action == "Disenchant" then
    return head .. " on " .. r.character
  elseif r.action == "Craft" then
    return r.uses and (head .. " on " .. r.character)
      or (head .. " (" .. RecommendationTable.note(r, nameOf) .. ")")
  elseif r.action == "Hold" then
    return head .. " under " .. r.prediction
  end
  return head .. " @ " .. Money.format(r.price)
end

-- A Shopping List row is a Flip; a Prediction buy is held under its Prediction. A Flip to
-- Craft buys the output's reagents, not the output, so it has no price.
local function buyLine(r)
  if r.buys then
    return "AQ: Buy reagents, Craft " .. r.quantity .. " on " .. r.character
  end
  local line = "AQ: Buy " .. r.quantity .. " @ max " .. Money.format(r.price)
  if r.prediction then
    line = line .. " under " .. r.prediction
  end
  return line
end

-- A Buy Under (#88), e.g. "AQ: Buy Under 21s: Craft Bolt of Linen Cloth (Kash-Patel), seen
-- 14 Scans / 7d".
local function buyUnderLine(r, nameOf)
  return "AQ: Buy Under " .. Money.format(r.price) .. ": " .. RecommendationTable.wayOut(r, nameOf)
    .. ", seen " .. RecommendationTable.seen(r)
end

-- The highest Buy Under of keys (a set of Item Keys), or of the item's Disenchant source
-- group (#88). item is { itemID, info, excluded }, or nil to leave groups out.
local function bestBuyUnder(entry, keys, item)
  local best
  for _, b in ipairs(entry.buyUnder or {}) do
    local mine
    if b.group then
      mine = item ~= nil and DisenchantGroup.contains(b.group, item.itemID, item.info, item.excluded)
    else
      mine = keys[b.itemKey]
    end
    if mine and (not best or b.price > best.price) then
      best = b
    end
  end
  return best
end

-- The lines for each of keys (a set of Item Keys) in the Market's entry, in the order the
-- Recommendation Table has them, then the one Buy Under (see bestBuyUnder), then who holds
-- each.
local function linesFor(entry, keys, nameOf, item)
  local lines = {}
  local held = RecommendationTable.heldUnits(entry.holdings)
  local holdersOf = entry.held or {}
  local function add(rows, lineOf)
    for _, r in ipairs(rows) do
      if keys[r.itemKey] and not RecommendationTable.lowValue(r) then
        lines[#lines + 1] = lineOf(r, nameOf)
        local details = r.action == "Craft" and RecommendationTable.reagentLines(r, nameOf, holdersOf)
          or r.mats and RecommendationTable.matLines(r, nameOf)
          or RecommendationTable.roiLines(r, held[r.itemKey])
        for _, line in ipairs(details) do
          lines[#lines + 1] = line
        end
      end
    end
  end
  add(entry.holdings, holdingLine)
  add(entry.shoppingList, buyLine)
  add(entry.predictionBuys, buyLine)
  local buyUnder = bestBuyUnder(entry, keys, item)
  if buyUnder then
    lines[#lines + 1] = buyUnderLine(buyUnder, nameOf)
  end
  local sorted = {}
  for key in pairs(keys) do
    sorted[#sorted + 1] = key
  end
  table.sort(sorted)
  for _, key in ipairs(sorted) do
    for _, line in ipairs(RecommendationTable.holderLines(holdersOf[key])) do
      lines[#lines + 1] = line
    end
  end
  return lines
end

local function entryFor(recommendations, realm, faction)
  return recommendations and recommendations[realm] and recommendations[realm][faction]
end

-- nameOf(itemString) names a Craft's reagents, as in the Recommendation Table. info is
-- what the client says about the item ({ quality, itemLevel, classID, equipLoc }) and
-- excluded the Brain's disenchantExcluded, for its Disenchant source group's Buy Under;
-- without info, groups are left out.
function TooltipLines.forLink(recommendations, realm, faction, link, nameOf, info, excluded)
  local entry = entryFor(recommendations, realm, faction)
  local key = link and itemKey(link)
  if not entry or not key then
    return {}
  end
  local item = info and { itemID = tonumber(key:match("^(%d+)")), info = info, excluded = excluded }
  return linesFor(entry, { [key] = true }, nameOf, item)
end

-- An AH browse row for a suffixed item links the plain item (#96), and one row can group
-- several Item Keys under one name ("Items in this group may vary in stats"). So its lines
-- are those of every Item Key in the Market with that itemID whose name, by nameOf, is the
-- row's name.
-- info and excluded as in forLink.
function TooltipLines.forItemName(recommendations, realm, faction, itemID, name, nameOf, info, excluded)
  local entry = entryFor(recommendations, realm, faction)
  if not entry then
    return {}
  end
  -- Until the client has the row's name, only the group's Buy Under can be told.
  local keys = {}
  local prefix = tostring(itemID)
  local function consider(key)
    local id = key:match("^(%d+)")
    if name and id == prefix and nameOf(RecommendationTable.itemString(key)) == name then
      keys[key] = true
    end
  end
  for _, rows in ipairs({ entry.holdings, entry.shoppingList, entry.predictionBuys, entry.buyUnder }) do
    for _, r in ipairs(rows or {}) do
      if r.itemKey then -- a Disenchant source group's Buy Under has none (#88)
        consider(r.itemKey)
      end
    end
  end
  for key in pairs(entry.held or {}) do
    consider(key)
  end
  local item = info and { itemID = itemID, info = info, excluded = excluded }
  return linesFor(entry, keys, nameOf, item)
end

ns.TooltipLines = TooltipLines
return TooltipLines
