local ColumnLayout = require("ColumnLayout")

local SHOPPING_LIST = {
  title = "Shopping List",
  columns = {
    "Item", "Action", "Qty", "Max price", "Post at", "Profit", "Per click", "Per day", "ROI", "Cost", "Beta", "Note",
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
  it("shows every column when the table is wide enough, the last taking what's left", function()
    local layout = ColumnLayout.fit(SHOPPING_LIST, 1400)

    assert.are.same(SHOPPING_LIST.columns, names(SHOPPING_LIST, layout))
    local used = ColumnLayout.ICON_WIDTH
    for _, placed in ipairs(layout) do
      used = used + placed.width
    end
    assert.are.equal(1400, used)
  end)

  it("hides Beta first, then Cost, then ROI, as the table narrows", function()
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

    assert.are.same(without("Beta"), names(SHOPPING_LIST, ColumnLayout.fit(SHOPPING_LIST, 1150)))
    assert.are.same(without("Beta", "Cost"), names(SHOPPING_LIST, ColumnLayout.fit(SHOPPING_LIST, 1050)))
    assert.are.same(without("Beta", "Cost", "ROI"), names(SHOPPING_LIST, ColumnLayout.fit(SHOPPING_LIST, 960)))
  end)

  it("gives every column of every tab a width, with a Beta Prior on or off", function()
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
        -- 1054: the rows' width in the frame's opening 1100.
        for _, placed in ipairs(ColumnLayout.fit(section, 1054)) do
          assert.is_true(
            type(placed.width) == "number" and placed.width > 0,
            section.title .. "'s " .. section.columns[placed.column] .. " has no width"
          )
        end
      end
    end
  end)

  it("never hides a tab's last column, which takes what's left", function()
    -- Prediction buys ends on Beta, Flips to Disenchant on Cost.
    local prediction = { title = "Prediction buys", columns = { "Item", "Prediction", "Qty", "Max price", "Max Loss", "Beta" } }
    local disenchant = { title = "Flips to Disenchant", columns = { "Item", "Way out", "Listings", "Profit", "Cost" } }

    assert.are.same(prediction.columns, names(prediction, ColumnLayout.fit(prediction, 600)))
    assert.are.same(disenchant.columns, names(disenchant, ColumnLayout.fit(disenchant, 600)))
  end)
end)
