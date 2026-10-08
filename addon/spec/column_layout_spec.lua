local ColumnLayout = require("ColumnLayout")

local SHOPPING_LIST = {
  title = "Shopping List",
  columns = {
    "Item", "Action", "Qty", "Max price", "Post at", "Profit", "Per click", "Per day", "ROI", "Cost", "Beta",
  },
}

-- The names of the columns a layout shows, in order.
local function names(section, layout)
  local out = {}
  for _, placed in ipairs(layout) do
    out[#out + 1] = section.columns[placed.column]
  end
  return out
end

describe("ColumnLayout.fit", function()
  it("shows every column when the table is wide enough, the Item taking what's left", function()
    local layout = ColumnLayout.fit(SHOPPING_LIST, 1400)

    assert.are.same(SHOPPING_LIST.columns, names(SHOPPING_LIST, layout))
    -- 1400 less the icon and the other columns' 830.
    assert.are.equal(544, layout[1].width)
    local used = ColumnLayout.ICON_WIDTH
    for _, placed in ipairs(layout) do
      used = used + placed.width
    end
    assert.are.equal(1400, used)
  end)

  it("hides Beta first, then Cost, ROI, Per click and Per day, as the table narrows", function()
    local all = SHOPPING_LIST.columns
    local function without(...)
      local hidden = {}
      for _, name in ipairs({ ... }) do
        hidden[name] = true
      end
      local out = {}
      for _, name in ipairs(all) do
        if not hidden[name] then
          out[#out + 1] = name
        end
      end
      return out
    end

    -- Every column but the Item takes 830, the icon 26, and the Item wants 150.
    assert.are.same(all, names(SHOPPING_LIST, ColumnLayout.fit(SHOPPING_LIST, 1006)))
    assert.are.same(without("Beta"), names(SHOPPING_LIST, ColumnLayout.fit(SHOPPING_LIST, 1000)))
    assert.are.same(without("Beta", "Cost"), names(SHOPPING_LIST, ColumnLayout.fit(SHOPPING_LIST, 900)))
    assert.are.same(without("Beta", "Cost", "ROI"), names(SHOPPING_LIST, ColumnLayout.fit(SHOPPING_LIST, 800)))
    assert.are.same(
      without("Beta", "Cost", "ROI", "Per click"),
      names(SHOPPING_LIST, ColumnLayout.fit(SHOPPING_LIST, 700))
    )
    assert.are.same(
      without("Beta", "Cost", "ROI", "Per click", "Per day"),
      names(SHOPPING_LIST, ColumnLayout.fit(SHOPPING_LIST, 600))
    )
  end)

  it("gives every column of every tab a width, and the Item its least, with a Beta Prior on or off", function()
    local RecommendationTable = require("RecommendationTable")
    for _, beta in ipairs({ false, true }) do
      local entry = { asOf = 0, gold = 0, windowHours = 1, predictionCost = 0, holdings = {}, shoppingList = {}, predictionBuys = {} }
      if beta then
        entry.beta = { realm = "Classic Beta PvP", faction = "Alliance", prices = {} }
      end
      local view = RecommendationTable.build(
        { ["Classic Beta PvP"] = { Alliance = entry } },
        "Classic Beta PvP",
        "Alliance",
        0,
        function() end
      )
      for _, section in ipairs(view.sections) do
        -- The rows' width beside the side pane at the frame's MIN_WIDTH 1000 and opening 1100.
        for _, width in ipairs({ 690, 790 }) do
          local layout = ColumnLayout.fit(section, width)
          for _, placed in ipairs(layout) do
            assert.is_true(
              type(placed.width) == "number" and placed.width > 0,
              section.title .. "'s " .. section.columns[placed.column] .. " has no width"
            )
          end
          assert.is_true(layout[1].width >= 150, section.title .. "'s Item is under 150 at " .. width)
        end
      end
    end
  end)
end)

describe("ColumnLayout.hiddenValues", function()
  it("names the values of the columns a layout left out, in column order, skipping blanks", function()
    local row = { cells = { "Linen Cloth", "Buy", "3", "10s", "42s", "94s 50c", "31s 50c", "now", "", "30s", "" } }
    -- 800 hides Beta, Cost and ROI.
    local layout = ColumnLayout.fit(SHOPPING_LIST, 800)

    assert.are.same({ { name = "Cost", text = "30s" } }, ColumnLayout.hiddenValues(SHOPPING_LIST, layout, row))
  end)

  it("names nothing when every column fits", function()
    local row = { cells = { "Linen Cloth", "Buy", "3", "10s", "42s", "94s 50c", "31s 50c", "now", "300%", "30s", "1s" } }

    assert.are.same({}, ColumnLayout.hiddenValues(SHOPPING_LIST, ColumnLayout.fit(SHOPPING_LIST, 1400), row))
  end)
end)
