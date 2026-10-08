-- Which of a Recommendation Table section's columns fit across the table, and how wide
-- each is (#136). The frame is resizable, so the width changes. Every column but the last
-- has a set width; the last (the Note, mostly) gets what's left.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for the
-- namespace fallback.
local _, ns = ...
ns = ns or {}

local ColumnLayout = {}

-- The item icon and its gap, left of the first column.
ColumnLayout.ICON_WIDTH = 26

-- Each column's width, by name. "2g 74s 50c*" needs about 85.
local WIDTHS = {
  ["Item"] = 190,
  ["Action"] = 60,
  ["Qty"] = 50,
  ["Price"] = 95,
  ["Max price"] = 95,
  ["Post at"] = 95,
  ["Profit"] = 95,
  ["Per click"] = 95,
  ["Per day"] = 95,
  ["ROI"] = 55,
  ["Cost"] = 95,
  ["Beta"] = 95,
  ["Max Loss"] = 95,
  ["Prediction"] = 150,
  ["Listings"] = 70,
  ["Buy Under"] = 95,
  ["Units"] = 70,
  ["Seen"] = 110,
  ["Way out"] = 200,
}
-- Where one tab's column needs another width: a Disenchant's way out lists its mats, and
-- a Holding's action can be Disenchant.
local TAB_WIDTHS = {
  ["Flips to Disenchant"] = { ["Way out"] = 330 },
  ["Holdings"] = { ["Action"] = 70 },
}

local function widthOf(section, name)
  local tab = TAB_WIDTHS[section.title]
  return tab and tab[name] or WIDTHS[name]
end

-- The least the last column may get before a column makes way for it.
local MIN_NOTE_WIDTH = 150

-- What makes way first when the table is narrow. Every value is still in the row's tooltip.
local HIDE_ORDER = { "Beta", "Cost", "ROI" }

-- The section's columns that fit in width, in order, as { column (its place in
-- section.columns), width }. Columns in HIDE_ORDER go, one at a time, until the last
-- column gets its least (a Note's MIN_NOTE_WIDTH, any other its own width). Once they're
-- all gone the last column gets what's left, however little.
function ColumnLayout.fit(section, width)
  local columns = section.columns
  local hidden = {}
  local layout, left
  local function place()
    layout, left = {}, width - ColumnLayout.ICON_WIDTH
    for c, name in ipairs(columns) do
      if not hidden[name] or c == #columns then
        layout[#layout + 1] = { column = c, width = widthOf(section, name) }
      end
    end
    for i = 1, #layout - 1 do
      left = left - layout[i].width
    end
  end
  place()
  local last = columns[#columns]
  local least = last == "Note" and MIN_NOTE_WIDTH or widthOf(section, last)
  for _, name in ipairs(HIDE_ORDER) do
    if left >= least then
      break
    end
    hidden[name] = true
    place()
  end
  layout[#layout].width = left
  return layout
end

ns.ColumnLayout = ColumnLayout
return ColumnLayout
