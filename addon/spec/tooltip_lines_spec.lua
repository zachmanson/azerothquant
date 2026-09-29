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

  it("follows a Holding's Sell and Vendor with what its units cost and net, and the hint to sell", function()
    local r = recs({
      holdings = {
        { itemKey = "2589", action = "Sell", quantity = 12, price = 15790, profit = 180000, paid = 12000, paidUnits = 5, roi = 0.25, roiHint = true },
        { itemKey = "2589", action = "Vendor", quantity = 8, price = 6000, profit = 48000, paid = 12000, paidUnits = 5, roi = -0.5 },
      },
    })

    assert.are.same({
      "AQ: Sell 12 @ 1g 57s 90c",
      "Paid 1g 20s each (5 of 20), nets 1g 50s: +25%",
      "Good time to sell: nets +25% on what you paid (hint only)",
      "AQ: Vendor 8 @ 60s",
      "Paid 1g 20s each (5 of 20), nets 60s: -50%",
    }, linesFor(r, "item:2589"))
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

  it("gives a Disenchant its Character and a line per expected mat, since it has no price", function()
    local r = recs({
      holdings = {
        {
          itemKey = "9999",
          action = "Disenchant",
          quantity = 2,
          profit = 535,
          note = "on Kash-Patel: expect 3.75 of 2589",
          character = "Kash-Patel",
          mats = { { itemKey = "2589", quantity = 3.75 } },
        },
      },
    })

    assert.are.same({ "AQ: Disenchant 2 on Kash-Patel", "Expect 3.75 Linen Cloth" }, linesFor(r, "item:9999"))
  end)

  it("follows a Craft's reagents with what to mail its crafter", function()
    local r = recs({
      holdings = {
        {
          itemKey = "2997",
          action = "Craft",
          quantity = 3,
          profit = 79.8,
          character = "Kash-Patel",
          uses = { { itemKey = "2592", quantity = 9 } },
        },
      },
      held = { ["2592"] = { { character = "Alt-One", bags = 9, bank = 0, bound = 0 } } },
    })

    assert.are.same(
      { "AQ: Craft 3 on Kash-Patel", "Use 9 Wool Cloth", "Mail 9 Wool Cloth from Alt-One to Kash-Patel" },
      linesFor(r, "item:2997")
    )
  end)

  it("gives a Craft on cooldown the note saying so", function()
    local r = recs({
      holdings = {
        {
          itemKey = "2996",
          action = "Craft",
          quantity = 0,
          note = "on Kash-Patel: on cooldown until 2026-09-28 12:00",
          character = "Kash-Patel",
        },
      },
    })

    assert.are.same({ "AQ: Craft 0 (on Kash-Patel: on cooldown until 2026-09-28 12:00)" }, linesFor(r, "item:2996"))
  end)

  -- As the Brain writes a Craft it couldn't value (#75).
  local function blockedCraft(blocked)
    return recs({
      holdings = {
        {
          itemKey = "2996",
          action = "Craft",
          quantity = 0,
          note = "on Kash-Patel: no data for 2589",
          character = "Kash-Patel",
          blocked = blocked,
        },
      },
    })
  end

  it("gives a Craft that can't be made the reason why, naming the reagent it has no market data for", function()
    local r = blockedCraft({ reason = "noData", itemKey = "2589" })

    assert.are.same({ "AQ: Craft 0 (on Kash-Patel: no market data for Linen Cloth)" }, linesFor(r, "item:2996"))
    assert.are.same(
      { "AQ: Craft 0 (on Kash-Patel: no market data for item:2589)" },
      TooltipLines.forLink(r, REALM, FACTION, link("item:2996"), function() end)
    )
  end)

  it("gives a Craft whose output bind type isn't known the reason why", function()
    local r = blockedCraft({ reason = "unknownBindType" })

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

  it("says which Characters hold the Item Key, after its Recommendations, leaving out zero parts", function()
    local r = recs({
      holdings = { { itemKey = "2589", action = "Sell", quantity = 51, price = 100, profit = 4845 } },
      held = {
        ["2589"] = {
          { character = "Alt-One", bags = 4, bank = 0, bound = 0 },
          { character = "Bank-Alt", bags = 0, bank = 5, bound = 0 },
          { character = "Kash-Patel", bags = 12, bank = 30, bound = 5 },
        },
      },
    })

    assert.are.same({
      "AQ: Sell 51 @ 1s",
      "On Alt-One: 4 bags",
      "On Bank-Alt: 5 bank",
      "On Kash-Patel: 12 bags, 30 bank (5 bound)",
    }, linesFor(r, "item:2589"))
  end)

  it("gives an item's Buy Under with its way out and the Scans that saw it, after its Recommendations (#88)", function()
    local r = recs({
      holdings = { { itemKey = "2589", action = "Sell", quantity = 2, price = 2500, profit = 4750 } },
      buyUnder = {
        {
          itemKey = "2589", price = 2100, way = "Craft", units = 40, seen = 14, windowDays = 7,
          recipe = 2963, output = "2996", crafter = "Kash-Patel",
        },
        { itemKey = "2592", price = 300, way = "Vendor", seen = 1, windowDays = 7 },
      },
      held = { ["2589"] = { { character = "Kash-Patel", bags = 2, bank = 0, bound = 0 } } },
    })
    local function named(itemString)
      return itemString == "item:2996" and "Bolt of Linen Cloth" or names(itemString)
    end

    assert.are.same({
      "AQ: Sell 2 @ 25s",
      "AQ: Buy Under 21s: Craft Bolt of Linen Cloth (Kash-Patel), seen 14 Scans / 7d",
      "On Kash-Patel: 2 bags",
    }, TooltipLines.forLink(r, REALM, FACTION, link("item:2589"), named))
    assert.are.same({ "AQ: Buy Under 3s: Vendor, seen 1 Scan / 7d" }, linesFor(r, "item:2592"))
  end)

  it("gives the higher of an item's own Buy Under and its Disenchant source group's (#88)", function()
    local group = {
      group = { quality = 2, class = "armor", minLevel = 16, maxLevel = 20 },
      price = 1812, way = "Disenchant", disenchanter = "Bob", seen = 2, windowDays = 7,
      mats = { { itemKey = "10940", quantity = 1.875 } },
    }
    local own = { itemKey = "9999", price = 1500, way = "Vendor", seen = 1, windowDays = 7 }
    local r = recs({ buyUnder = { own, group } })
    local info = { quality = 2, itemLevel = 18, classID = 4, equipLoc = "INVTYPE_CHEST" }
    local excluded = { itemIDs = {}, equipLocs = { INVTYPE_BODY = true } }
    local function named(itemString)
      return itemString == "item:10940" and "Strange Dust" or names(itemString)
    end
    local function lines(itemInfo)
      return TooltipLines.forLink(r, REALM, FACTION, link("item:9999"), named, itemInfo, excluded)
    end

    assert.are.same({ "AQ: Buy Under 18s 12c: Disenchant (Bob) -> Strange Dust, seen 2 Scans / 7d" }, lines(info))
    own.price = 2000
    assert.are.same({ "AQ: Buy Under 20s: Vendor, seen 1 Scan / 7d" }, lines(info))
    own.price = 1500
    info.equipLoc = "INVTYPE_BODY"
    assert.are.same({ "AQ: Buy Under 15s: Vendor, seen 1 Scan / 7d" }, lines(info))
    assert.are.same({ "AQ: Buy Under 15s: Vendor, seen 1 Scan / 7d" }, lines(nil))
    info.equipLoc = "INVTYPE_CHEST"
    assert.are.same({ "AQ: Buy Under 18s 12c: Disenchant (Bob) -> Strange Dust, seen 2 Scans / 7d" },
      TooltipLines.forLink(r, REALM, FACTION, link("item:8888"), named, info, excluded))
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

describe("TooltipLines.forItemName", function()
  -- An AH browse row for a suffixed item has a link without the suffix (#96), so it's found
  -- by itemID and the row's name instead.
  local SUFFIXED = {
    ["item:15932"] = "Willow Belt",
    ["item:15932::::::::::::1:1854"] = "Willow Belt of the Sorcerer",
    ["item:15932::::::::::::1:1855"] = "Willow Belt of the Sorcerer",
    ["item:15932::::::::::::1:1873"] = "Willow Belt of the Owl",
  }

  local function suffixedNames(itemString)
    return SUFFIXED[itemString]
  end

  local function linesForName(recommendations, itemID, name)
    return TooltipLines.forItemName(recommendations, REALM, FACTION, itemID, name, suffixedNames)
  end

  it("gives the lines of the Item Key with that itemID and name", function()
    local r = recs({
      holdings = {
        { itemKey = "15932", action = "Sell", quantity = 1, price = 500, profit = 475 },
        { itemKey = "15932:1854", action = "Sell", quantity = 1, price = 1999, profit = 1899 },
        { itemKey = "15932:1873", action = "Vendor", quantity = 1, price = 300, profit = 300 },
      },
      held = { ["15932:1854"] = { { character = "Kash-Patel", bags = 1, bank = 0, bound = 0 } } },
    })

    assert.are.same(
      { "AQ: Sell 1 @ 19s 99c", "On Kash-Patel: 1 bags" },
      linesForName(r, 15932, "Willow Belt of the Sorcerer")
    )
  end)

  it("gives the lines of every Item Key a row groups under one name", function()
    local r = recs({
      holdings = { { itemKey = "15932:1854", action = "Sell", quantity = 1, price = 1999, profit = 1899 } },
      shoppingList = { { itemKey = "15932:1855", action = "Sell", quantity = 2, price = 1500, profit = 800 } },
    })

    assert.are.same(
      { "AQ: Sell 1 @ 19s 99c", "AQ: Buy 2 @ max 15s" },
      linesForName(r, 15932, "Willow Belt of the Sorcerer")
    )
  end)

  it("gives the Buy Under of the Item Key with that itemID and name (#88)", function()
    local r = recs({
      buyUnder = { { itemKey = "15932:1873", price = 250, way = "Vendor", seen = 2, windowDays = 7 } },
    })

    assert.are.same({ "AQ: Buy Under 2s 50c: Vendor, seen 2 Scans / 7d" }, linesForName(r, 15932, "Willow Belt of the Owl"))
  end)

  it("gives the item's Disenchant source group's Buy Under even before the row's name loads (#88)", function()
    local r = recs({
      buyUnder = {
        {
          group = { quality = 2, class = "armor", minLevel = 16, maxLevel = 20 },
          price = 1812, way = "Disenchant", disenchanter = "Bob", seen = 2, windowDays = 7,
          mats = { { itemKey = "10940", quantity = 1.875 } },
        },
      },
    })
    local info = { quality = 2, itemLevel = 18, classID = 4, equipLoc = "INVTYPE_CHEST" }

    assert.are.same(
      { "AQ: Buy Under 18s 12c: Disenchant (Bob) -> item:10940, seen 2 Scans / 7d" },
      TooltipLines.forItemName(r, REALM, FACTION, 15932, nil, names, info, {})
    )
  end)

  it("adds nothing for a name no Item Key has, or one the client hasn't loaded", function()
    local r = recs({
      holdings = { { itemKey = "15932:1999", action = "Sell", quantity = 1, price = 1999, profit = 1899 } },
    })

    assert.are.same({}, linesForName(r, 15932, "Willow Belt of the Sorcerer"))
    assert.are.same({}, linesForName(nil, 15932, "Willow Belt of the Sorcerer"))
  end)
end)
