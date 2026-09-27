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
    "as of " .. formatTime(entry.asOf) .. ", " .. age(now - entry.asOf)
      .. string.format(", Observation Window %.1f h", entry.windowHours),
    "Gold " .. Money.format(entry.gold)
      .. ", Shopping List " .. Money.format(entry.shoppingCost)
      .. ", Prediction buys " .. Money.format(entry.predictionCost),
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

-- The item's name, or its Item Key until the client has loaded it.
local function nameFor(itemKey, nameOf)
  return nameOf(itemString(itemKey)) or ("item:" .. itemKey)
end

-- A Flip to Craft's reagent buy, e.g. "Buy 12 Linen Cloth @ max 1s 20c". The Brain only
-- knows names from own Listings, so naming reagents falls to the Addon (ADR-0009).
local function reagentLine(buy, nameOf)
  local where = buy.merchant and " from a merchant @ " or " @ max "
  return "Buy " .. buy.quantity .. " " .. nameFor(buy.itemKey, nameOf) .. where
    .. Money.format(buy.maxUnitPrice)
end

-- A Flip to Craft's tooltip lists its reagent buys; its note only names them by ID.
local function tooltip(r, nameOf)
  local lines = {}
  if r.buys then
    for _, buy in ipairs(r.buys) do
      lines[#lines + 1] = reagentLine(buy, nameOf)
    end
    return lines
  end
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

-- A row the Brain couldn't choose an Action for, or a Vendor that brings nothing. The
-- Table folds these into a count, and item tooltips leave them out.
function RecommendationTable.lowValue(r)
  return r.action == nil or (r.action == "Vendor" and r.profit == 0)
end

-- The Character a Craft row names in its note ("on <Character>: uses ..."), or nil.
function RecommendationTable.crafter(r)
  return r.note and r.note:match("^on ([^:]+):")
end

-- A Flip to Craft's note names reagents by ID, which is no use in game: the summary keeps
-- the Character and leaves the reagents to the tooltip. The Action column says "Craft".
local function flipToCraftNote(r)
  local character = RecommendationTable.crafter(r)
  local n = #r.buys
  return (character and ("on " .. character .. ", ") or "") .. n
    .. (n == 1 and " reagent" or " reagents")
end

-- A Shopping List row is bought to sell as is, or its reagents are bought to craft it.
local function shoppingCells(r, name)
  local action = r.buys and "Craft" or "Buy"
  local note = r.buys and flipToCraftNote(r) or r.note or ""
  return {
    name, action, tostring(r.quantity), money(r.price), money(r.postAt), money(r.profit), money(r.cost), note,
  }
end

-- Raw sort keys, column for column with the cells, so money never sorts as text. A nil key
-- (not known) sorts last whichever way the column goes.
local function holdingKeys(r, name, cells)
  local profit = r.action ~= "Hold" and r.profit or nil
  return { name:lower(), cells[2]:lower(), r.quantity, r.price, profit, cells[6]:lower() }
end

local function shoppingKeys(r, name, cells)
  return { name:lower(), cells[2]:lower(), r.quantity, r.price, r.postAt, r.profit, r.cost, cells[8]:lower() }
end

local function predictionBuyCells(r, name)
  return { name, r.prediction or "", tostring(r.quantity), money(r.price), money(r.maxLoss) }
end

local function predictionBuyKeys(r, name, cells)
  return { name:lower(), cells[2]:lower(), r.quantity, r.price, r.maxLoss }
end

-- What an empty tab says, in place of its rows.
local NOTHING = {
  ["Holdings"] = "Nothing in Holdings right now",
  ["Shopping List"] = "Nothing on the Shopping List right now",
  ["Prediction buys"] = "No Prediction buys right now",
}

-- Orders a section's rows by state.column, largest first when state.descending. Rows
-- without a key for that column go last. Ties go largest Price x Qty first (so Holds,
-- whose Profit is unknown, line up by the gold they tie up), then in the Brain's order.
function RecommendationTable.sort(section, state)
  local c = state.column
  table.sort(section.rows, function(a, b)
    local ka, kb = a.keys[c], b.keys[c]
    if ka ~= kb then
      if ka == nil or kb == nil then
        return kb == nil
      end
      if state.descending then
        return ka > kb
      end
      return ka < kb
    end
    if a.worth ~= b.worth then
      return a.worth > b.worth
    end
    return a.order < b.order
  end)
end

-- Columns sorted by their text. A first click sorts these A to Z and the rest largest first.
local TEXT_COLUMNS = { Item = true, Action = true, Note = true, Prediction = true }

-- The sort after a click on a column header: the clicked column's first direction, or the
-- other direction if it's the column already sorted by.
function RecommendationTable.nextSort(section, state, column)
  if state.column == column then
    return { column = column, descending = not state.descending }
  end
  return { column = column, descending = not TEXT_COLUMNS[section.columns[column]] }
end

local function section(title, columns, rows, cells, keys, default, nameOf)
  local out = { title = title, columns = columns, rows = {}, sort = default }
  local folded = 0
  for _, r in ipairs(rows) do
    if RecommendationTable.lowValue(r) then
      folded = folded + 1
    else
      local name = nameFor(r.itemKey, nameOf)
      local rowCells = cells(r, name)
      out.rows[#out.rows + 1] = {
        itemString = itemString(r.itemKey),
        cells = rowCells,
        keys = keys(r, name, rowCells),
        worth = (r.price or 0) * (r.quantity or 0),
        order = #out.rows + 1,
        tooltip = tooltip(r, nameOf),
      }
    end
  end
  RecommendationTable.sort(out, default)
  out.tab = title .. " (" .. #out.rows .. ")"
  if #out.rows == 0 then
    out.empty = NOTHING[title]
  end
  if folded > 0 then
    out.more = folded .. " more (worth 0c or no data)"
  end
  return out
end

-- The tab the table opens on. The AH is where the Shopping List gets bought, so opening
-- there always lands on it; /aq recs reopens the tab last picked (saved as its title).
function RecommendationTable.openingTab(saved, byAuctionHouse)
  if byAuctionHouse or not NOTHING[saved] then
    return "Shopping List"
  end
  return saved
end

-- The header note for Scans the table doesn't reflect yet, or nil when there are none.
-- unsaved: taken since the last reload, so still only in memory. unimported: saved at the
-- last reload, waiting on the Brain. Unsaved ones need a reload first, whatever the rest.
function RecommendationTable.waitingNote(unsaved, unimported)
  local n = unsaved + unimported
  if n == 0 then
    return nil
  end
  local scans = n == 1 and "1 Scan" or n .. " Scans"
  local them = n == 1 and "it" or "them"
  local step = unsaved > 0 and "Reload to send " .. them .. " to the Brain"
    or "Reload once the Brain has " .. them
  -- Short: it sits right of the header lines, left of the Reload button.
  return scans .. " waiting: " .. step
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
        holdingKeys,
        { column = 5, descending = true },
        nameOf
      ),
      section(
        "Shopping List",
        { "Item", "Action", "Qty", "Max price", "Post at", "Profit", "Cost", "Note" },
        entry.shoppingList,
        shoppingCells,
        shoppingKeys,
        { column = 6, descending = true },
        nameOf
      ),
      section(
        "Prediction buys",
        { "Item", "Prediction", "Qty", "Max price", "Max Loss" },
        entry.predictionBuys,
        predictionBuyCells,
        predictionBuyKeys,
        { column = 5, descending = false },
        nameOf
      ),
    },
  }
end

ns.RecommendationTable = RecommendationTable
return RecommendationTable
