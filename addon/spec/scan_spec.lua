local Scan = require("Scan")

-- Rows as the glue layer reads them from C_AuctionHouse.GetReplicateItemInfo /
-- GetReplicateItemLink / GetReplicateItemTimeLeft. Links are real ones from the
-- beta client (spike #1).
local WOLF_MEAT = "|cnIQ1:|Hitem:2680::::::::20:1490:::::::::|h[Spiced Wolf Meat]|h|r"
local NATURE_PROT = "|cnIQ2:|Hitem:9768::::::::20:1490::1:1:12743:::::::|h[Scouting Belt of Nature Protection]|h|r"
local LINEN = "|cnIQ1:|Hitem:2589::::::::20:1490:::::::::|h[Linen Cloth]|h|r"

local REQUEST = {
  id = 7,
  requestedAt = 1790000000,
  realm = "Classic Beta PvP",
  character = "Kash-Patel",
  faction = "Alliance",
}

local function row(overrides)
  local r = {
    link = WOLF_MEAT,
    count = 10,
    buyout = 280,
    timeLeft = 3,
  }
  for k, v in pairs(overrides or {}) do
    r[k] = v
  end
  return r
end

-- A row the main read dropped: the game gave its itemID but not its link yet (#150).
local function dropped(itemID)
  local r = row({ itemID = itemID })
  r.link = nil
  return r
end

-- Everyone else's rows, unpacked from packedListings as the Brain reads them (#144).
local function others(scan)
  local result = {}
  for packed in scan.packedListings:gmatch("[^;]+") do
    local itemString, quantity, buyout, timeLeft = packed:match("^([^,]*),([^,]*),([^,]*),([^,]*)$")
    result[#result + 1] = {
      itemString = itemString,
      quantity = tonumber(quantity),
      buyout = tonumber(buyout),
      timeLeft = tonumber(timeLeft),
    }
  end
  return result
end

describe("Scan.marketFaction", function()
  -- UnitGUID("npc") format: Creature-0-<server>-<instance>-<zone>-<npcID>-<spawn>
  it("is Neutral at a neutral auctioneer, whatever the player's faction", function()
    assert.are.equal("Neutral", Scan.marketFaction("Creature-0-4378-1-17-8661-000054A1B2", "Alliance")) -- Beardo, Gadgetzan
    assert.are.equal("Neutral", Scan.marketFaction("Creature-0-4378-0-17-9858-000054A1B2", "Horde")) -- Kresky, Booty Bay
    assert.are.equal("Neutral", Scan.marketFaction("Creature-0-4378-1-17-9857-000054A1B2", "Horde")) -- Grizzlin, Everlook
  end)

  it("is the player's faction at any other auctioneer", function()
    -- Any NPC ID not on the neutral list, e.g. a capital-city auctioneer.
    assert.are.equal("Alliance", Scan.marketFaction("Creature-0-4378-0-12-8719-000054A1B2", "Alliance"))
    assert.are.equal("Horde", Scan.marketFaction("Creature-0-4378-1-1637-8673-000054A1B2", "Horde"))
  end)

  it("falls back to the player's faction without an NPC GUID", function()
    -- The npc unit can be gone by the time the Scan is requested.
    assert.are.equal("Alliance", Scan.marketFaction(nil, "Alliance"))
    assert.are.equal("Horde", Scan.marketFaction("Player-4378-0ABC1234", "Horde"))
  end)
end)

describe("Scan.build", function()
  it("records who requested the Scan, where and when", function()
    local scan = Scan.build(REQUEST, {}, "Kash")

    assert.are.equal(7, scan.id)
    assert.are.equal(1790000000, scan.requestedAt)
    assert.are.equal("Classic Beta PvP", scan.realm)
    assert.are.equal("Kash-Patel", scan.character)
    assert.are.equal("Alliance", scan.faction)
    assert.are.same({}, scan.listings)
    assert.are.equal("", scan.packedListings)
    assert.are.equal(0, scan.droppedRows)
  end)

  it("records when the Auction House first answered and when the rows were read", function()
    local request = {}
    for k, v in pairs(REQUEST) do
      request[k] = v
    end
    request.firstUpdateAt = 1790000005
    request.readAt = 1790000031

    local scan = Scan.build(request, {}, "Kash")

    assert.are.equal(1790000005, scan.firstUpdateAt)
    assert.are.equal(1790000031, scan.readAt)
    -- The Listings still stand as of the request, so requestedAt stays the Scan's time.
    assert.are.equal(1790000000, scan.requestedAt)
  end)

  it("packs everyone else's rows into one string, and keeps the player's own as tables", function()
    -- #144: one string per Scan parses ~50x faster in the Brain and makes the file ~4x
    -- smaller. Own rows carry the item name, which can have a comma in it, so they stay tables.
    local rows = {
      row({ count = 20, buyout = 1940, timeLeft = 4 }),
      row({ owner = "Kash" }),
      row({ link = NATURE_PROT, count = 1, buyout = 5000, timeLeft = 2 }),
    }

    local scan = Scan.build(REQUEST, rows, "Kash")

    assert.are.equal("item:2680::::::::20:1490,20,1940,4;item:9768::::::::20:1490::1:1:12743,1,5000,2",
      scan.packedListings)
    assert.are.equal(1, #scan.listings)
    assert.is_true(scan.listings[1].own)
    assert.are.equal("Spiced Wolf Meat", scan.listings[1].name)
    assert.are.equal(3, Scan.listingCount(scan))
    assert.are.equal(0, Scan.listingCount(Scan.build(REQUEST, {}, "Kash")))
  end)

  it("keeps the compact item string from the link", function()
    local scan = Scan.build(REQUEST, { row(), row({ link = NATURE_PROT }) }, "Kash")

    assert.are.equal("item:2680::::::::20:1490", others(scan)[1].itemString)
    assert.are.equal("item:9768::::::::20:1490::1:1:12743", others(scan)[2].itemString)
  end)

  it("keeps the whole-auction buyout, quantity and time-left bucket as the game gives them", function()
    -- Linen Cloth x20 @ 1940c is 97c/unit; the Brain does that division, not the Addon.
    local scan = Scan.build(REQUEST, { row({ count = 20, buyout = 1940, timeLeft = 4 }) }, "Kash")

    local listing = others(scan)[1]
    assert.are.equal(20, listing.quantity)
    assert.are.equal(1940, listing.buyout)
    assert.are.equal(4, listing.timeLeft)
  end)

  it("drops bid-only rows, since buyout is the only price", function()
    local noBuyout = row()
    noBuyout.buyout = nil -- (row() can't override with nil: pairs skips nil values)
    local rows = {
      row({ buyout = 0 }),
      noBuyout,
      row({ buyout = 280 }),
    }

    local scan = Scan.build(REQUEST, rows, "Kash")

    assert.are.equal(1, #others(scan))
    assert.are.equal(280, others(scan)[1].buyout)
    -- droppedRows is only for missing item data, not for rows with no price.
    assert.are.equal(0, scan.droppedRows)
  end)

  it("drops rows whose item data never loaded and counts them", function()
    local noLink = row()
    noLink.link = nil
    local rows = {
      noLink,
      row({ link = "" }),
      row({ buyout = 1111, hasAllInfo = false }), -- incomplete info but has a link, so it is kept
    }

    local scan = Scan.build(REQUEST, rows, "Kash")

    assert.are.equal(1, #others(scan))
    assert.are.equal(1111, others(scan)[1].buyout)
    assert.are.equal(2, scan.droppedRows)
  end)

  it("records the itemIDs of dropped rows once each, when the game gave them", function()
    -- #150: GetReplicateItemInfo's itemID is there even when the link isn't, so the Brain
    -- can leave those items out of the Observation Windows this Scan touches.
    local noID = row()
    noID.link = nil
    local rows = { dropped(2589), dropped(2589), dropped(4306), noID, row({ itemID = 2680 }) }

    local scan = Scan.build(REQUEST, rows, "Kash")

    table.sort(scan.droppedItemIDs)
    assert.are.same({ 2589, 4306 }, scan.droppedItemIDs)
    assert.are.equal(4, scan.droppedRows)
  end)

  it("flags the player's own Listings", function()
    local rows = {
      row({ owner = "Kash", ownerFullName = "Kash Patel" }), -- as spike #1 saw it
      row(),
      row({ owner = "Someone" }),
    }

    local scan = Scan.build(REQUEST, rows, "Kash")

    assert.are.equal(1, #scan.listings)
    assert.is_true(scan.listings[1].own)
    -- Everyone else's rows are packed, with no own flag.
    assert.are.equal(2, #others(scan))
  end)

  it("records the item name on the player's own Listings only", function()
    -- Sold mail names the item but carries no Item Key (#17), so own rows need the name.
    local rows = {
      row({ owner = "Kash" }),
      row({ owner = "Kash", link = NATURE_PROT }),
      row(),
      row({ owner = "Someone" }),
    }

    local scan = Scan.build(REQUEST, rows, "Kash")

    assert.are.equal("Spiced Wolf Meat", scan.listings[1].name)
    -- A suffix item keeps its suffix, as the sale mail spells it.
    assert.are.equal("Scouting Belt of Nature Protection", scan.listings[2].name)
    -- Everyone else's rows are packed with no name, so the Scan barely grows.
    assert.are.equal(2, #others(scan))
    assert.are.equal("item:2680::::::::20:1490,10,280,3;item:2680::::::::20:1490,10,280,3", scan.packedListings)
  end)

  it("records each distinct item's Vendor Price once, by itemID", function()
    local lookups = {}
    local function sellPrice(itemID)
      lookups[#lookups + 1] = itemID
      return ({ [2680] = 11, [9768] = 245 })[itemID]
    end
    local rows = { row(), row({ buyout = 300 }), row({ link = NATURE_PROT }), row() }

    local scan = Scan.build(REQUEST, rows, "Kash", sellPrice)

    -- Every random suffix shares its itemID's Vendor Price, so the key is the itemID alone.
    assert.are.same({ [2680] = 11, [9768] = 245 }, scan.vendorPrices)
    -- ~58k rows but ~4.7k distinct items per Scan: one lookup each.
    table.sort(lookups)
    assert.are.same({ 2680, 9768 }, lookups)
    assert.are.equal(0, scan.vendorPricesMissing)
  end)

  it("keeps a Vendor Price of 0 and counts items whose data hasn't loaded", function()
    local rows = { row(), row({ link = NATURE_PROT }) }
    -- 0: the vendor won't buy it. nil: GetItemInfo has nothing for it yet.
    local scan = Scan.build(REQUEST, rows, "Kash", function(itemID)
      return itemID == 2680 and 0 or nil
    end)

    assert.are.same({ [2680] = 0 }, scan.vendorPrices)
    assert.are.equal(1, scan.vendorPricesMissing)
  end)

  it("records the Item Info of each distinct armor or weapon that could be Disenchanted", function()
    -- #76: GetItemInfo's quality, itemLevel, classID and equipLoc, by itemID.
    local infos = {
      [9768] = { quality = 2, itemLevel = 18, classID = 4, equipLoc = "INVTYPE_WAIST" },
      [2680] = { quality = 1, itemLevel = 5, classID = 0, equipLoc = "" }, -- food: left out
      [4306] = { quality = 2, itemLevel = 25, classID = 7, equipLoc = "" }, -- a green trade good
    }
    local lookups = 0
    local function itemInfo(itemID)
      lookups = lookups + 1
      return infos[itemID]
    end
    local rows = {
      row({ link = NATURE_PROT }),
      row({ link = NATURE_PROT, buyout = 900 }),
      row(),
      row({ link = "|cnIQ2:|Hitem:4306::::::::20:1490:::::::::|h[Silk Cloth]|h|r" }),
      row({ link = "|cnIQ2:|Hitem:1234::::::::20:1490:::::::::|h[Not Loaded]|h|r" }),
    }

    local scan = Scan.build(REQUEST, rows, "Kash", nil, itemInfo)

    assert.are.same({
      [9768] = { itemLevel = 18, quality = 2, classID = 4, equipLoc = "INVTYPE_WAIST" },
    }, scan.itemInfo)
    assert.are.equal(4, lookups) -- once per itemID
    -- Retried on a later Scan, like a missing Vendor Price.
    assert.are.equal(1, scan.itemInfoMissing)
  end)

  it("reads an item's Item Info from GetItemInfo's returns", function()
    -- name, link, quality, itemLevel, minLevel, type, subType, stackCount, equipLoc,
    -- texture, sellPrice, classID
    assert.are.same(
      { quality = 2, itemLevel = 18, classID = 4, equipLoc = "INVTYPE_WAIST" },
      Scan.fromGetItemInfo("Belt", "link", 2, 18, 13, "Armor", "Leather", 1, "INVTYPE_WAIST", 1, 245, 4)
    )
    assert.is_nil(Scan.fromGetItemInfo()) -- not loaded yet
  end)

  it("stores no seller or bid fields", function()
    local rows = {
      row({ owner = "Kash", ownerFullName = "Kash Patel", bidAmount = 250, minBid = 200, minIncrement = 5 }),
    }

    local scan = Scan.build(REQUEST, rows, "Kash")

    local keys = {}
    for k in pairs(scan.listings[1]) do
      keys[#keys + 1] = k
    end
    table.sort(keys)
    assert.are.same({ "buyout", "itemString", "name", "own", "quantity", "timeLeft" }, keys)
  end)
end)

describe("Scan.newReread", function()
  it("re-reads only the rows of the item that just loaded, and puts them back", function()
    -- #226: an item's rows are read again the moment it loads, before the client evicts it.
    local rows = { row(), dropped(2589), dropped(4306), dropped(2589) }
    local reread = Scan.newReread(rows)
    local asked = {}

    reread:itemLoaded(2589, function(index)
      asked[#asked + 1] = index
      return LINEN
    end)
    local scan = Scan.build(REQUEST, rows, "Kash")

    assert.are.same({ 1, 3 }, asked)
    assert.are.equal(1, scan.droppedRows)
    assert.are.same({ 4306 }, scan.droppedItemIDs)
    assert.are.equal("item:2589::::::::20:1490", others(scan)[2].itemString)
  end)

  it("lists each dropped row's item once, to ask the game to load", function()
    local noID = row()
    noID.link = nil
    local rows = { dropped(2589), row({ itemID = 2680 }), dropped(4306), dropped(2589), noID }

    local itemIDs = Scan.newReread(rows):itemIDs()

    table.sort(itemIDs)
    assert.are.same({ 2589, 4306 }, itemIDs)
    assert.are.same({}, Scan.newReread({ row() }):itemIDs())
  end)

  it("says it's done once every item has reported, read or not", function()
    -- The Scan saves then, without waiting out the cap. An item that loaded but whose rows
    -- still don't read has nothing more to wait for either.
    local rows = { dropped(2589), dropped(4306), dropped(4306) }
    local reread = Scan.newReread(rows)
    local function nothing()
      return nil
    end

    assert.is_false(reread:itemLoaded(4306, nothing))
    assert.is_false(reread:itemLoaded(4306, nothing)) -- reported twice
    assert.is_false(reread:itemLoaded(9999, nothing)) -- not one we asked for
    assert.is_true(reread:itemLoaded(2589, nothing))
  end)

  it("counts the rows that came back out of all the main read dropped", function()
    -- For the "re-read N of M dropped rows" chat line. A row with no itemID can't be
    -- re-read but still counts as dropped.
    local noID = row()
    noID.link = nil
    local rows = { dropped(2589), dropped(2589), dropped(4306), noID, row() }
    local reread = Scan.newReread(rows)

    reread:itemLoaded(2589, function()
      return LINEN
    end)
    reread:itemLoaded(4306, function()
      return nil
    end)
    local back, droppedCount = reread:counts()

    assert.are.equal(2, back)
    assert.are.equal(4, droppedCount)
  end)

  it("leaves a row dropped when the link it reads now is another item's", function()
    -- The list can change during the wait (another addon's Scan), shifting the indices.
    -- A link for a different item would put one auction's item on another's price.
    local rows = { dropped(4306) }
    local reread = Scan.newReread(rows)

    reread:itemLoaded(4306, function()
      return LINEN
    end)
    local scan = Scan.build(REQUEST, rows, "Kash")

    assert.are.equal(0, (reread:counts()))
    assert.are.same({ 4306 }, scan.droppedItemIDs)
  end)
end)

