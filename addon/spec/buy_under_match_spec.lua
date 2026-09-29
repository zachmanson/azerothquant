local BuyUnderMatch = require("BuyUnderMatch")

local REALM, FACTION = "Classic Beta PvP", "Alliance"

-- Recommendations shaped like the Brain writes them (see Recommendations.lua).
local function recs(buyUnder)
  return { [REALM] = { [FACTION] = { holdings = {}, shoppingList = {}, predictionBuys = {}, buyUnder = buyUnder } } }
end

local function link(itemString)
  return "|cffffffff|H" .. itemString .. "|h[Thing]|h|r"
end

local function noNames()
  return nil
end

local EXCLUDED = { itemIDs = { [11288] = true }, equipLocs = { INVTYPE_BODY = true } }

local function under(recommendations, listing, nameOf)
  return BuyUnderMatch.under(recommendations, REALM, FACTION, listing, nameOf or noNames, EXCLUDED)
end

describe("BuyUnderMatch.under", function()
  local linen = { itemKey = "2589", price = 2100, way = "Sell", units = 40, seen = 14, windowDays = 7 }

  it("flags a Listing at or under its Item Key's Buy Under, and not one over it", function()
    local r = recs({ linen })

    assert.are.same(linen, under(r, { link = link("item:2589"), unitPrice = 2100 }))
    assert.are.same(linen, under(r, { link = link("item:2589"), unitPrice = 1500 }))
    assert.is_nil(under(r, { link = link("item:2589"), unitPrice = 2101 }))
  end)

  it("flags a browse row or commodity Listing by its itemID, which has no link", function()
    local r = recs({ linen })

    assert.are.same(linen, under(r, { itemID = 2589, unitPrice = 2000 }))
    assert.is_nil(under(r, { itemID = 2589, unitPrice = 2200 }))
    assert.is_nil(under(r, { itemID = 2592, unitPrice = 1 }))
  end)

  it("flags a browse row of a suffixed item only by the Item Key with the row's name (#96)", function()
    local owl = { itemKey = "15932:1873", price = 900, way = "Vendor", seen = 1, windowDays = 7 }
    local r = recs({ owl })
    local function names(itemString)
      return ({ ["item:15932::::::::::::1:1873"] = "Willow Belt of the Owl" })[itemString]
    end

    assert.are.same(owl, under(r, { itemID = 15932, name = "Willow Belt of the Owl", unitPrice = 800 }, names))
    assert.is_nil(under(r, { itemID = 15932, name = "Willow Belt of the Sorcerer", unitPrice = 800 }, names))
    assert.is_nil(under(r, { itemID = 15932, unitPrice = 800 }, names))
  end)

  it("flags nothing without Recommendations for the Market, or for a bid-only Listing", function()
    local listing = { itemID = 2589, unitPrice = 1 }

    assert.is_nil(under(nil, listing))
    assert.is_nil(BuyUnderMatch.under(recs({ linen }), REALM, "Horde", listing, noNames))
    assert.is_nil(under(recs(nil), listing))
    assert.is_nil(under(recs({ linen }), { itemID = 2589 }))
  end)

  local greenWeapons = {
    group = { quality = 2, class = "weapon", minLevel = 16, maxLevel = 20 },
    price = 1812, way = "Disenchant", disenchanter = "Bob", seen = 2, windowDays = 7,
  }
  local function weapon(level, fields)
    local info = { quality = 2, itemLevel = level, classID = 2, equipLoc = "INVTYPE_WEAPON" }
    for k, v in pairs(fields or {}) do
      info[k] = v
    end
    return info
  end

  it("flags a Listing of any item in a Disenchant source group at or under the group's Buy Under", function()
    local r = recs({ greenWeapons })

    assert.are.same(greenWeapons, under(r, { itemID = 5000, info = weapon(16), unitPrice = 1812 }))
    assert.are.same(greenWeapons, under(r, { link = link("item:5001"), itemID = 5001, info = weapon(20), unitPrice = 900 }))
    assert.is_nil(under(r, { itemID = 5000, info = weapon(16), unitPrice = 1813 }))
    assert.is_nil(under(r, { itemID = 5000, info = weapon(21), unitPrice = 1 }))
    assert.is_nil(under(r, { itemID = 5000, info = weapon(18, { classID = 4, equipLoc = "INVTYPE_CHEST" }), unitPrice = 1 }))
    assert.is_nil(under(r, { itemID = 5000, info = weapon(18, { quality = 3 }), unitPrice = 1 }))
    assert.is_nil(under(r, { itemID = 5000, unitPrice = 1 }))
  end)

  it("never flags by group an item that can't be Disenchanted", function()
    local r = recs({ greenWeapons })

    assert.is_nil(under(r, { itemID = 11288, info = weapon(18), unitPrice = 1 }))
    assert.is_nil(under(r, { itemID = 5000, info = weapon(18, { equipLoc = "INVTYPE_BODY" }), unitPrice = 1 }))
    assert.is_nil(under(r, { itemID = 5000, info = weapon(18, { equipLoc = "" }), unitPrice = 1 }))
  end)

  it("gives whichever is higher of the item's own Buy Under and its group's", function()
    local own = { itemKey = "5000", price = 2500, way = "Sell", units = 2, seen = 1, windowDays = 7 }
    local listing = { itemID = 5000, info = weapon(18), unitPrice = 1000 }

    assert.are.same(own, under(recs({ greenWeapons, own }), listing))
    own.price = 1500
    assert.are.same(greenWeapons, under(recs({ own, greenWeapons }), listing))
  end)
end)
