local RecommendationTable = require("RecommendationTable")

local REALM, FACTION = "Classic Beta PvP", "Alliance"

local function noNames()
  return nil
end

local function build(recommendations, now, nameOf, character, budget)
  return RecommendationTable.build(
    recommendations,
    REALM,
    FACTION,
    now or 0,
    nameOf or noNames,
    character,
    budget
  )
end

local AS_OF = 1790524206

-- An entry shaped like the Brain writes it (see Recommendations.lua), with no rows.
local function entry(fields)
  local e = {
    asOf = AS_OF,
    gold = 175471,
    windowHours = 0.2975,
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

-- A Holdings Craft the Brain couldn't value, as it writes one (#75).
local function blockedCraft(blocked)
  return {
    itemKey = "2996",
    action = "Craft",
    quantity = 0,
    note = "on Kash-Patel: no data for 2770",
    character = "Kash-Patel",
    blocked = blocked,
  }
end

local NAMES = {
  ["item:2589"] = "Linen Cloth",
  ["item:2320"] = "Coarse Thread",
  ["item:2592"] = "Wool Cloth",
  ["item:2770"] = "Copper Ore",
  ["item:2840"] = "Copper Bar",
}

local function names(itemString)
  return NAMES[itemString]
end

describe("RecommendationTable.reagentLines", function()
  it("lists a Craft's Sub-crafts deepest first, before what it uses and buys", function()
    local craft = {
      itemKey = "5762",
      action = "Craft",
      quantity = 1,
      character = "Kash-Patel",
      via = {
        { itemKey = "2840", crafts = 10, character = "Alt-One" },
        { itemKey = "2996", crafts = 5, character = "Kash-Patel" },
      },
      uses = { { itemKey = "2770", quantity = 20 } },
      buys = { { itemKey = "2589", quantity = 12, maxUnitPrice = 120 } },
    }

    assert.are.same({
      "Craft 10 Copper Bar on Alt-One",
      "Craft 5 item:2996 on Kash-Patel",
      "Use 20 Copper Ore",
      "Buy 12 Linen Cloth @ max 1s 20c",
    }, RecommendationTable.reagentLines(craft, names))
  end)
end)

describe("RecommendationTable.matLines", function()
  it("names a Disenchant's expected mats, which come in fractions", function()
    local disenchant = {
      itemKey = "9999",
      action = "Disenchant",
      quantity = 2,
      character = "Kash-Patel",
      mats = { { itemKey = "2589", quantity = 3.75 }, { itemKey = "10939", quantity = 0.6 } },
    }

    assert.are.same({
      "Expect 3.75 Linen Cloth",
      "Expect 0.60 item:10939",
    }, RecommendationTable.matLines(disenchant, names))
  end)
end)

describe("RecommendationTable.reagentLines' mail lines", function()
  local craft = {
    itemKey = "2997",
    action = "Craft",
    quantity = 1,
    character = "Kash-Patel",
    uses = {
      { itemKey = "2589", quantity = 20 },
      { itemKey = "2320", quantity = 3 },
      { itemKey = "2592", quantity = 9 },
    },
  }

  it("mails a held reagent the crafter is short of from the biggest holders first, never bound units", function()
    local holdersOf = {
      -- The crafter's own bound units still count: it can use them.
      ["2589"] = {
        { character = "Alt-One", bags = 12, bank = 0, bound = 2 },
        { character = "Bank-Alt", bags = 0, bank = 8, bound = 0 },
        { character = "Kash-Patel", bags = 5, bank = 0, bound = 2 },
      },
      ["2320"] = { { character = "Kash-Patel", bags = 3, bank = 0, bound = 0 } },
      ["2592"] = {
        { character = "Alt-One", bags = 4, bank = 0, bound = 4 },
        { character = "Kash-Patel", bags = 5, bank = 0, bound = 0 },
      },
    }

    assert.are.same({
      "Use 20 Linen Cloth",
      "Use 3 Coarse Thread",
      "Use 9 Wool Cloth",
      "Mail 10 Linen Cloth from Alt-One to Kash-Patel",
      "Mail 5 Linen Cloth from Bank-Alt to Kash-Patel",
    }, RecommendationTable.reagentLines(craft, names, holdersOf))
  end)

  it("mails nothing when a Sub-craft runs on another Character, since uses can't say whose reagents are whose", function()
    local chained = {
      itemKey = "2997",
      action = "Craft",
      quantity = 1,
      character = "Kash-Patel",
      via = { { itemKey = "2996", crafts = 5, character = "Alt-One" } },
      uses = { { itemKey = "2589", quantity = 10 } },
    }
    local holdersOf = { ["2589"] = { { character = "Alt-One", bags = 10, bank = 0, bound = 0 } } }

    assert.are.same(
      { "Craft 5 item:2996 on Alt-One", "Use 10 Linen Cloth" },
      RecommendationTable.reagentLines(chained, names, holdersOf)
    )
  end)

  it("mails nothing without knowing who holds what", function()
    assert.are.same(
      { "Use 20 Linen Cloth", "Use 3 Coarse Thread", "Use 9 Wool Cloth" },
      RecommendationTable.reagentLines(craft, names)
    )
  end)
end)

describe("RecommendationTable.build", function()
  it("sums up a Holdings Craft's Character and reagents in its note, and names what it uses in its tooltip", function()
    local view = build(entry({ holdings = { holdingsCraft() } }), AS_OF, names)

    local row = view.sections[1].rows[1]
    assert.are.same({ "item:2997", "Craft", "3", "", "79c", "", "on Kash-Patel, 2 reagents" }, row.cells)
    assert.are.same({ "Use 9 Wool Cloth", "Use 3 Coarse Thread" }, row.tooltip)
  end)

  it("ends a row's tooltip with which Characters hold its Item Key", function()
    local sell = { itemKey = "2589", action = "Sell", quantity = 16, price = 100, profit = 1520, saleEvents = 3 }
    local held = { ["2589"] = { { character = "Kash-Patel", bags = 12, bank = 4, bound = 0 } } }

    local view = build(entry({ holdings = { sell }, held = held }), AS_OF, names)

    assert.are.same({ "Sales 3", "On Kash-Patel: 12 bags, 4 bank" }, view.sections[1].rows[1].tooltip)
  end)

  it("tells a Flip to Craft's crafter what to mail it", function()
    local held = { ["2320"] = { { character = "Alt-One", bags = 1, bank = 0, bound = 0 } } }

    local view = build(entry({ shoppingList = { flipToCraft() }, held = held }), AS_OF, names)

    assert.are.same({
      "Use 1 Coarse Thread",
      "Buy 12 Linen Cloth @ max 1s 20c",
      "Buy 5 Coarse Thread from a merchant @ 10c",
      "Mail 1 Coarse Thread from Alt-One to Kash-Patel",
    }, view.sections[3].rows[1].tooltip)
  end)

  it("marks the Holdings rows whose Item Key is in the logged-in Character's bags", function()
    local function sell(itemKey)
      return { itemKey = itemKey, action = "Sell", quantity = 1, price = 100, profit = 95 }
    end
    local held = {
      ["2589"] = { { character = "Kash-Patel", bags = 2, bank = 0, bound = 0 } },
      ["2592"] = { { character = "Kash-Patel", bags = 0, bank = 3, bound = 0 } },
      ["2320"] = { { character = "Alt-One", bags = 4, bank = 0, bound = 0 } },
    }
    local recs = entry({ holdings = { sell("2589"), sell("2592"), sell("2320") }, shoppingList = { sell("2589") }, held = held })

    local view = build(recs, AS_OF, names, "Kash-Patel")

    local marked = {}
    for _, row in ipairs(view.sections[1].rows) do
      marked[row.itemString] = row.cells[1]
    end
    assert.are.same({
      ["item:2589"] = RecommendationTable.BAG .. " Linen Cloth",
      ["item:2592"] = "Wool Cloth",
      ["item:2320"] = "Coarse Thread",
    }, marked)
    assert.are.equal("Linen Cloth", view.sections[2].rows[1].cells[1])
  end)

  it("says why a Holdings Craft can't be made, naming the reagent it has no market data for", function()
    local view = build(entry({ holdings = { blockedCraft({ reason = "noData", itemKey = "2770" }) } }), AS_OF, names)

    local row = view.sections[1].rows[1]
    assert.are.same({ "item:2996", "Craft", "0", "", "", "", "on Kash-Patel: no market data for Copper Ore" }, row.cells)
    assert.are.same({ "on Kash-Patel: no market data for Copper Ore" }, row.tooltip)
  end)

  it("names a blocked Craft's reagent by its Item Key until the client has loaded it", function()
    local view = build(entry({ holdings = { blockedCraft({ reason = "noData", itemKey = "2770" }) } }))

    local row = view.sections[1].rows[1]
    assert.are.equal("on Kash-Patel: no market data for item:2770", row.cells[7])
    assert.are.same({ "on Kash-Patel: no market data for item:2770" }, row.tooltip)
  end)

  it("says when a Holdings Craft's output bind type isn't known", function()
    local view = build(entry({ holdings = { blockedCraft({ reason = "unknownBindType" }) } }), AS_OF, names)

    local row = view.sections[1].rows[1]
    assert.are.equal("on Kash-Patel: unknown bind type", row.cells[7])
    assert.are.same({ "on Kash-Patel: unknown bind type" }, row.tooltip)
  end)

  it("keeps a blocked Craft's note when it doesn't know the reason", function()
    local view = build(entry({ holdings = { blockedCraft({ reason = "somethingNew" }) } }), AS_OF, names)

    local row = view.sections[1].rows[1]
    assert.are.equal("on Kash-Patel: no data for 2770", row.cells[7])
    assert.are.same({ "on Kash-Patel: no data for 2770" }, row.tooltip)
  end)

  it("shows a Holding's ROI green, red, or brighter green and starred when it's a good time to sell", function()
    local function roiCell(fields)
      local r = { itemKey = "2589", action = "Sell", quantity = 1, price = 200, profit = 190 }
      for k, v in pairs(fields) do
        r[k] = v
      end
      return build(entry({ holdings = { r } })).sections[1].rows[1].cells[6]
    end

    assert.are.equal("|cff1eff00+19%|r", roiCell({ paid = 160, paidUnits = 1, roi = 0.1875 }))
    assert.are.equal("|cffff2020-12%|r", roiCell({ paid = 216, paidUnits = 1, roi = -0.12 }))
    assert.are.equal(
      "|cff80ff80+90% " .. RecommendationTable.STAR .. "|r",
      roiCell({ paid = 100, paidUnits = 1, roi = 0.9, roiHint = true })
    )
    assert.are.equal("|cff1eff00+0%|r", roiCell({ paid = 100, paidUnits = 1, roi = -0.003 }))
    assert.are.equal("", roiCell({}))
  end)

  it("tells in a Holding's tooltip what its units cost and what they net, and hints when to sell", function()
    -- 5 of the 20 held were bought, at 1g 20s each: Sold they net 1g 50s, Vendored 60s.
    local view = build(entry({
      holdings = {
        { itemKey = "2589", action = "Sell", quantity = 12, price = 15790, profit = 180000, paid = 12000, paidUnits = 5, roi = 0.25, roiHint = true },
        { itemKey = "2589", action = "Vendor", quantity = 8, price = 6000, profit = 48000, paid = 12000, paidUnits = 5, roi = -0.5 },
        { itemKey = "2592", action = "Sell", quantity = 3, price = 100, profit = 285, paid = 50, paidUnits = 3, roi = 0.9 },
      },
    }))

    local tooltips = {}
    for _, row in ipairs(view.sections[1].rows) do
      tooltips[row.itemString .. " " .. row.cells[2]] = row.tooltip
    end
    assert.are.same({
      "Paid 1g 20s each (5 of 20), nets 1g 50s: +25%",
      "Good time to sell: nets +25% on what you paid (hint only)",
    }, tooltips["item:2589 Sell"])
    assert.are.same({ "Paid 1g 20s each (5 of 20), nets 60s: -50%" }, tooltips["item:2589 Vendor"])
    assert.are.same({ "Paid 50c each, nets 95c: +90%" }, tooltips["item:2592 Sell"])
  end)

  it("heads the table in two lines: the Scan's age and window hours, then gold and totals", function()
    local view = build(entry(), AS_OF + 12 * 60 + 30)

    assert.are.equal("Classic Beta PvP Alliance", view.title)
    assert.matches("^as of %d%d:%d%d, 12 min ago, Observation Window 0.3 h$", view.header[1])
    assert.are.equal("Gold 17g 54s 71c, Budget all, Prediction buys 0c", view.header[2])
    assert.are.equal(2, #view.header)
  end)

  it("heads the table with the Budget the player set, and asks for a Reload when the Brain sized for another", function()
    assert.are.equal(
      "Gold 17g 54s 71c, Budget 5g, Prediction buys 0c",
      build(entry({ budget = 50000 }), AS_OF, nil, nil, 50000).header[2]
    )
    assert.are.equal(
      "Gold 17g 54s 71c, Budget 5g (Reload to re-size), Prediction buys 0c",
      build(entry(), AS_OF, nil, nil, 50000).header[2]
    )
    assert.are.equal(
      "Gold 17g 54s 71c, Budget all (Reload to re-size), Prediction buys 0c",
      build(entry({ budget = 50000 }), AS_OF).header[2]
    )
  end)

  it("keys the saved Budgets by Market, since gold pools per realm and faction", function()
    assert.are.equal("Classic Beta PvP-Alliance", RecommendationTable.budgetKey(REALM, FACTION))
  end)

  it("folds Shopping List options that cost more than the Budget into a count (#86)", function()
    local view = build(
      entry({
        shoppingList = {
          { itemKey = "9749", action = "Sell", quantity = 3, price = 1000, postAt = 4200.0, profit = 9450.0, cost = 3000 },
          { itemKey = "2589", action = "Vendor", quantity = 2, price = 100, profit = 20.0, cost = 200 },
        },
      }),
      AS_OF,
      nil,
      nil,
      2000
    )

    local shopping = view.sections[2]
    assert.are.equal(1, #shopping.rows)
    assert.are.equal("item:2589", shopping.rows[1].itemString)
    assert.are.equal("1 over the Budget (Reload to re-size)", shopping.more)
    assert.are.equal("Shopping List (1)", shopping.tab)
  end)

  it("puts Flips to Craft in their own tab after the Shopping List, each folding over the Budget (#87)", function()
    local dear = flipToCraft()
    dear.cost = 3000
    local view = build(
      entry({
        shoppingList = {
          { itemKey = "9749", action = "Sell", quantity = 3, price = 1000, postAt = 4200.0, profit = 9450.0, cost = 3000 },
          flipToCraft(),
          dear,
          { itemKey = "2589", action = "Vendor", quantity = 2, price = 100, profit = 20.0, cost = 200 },
        },
      }),
      AS_OF,
      nil,
      nil,
      2000
    )

    local shopping, crafts = view.sections[2], view.sections[3]
    assert.are.equal("item:2589", shopping.rows[1].itemString)
    assert.are.equal("Shopping List (1)", shopping.tab)
    assert.are.equal("1 over the Budget (Reload to re-size)", shopping.more)
    assert.are.equal("Flips to Craft", crafts.title)
    assert.are.equal("item:2996", crafts.rows[1].itemString)
    assert.are.equal("Flips to Craft (1)", crafts.tab)
    assert.are.equal("1 over the Budget (Reload to re-size)", crafts.more)
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
    assert.are.same({ "Item", "Action", "Qty", "Price", "Profit", "ROI", "Note" }, holdings.columns)
    local row = holdings.rows[1]
    assert.are.equal("item:248704", row.itemString)
    assert.are.same(
      { "Heavy Leather", "Sell", "2", "1g 13s 43c", "2g 15s 51c", "", "incl. 3 crafted" },
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

    assert.are.same(
      { "Holdings (1)", "Shopping List (0)", "Flips to Craft (0)", "Prediction buys (0)", "Buy Under (0)" },
      {
        view.sections[1].tab,
        view.sections[2].tab,
        view.sections[3].tab,
        view.sections[4].tab,
        view.sections[5].tab,
      }
    )
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
    assert.are.equal("No Flips to Craft right now", view.sections[3].empty)
    assert.are.equal("No Prediction buys right now", view.sections[4].empty)
    assert.are.equal("No Buy Unders right now", view.sections[5].empty)
  end)

  it("shows the Shopping List under the Holdings, with Buy as a Flip to Sell's Action", function()
    local view = build(entry({
      shoppingList = {
        { itemKey = "9749", action = "Sell", quantity = 3, price = 1000, postAt = 4200.0, profit = 9450.0, saleEvents = 4, cost = 3000 },
      },
    }))

    local shopping = view.sections[2]
    assert.are.equal("Shopping List", shopping.title)
    assert.are.same(
      { "Item", "Action", "Qty", "Max price", "Post at", "Profit", "Per click", "Per day", "ROI", "Cost", "Note" },
      shopping.columns
    )
    assert.are.same({ "item:9749", "Buy", "3", "10s", "42s", "94s 50c", "", "", "", "30s", "" }, shopping.rows[1].cells)
    assert.are.same({ "Sales 4" }, shopping.rows[1].tooltip)
  end)

  it("shows a Flip's Profit per click and per day, and its ROI, and sums up the clicks and wait in its tooltip (#98)", function()
    local view = build(entry({
      shoppingList = {
        {
          itemKey = "9749", action = "Sell", quantity = 30, price = 1000, postAt = 4200.0, profit = 90000.0,
          saleEvents = 4, cost = 25000, listings = 12, posts = 3, days = 2.5,
        },
      },
    }))

    local row = view.sections[2].rows[1]
    -- 9g over 15 clicks, over 2.5 days, and on 2g 50s.
    assert.are.same({ "60s", "3g 60s", "360%" }, { row.cells[7], row.cells[8], row.cells[9] })
    assert.are.same({ "12 Listings + 3 posts, sells in ~2.5 days", "Sales 4" }, row.tooltip)
  end)

  it("shows a Flip to Vendor's Per day as now, and says it posts nothing (#98)", function()
    local view = build(entry({
      shoppingList = {
        { itemKey = "2770", action = "Vendor", quantity = 1, price = 5, profit = 20, cost = 5, listings = 1, posts = 0 },
      },
    }))

    local row = view.sections[2].rows[1]
    assert.are.same({ "20c", "now", "400%" }, { row.cells[7], row.cells[8], row.cells[9] })
    assert.are.same({ "1 Listing, vendor now" }, row.tooltip)
  end)

  it("gives a wait under a day in hours, and one post as a post (#98)", function()
    local view = build(entry({
      shoppingList = {
        { itemKey = "9749", action = "Sell", quantity = 1, price = 100, profit = 50, cost = 100, listings = 1, posts = 1, days = 0.125 },
      },
    }))

    assert.are.same({ "1 Listing + 1 post, sells in ~3 h" }, view.sections[2].rows[1].tooltip)
  end)

  it("leaves the Flips to Craft tab's columns as they were (#98)", function()
    local view = build(entry({ shoppingList = { flipToCraft() } }))

    assert.are.same(
      { "Item", "Action", "Qty", "Max price", "Post at", "Profit", "Cost", "Note" },
      view.sections[3].columns
    )
  end)

  it("lists a Flip to Craft's held reagents, then its reagent buys, by name in its tooltip", function()
    local view = build(entry({ shoppingList = { flipToCraft() } }), AS_OF, names)

    assert.are.same({
      "Use 1 Coarse Thread",
      "Buy 12 Linen Cloth @ max 1s 20c",
      "Buy 5 Coarse Thread from a merchant @ 10c",
    }, view.sections[3].rows[1].tooltip)
  end)

  it("shows a Flip to Craft's Action as Craft, and sums up who crafts it and how many distinct reagents", function()
    local oneBuy = flipToCraft()
    oneBuy.buys[2] = nil
    oneBuy.uses = nil
    local view = build(entry({ shoppingList = { flipToCraft(), oneBuy } }))

    local rows = view.sections[3].rows
    assert.are.same(
      { "item:2996", "Craft", "6", "", "", "45s", "12s 50c", "on Kash-Patel, 2 reagents" },
      rows[1].cells
    )
    assert.are.equal("on Kash-Patel, 1 reagent", rows[2].cells[8])
  end)

  it("names a reagent not cached yet by its Item Key", function()
    local view = build(entry({ shoppingList = { flipToCraft() } }))

    assert.are.equal("Buy 12 item:2589 @ max 1s 20c", view.sections[3].rows[1].tooltip[2])
  end)

  it("shows Prediction buys after the Flips to Craft", function()
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

    local buys = view.sections[4]
    assert.are.equal("Prediction buys", buys.title)
    assert.are.same({ "Item", "Prediction", "Qty", "Max price", "Max Loss" }, buys.columns)
    assert.are.same({ "item:12359", "Phase 2", "20", "25s", "1g 20s" }, buys.rows[1].cells)
  end)

  it("shows the Buy Unders after the Prediction buys, with the way out, units and Scans that saw one (#88)", function()
    local view = build(entry({
      buyUnder = {
        { itemKey = "2589", price = 2100, way = "Sell", units = 40, seen = 14, windowDays = 7, listedNow = true },
      },
    }))

    local buyUnder = view.sections[5]
    assert.are.equal("Buy Under", buyUnder.title)
    assert.are.same({ "Item", "Buy Under", "Way out", "Units", "Seen", "Note" }, buyUnder.columns)
    assert.are.same({ "item:2589", "21s", "Sell", "40", "14 Scans / 7d", "listed now" }, buyUnder.rows[1].cells)
  end)

  it("keeps the Brain's order of Buy Unders, and never folds one over the Budget (#88)", function()
    local view = build(entry({
      buyUnder = {
        { itemKey = "1", price = 100, way = "Vendor", seen = 1, windowDays = 7 },
        { itemKey = "2", price = 900000, way = "Sell", units = 3, seen = 2, windowDays = 7 },
      },
    }), AS_OF, nil, nil, 5000)

    local buyUnder = view.sections[5]
    assert.are.same({ "item:1", "item:2" }, { buyUnder.rows[1].cells[1], buyUnder.rows[2].cells[1] })
    assert.is_nil(buyUnder.more)
  end)

  it("names a Craft way's output and crafter, and a Buy Under with no unit limit (#88)", function()
    local view = build(entry({
      buyUnder = {
        {
          itemKey = "2589", price = 90, way = "Craft", seen = 1, windowDays = 7,
          recipe = 2963, output = "2996", crafter = "Kash-Patel",
        },
      },
    }), AS_OF, function(itemString)
      return itemString == "item:2996" and "Bolt of Linen Cloth" or names(itemString)
    end)

    assert.are.same(
      { "Linen Cloth", "90c", "Craft Bolt of Linen Cloth (Kash-Patel)", "no limit", "1 Scan / 7d", "" },
      view.sections[5].rows[1].cells
    )
  end)

  it("shows a Disenchant source group's Buy Under by the group, with the disenchanter and mats (#88)", function()
    local mats = { { itemKey = "10940", quantity = 1.875 }, { itemKey = "10939", quantity = 0.3 } }
    local view = build(entry({
      buyUnder = {
        {
          group = { quality = 2, class = "weapon", minLevel = 16, maxLevel = 20 },
          price = 1812, way = "Disenchant", disenchanter = "Bob", mats = mats, units = 3, seen = 2, windowDays = 7,
        },
        { itemKey = "9999", price = 1700, way = "Disenchant", disenchanter = "Bob", mats = mats, seen = 1, windowDays = 7 },
      },
    }), AS_OF, function(itemString)
      return ({ ["item:10940"] = "Strange Dust", ["item:10939"] = "Greater Magic Essence" })[itemString]
    end)

    local rows = view.sections[5].rows
    local way = "Disenchant (Bob) -> Strange Dust, Greater Magic Essence"
    assert.are.same({ "Green weapons ilvl 16-20", "18s 12c", way, "3", "2 Scans / 7d", "" }, rows[1].cells)
    assert.is_nil(rows[1].itemString)
    assert.are.same({ "Expect 1.88 Strange Dust", "Expect 0.30 Greater Magic Essence" }, rows[1].tooltip)
    assert.are.same({ "item:9999", "17s", way, "no limit", "1 Scan / 7d", "" }, rows[2].cells)
  end)

  it("shows a Hold's profit as unknown and the Prediction it's under, as brain recommend does", function()
    local view = build(entry({
      holdings = {
        { itemKey = "12359", action = "Hold", quantity = 20, price = 2500, cost = 50000, prediction = "Phase 2" },
      },
    }))

    assert.are.same(
      { "item:12359", "Hold", "20", "25s", "unknown", "", "under Phase 2" },
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

    local buys = view.sections[4]
    assert.are.same({ "item:2", "item:3", "item:1" }, itemStrings(buys))
    assert.are.same({ column = 5, descending = false }, buys.sort)
  end)

  it("re-sorts by a money column's value, not its text, keeping rows with no value last", function()
    -- As text "1g" sorts before "9s"; a Hold's Profit is unknown.
    local view = build(entry({
      holdings = {
        { itemKey = "1", action = "Sell", quantity = 1, price = 10000, profit = 10000 },
        { itemKey = "2", action = "Hold", quantity = 1, price = 500, cost = 500, prediction = "Phase 2" },
        { itemKey = "3", action = "Sell", quantity = 1, price = 900, profit = 900 },
      },
    }))
    local holdings = view.sections[1]

    RecommendationTable.sort(holdings, { column = 5, descending = false })
    assert.are.same({ "item:3", "item:1", "item:2" }, itemStrings(holdings))

    RecommendationTable.sort(holdings, { column = 5, descending = true })
    assert.are.same({ "item:1", "item:3", "item:2" }, itemStrings(holdings))
  end)

  it("sorts the Shopping List by Per click, Per day or ROI, with a Flip to Vendor's now first per day (#98)", function()
    local view = build(entry({
      shoppingList = {
        { itemKey = "1", action = "Sell", quantity = 1, price = 100, profit = 900, cost = 100, listings = 5, posts = 4, days = 1 },
        { itemKey = "2", action = "Vendor", quantity = 1, price = 100, profit = 20, cost = 1000, listings = 1, posts = 0 },
        { itemKey = "3", action = "Sell", quantity = 1, price = 100, profit = 500, cost = 250, listings = 1, posts = 1, days = 5 },
      },
    }))
    local shopping = view.sections[2]

    -- Per click: 100, 20, 250.
    RecommendationTable.sort(shopping, { column = 7, descending = true })
    assert.are.same({ "item:3", "item:1", "item:2" }, itemStrings(shopping))
    -- Per day: 900, now, 100.
    RecommendationTable.sort(shopping, { column = 8, descending = true })
    assert.are.same({ "item:2", "item:1", "item:3" }, itemStrings(shopping))
    -- ROI: 9, 0.02, 2.
    RecommendationTable.sort(shopping, { column = 9, descending = true })
    assert.are.same({ "item:1", "item:3", "item:2" }, itemStrings(shopping))
  end)

  it("sorts the Shopping List by Post at, with a Flip to Vendor (no Post at) last", function()
    local view = build(entry({
      shoppingList = {
        { itemKey = "1", action = "Sell", quantity = 1, price = 100, postAt = 900, profit = 500, cost = 100 },
        { itemKey = "2", action = "Vendor", quantity = 1, price = 100, profit = 20, cost = 100 },
        { itemKey = "3", action = "Sell", quantity = 1, price = 100, postAt = 10000, profit = 500, cost = 100 },
      },
    }))
    local shopping = view.sections[2]

    RecommendationTable.sort(shopping, { column = 5, descending = true })
    assert.are.same({ "item:3", "item:1", "item:2" }, itemStrings(shopping))

    RecommendationTable.sort(shopping, { column = 5, descending = false })
    assert.are.same({ "item:1", "item:3", "item:2" }, itemStrings(shopping))
  end)

  it("sorts Holdings by ROI, with rows none of whose units were bought last", function()
    local function sell(itemKey, roi)
      return { itemKey = itemKey, action = "Sell", quantity = 1, price = 100, profit = 95, paid = 50, paidUnits = 1, roi = roi }
    end
    local holdings = build(entry({ holdings = { sell("1", 0.9), sell("2"), sell("3", -0.5), sell("4", 2) } })).sections[1]

    RecommendationTable.sort(holdings, { column = 6, descending = true })
    assert.are.same({ "item:4", "item:1", "item:3", "item:2" }, itemStrings(holdings))

    RecommendationTable.sort(holdings, { column = 6, descending = false })
    assert.are.same({ "item:3", "item:1", "item:4", "item:2" }, itemStrings(holdings))
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
  local holdings = build(entry()).sections[1] -- Item, Action, Qty, Price, Profit, ROI, Note

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
    assert.are.same({ column = 7, descending = false }, RecommendationTable.nextSort(holdings, holdings.sort, 7))
  end)

  it("sorts a Buy Under's way out A to Z on its first click, and its units largest first (#88)", function()
    local buyUnder = build(entry()).sections[5] -- Item, Buy Under, Way out, Units, Seen, Note
    assert.are.same({ column = 3, descending = false }, RecommendationTable.nextSort(buyUnder, buyUnder.sort, 3))
    assert.are.same({ column = 4, descending = true }, RecommendationTable.nextSort(buyUnder, buyUnder.sort, 4))
  end)
end)

describe("RecommendationTable saved sorts", function()
  local holdings = build(entry()).sections[1] -- Item, Action, Qty, Price, Profit, ROI, Note

  it("saves a sort by its column's name, so it outlives a change of column order", function()
    assert.are.same({ column = "Qty", descending = true },
      RecommendationTable.savedSort(holdings, { column = 3, descending = true }))
  end)

  it("restores a saved sort to its column's place", function()
    assert.are.same({ column = 3, descending = false },
      RecommendationTable.restoredSort(holdings, { column = "Qty", descending = false }))
  end)

  it("restores nothing for a column the section no longer has, or with nothing saved", function()
    assert.is_nil(RecommendationTable.restoredSort(holdings, { column = "Gone", descending = true }))
    assert.is_nil(RecommendationTable.restoredSort(holdings, nil))
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
