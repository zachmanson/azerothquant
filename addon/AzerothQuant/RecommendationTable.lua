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

-- A Craft's reagents by name: the Sub-crafts that make short ones (#33), deepest first,
-- then the held ones it uses, then the ones it buys, across the whole chain. A reagent
-- that's partly held and partly bought shows as a line of each.
function RecommendationTable.reagentLines(r, nameOf)
  local lines = {}
  for _, sub in ipairs(r.via or {}) do
    lines[#lines + 1] = "Craft " .. sub.crafts .. " " .. nameFor(sub.itemKey, nameOf) .. " on " .. sub.character
  end
  for _, use in ipairs(r.uses or {}) do
    lines[#lines + 1] = "Use " .. use.quantity .. " " .. nameFor(use.itemKey, nameOf)
  end
  for _, buy in ipairs(r.buys or {}) do
    lines[#lines + 1] = reagentLine(buy, nameOf)
  end
  return lines
end

-- A row's note. A Craft that can't be made says why, e.g. "on Kash-Patel: no market data
-- for Copper Ore": the Brain writes the reason as fields, so the reagent goes by name (#75).
-- A reason the Addon doesn't know yet keeps the Brain's note.
function RecommendationTable.note(r, nameOf)
  local reason = r.blocked and r.blocked.reason
  if reason == "noData" then
    return "on " .. r.character .. ": no market data for " .. nameFor(r.blocked.itemKey, nameOf)
  elseif reason == "unknownBindType" then
    return "on " .. r.character .. ": unknown bind type"
  end
  return r.note
end

-- The hint that it's a good time to sell (#50): the raid-target star tinted to the hint's
-- green (its last three numbers), since the game's fonts may not have a star glyph.
RecommendationTable.STAR = "|TInterface\\TargetingFrame\\UI-RaidTargetingIcon_1:0:0:0:0:64:64:0:64:0:64:128:255:128|t"

local GAIN_COLOR, LOSS_COLOR, HINT_COLOR = "|cff1eff00", "|cffff2020", "|cff80ff80"

local function wholePercent(share)
  return math.floor(share * 100 + 0.5)
end

local function percent(share)
  return string.format("%+d%%", wholePercent(share))
end

-- A Sell or Vendor's ROI on what its units cost (#50), blank when none of them were
-- bought on the Auction House.
local function roiCell(r)
  if not r.roi then
    return ""
  end
  if r.roiHint then
    return HINT_COLOR .. percent(r.roi) .. " " .. RecommendationTable.STAR .. "|r"
  end
  -- By the percent shown, so a loss that rounds to +0% isn't red.
  return (wholePercent(r.roi) < 0 and LOSS_COLOR or GAIN_COLOR) .. percent(r.roi) .. "|r"
end

-- How many units of each Item Key the Holdings hold, which a Paid covers some or all of:
-- every row but a Craft's, whose units are made rather than held.
function RecommendationTable.heldUnits(holdings)
  local held = {}
  for _, r in ipairs(holdings or {}) do
    if r.action ~= "Craft" then
      held[r.itemKey] = (held[r.itemKey] or 0) + r.quantity
    end
  end
  return held
end

-- A Sell or Vendor's lines on what its units cost and what they net per unit after the cut
-- (#50), and the hint when it's a good time to sell. held is heldUnits' count for its
-- Item Key.
function RecommendationTable.roiLines(r, held)
  if not r.roi then
    return {}
  end
  local share = r.paidUnits < held and (" (" .. r.paidUnits .. " of " .. held .. ")") or ""
  local lines = {
    "Paid " .. Money.format(r.paid) .. " each" .. share .. ", nets " .. Money.format(r.paid * (1 + r.roi))
      .. ": " .. percent(r.roi),
  }
  if r.roiHint then
    lines[2] = "Good time to sell: nets " .. percent(r.roi) .. " on what you paid (hint only)"
  end
  return lines
end

-- A Craft's tooltip lists its reagents; its note only names them by ID.
local function tooltip(r, nameOf, held)
  if r.uses or r.buys then
    return RecommendationTable.reagentLines(r, nameOf)
  end
  local lines = RecommendationTable.roiLines(r, held[r.itemKey])
  if r.margin then
    lines[#lines + 1] = "Margin " .. Money.format(r.margin)
  end
  if r.saleEvents then
    lines[#lines + 1] = "Sales " .. r.saleEvents
  end
  local note = RecommendationTable.note(r, nameOf)
  if note then
    lines[#lines + 1] = note
  end
  return lines
end

-- A row the Brain couldn't choose an Action for, or a Vendor that brings nothing. The
-- Table folds these into a count, and item tooltips leave them out.
function RecommendationTable.lowValue(r)
  return r.action == nil or (r.action == "Vendor" and r.profit == 0)
end

-- A Craft's note names reagents by ID, which is no use in game: the summary keeps the
-- Character and the count of distinct reagents, and leaves the reagents to the tooltip.
local function craftNote(r)
  local seen, n = {}, 0
  for _, list in ipairs({ r.uses or {}, r.buys or {} }) do
    for _, reagent in ipairs(list) do
      if not seen[reagent.itemKey] then
        seen[reagent.itemKey] = true
        n = n + 1
      end
    end
  end
  return "on " .. r.character .. ", " .. n .. (n == 1 and " reagent" or " reagents")
end

-- A Hold only pays off if its Prediction comes true, so its profit isn't known (ADR-0006).
-- A Craft that can't be made (it uses nothing) says why.
local function holdingCells(r, name, nameOf)
  local profit = r.action == "Hold" and "unknown" or money(r.profit)
  local note = r.prediction and ("under " .. r.prediction) or (r.uses and craftNote(r))
    or RecommendationTable.note(r, nameOf) or ""
  return { name, r.action, tostring(r.quantity), money(r.price), profit, roiCell(r), note }
end

-- A Shopping List row is bought to sell as is, or its reagents are bought to craft it.
local function shoppingCells(r, name)
  local action = r.buys and "Craft" or "Buy"
  local note = r.buys and craftNote(r) or r.note or ""
  return {
    name, action, tostring(r.quantity), money(r.price), money(r.postAt), money(r.profit), money(r.cost), note,
  }
end

-- Raw sort keys, column for column with the cells, so money never sorts as text. A nil key
-- (not known) sorts last whichever way the column goes.
local function holdingKeys(r, name, cells)
  local profit = r.action ~= "Hold" and r.profit or nil
  return { name:lower(), cells[2]:lower(), r.quantity, r.price, profit, r.roi, cells[7]:lower() }
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
  local held = RecommendationTable.heldUnits(rows)
  local out = { title = title, columns = columns, rows = {}, sort = default }
  local folded = 0
  for _, r in ipairs(rows) do
    if RecommendationTable.lowValue(r) then
      folded = folded + 1
    else
      local name = nameFor(r.itemKey, nameOf)
      local rowCells = cells(r, name, nameOf)
      out.rows[#out.rows + 1] = {
        itemString = itemString(r.itemKey),
        cells = rowCells,
        keys = keys(r, name, rowCells),
        worth = (r.price or 0) * (r.quantity or 0),
        order = #out.rows + 1,
        tooltip = tooltip(r, nameOf, held),
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
        { "Item", "Action", "Qty", "Price", "Profit", "ROI", "Note" },
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
