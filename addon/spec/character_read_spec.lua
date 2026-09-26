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
end)
