local DisenchantCapture = require("DisenchantCapture")

local GREEN = "|cff1eff00|Hitem:9999::::::::20:1490:::::::::|h[Green Chest]|h|r"
local LINEN = "|cffffffff|Hitem:2589::::::::20:1490:::::::::|h[Linen Cloth]|h|r"
local DUST = "|cffffffff|Hitem:10940::::::::20:1490:::::::::|h[Strange Dust]|h|r"
local ESSENCE = "|cff1eff00|Hitem:10938::::::::20:1490:::::::::|h[Lesser Magic Essence]|h|r"

local CHEST = { quality = 2, itemLevel = 18, classID = 4, equipLoc = "INVTYPE_CHEST" }
local CLOTH = { quality = 1, itemLevel = 5, classID = 7, equipLoc = "" }

-- One bag slot as Character.lua reads it; slot(n) alone is an empty one.
local function slot(n, link, count, itemInfo)
  return { bag = 0, slot = n, info = link and { hyperlink = link, stackCount = count }, itemInfo = itemInfo }
end

describe("DisenchantCapture", function()
  it("records the mats looted and the one Disenchantable item that left the bags", function()
    local capture = DisenchantCapture.new()

    capture:castStarted({ slot(1, GREEN, 1, CHEST), slot(2, LINEN, 20, CLOTH) })
    capture:castSucceeded()
    capture:lootReady(
      { { link = DUST, quantity = 2 }, { link = ESSENCE, quantity = 1 } },
      { slot(1), slot(2, LINEN, 20, CLOTH) },
      1790450000
    )

    assert.are.same({
      {
        itemID = 9999,
        itemLevel = 18,
        quality = 2,
        classID = 4,
        mats = { [10940] = 2, [10938] = 1 },
        at = 1790450000,
      },
    }, capture.results)
  end)

  it("ignores loot that no Disenchant came before, and a cast that never finished", function()
    local capture = DisenchantCapture.new()
    local bags = { slot(1, GREEN, 1, CHEST) }

    capture:lootReady({ { link = LINEN, quantity = 3 } }, bags, 1790450000) -- a mob's loot
    capture:castStarted(bags) -- interrupted: no castSucceeded
    capture:lootReady({ { link = LINEN, quantity = 3 } }, bags, 1790450010)

    assert.are.same({}, capture.results)
  end)

  it("records one Result per Disenchant, however often its loot window says it's ready", function()
    local capture = DisenchantCapture.new()

    capture:castStarted({ slot(1, GREEN, 1, CHEST) })
    capture:castSucceeded()
    capture:lootReady({ { link = DUST, quantity = 2 } }, { slot(1) }, 1790450000)
    capture:lootReady({ { link = DUST, quantity = 2 } }, { slot(1) }, 1790450001)

    assert.are.equal(1, #capture.results)
  end)

  it("waits for a later bag read when the item hadn't left the bags by the loot (#85 probe)", function()
    local capture = DisenchantCapture.new()
    local before = { slot(1, GREEN, 1, CHEST) }

    capture:castStarted(before)
    capture:castSucceeded()
    capture:lootReady({ { link = DUST, quantity = 2 } }, before, 1790450000)
    assert.are.same({}, capture.results)

    capture:bagsRead({ slot(1, DUST, 2, CLOTH) }, 1790450001)

    assert.are.same({
      {
        itemID = 9999,
        itemLevel = 18,
        quality = 2,
        classID = 4,
        mats = { [10940] = 2 },
        at = 1790450000,
      },
    }, capture.results)
  end)

  it("records the group only, with no itemID, when alike items left the bags together", function()
    -- Say the player sold another green to a vendor while the Disenchant cast.
    local OTHER = "|cff1eff00|Hitem:8888::::::::20:1490:::::::::|h[Green Robe]|h|r"
    local robe = { quality = 2, itemLevel = 18, classID = 4, equipLoc = "INVTYPE_ROBE" }
    local capture = DisenchantCapture.new()

    capture:castStarted({ slot(1, GREEN, 1, CHEST), slot(2, OTHER, 1, robe) })
    capture:castSucceeded()
    capture:lootReady({ { link = DUST, quantity = 2 } }, { slot(1), slot(2) }, 1790450000)

    assert.are.same({
      { itemLevel = 18, quality = 2, classID = 4, mats = { [10940] = 2 }, at = 1790450000 },
    }, capture.results)
  end)

  it("records the mats alone when unalike items left the bags together", function()
    local OTHER = "|cff0070dd|Hitem:8888::::::::20:1490:::::::::|h[Blue Sword]|h|r"
    local sword = { quality = 3, itemLevel = 30, classID = 2, equipLoc = "INVTYPE_WEAPON" }
    local capture = DisenchantCapture.new()

    capture:castStarted({ slot(1, GREEN, 1, CHEST), slot(2, OTHER, 1, sword) })
    capture:castSucceeded()
    capture:lootReady({ { link = DUST, quantity = 2 } }, { slot(1), slot(2) }, 1790450000)

    assert.are.same({ { mats = { [10940] = 2 }, at = 1790450000 } }, capture.results)
  end)

  it("records the mats alone when the item never left the bags by the next cast or logout", function()
    local capture = DisenchantCapture.new()
    local bags = { slot(1, GREEN, 1, CHEST) }

    capture:castStarted(bags)
    capture:castSucceeded()
    capture:lootReady({ { link = DUST, quantity = 2 } }, bags, 1790450000)
    capture:castStarted(bags)
    capture:castSucceeded()
    capture:lootReady({ { link = DUST, quantity = 1 } }, bags, 1790450010)
    capture:flush() -- at logout

    assert.are.same({
      { mats = { [10940] = 2 }, at = 1790450000 },
      { mats = { [10940] = 1 }, at = 1790450010 },
    }, capture.results)
  end)

  it("stops waiting for the item after a few seconds, so a later sale isn't taken for it", function()
    local capture = DisenchantCapture.new()
    local before = { slot(1, GREEN, 1, CHEST) }

    capture:castStarted(before)
    capture:castSucceeded()
    capture:lootReady({ { link = DUST, quantity = 2 } }, before, 1790450000)
    capture:bagsRead({ slot(1) }, 1790450060) -- a minute on: the player vendored the green

    assert.are.same({ { mats = { [10940] = 2 }, at = 1790450000 } }, capture.results)
  end)
end)
