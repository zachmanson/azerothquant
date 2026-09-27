local RecommendationTable = require("RecommendationTable")

local REALM, FACTION = "Classic Beta PvP", "Alliance"

local function noNames()
  return nil
end

local function build(recommendations, now, nameOf)
  return RecommendationTable.build(recommendations, REALM, FACTION, now or 0, nameOf or noNames)
end

local AS_OF = 1790524206

-- An entry shaped like the Brain writes it (see Recommendations.lua), with no rows.
local function entry(fields)
  local e = {
    asOf = AS_OF,
    gold = 175471,
    windowHours = 0.2975,
    shoppingCost = 126793,
    predictionCost = 0,
    holdings = {},
    shoppingList = {},
    predictionBuys = {},
  }
  for k, v in pairs(fields or {}) do
    e[k] = v
  end
  return { [REALM] = { [FACTION] = e } }
end

describe("RecommendationTable.build", function()
  it("heads the table with the Market, the Scan's age, gold, totals and window hours", function()
    local view = build(entry(), AS_OF + 12 * 60 + 30)

    assert.are.equal("Classic Beta PvP Alliance", view.title)
    assert.matches("^as of %d%d:%d%d, 12 min ago$", view.header[1])
    assert.are.equal("Gold 17g 54s 71c, Shopping List 12g 67s 93c, Prediction buys 0c", view.header[2])
    assert.are.equal("Observation Window 0.3 h", view.header[3])
  end)

  it("formats the time with WoW's global date, since the client has no os library", function()
    local realOs = os
    _G.date, _G.os = realOs.date, nil
    local ok, view = pcall(build, entry(), AS_OF)
    _G.date, _G.os = nil, realOs

    assert.is_true(ok, tostring(view))
    assert.matches("^as of %d%d:%d%d, ", view.header[1])
  end)

  it("gives older Scans' age in hours, then days", function()
    assert.matches(", 5 h ago$", build(entry(), AS_OF + 5 * 3600 + 59 * 60).header[1])
    assert.matches(", 3 days ago$", build(entry(), AS_OF + 3 * 86400 + 3600).header[1])
  end)

  it("shows a Holding's columns with money formatted, and Margin, Sales and note in its tooltip", function()
    local names = { ["item:248704"] = "Heavy Leather" }
    local view = build(
      entry({
        holdings = {
          {
            itemKey = "248704",
            action = "Sell",
            quantity = 2,
            price = 11343.076923076924,
            profit = 21551.846153846152,
            margin = 10775.923076923076,
            saleEvents = 1,
            note = "incl. 3 crafted",
          },
        },
      }),
      AS_OF,
      function(itemString)
        return names[itemString]
      end
    )

    local holdings = view.sections[1]
    assert.are.equal("Holdings", holdings.title)
    assert.are.same({ "Item", "Action", "Qty", "Price", "Profit", "Note" }, holdings.columns)
    local row = holdings.rows[1]
    assert.are.equal("item:248704", row.itemString)
    assert.are.same(
      { "Heavy Leather", "Sell", "2", "1g 13s 43c", "2g 15s 51c", "incl. 3 crafted" },
      row.cells
    )
    assert.are.same({ "Margin 1g 7s 75c", "Sales 1", "incl. 3 crafted" }, row.tooltip)
  end)

  it("names an item not cached yet by its Item Key, and links suffixed items by bonus ID", function()
    local view = build(entry({
      holdings = { { itemKey = "6581:12732", action = "Sell", quantity = 1, price = 1000, profit = 950 } },
    }))

    local row = view.sections[1].rows[1]
    assert.are.equal("item:6581:12732", row.cells[1])
    -- The Brain's example itemString "item:9768::::::::20:1490::1:1:12743" keeps the bonus
    -- count in field 12; level and spec fields are left empty.
    assert.are.equal("item:6581::::::::::::1:12732", row.itemString)
  end)

  it("folds Vendor rows worth 0c and no-data rows into a count, keeping the rest in order", function()
    local view = build(entry({
      holdings = {
        { itemKey = "1", action = "Sell", quantity = 2, price = 100, profit = 190 },
        { itemKey = "2", action = "Vendor", quantity = 1, price = 0, profit = 0 },
        { itemKey = "3", action = "Vendor", quantity = 1, price = 5, profit = 5 },
        { itemKey = "4", quantity = 4, note = "no data" },
      },
    }))

    local holdings = view.sections[1]
    assert.are.same({ "item:1", "item:3" }, {
      holdings.rows[1].itemString,
      holdings.rows[2].itemString,
    })
    assert.are.equal(2, #holdings.rows)
    assert.are.equal("2 more (worth 0c or no data)", holdings.more)
  end)

  it("shows the Shopping List under the Holdings", function()
    local view = build(entry({
      shoppingList = {
        { itemKey = "9749", action = "Sell", quantity = 3, price = 1000, profit = 9450.0, saleEvents = 4, cost = 3000 },
      },
    }))

    local shopping = view.sections[2]
    assert.are.equal("Shopping List", shopping.title)
    assert.are.same({ "Item", "Qty", "Max price", "Profit", "Cost" }, shopping.columns)
    assert.are.same({ "item:9749", "3", "10s", "94s 50c", "30s" }, shopping.rows[1].cells)
    assert.are.same({ "Sales 4" }, shopping.rows[1].tooltip)
  end)

  it("shows Prediction buys under the Shopping List", function()
    local view = build(entry({
      predictionBuys = {
        {
          itemKey = "12359",
          action = "Hold",
          quantity = 20,
          price = 2500,
          cost = 50000,
          prediction = "Phase 2",
          maxLoss = 12000,
        },
      },
    }))

    local buys = view.sections[3]
    assert.are.equal("Prediction buys", buys.title)
    assert.are.same({ "Item", "Prediction", "Qty", "Max price", "Max Loss" }, buys.columns)
    assert.are.same({ "item:12359", "Phase 2", "20", "25s", "1g 20s" }, buys.rows[1].cells)
  end)

  it("shows a Hold's profit as unknown and the Prediction it's under, as brain recommend does", function()
    local view = build(entry({
      holdings = {
        { itemKey = "12359", action = "Hold", quantity = 20, price = 2500, cost = 50000, prediction = "Phase 2" },
      },
    }))

    assert.are.same(
      { "item:12359", "Hold", "20", "25s", "unknown", "under Phase 2" },
      view.sections[1].rows[1].cells
    )
  end)

  it("says how to get Recommendations when the Market has none", function()
    local view = build({ ["Classic Beta PvP"] = { ["Horde"] = {} } })

    assert.are.equal("No Recommendations yet: Scan, /reload, and let the Brain import.", view.empty)
    assert.is_nil(view.sections)
  end)
end)
