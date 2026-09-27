-- Turns one Market's entry in AzerothQuantRecommendations into what the Recommendation
-- Table frame draws: header lines, and per section the cell text, tooltip lines and how
-- many low-value rows were folded away.
--
-- Plain Lua with no WoW API calls, so it runs under busted. Item names come through
-- nameOf(itemID), which the glue backs with GetItemInfo.
local _, ns = ...
ns = ns or {}

-- In game Money.lua loads first (see the .toc), so require, which WoW lacks, isn't reached.
local Money = ns.Money or require("Money")

local RecommendationTable = {}

local EMPTY = "No Recommendations yet: Scan, /reload, and let the Brain import."

local function age(seconds)
  local minutes = math.floor(seconds / 60)
  if minutes < 60 then
    return minutes .. " min ago"
  end
  local hours = math.floor(minutes / 60)
  if hours < 48 then
    return hours .. " h ago"
  end
  return math.floor(hours / 24) .. " days ago"
end

-- The WoW client has no os library, only a global date; plain Lua (busted) has os.date.
local function formatTime(t)
  return (date or os.date)("%H:%M", t)
end

local function header(entry, now)
  return {
    "as of " .. formatTime(entry.asOf) .. ", " .. age(now - entry.asOf),
    "Gold " .. Money.format(entry.gold)
      .. ", Shopping List " .. Money.format(entry.shoppingCost)
      .. ", Prediction buys " .. Money.format(entry.predictionCost),
    string.format("Observation Window %.1f h", entry.windowHours),
  }
end

local NUM_BONUS_IDS_FIELD = 12

-- An Item Key is "itemID" or "itemID:bonus1:bonus2...". The item string carries the bonus
-- IDs (the random suffix is one) so GetItemInfo gives the suffixed name and link.
local function itemString(itemKey)
  local ids = {}
  for id in itemKey:gmatch("%d+") do
    ids[#ids + 1] = id
  end
  if #ids == 1 then
    return "item:" .. ids[1]
  end
  return "item:" .. ids[1] .. string.rep(":", NUM_BONUS_IDS_FIELD) .. (#ids - 1) .. ":"
    .. table.concat(ids, ":", 2)
end

local function money(copper)
  return copper and Money.format(copper) or ""
end

local function tooltip(r)
  local lines = {}
  if r.margin then
    lines[#lines + 1] = "Margin " .. Money.format(r.margin)
  end
  if r.saleEvents then
    lines[#lines + 1] = "Sales " .. r.saleEvents
  end
  if r.note then
    lines[#lines + 1] = r.note
  end
  return lines
end

-- A Hold only pays off if its Prediction comes true, so its profit isn't known (ADR-0006).
local function holdingCells(r, name)
  local profit = r.action == "Hold" and "unknown" or money(r.profit)
  local note = r.prediction and ("under " .. r.prediction) or r.note or ""
  return { name, r.action, tostring(r.quantity), money(r.price), profit, note }
end

-- A row the Brain couldn't choose an Action for, or a Vendor that brings nothing.
local function lowValue(r)
  return r.action == nil or (r.action == "Vendor" and r.profit == 0)
end

local function shoppingCells(r, name)
  return { name, tostring(r.quantity), money(r.price), money(r.profit), money(r.cost) }
end

local function predictionBuyCells(r, name)
  return { name, r.prediction or "", tostring(r.quantity), money(r.price), money(r.maxLoss) }
end

local function section(title, columns, rows, cells, nameOf)
  local out = { title = title, columns = columns, rows = {} }
  local folded = 0
  for _, r in ipairs(rows) do
    if lowValue(r) then
      folded = folded + 1
    else
      local s = itemString(r.itemKey)
      local name = nameOf(s) or ("item:" .. r.itemKey)
      out.rows[#out.rows + 1] = { itemString = s, cells = cells(r, name), tooltip = tooltip(r) }
    end
  end
  if folded > 0 then
    out.more = folded .. " more (worth 0c or no data)"
  end
  return out
end

function RecommendationTable.build(recommendations, realm, faction, now, nameOf)
  local entry = recommendations and recommendations[realm] and recommendations[realm][faction]
  if not entry then
    return { empty = EMPTY }
  end
  return {
    title = realm .. " " .. faction,
    header = header(entry, now),
    sections = {
      section(
        "Holdings",
        { "Item", "Action", "Qty", "Price", "Profit", "Note" },
        entry.holdings,
        holdingCells,
        nameOf
      ),
      section(
        "Shopping List",
        { "Item", "Qty", "Max price", "Profit", "Cost" },
        entry.shoppingList,
        shoppingCells,
        nameOf
      ),
      section(
        "Prediction buys",
        { "Item", "Prediction", "Qty", "Max price", "Max Loss" },
        entry.predictionBuys,
        predictionBuyCells,
        nameOf
      ),
    },
  }
end

ns.RecommendationTable = RecommendationTable
return RecommendationTable
