local ContainerIds = require("ContainerIds")

-- The client constants as an old client defines them: no Reagent Bag.
local OLD_CLIENT = { BACKPACK_CONTAINER = 0, NUM_BAG_SLOTS = 4, BANK_CONTAINER = -1, NUM_BANKBAGSLOTS = 6 }

-- As a client with a Reagent Bag slot defines them (container 5; bank bags 6-12).
local REAGENT_BAG_CLIENT = {
  BACKPACK_CONTAINER = 0,
  NUM_BAG_SLOTS = 4,
  REAGENTBAG_CONTAINER = 5,
  NUM_REAGENTBAG_SLOTS = 1,
  NUM_TOTAL_EQUIPPED_BAG_SLOTS = 5,
  BANK_CONTAINER = -1,
  NUM_BANKBAGSLOTS = 7,
}

describe("ContainerIds", function()
  it("reads the backpack and the four bag slots on a client with no Reagent Bag", function()
    assert.are.same({ 0, 1, 2, 3, 4 }, ContainerIds.bags(OLD_CLIENT))
  end)

  it("reads the Reagent Bag with the bags, since reagents land there by themselves", function()
    assert.are.same({ 0, 1, 2, 3, 4, 5 }, ContainerIds.bags(REAGENT_BAG_CLIENT))
  end)

  it("reads the main bank and the bank bags after the bag slots on a client with no Reagent Bag", function()
    assert.are.same({ -1, 5, 6, 7, 8, 9, 10 }, ContainerIds.bank(OLD_CLIENT))
  end)

  it("starts the bank bags after the Reagent Bag, so it isn't read as a bank bag", function()
    assert.are.same({ -1, 6, 7, 8, 9, 10, 11, 12 }, ContainerIds.bank(REAGENT_BAG_CLIENT))
  end)

  it("starts the bank bags after the Reagent Bag even when the client doesn't count it", function()
    local client = { REAGENTBAG_CONTAINER = 5, NUM_REAGENTBAG_SLOTS = 1, NUM_BANKBAGSLOTS = 7 }
    assert.are.same({ -1, 6, 7, 8, 9, 10, 11, 12 }, ContainerIds.bank(client))
  end)
end)
