local CancelButton = require("CancelButton")

describe("CancelButton.undercut", function()
  it("is the lowest other price when another player's Listing is cheaper, even by 1c", function()
    local results = { { unitPrice = 449, quantity = 5, ownUnits = 0 } }

    assert.are.equal(449, CancelButton.undercut({ unitPrice = 450 }, results))
  end)

  it("counts another player at exactly the same price, since the newest sells first", function()
    local results = { { unitPrice = 450, quantity = 8, ownUnits = 3 } } -- 5 of them aren't ours

    assert.are.equal(450, CancelButton.undercut({ unitPrice = 450 }, results))
  end)

  it("never counts the player's own units", function()
    local results = {
      { unitPrice = 400, quantity = 2, ownUnits = 2 }, -- all own, cheaper
      { unitPrice = 450, quantity = 20, ownUnits = 20 }, -- the Listing itself
    }

    assert.is_nil(CancelButton.undercut({ unitPrice = 450 }, results))
  end)

  it("is nil when every other Listing is dearer, or there are none", function()
    assert.is_nil(CancelButton.undercut({ unitPrice = 450 }, { { unitPrice = 451, quantity = 1, ownUnits = 0 } }))
    assert.is_nil(CancelButton.undercut({ unitPrice = 450 }, {}))
  end)
end)

-- The logged-in Character's active Listings, as the glue reads them from the owned list.
local HIDE = { auctionID = 11, key = "hide", name = "Medium Hide", unitPrice = 450, quantity = 20 }
local SWORD = { auctionID = 12, key = "sword", name = "Training Sword", unitPrice = 5000, quantity = 1 }
local CLOTH = { auctionID = 13, key = "cloth", name = "Wool Cloth", unitPrice = 100, quantity = 10 }

local function other(unitPrice)
  return { { unitPrice = unitPrice, quantity = 1, ownUnits = 0 } }
end

describe("CancelButton.state", function()
  it("is disabled while the Auction House hasn't listed the Character's own auctions yet", function()
    local state = CancelButton.state(nil, {}, {})

    assert.is_false(state.enabled)
    assert.are.equal("Checking...", state.label)
    assert.is_nil(state.call)
  end)

  it("is disabled and counts the Item Keys checked while searches are still out", function()
    local listings = { HIDE, SWORD, CLOTH }
    local checks = { hide = other(420) } -- sword and cloth not searched yet

    local state = CancelButton.state(listings, checks, {})

    assert.is_false(state.enabled)
    assert.are.equal("Checking 1/3...", state.label)
    assert.is_nil(state.call)
  end)

  it("is disabled and reads No undercut Listings when every Listing is still cheapest", function()
    local checks = { hide = other(460), sword = {} } -- dearer, and no other Listing

    for _, listings in ipairs({ { HIDE, SWORD }, {} }) do
      local state = CancelButton.state(listings, checks, {})

      assert.is_false(state.enabled)
      assert.are.equal("No undercut Listings", state.label)
      assert.is_nil(state.call)
    end
  end)

  it("counts the Undercut Listings and cancels the one with the most gold tied up first", function()
    -- Hide ties up 20 x 450 = 9000, the sword 5000, cloth 1000 (cloth isn't Undercut).
    local listings = { SWORD, CLOTH, HIDE }
    local checks = { hide = other(420), sword = other(5000), cloth = other(150) }

    local state = CancelButton.state(listings, checks, {})

    assert.is_true(state.enabled)
    assert.are.equal("Cancel undercut (2)", state.label)
    assert.are.equal("Medium Hide ×20 at 4s 50c, lowest other 4s 20c", state.tip)
    assert.are.same({ auctionID = 11 }, state.call)
  end)

  it("makes no call while the last cancel waits for the Auction House to confirm it", function()
    local state = CancelButton.state({ HIDE }, { hide = other(420) }, { pending = true })

    assert.is_false(state.enabled)
    assert.are.equal("Cancelling...", state.label)
    assert.is_nil(state.call)
  end)

  describe("CancelButton.outcome", function()
    local target = { listing = HIDE, lowest = 420 }

    it("is cancelled once the Listing is off the Character's owned list", function()
      assert.are.equal("cancelled", CancelButton.outcome({ SWORD }, target, nil))
      assert.are.equal("cancelled", CancelButton.outcome({ SWORD }, target, "an unrelated error"))
    end)

    it("waits while the Listing is still up and nothing went wrong", function()
      assert.is_nil(CancelButton.outcome({ HIDE, SWORD }, target, nil))
    end)

    it("failed when the Listing is still up after an error", function()
      assert.are.equal("failed", CancelButton.outcome({ HIDE }, target, "Item not found"))
    end)
  end)

  describe("after a cancel", function()
    -- Hide was cancelled; the sword and cloth were searched before it was.
    local listings = { SWORD, CLOTH }
    local checks = { sword = other(4000), cloth = other(90) }

    it("waits while the next target's Item Key is searched again", function()
      local state = CancelButton.state(listings, checks, { fresh = {} })

      assert.is_false(state.enabled)
      assert.are.equal("Checking...", state.label)
      assert.are.equal("sword", state.recheck)
      assert.is_nil(state.call)
    end)

    it("cancels the next target once its search is fresh", function()
      local state = CancelButton.state(listings, checks, { fresh = { sword = true } })

      assert.is_true(state.enabled)
      assert.are.equal("Cancel undercut (2)", state.label)
      assert.are.same({ auctionID = 12 }, state.call)
    end)

    it("drops a target no longer Undercut and checks the one after it", function()
      local rechecked = { sword = other(6000), cloth = other(90) } -- the cheaper sword sold

      local state = CancelButton.state(listings, rechecked, { fresh = { sword = true } })

      assert.are.equal("cloth", state.recheck)
    end)
  end)
end)
