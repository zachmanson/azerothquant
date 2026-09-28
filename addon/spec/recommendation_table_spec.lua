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

-- A Flip to Craft as the Brain writes it (brain/tests/test_recommendations.py).
local function flipToCraft()
  return {
    itemKey = "2996",
    action = "Craft",
    quantity = 6,
    profit = 4500.0,
    cost = 1250.0,
    note = "on Kash-Patel: uses 12 of 2589 (buy 12), 6 of 2320 (buy 5)",
    buys = {
      { itemKey = "2589", quantity = 12, maxUnitPrice = 120 },
      { itemKey = "2320", quantity = 5, maxUnitPrice = 10.0, merchant = true },
    },
    character = "Kash-Patel",
    uses = { { itemKey = "2320", quantity = 1 } },
  }
end

-- A Holdings Craft as the Brain writes it: every reagent it uses is held.
local function holdingsCraft()
  return {
    itemKey = "2997",
    action = "Craft",
    quantity = 3,
    profit = 79.8,
    note = "on Kash-Patel: uses 9 of 2592, 3 of 2320",
    character = "Kash-Patel",
    uses = { { itemKey = "2592", quantity = 9 }, { itemKey = "2320", quantity = 3 } },
  }
end

local NAMES = { ["item:2589"] = "Linen Cloth", ["item:2320"] = "Coarse Thread", ["item:2592"] = "Wool Cloth" }

local function names(itemString)
  return NAMES[itemString]
end

describe("RecommendationTable.build", function()
  it("sums up a Holdings Craft's Character and reagents in its note, and names what it uses in its tooltip", function()
    local view = build(entry({ holdings = { holdingsCraft() } }), AS_OF, names)

    local row = view.sections[1].rows[1]
    assert.are.same({ "item:2997", "Craft", "3", "", "79c", "on Kash-Patel, 2 reagents" }, row.cells)
    assert.are.same({ "Use 9 Wool Cloth", "Use 3 Coarse Thread" }, row.tooltip)
  end)

  it("heads the table in two lines: the Scan's age and window hours, then gold and totals", function()
    local view = build(entry(), AS_OF + 12 * 60 + 30)

    assert.are.equal("Classic Beta PvP Alliance", view.title)
    assert.matches("^as of %d%d:%d%d, 12 min ago, Observation Window 0.3 h$", view.header[1])
    assert.are.equal("Gold 17g 54s 71c, Shopping List 12g 67s 93c, Prediction buys 0c", view.header[2])
    assert.are.equal(2, #view.header)
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
    assert.matches(", 5 h ago, ", build(entry(), AS_OF + 5 * 3600 + 59 * 60).header[1])
    assert.matches(", 3 days ago, ", build(entry(), AS_OF + 3 * 86400 + 3600).header[1])
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

  it("labels each section's tab with its count of rows, leaving out the folded ones", function()
    local view = build(entry({
      holdings = {
        { itemKey = "1", action = "Sell", quantity = 2, price = 100, profit = 190 },
        { itemKey = "2", action = "Vendor", quantity = 1, price = 0, profit = 0 },
      },
    }))

    assert.are.same({ "Holdings (1)", "Shopping List (0)", "Prediction buys (0)" }, {
      view.sections[1].tab,
      view.sections[2].tab,
      view.sections[3].tab,
    })
  end)

  it("says a section is empty when it has no rows to show, folded ones aside", function()
    local view = build(entry({
      holdings = { { itemKey = "2", action = "Vendor", quantity = 1, price = 0, profit = 0 } },
      shoppingList = { { itemKey = "9749", action = "Sell", quantity = 3, price = 1000, profit = 9450, cost = 3000 } },
    }))

    assert.are.same({ "Nothing in Holdings right now", "1 more (worth 0c or no data)" }, {
      view.sections[1].empty,
      view.sections[1].more,
    })
    assert.is_nil(view.sections[2].empty)
    assert.are.equal("Nothing on the Shopping List right now", build(entry()).sections[2].empty)
    assert.are.equal("No Prediction buys right now", view.sections[3].empty)
  end)

  it("shows the Shopping List under the Holdings, with Buy as a Flip to Sell's Action", function()
    local view = build(entry({
      shoppingList = {
        { itemKey = "9749", action = "Sell", quantity = 3, price = 1000, postAt = 4200.0, profit = 9450.0, saleEvents = 4, cost = 3000 },
      },
    }))

    local shopping = view.sections[2]
    assert.are.equal("Shopping List", shopping.title)
    assert.are.same({ "Item", "Action", "Qty", "Max price", "Post at", "Profit", "Cost", "Note" }, shopping.columns)
    assert.are.same({ "item:9749", "Buy", "3", "10s", "42s", "94s 50c", "30s", "" }, shopping.rows[1].cells)
    assert.are.same({ "Sales 4" }, shopping.rows[1].tooltip)
  end)

  it("lists a Flip to Craft's held reagents, then its reagent buys, by name in its tooltip", function()
    local view = build(entry({ shoppingList = { flipToCraft() } }), AS_OF, names)

    assert.are.same({
      "Use 1 Coarse Thread",
      "Buy 12 Linen Cloth @ max 1s 20c",
      "Buy 5 Coarse Thread from a merchant @ 10c",
    }, view.sections[2].rows[1].tooltip)
  end)

  it("shows a Flip to Craft's Action as Craft, and sums up who crafts it and how many distinct reagents", function()
    local oneBuy = flipToCraft()
    oneBuy.buys[2] = nil
    oneBuy.uses = nil
    local view = build(entry({ shoppingList = { flipToCraft(), oneBuy } }))

    local rows = view.sections[2].rows
    assert.are.same(
      { "item:2996", "Craft", "6", "", "", "45s", "12s 50c", "on Kash-Patel, 2 reagents" },
      rows[1].cells
    )
    assert.are.equal("on Kash-Patel, 1 reagent", rows[2].cells[8])
  end)

  it("names a reagent not cached yet by its Item Key", function()
    local view = build(entry({ shoppingList = { flipToCraft() } }))

    assert.are.equal("Buy 12 item:2589 @ max 1s 20c", view.sections[2].rows[1].tooltip[2])
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

describe("RecommendationTable.openingTab", function()
  it("lands on the Shopping List when the Auction House opens the table, whatever was saved", function()
    assert.are.equal("Shopping List", RecommendationTable.openingTab("Holdings", true))
  end)

  it("reopens the last tab picked when /aq recs opens the table", function()
    assert.are.equal("Prediction buys", RecommendationTable.openingTab("Prediction buys", false))
  end)

  it("opens the Shopping List when no tab was saved, or the saved one no longer exists", function()
    assert.are.equal("Shopping List", RecommendationTable.openingTab(nil, false))
    assert.are.equal("Shopping List", RecommendationTable.openingTab("Crafts", false))
  end)
end)

describe("sorting the Recommendation Table", function()
  local function itemStrings(section)
    local out = {}
    for i, row in ipairs(section.rows) do
      out[i] = row.itemString
    end
    return out
  end

  it("shows the Shopping List largest Profit first by default", function()
    local view = build(entry({
      shoppingList = {
        { itemKey = "1", action = "Sell", quantity = 1, price = 100, profit = 500, cost = 100 },
        { itemKey = "2", action = "Sell", quantity = 1, price = 100, profit = 90000, cost = 100 },
        { itemKey = "3", action = "Sell", quantity = 1, price = 100, profit = 7000, cost = 100 },
      },
    }))

    local shopping = view.sections[2]
    assert.are.same({ "item:2", "item:3", "item:1" }, itemStrings(shopping))
    assert.are.same({ column = 6, descending = true }, shopping.sort)
  end)

  it("shows Holdings largest Profit first, with Holds last, largest Price x Qty first among them", function()
    local view = build(entry({
      holdings = {
        { itemKey = "1", action = "Hold", quantity = 2, price = 100, prediction = "Phase 2" },
        { itemKey = "2", action = "Sell", quantity = 1, price = 100, profit = 95 },
        { itemKey = "3", action = "Hold", quantity = 5, price = 100, prediction = "Phase 2" },
        { itemKey = "4", action = "Sell", quantity = 1, price = 900, profit = 855 },
      },
    }))

    local holdings = view.sections[1]
    assert.are.same({ "item:4", "item:2", "item:3", "item:1" }, itemStrings(holdings))
    assert.are.same({ column = 5, descending = true }, holdings.sort)
  end)

  it("shows Prediction buys smallest Max Loss first", function()
    local function buy(itemKey, maxLoss)
      return { itemKey = itemKey, action = "Hold", quantity = 1, price = 100, prediction = "Phase 2", maxLoss = maxLoss }
    end
    local view = build(entry({ predictionBuys = { buy("1", 5000), buy("2", 40), buy("3", 900) } }))

    local buys = view.sections[3]
    assert.are.same({ "item:2", "item:3", "item:1" }, itemStrings(buys))
    assert.are.same({ column = 5, descending = false }, buys.sort)
  end)

  it("re-sorts by a money column's value, not its text, keeping rows with no value last", function()
    -- As text "1g" sorts before "9s"; a Flip to Craft has no Max price of its own.
    local craft = flipToCraft()
    local view = build(entry({
      shoppingList = {
        { itemKey = "1", action = "Sell", quantity = 1, price = 10000, profit = 500, cost = 10000 },
        craft,
        { itemKey = "3", action = "Sell", quantity = 1, price = 900, profit = 500, cost = 900 },
      },
    }))
    local shopping = view.sections[2]

    RecommendationTable.sort(shopping, { column = 4, descending = false })
    assert.are.same({ "item:3", "item:1", "item:2996" }, itemStrings(shopping))

    RecommendationTable.sort(shopping, { column = 4, descending = true })
    assert.are.same({ "item:1", "item:3", "item:2996" }, itemStrings(shopping))
  end)

  it("sorts the Shopping List by Post at, with a Flip to Craft (no Post at) last", function()
    local view = build(entry({
      shoppingList = {
        { itemKey = "1", action = "Sell", quantity = 1, price = 100, postAt = 900, profit = 500, cost = 100 },
        flipToCraft(),
        { itemKey = "3", action = "Sell", quantity = 1, price = 100, postAt = 10000, profit = 500, cost = 100 },
      },
    }))
    local shopping = view.sections[2]

    RecommendationTable.sort(shopping, { column = 5, descending = true })
    assert.are.same({ "item:3", "item:1", "item:2996" }, itemStrings(shopping))

    RecommendationTable.sort(shopping, { column = 5, descending = false })
    assert.are.same({ "item:1", "item:3", "item:2996" }, itemStrings(shopping))
  end)

  it("sorts the Item column by the item's name, ignoring case", function()
    local names = { ["item:1"] = "linen Cloth", ["item:2"] = "Copper Ore", ["item:3"] = "Wool Cloth" }
    local function sell(itemKey)
      return { itemKey = itemKey, action = "Sell", quantity = 1, price = 100, profit = 95 }
    end
    local holdings = build(entry({ holdings = { sell("1"), sell("2"), sell("3") } }), AS_OF, function(itemString)
      return names[itemString]
    end).sections[1]

    RecommendationTable.sort(holdings, { column = 1, descending = false })
    assert.are.same({ "item:2", "item:1", "item:3" }, itemStrings(holdings))
  end)
end)

describe("RecommendationTable.nextSort", function()
  local holdings = build(entry()).sections[1] -- Item, Action, Qty, Price, Profit, Note

  it("sorts a number column largest first on its first click, and flips it on the next", function()
    local state = RecommendationTable.nextSort(holdings, holdings.sort, 3)
    assert.are.same({ column = 3, descending = true }, state)
    assert.are.same({ column = 3, descending = false }, RecommendationTable.nextSort(holdings, state, 3))
  end)

  it("flips the default column on its first click", function()
    assert.are.same(
      { column = 5, descending = false },
      RecommendationTable.nextSort(holdings, { column = 5, descending = true }, 5)
    )
  end)

  it("sorts a text column A to Z on its first click", function()
    assert.are.same({ column = 1, descending = false }, RecommendationTable.nextSort(holdings, holdings.sort, 1))
    assert.are.same({ column = 6, descending = false }, RecommendationTable.nextSort(holdings, holdings.sort, 6))
  end)
end)

describe("RecommendationTable.waitingNote", function()
  it("says nothing when every Scan is in the table", function()
    assert.is_nil(RecommendationTable.waitingNote(0, 0))
  end)

  it("asks for a Reload to hand a Scan taken since the last one to the Brain", function()
    assert.are.equal("1 Scan waiting: Reload to send it to the Brain",
      RecommendationTable.waitingNote(1, 0))
  end)

  it("asks for a Reload once the Brain has imported Scans that were already saved", function()
    assert.are.equal("2 Scans waiting: Reload once the Brain has them",
      RecommendationTable.waitingNote(0, 2))
  end)

  it("asks to send them first when some Scans aren't even saved yet", function()
    assert.are.equal("3 Scans waiting: Reload to send them to the Brain",
      RecommendationTable.waitingNote(1, 2))
  end)
end)
