local CharacterRead = require("CharacterRead")

local WHO = {
  readAt = 1790450000,
  realm = "Classic Beta PvP",
  character = "Kash-Patel",
  faction = "Alliance",
  money = 1234567,
}

local LINEN = "|cffffffff|Hitem:2589::::::::20:1490:::::::::|h[Linen Cloth]|h|r"
local HEARTHSTONE = "|cffffffff|Hitem:6948::::::::20:1490:::::::::|h[Hearthstone]|h|r"

describe("CharacterRead.build", function()
  it("records whose Read it is, when, their faction and gold", function()
    local read = CharacterRead.build(WHO, {})

    assert.are.equal(1790450000, read.readAt)
    assert.are.equal("Classic Beta PvP", read.realm)
    assert.are.equal("Kash-Patel", read.character)
    assert.are.equal("Alliance", read.faction)
    assert.are.equal(1234567, read.money)
    assert.are.same({}, read.bags)
  end)

  it("keeps each filled slot's link, count and whether it's bound, and skips empty slots", function()
    local read = CharacterRead.build(WHO, {
      { bag = 0, slot = 1, info = { hyperlink = LINEN, stackCount = 20, isBound = false, iconFileID = 132889 } },
      { bag = 0, slot = 2 }, -- empty: GetContainerItemInfo returned nil
      { bag = 4, slot = 16, info = { hyperlink = HEARTHSTONE, stackCount = 1, isBound = true } },
    })

    assert.are.same({
      { bag = 0, slot = 1, link = LINEN, count = 20, isBound = false },
      { bag = 4, slot = 16, link = HEARTHSTONE, count = 1, isBound = true },
    }, read.bags)
  end)

  it("leaves the bank out when it wasn't opened this session", function()
    local read = CharacterRead.build(WHO, {}, nil)

    assert.is_nil(read.bank)
    assert.is_nil(read.bankReadAt)
  end)

  it("includes the bank as last read while open, shaped like the bags", function()
    local bank = {
      readAt = 1790449000,
      slots = {
        { bag = -1, slot = 3, info = { hyperlink = LINEN, stackCount = 7, isBound = false } },
        { bag = -1, slot = 4 },
      },
    }

    local read = CharacterRead.build(WHO, {}, bank)

    assert.are.equal(1790449000, read.bankReadAt)
    assert.are.same({ { bag = -1, slot = 3, link = LINEN, count = 7, isBound = false } }, read.bank)
  end)

  it("records the Vendor Price of every item in the bags and bank, by itemID", function()
    local JUNK = "|cff9d9d9d|Hitem:3300::::::::20:1490:::::::::|h[Rabbit's Foot]|h|r"
    local MONKEY = "|cff1eff00|Hitem:9768::::::::20:1490::1:1:12743:::::::|h[Scouting Trousers of the Monkey]|h|r"
    local bags = {
      { bag = 0, slot = 1, sellPrice = 10, info = { hyperlink = LINEN, stackCount = 20, isBound = false } },
      { bag = 0, slot = 2, sellPrice = 10, info = { hyperlink = LINEN, stackCount = 5, isBound = false } },
      -- 0: a vendor won't buy it. Recorded as it is; the Brain decides what it means.
      { bag = 0, slot = 3, sellPrice = 0, info = { hyperlink = HEARTHSTONE, stackCount = 1, isBound = true } },
      -- nil: the client hadn't loaded it when the bags were read.
      { bag = 0, slot = 4, info = { hyperlink = MONKEY, stackCount = 1, isBound = false } },
      { bag = 0, slot = 5 },
    }
    local bank = {
      readAt = 1790449000,
      slots = { { bag = -1, slot = 1, sellPrice = 25, info = { hyperlink = JUNK, stackCount = 3, isBound = false } } },
    }

    local read = CharacterRead.build(WHO, bags, bank)

    assert.are.same({ [2589] = 10, [6948] = 0, [3300] = 25 }, read.vendorPrices)
    assert.are.equal(1, read.vendorPricesMissing)
  end)

  it("includes the Known Recipes of each profession read this session, and the profession list", function()
    local tailoring = { readAt = 1790449500, professionID = 197, professionName = "Tailoring", recipes = {} }
    local list = {
      { professionID = 197, professionName = "Tailoring" },
      { professionID = 333, professionName = "Enchanting" },
    }

    local read = CharacterRead.build(WHO, {}, nil, { [197] = tailoring }, list)

    assert.are.same({ [197] = tailoring }, read.professions)
    assert.are.same(list, read.professionList)
  end)

  it("leaves professions out when no window was opened this session", function()
    local read = CharacterRead.build(WHO, {}, nil, {}, {})

    assert.is_nil(read.professions)
    assert.are.same({}, read.professionList)
  end)

  it("includes the Merchant Costs of every merchant visited this session", function()
    local costs = { [2320] = 10, [3371] = 4 }

    local read = CharacterRead.build(WHO, {}, nil, {}, {}, costs)

    assert.are.same(costs, read.merchantCosts)
  end)

  it("leaves Merchant Costs out when no merchant was visited this session", function()
    local read = CharacterRead.build(WHO, {}, nil, {}, {}, {})

    assert.is_nil(read.merchantCosts)
  end)
end)
