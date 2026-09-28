local TooltipLines = require("TooltipLines")

local REALM, FACTION = "Classic Beta PvP", "Alliance"

-- Recommendations shaped like the Brain writes them (see Recommendations.lua).
local function recs(fields)
  local e = { holdings = {}, shoppingList = {}, predictionBuys = {} }
  for k, v in pairs(fields) do
    e[k] = v
  end
  return { [REALM] = { [FACTION] = e } }
end

local function link(itemString, name)
  return "|cffffffff|H" .. itemString .. "|h[" .. (name or "Thing") .. "]|h|r"
end

local NAMES = { ["item:2589"] = "Linen Cloth", ["item:2320"] = "Coarse Thread", ["item:2592"] = "Wool Cloth" }

local function names(itemString)
  return NAMES[itemString]
end

local function linesFor(recommendations, itemString)
  return TooltipLines.forLink(recommendations, REALM, FACTION, link(itemString), names)
end

describe("TooltipLines.forLink", function()
  it("gives a Holding's Sell as quantity at price", function()
    local r = recs({
      holdings = { { itemKey = "248704", action = "Sell", quantity = 2, price = 12800.4, profit = 24000 } },
    })

    assert.are.same({ "AQ: Sell 2 @ 1g 28s" }, linesFor(r, "item:248704::::::::20:1490::::::"))
  end)

  it("keys a suffixed item by its bonus IDs in ascending order, like the Brain", function()
    local r = recs({
      holdings = {
        { itemKey = "6581", action = "Sell", quantity = 1, price = 100, profit = 95 },
        { itemKey = "6581:1500:12732", action = "Sell", quantity = 1, price = 5000, profit = 4750 },
      },
    })

    assert.are.same({ "AQ: Sell 1 @ 50s" }, linesFor(r, "item:6581::::::::20:1490::1:2:12732:1500"))
  end)

  it("ignores the bonus ID 3524 the AH adds to its browse-row links", function()
    local r = recs({
      holdings = { { itemKey = "1179", action = "Sell", quantity = 4, price = 49, profit = 187 } },
    })

    -- Captured in game (#37): the AH's Ice Cold Milk vs. the same milk in bags.
    assert.are.same({ "AQ: Sell 4 @ 49c" }, linesFor(r, "item:1179::::::::20:1490:::1:3524::::::"))
    assert.are.same({ "AQ: Sell 4 @ 49c" }, linesFor(r, "item:1179::::::::20:1490::::::::"))
  end)

  it("gives a Hold its Prediction instead of a price", function()
    local r = recs({
      holdings = { { itemKey = "12359", action = "Hold", quantity = 20, price = 2500, prediction = "Phase 2" } },
    })

    assert.are.same({ "AQ: Hold 20 under Phase 2" }, linesFor(r, "item:12359"))
  end)

  it("gives a Craft its Character and a line per held reagent it uses, since it has no price", function()
    local r = recs({
      holdings = {
        {
          itemKey = "2997",
          action = "Craft",
          quantity = 3,
          profit = 79.8,
          note = "on Kash-Patel: uses 9 of 2592, 3 of 2320",
          character = "Kash-Patel",
          uses = { { itemKey = "2592", quantity = 9 }, { itemKey = "2320", quantity = 3 } },
        },
      },
    })

    assert.are.same(
      { "AQ: Craft 3 on Kash-Patel", "Use 9 Wool Cloth", "Use 3 Coarse Thread" },
      linesFor(r, "item:2997")
    )
  end)

  it("gives a Craft that can't be made the note saying why", function()
    local r = recs({
      holdings = {
        {
          itemKey = "2996",
          action = "Craft",
          quantity = 0,
          note = "on Kash-Patel: unknown bind type",
          character = "Kash-Patel",
        },
      },
    })

    assert.are.same({ "AQ: Craft 0 (on Kash-Patel: unknown bind type)" }, linesFor(r, "item:2996"))
  end)

  it("gives a Flip to Craft's output a buy-then-craft line, then the reagents it uses and buys", function()
    local r = recs({
      shoppingList = {
        {
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
        },
      },
    })

    assert.are.same({
      "AQ: Buy reagents, Craft 6 on Kash-Patel",
      "Use 1 Coarse Thread",
      "Buy 12 Linen Cloth @ max 1s 20c",
      "Buy 5 Coarse Thread from a merchant @ 10c",
    }, linesFor(r, "item:2996"))
  end)

  it("adds nothing for rows the Recommendation Table folds away", function()
    local r = recs({
      holdings = {
        { itemKey = "1", quantity = 4, note = "no data" },
        { itemKey = "2", action = "Vendor", quantity = 1, price = 0, profit = 0 },
        { itemKey = "3", action = "Vendor", quantity = 3, price = 5, profit = 15 },
      },
    })

    assert.are.same({}, linesFor(r, "item:1"))
    assert.are.same({}, linesFor(r, "item:2"))
    assert.are.same({ "AQ: Vendor 3 @ 5c" }, linesFor(r, "item:3"))
  end)

  it("gives a line per section the Item Key is in: Holdings, Shopping List, Prediction buys", function()
    local r = recs({
      holdings = { { itemKey = "12359", action = "Sell", quantity = 2, price = 3000, profit = 5700 } },
      shoppingList = {
        { itemKey = "12359", action = "Sell", quantity = 3, price = 1000, profit = 4500, cost = 3000 },
      },
      predictionBuys = {
        { itemKey = "12359", action = "Hold", quantity = 20, price = 2500, cost = 50000, prediction = "Phase 2" },
      },
    })

    assert.are.same({
      "AQ: Sell 2 @ 30s",
      "AQ: Buy 3 @ max 10s",
      "AQ: Buy 20 @ max 25s under Phase 2",
    }, linesFor(r, "item:12359"))
  end)

  it("adds nothing without Recommendations for the Market or an item link", function()
    local r = recs({ holdings = { { itemKey = "1", action = "Sell", quantity = 1, price = 1, profit = 1 } } })

    assert.are.same({}, TooltipLines.forLink(nil, REALM, FACTION, link("item:1")))
    assert.are.same({}, TooltipLines.forLink({}, REALM, FACTION, link("item:1")))
    assert.are.same({}, TooltipLines.forLink(r, REALM, "Horde", link("item:1")))
    assert.are.same({}, TooltipLines.forLink(r, REALM, FACTION, nil))
    assert.are.same({}, TooltipLines.forLink(r, REALM, FACTION, link("battlepet:1:25", "Pet")))
  end)
end)
