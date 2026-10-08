-- Which of a Recommendation Table section's columns fit across the table, and how wide
-- each is (#136). The frame is resizable, so the width changes. Every column but the Item
-- has a set width; the Item gets what's left (#160).
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

-- The least the Item may get before a column makes way for it.
local MIN_ITEM_WIDTH = 150

-- What makes way first when the table is narrow. Every value is still in the side pane.
local HIDE_ORDER = { "Beta", "Cost", "ROI", "Per click", "Per day" }

-- The section's columns that fit in width, in order, as { column (its place in
-- section.columns), width }. Columns in HIDE_ORDER go, one at a time, until the Item (the
-- first column) gets MIN_ITEM_WIDTH. Once they're all gone the Item gets what's left,
-- however little.
function ColumnLayout.fit(section, width)
  local columns = section.columns
  local hidden = {}
  local layout, left
  local function place()
    layout, left = {}, width - ColumnLayout.ICON_WIDTH
    for c, name in ipairs(columns) do
      if not hidden[name] then
        layout[#layout + 1] = { column = c, width = widthOf(section, name) }
      end
    end
    for i = 2, #layout do
      left = left - layout[i].width
    end
  end
  place()
  for _, name in ipairs(HIDE_ORDER) do
    if left >= MIN_ITEM_WIDTH then
      break
    end
    hidden[name] = true
    place()
  end
  layout[1].width = left
  return layout
end

-- The row's values in the columns layout left out, as { name, text } in column order, for
-- the side pane. Blank cells are skipped.
function ColumnLayout.hiddenValues(section, layout, row)
  local onShow = {}
  for _, placed in ipairs(layout) do
    onShow[placed.column] = true
  end
  local values = {}
  for c, name in ipairs(section.columns) do
    local text = row.cells[c]
    if not onShow[c] and text and text ~= "" then
      values[#values + 1] = { name = name, text = text }
    end
  end
  return values
end

ns.ColumnLayout = ColumnLayout
return ColumnLayout
