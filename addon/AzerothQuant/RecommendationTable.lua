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
local DisenchantGroup = ns.DisenchantGroup or require("DisenchantGroup")
local BoughtMarks = ns.BoughtMarks or require("BoughtMarks")

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

-- budget: the one the player set in the box, nil for all the gold. entry.budget is the one
-- the Brain sized the options within, which lags it until the next reload. spent: what the
-- rows marked Bought spent (#97).
local function header(entry, now, budget, spent)
  local stale = budget ~= entry.budget and " (Reload to re-size)" or ""
  local bought = spent > 0 and ", Bought " .. Money.format(spent) or ""
  return {
    "as of " .. formatTime(entry.asOf) .. ", " .. age(now - entry.asOf)
      .. string.format(", Observation Window %.1f h", entry.windowHours),
    "Gold " .. Money.format(entry.gold)
      .. ", Budget " .. (budget and Money.format(budget) or "all") .. stale .. bought
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

RecommendationTable.itemString = itemString

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

-- Units the crafter doesn't hold of a reagent it uses, mailed from the Characters that
-- hold the most unbound ones first (#38). Bound units can't be mailed, but the crafter's
-- own bound ones still count toward what it has. holdersOf is the entry's held. uses
-- covers the whole chain, so with a Sub-craft on another Character it can't say which
-- Character needs which reagents: no mail lines then.
local function mailLines(r, nameOf, holdersOf)
  local lines = {}
  for _, sub in ipairs(r.via or {}) do
    if sub.character ~= r.character then
      return lines
    end
  end
  for _, use in ipairs(r.uses or {}) do
    local holders, short = {}, use.quantity
    for _, h in ipairs(holdersOf[use.itemKey] or {}) do
      local mailable = h.bags + h.bank - h.bound
      if h.character == r.character then
        short = short - h.bags - h.bank
      elseif mailable > 0 then
        holders[#holders + 1] = { character = h.character, mailable = mailable }
      end
    end
    table.sort(holders, function(a, b)
      if a.mailable ~= b.mailable then
        return a.mailable > b.mailable
      end
      return a.character < b.character
    end)
    for _, h in ipairs(holders) do
      if short <= 0 then
        break
      end
      local n = math.min(short, h.mailable)
      lines[#lines + 1] = "Mail " .. n .. " " .. nameFor(use.itemKey, nameOf) .. " from " .. h.character
        .. " to " .. r.character
      short = short - n
    end
  end
  return lines
end

-- A Craft's reagents by name: the Sub-crafts that make short ones (#33), deepest first,
-- then the held ones it uses, then the ones it buys, across the whole chain. A reagent
-- that's partly held and partly bought shows as a line of each. Given holdersOf (the
-- entry's held), the held ones the crafter is short of follow as mail lines.
function RecommendationTable.reagentLines(r, nameOf, holdersOf)
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
  for _, line in ipairs(mailLines(r, nameOf, holdersOf or {})) do
    lines[#lines + 1] = line
  end
  return lines
end

-- A Disenchant's expected mats by name (#76). They're expected quantities, so they come
-- in fractions.
function RecommendationTable.matLines(r, nameOf)
  local lines = {}
  for _, mat in ipairs(r.mats or {}) do
    lines[#lines + 1] = string.format("Expect %.2f %s", mat.quantity, nameFor(mat.itemKey, nameOf))
  end
  return lines
end

-- Which Characters hold an Item Key (#38), one line each in the Brain's order (by name),
-- e.g. "On Kash-Patel: 12 bags, 30 bank (5 bound)". holders is the entry's held[itemKey].
function RecommendationTable.holderLines(holders)
  local lines = {}
  for _, h in ipairs(holders or {}) do
    local parts = {}
    if h.bags > 0 then
      parts[#parts + 1] = h.bags .. " bags"
    end
    if h.bank > 0 then
      parts[#parts + 1] = h.bank .. " bank"
    end
    local bound = h.bound > 0 and (" (" .. h.bound .. " bound)") or ""
    lines[#lines + 1] = "On " .. h.character .. ": " .. table.concat(parts, ", ") .. bound
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

-- Marks a Holdings row the logged-in Character has in its bags (#38): the backpack icon.
RecommendationTable.BAG = "|TInterface\\Buttons\\Button-Backpack-Up:0|t"

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
-- every row but a Craft's, whose units are made rather than held, and a Buy Under's, which
-- has none (#88).
function RecommendationTable.heldUnits(holdings)
  local held = {}
  for _, r in ipairs(holdings or {}) do
    if r.quantity and r.action ~= "Craft" then
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

local function plural(n, word)
  return n .. " " .. word .. (n == 1 and "" or "s")
end

-- A Flip's clicks and wait (#98), e.g. "12 Listings + 3 posts, sells in ~2.5 days". A Flip
-- to Vendor posts nothing and has no wait.
local function clicksLine(r)
  if not r.days then
    return plural(r.listings, "Listing") .. ", vendor now"
  end
  local wait = r.days < 1 and string.format("~%d h", math.max(1, math.floor(r.days * 24 + 0.5)))
    or string.format("~%.1f days", r.days)
  return plural(r.listings, "Listing") .. " + " .. plural(r.posts, "post") .. ", sells in " .. wait
end

-- A row's details. A Craft's list its reagents, since its note only names them by ID.
local function details(r, nameOf, held, holdersOf)
  if r.uses or r.buys then
    return RecommendationTable.reagentLines(r, nameOf, holdersOf)
  end
  if r.mats then
    return RecommendationTable.matLines(r, nameOf)
  end
  local lines = RecommendationTable.roiLines(r, held[r.itemKey])
  if r.listings then
    lines[#lines + 1] = clicksLine(r)
  end
  if r.margin then
    lines[#lines + 1] = "Margin " .. Money.format(r.margin)
  end
  if r.saleEvents then
    -- A held suffix's Sell Rate also counts its siblings' Sale Events (#58).
    local siblings = (r.siblingSales or 0) > 0 and " (+" .. r.siblingSales .. " other suffixes)" or ""
    lines[#lines + 1] = "Sales " .. r.saleEvents .. siblings
  end
  -- A Prediction buy's Max Loss counted Beta's Sale Events toward its room (#110).
  if r.roomFromBeta then
    lines[#lines + 1] = "Room partly from Beta"
  end
  local note = RecommendationTable.note(r, nameOf)
  if note then
    lines[#lines + 1] = note
  end
  return lines
end

-- A row's details, then which Characters hold its Item Key (#38).
local function tooltip(r, nameOf, held, holdersOf)
  local lines = details(r, nameOf, held, holdersOf)
  for _, line in ipairs(RecommendationTable.holderLines(holdersOf[r.itemKey])) do
    lines[#lines + 1] = line
  end
  return lines
end

-- A row the Brain couldn't choose an Action for, or a Vendor that brings nothing. The
-- Table folds these into a count, and item tooltips leave them out. A Buy Under has a way
-- out rather than an Action (#88).
function RecommendationTable.lowValue(r)
  return (r.action == nil and r.way == nil) or (r.action == "Vendor" and r.profit == 0)
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
-- A Craft that can't be made (it uses nothing) says why. A Disenchant's note names mats by
-- ID, so the summary keeps its Character and leaves the mats to the tooltip.
local function holdingCells(r, name, nameOf)
  local profit = r.action == "Hold" and "unknown" or money(r.profit)
  local note = r.prediction and ("under " .. r.prediction) or (r.uses and craftNote(r))
    or (r.mats and ("on " .. r.character)) or RecommendationTable.note(r, nameOf) or ""
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

-- A Flip's Profit per Listing bought and stack posted, per day until its last unit sells,
-- and on its Cost (#98). The days are at least one (#101). A Flip to Vendor sells now, so
-- it sorts first per day. nil each for a row the Brain wrote no counts for.
local function measures(r)
  if not r.listings then
    return nil, nil, nil
  end
  local perDay = r.days and r.profit / math.max(r.days, 1) or math.huge
  return r.profit / (r.listings + r.posts), perDay, r.profit / r.cost
end

-- The Shopping List tab's Flips to Sell and Flips to Vendor: the Flips to Craft's columns
-- with Per click, Per day and ROI after Profit.
local function flipCells(r, name)
  local cells = shoppingCells(r, name)
  local perClick, perDay, roi = measures(r)
  local day = perDay == math.huge and "now" or money(perDay)
  local share = roi and string.format("%d%%", wholePercent(roi)) or ""
  table.insert(cells, 7, money(perClick))
  table.insert(cells, 8, day)
  table.insert(cells, 9, share)
  return cells
end

local function flipKeys(r, name, cells)
  local perClick, perDay, roi = measures(r)
  return {
    name:lower(), cells[2]:lower(), r.quantity, r.price, r.postAt, r.profit, perClick, perDay, roi, r.cost,
    cells[11]:lower(),
  }
end

local function predictionBuyCells(r, name)
  return { name, r.prediction or "", tostring(r.quantity), money(r.price), money(r.maxLoss) }
end

local function predictionBuyKeys(r, name, cells)
  return { name:lower(), cells[2]:lower(), r.quantity, r.price, r.maxLoss }
end

-- How a Buy Under gets out (#88): Vendor, Sell, e.g. "Craft Bolt of Linen Cloth
-- (Kash-Patel)" for a Craft it's a reagent of, or "Disenchant (Bob) -> Strange Dust, Greater
-- Magic Essence" (an arrow the game fonts surely have).
function RecommendationTable.wayOut(r, nameOf)
  if r.way == "Craft" then
    return "Craft " .. nameFor(r.output, nameOf) .. " (" .. r.crafter .. ")"
  end
  if r.way == "Disenchant" then
    local mats = {}
    for _, mat in ipairs(r.mats or {}) do
      mats[#mats + 1] = nameFor(mat.itemKey, nameOf)
    end
    return "Disenchant (" .. r.disenchanter .. ") -> " .. table.concat(mats, ", ")
  end
  return r.way
end

-- How many Scans saw a Listing at or under a Buy Under, in how many days, e.g.
-- "14 Scans / 7d" (#88).
function RecommendationTable.seen(r)
  return plural(r.seen, "Scan") .. " / " .. r.windowDays .. "d"
end

-- A Buy Under's cells (#88): its price, how it gets out, how many units it's good for, and
-- how many Scans saw a Listing at or under it.
local function buyUnderCells(r, name, nameOf)
  local units = r.units and tostring(r.units) or "no limit"
  local seen = RecommendationTable.seen(r)
  return { name, money(r.price), RecommendationTable.wayOut(r, nameOf), units, seen, r.listedNow and "listed now" or "" }
end

local function buyUnderKeys(r, name, cells)
  return { name:lower(), r.price, cells[3]:lower(), r.units or math.huge, r.seen, cells[6] }
end

-- The Beta Prior (#90): a Beta price beside each row early in Live, grey since it's only a
-- reference and never decides anything. A price only listed, not sold, is starred. beta is
-- the entry's; nil where Beta has no number for the Item Key.
local BETA_COLOR = "|cff808080"

local function betaPrice(beta, itemKey)
  return beta and itemKey and beta.prices[itemKey]
end

function RecommendationTable.betaCell(beta, itemKey)
  local p = betaPrice(beta, itemKey)
  if not p then
    return ""
  end
  return BETA_COLOR .. Money.format(p.price) .. (p.sold and "" or "*") .. "|r"
end

-- e.g. "Beta (Alliance, Classic Beta PvP): 2g 50s median sold, 7 Sale Events, 1.2/day".
function RecommendationTable.betaLine(beta, itemKey)
  local p = betaPrice(beta, itemKey)
  if not p then
    return nil
  end
  local how = p.sold and " median sold, " or " median listed, not sold, "
  local rate = p.perDay and string.format(", %.1f/day", p.perDay) or ""
  return "Beta (" .. beta.faction .. ", " .. beta.realm .. "): " .. Money.format(p.price) .. how
    .. plural(p.saleEvents, "Sale Event") .. rate
end

-- Puts value at place pos of a row's n cells or sort keys, moving the rest along. Keys can
-- hold nils, so the length operator can't be trusted to find the end.
local function insertAt(list, n, pos, value)
  for i = n, pos, -1 do
    list[i + 1] = list[i]
  end
  list[pos] = value
end

-- The place of the column with that name, or nil.
local function columnAt(columns, name)
  for c, column in ipairs(columns) do
    if column == name then
      return c
    end
  end
  return nil
end

-- Where the Beta column goes in a section's columns: before the Note, else last.
local function betaPlace(columns)
  return columnAt(columns, "Note") or #columns + 1
end

local BOUGHT_LINE = "Bought: right-click to undo"

-- What an empty tab says, in place of its rows.
local NOTHING = {
  ["Holdings"] = "Nothing in Holdings right now",
  ["Shopping List"] = "Nothing on the Shopping List right now",
  ["Flips to Craft"] = "No Flips to Craft right now",
  ["Prediction buys"] = "No Prediction buys right now",
  ["Buy Under"] = "No Buy Unders right now",
}

-- Orders a section's rows by state.column, largest first when state.descending. Rows
-- marked Bought (#97) go after the rest, and rows without a key for that column go last.
-- Ties go largest Price x Qty first (so Holds, whose Profit is unknown, line up by the gold
-- they tie up), then in the Brain's order.
function RecommendationTable.sort(section, state)
  local c = state.column
  table.sort(section.rows, function(a, b)
    if a.bought ~= b.bought then
      return b.bought ~= nil
    end
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
local TEXT_COLUMNS = { Item = true, Action = true, Note = true, Prediction = true, ["Way out"] = true }

-- The sort after a click on a column header: the clicked column's first direction, or the
-- other direction if it's the column already sorted by.
function RecommendationTable.nextSort(section, state, column)
  if state.column == column then
    return { column = column, descending = not state.descending }
  end
  return { column = column, descending = not TEXT_COLUMNS[section.columns[column]] }
end

-- A header-click sort as saved across sessions (#98): by its column's name, not its place,
-- so a saved sort survives a change of columns.
function RecommendationTable.savedSort(section, sort)
  return { column = section.columns[sort.column], descending = sort.descending }
end

-- A saved sort back in the section's column places, or nil when nothing is saved or the
-- section no longer has that column.
function RecommendationTable.restoredSort(section, saved)
  if not saved then
    return nil
  end
  for c, name in ipairs(section.columns) do
    if name == saved.column then
      return { column = c, descending = saved.descending }
    end
  end
  return nil
end

-- holdersOf is the entry's held: which Characters hold each Item Key. inBags(itemKey), given
-- for Holdings only, says whether the logged-in Character has it in its bags. budget, given
-- for the Shopping List and Flips to Craft only, folds away the options that cost more (#86).
-- beta is the entry's Beta Prior, and adds its column while the Brain writes one (#90).
-- marks, given for the buy-side tabs only, are the Market's rows marked Bought by id (#97).
local function section(title, columns, rows, cells, keys, default, nameOf, holdersOf, inBags, budget, beta, marks)
  local held = RecommendationTable.heldUnits(rows)
  local n, place = #columns, betaPlace(columns)
  if beta then
    columns = { unpack(columns) }
    insertAt(columns, n, place, "Beta")
  end
  -- markable: a right-click toggles a row's Bought mark (#97).
  local out = { title = title, columns = columns, rows = {}, sort = default, markable = marks ~= nil or nil }
  local noteAt = columnAt(columns, "Note")
  local folded, over = 0, 0
  for _, r in ipairs(rows) do
    -- A Disenchant source group's Buy Under is for no one item (#88).
    local name = r.group and DisenchantGroup.name(r.group) or nameFor(r.itemKey, nameOf)
    -- What a selection finds the row by after a redraw (#77), and what a Bought mark is
    -- kept under (#97). A Buy Under has a way out instead of an action, and two Characters
    -- can each Craft one output.
    local id = table.concat({ r.itemKey or name, r.action or r.way or "", r.character or "" }, " ")
    local bought = marks and marks[id] ~= nil or nil
    -- A marked row stays on show whatever it's worth now: its mark is still undone there.
    if RecommendationTable.lowValue(r) and not bought then
      folded = folded + 1
    elseif budget and not bought and (r.cost or 0) > budget then
      over = over + 1
    else
      local rowCells = cells(r, name, nameOf)
      if inBags and inBags(r.itemKey) then
        rowCells[1] = RecommendationTable.BAG .. " " .. name
      end
      local rowKeys = keys(r, name, rowCells)
      local rowTooltip = tooltip(r, nameOf, held, holdersOf)
      if beta then
        local p = betaPrice(beta, r.itemKey)
        insertAt(rowCells, n, place, RecommendationTable.betaCell(beta, r.itemKey))
        insertAt(rowKeys, n, place, p and p.price)
        rowTooltip[#rowTooltip + 1] = RecommendationTable.betaLine(beta, r.itemKey)
      end
      if bought then
        -- The Prediction buys tab has no Note: greyed out is all it shows.
        if noteAt then
          rowCells[noteAt] = "Bought"
        end
        rowTooltip[#rowTooltip + 1] = BOUGHT_LINE
      end
      out.rows[#out.rows + 1] = {
        id = id,
        bought = bought,
        record = r,
        itemString = r.itemKey and itemString(r.itemKey),
        cells = rowCells,
        keys = rowKeys,
        worth = (r.price or 0) * (r.quantity or 0),
        order = #out.rows + 1,
        tooltip = rowTooltip,
      }
    end
  end
  RecommendationTable.sort(out, default)
  out.tab = title .. " (" .. #out.rows .. ")"
  -- A tab whose options are all over the Budget isn't empty: its more line says so (#93).
  -- Low-value rows aren't options, so a tab of only those still says it's empty.
  if #out.rows == 0 and over == 0 then
    out.empty = NOTHING[title]
  end
  local more = {}
  if folded > 0 then
    more[#more + 1] = folded .. " more (worth 0c or no data)"
  end
  if over > 0 then
    more[#more + 1] = over .. " over the " .. (marks and BoughtMarks.spent(marks) > 0 and "gold left" or "Budget") .. " (Reload to re-size)"
  end
  out.more = #more > 0 and table.concat(more, ", ") or nil
  return out
end

-- The section's row with that id, if a redraw kept it (#77).
function RecommendationTable.find(section, id)
  for _, row in ipairs(section.rows) do
    if row.id == id then
      return row
    end
  end
  return nil
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
-- behind: the Brain hasn't imported Scans it should have (Nudge.brainBehind, #104), so
-- no Reload of the saved ones helps until `brain watch` runs. canLoad: the button is Load
-- (DataAddon.lua, #106), which picks up the Brain's import without a reload.
function RecommendationTable.waitingNote(unsaved, unimported, behind, canLoad)
  local n = unsaved + unimported
  if n == 0 then
    return nil
  end
  local scans = n == 1 and "1 Scan" or n .. " Scans"
  local them = n == 1 and "it" or "them"
  local step = unsaved > 0 and "Reload to send " .. them .. " to the Brain"
    or behind and "start brain watch"
    or (canLoad and "Load" or "Reload") .. " once the Brain has " .. them
  -- Short: it sits right of the header lines, left of the Reload button.
  return scans .. " waiting: " .. step
end

-- The key of a Market's Budget and Days to Sell in AzerothQuantDB (#86, #109): gold pools
-- per realm and faction, so that's what each covers.
function RecommendationTable.marketKey(realm, faction)
  return realm .. "-" .. faction
end

-- What the player typed in the Days to Sell box (#109), e.g. "2", "0.5" or "1d", as days.
-- A blank box is nil (not set) and still ok; zero or anything else is nil and not ok.
-- Saved per Market (`marketKey`) in AzerothQuantDB.daysToSell.
function RecommendationTable.parseDays(text)
  local trimmed = text:lower():match("^%s*(.-)%s*$")
  if trimmed == "" then
    return nil, true
  end
  local number = trimmed:match("^(%d+%.?%d*)%s*d?$") or trimmed:match("^(%.%d+)%s*d?$")
  local days = number and tonumber(number)
  if not days or days <= 0 then
    return nil, false
  end
  return days, true
end

-- Days as the player would type them back, e.g. 0.5 -> "0.5"; "" for nil.
function RecommendationTable.daysText(days)
  if not days then
    return ""
  end
  return (string.format("%.4f", days):gsub("0+$", ""):gsub("%.$", ""))
end

-- character: the logged-in Character, as the Brain names it ("Name-Realm"). budget: the
-- copper the player set in the Budget box, nil for all the gold (#86). marks: the Market's
-- rows marked Bought (BoughtMarks.forMarket, #97). gold: the copper on hand now.
function RecommendationTable.build(recommendations, realm, faction, now, nameOf, character, budget, marks, gold)
  local entry = recommendations and recommendations[realm] and recommendations[realm][faction]
  if not entry then
    return { empty = EMPTY }
  end
  local holdersOf = entry.held or {}
  local spent = BoughtMarks.spent(marks or {})
  -- Once something is marked, the buy-side tabs fold on the gold left (#97).
  local fold = BoughtMarks.goldLeft(budget, gold, spent)
  -- No re-sort and no filter: the marker only points out what's on hand (#38).
  local function inBags(itemKey)
    for _, h in ipairs(holdersOf[itemKey] or {}) do
      if h.character == character and h.bags > 0 then
        return true
      end
    end
    return false
  end
  -- The Shopping List's Flips to Craft get their own tab (#87).
  local flips, crafts = {}, {}
  for _, r in ipairs(entry.shoppingList or {}) do
    local rows = r.action == "Craft" and crafts or flips
    rows[#rows + 1] = r
  end
  local shoppingColumns = { "Item", "Action", "Qty", "Max price", "Post at", "Profit", "Cost", "Note" }
  local flipColumns = {
    "Item", "Action", "Qty", "Max price", "Post at", "Profit", "Per click", "Per day", "ROI", "Cost", "Note",
  }
  return {
    title = realm .. " " .. faction,
    header = header(entry, now, budget, spent),
    sections = {
      section(
        "Holdings",
        { "Item", "Action", "Qty", "Price", "Profit", "ROI", "Note" },
        entry.holdings,
        holdingCells,
        holdingKeys,
        { column = 5, descending = true },
        nameOf,
        holdersOf,
        inBags,
        nil,
        entry.beta
      ),
      section(
        "Shopping List",
        flipColumns,
        flips,
        flipCells,
        flipKeys,
        { column = 6, descending = true },
        nameOf,
        holdersOf,
        nil,
        fold,
        entry.beta,
        marks
      ),
      section(
        "Flips to Craft",
        shoppingColumns,
        crafts,
        shoppingCells,
        shoppingKeys,
        { column = 6, descending = true },
        nameOf,
        holdersOf,
        nil,
        fold,
        entry.beta,
        marks
      ),
      section(
        "Prediction buys",
        { "Item", "Prediction", "Qty", "Max price", "Max Loss" },
        entry.predictionBuys,
        predictionBuyCells,
        predictionBuyKeys,
        { column = 5, descending = false },
        nameOf,
        holdersOf,
        nil,
        nil,
        entry.beta,
        marks
      ),
      -- In the Brain's order, best profit per unit first: no column sorts it by default, so
      -- the rows fall through to the tie-break on their order (a Buy Under's worth is 0).
      -- Never over the Budget: the player only buys one when it shows up on the AH (#88).
      section(
        "Buy Under",
        { "Item", "Buy Under", "Way out", "Units", "Seen", "Note" },
        entry.buyUnder or {},
        buyUnderCells,
        buyUnderKeys,
        {},
        nameOf,
        holdersOf,
        nil,
        nil,
        entry.beta
      ),
    },
  }
end

ns.RecommendationTable = RecommendationTable
return RecommendationTable
