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

-- budget: the one the player set in the box, nil for all the gold. entry.budget is the one
-- the Brain sized the options within, which lags it until the next reload.
local function header(entry, now, budget)
  local stale = budget ~= entry.budget and " (Reload to re-size)" or ""
  return {
    "as of " .. formatTime(entry.asOf) .. ", " .. age(now - entry.asOf)
      .. string.format(", Observation Window %.1f h", entry.windowHours),
    "Gold " .. Money.format(entry.gold)
      .. ", Budget " .. (budget and Money.format(budget) or "all") .. stale
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
    lines[#lines + 1] = "Sales " .. r.saleEvents
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

-- A Flip's Profit per Listing bought and stack posted, per day until its last unit sells
-- (a Flip to Vendor's sells now, so it sorts first), and on its Cost (#98). nil each for a
-- row the Brain wrote no counts for.
local function measures(r)
  if not r.listings then
    return nil, nil, nil
  end
  local perDay = r.days and r.profit / r.days or math.huge
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

-- How a Buy Under gets out (#88): Vendor, Sell, or e.g. "Craft Bolt of Linen Cloth
-- (Kash-Patel)" for a Craft it's a reagent of.
function RecommendationTable.wayOut(r, nameOf)
  if r.way == "Craft" then
    return "Craft " .. nameFor(r.output, nameOf) .. " (" .. r.crafter .. ")"
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

-- What an empty tab says, in place of its rows.
local NOTHING = {
  ["Holdings"] = "Nothing in Holdings right now",
  ["Shopping List"] = "Nothing on the Shopping List right now",
  ["Flips to Craft"] = "No Flips to Craft right now",
  ["Prediction buys"] = "No Prediction buys right now",
  ["Buy Under"] = "No Buy Unders right now",
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
local function section(title, columns, rows, cells, keys, default, nameOf, holdersOf, inBags, budget)
  local held = RecommendationTable.heldUnits(rows)
  local out = { title = title, columns = columns, rows = {}, sort = default }
  local folded, over = 0, 0
  for _, r in ipairs(rows) do
    if RecommendationTable.lowValue(r) then
      folded = folded + 1
    elseif budget and (r.cost or 0) > budget then
      over = over + 1
    else
      local name = nameFor(r.itemKey, nameOf)
      local rowCells = cells(r, name, nameOf)
      if inBags and inBags(r.itemKey) then
        rowCells[1] = RecommendationTable.BAG .. " " .. name
      end
      out.rows[#out.rows + 1] = {
        itemString = itemString(r.itemKey),
        cells = rowCells,
        keys = keys(r, name, rowCells),
        worth = (r.price or 0) * (r.quantity or 0),
        order = #out.rows + 1,
        tooltip = tooltip(r, nameOf, held, holdersOf),
      }
    end
  end
  RecommendationTable.sort(out, default)
  out.tab = title .. " (" .. #out.rows .. ")"
  if #out.rows == 0 then
    out.empty = NOTHING[title]
  end
  local more = {}
  if folded > 0 then
    more[#more + 1] = folded .. " more (worth 0c or no data)"
  end
  if over > 0 then
    more[#more + 1] = over .. " over the Budget (Reload to re-size)"
  end
  out.more = #more > 0 and table.concat(more, ", ") or nil
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

-- The key of a Market's Budget in AzerothQuantDB.budgets (#86): gold pools per realm and
-- faction, so that's what a Budget covers.
function RecommendationTable.budgetKey(realm, faction)
  return realm .. "-" .. faction
end

-- character: the logged-in Character, as the Brain names it ("Name-Realm"). budget: the
-- copper the player set in the Budget box, nil for all the gold (#86).
function RecommendationTable.build(recommendations, realm, faction, now, nameOf, character, budget)
  local entry = recommendations and recommendations[realm] and recommendations[realm][faction]
  if not entry then
    return { empty = EMPTY }
  end
  local holdersOf = entry.held or {}
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
    header = header(entry, now, budget),
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
        inBags
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
        budget
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
        budget
      ),
      section(
        "Prediction buys",
        { "Item", "Prediction", "Qty", "Max price", "Max Loss" },
        entry.predictionBuys,
        predictionBuyCells,
        predictionBuyKeys,
        { column = 5, descending = false },
        nameOf,
        holdersOf
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
        holdersOf
      ),
    },
  }
end

ns.RecommendationTable = RecommendationTable
return RecommendationTable
