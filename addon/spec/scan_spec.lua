local Scan = require("Scan")

-- Rows as the glue layer reads them from C_AuctionHouse.GetReplicateItemInfo /
-- GetReplicateItemLink / GetReplicateItemTimeLeft. Links are real ones from the
-- beta client (spike #1).
local WOLF_MEAT = "|cnIQ1:|Hitem:2680::::::::20:1490:::::::::|h[Spiced Wolf Meat]|h|r"
local NATURE_PROT = "|cnIQ2:|Hitem:9768::::::::20:1490::1:1:12743:::::::|h[Scouting Belt of Nature Protection]|h|r"

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
    assert.are.equal(0, scan.droppedRows)
  end)

  it("keeps the compact item string from the link", function()
    local scan = Scan.build(REQUEST, { row(), row({ link = NATURE_PROT }) }, "Kash")

    assert.are.equal("item:2680::::::::20:1490", scan.listings[1].itemString)
    assert.are.equal("item:9768::::::::20:1490::1:1:12743", scan.listings[2].itemString)
  end)

  it("keeps the whole-auction buyout, quantity and time-left bucket as the game gives them", function()
    -- Linen Cloth x20 @ 1940c is 97c/unit; the Brain does that division, not the Addon.
    local scan = Scan.build(REQUEST, { row({ count = 20, buyout = 1940, timeLeft = 4 }) }, "Kash")

    local listing = scan.listings[1]
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

    assert.are.equal(1, #scan.listings)
    assert.are.equal(280, scan.listings[1].buyout)
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

    assert.are.equal(1, #scan.listings)
    assert.are.equal(1111, scan.listings[1].buyout)
    assert.are.equal(2, scan.droppedRows)
  end)

  it("flags the player's own Listings", function()
    local rows = {
      row({ owner = "Kash", ownerFullName = "Kash Patel" }), -- as spike #1 saw it
      row(),
      row({ owner = "Someone" }),
    }

    local scan = Scan.build(REQUEST, rows, "Kash")

    assert.is_true(scan.listings[1].own)
    -- Left out rather than false: it saves a field on ~58k rows per Scan.
    assert.is_nil(scan.listings[2].own)
    assert.is_nil(scan.listings[3].own)
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
    assert.are.same({ "buyout", "itemString", "own", "quantity", "timeLeft" }, keys)
  end)
end)
