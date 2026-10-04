local PostButton = require("PostButton")

-- The AH is open, this Character's bags hold 10 units, nothing is posted or waiting, the
-- item is a commodity and the Brain charged Deposits for 24h posts. Each test overrides
-- what it's about.
local function ctx(overrides)
  local out = { ahOpen = true, bagUnits = 10, posted = 0, pending = false, commodity = true, durationHours = 24 }
  for k, v in pairs(overrides or {}) do
    out[k] = v
  end
  return out
end

describe("PostButton.lowestOther", function()
  it("is the lowest unit price among Listings that aren't all the player's own", function()
    local results = {
      { unitPrice = 400, quantity = 3, ownUnits = 3 }, -- all own: posting under yourself isn't an undercut
      { unitPrice = 430, quantity = 5, ownUnits = 2 }, -- some other player's units at this price
      { unitPrice = 420, quantity = 1, ownUnits = 0 },
      { unitPrice = 500, quantity = 9, ownUnits = 0 },
    }

    assert.are.equal(420, PostButton.lowestOther(results))
  end)

  it("is nil with no results, or only the player's own", function()
    assert.is_nil(PostButton.lowestOther({}))
    assert.is_nil(PostButton.lowestOther({ { unitPrice = 400, quantity = 3, ownUnits = 3 } }))
  end)
end)

describe("PostButton.state", function()
  it("is disabled with no row selected", function()
    local state = PostButton.state(nil, ctx())

    assert.is_false(state.enabled)
    assert.are.equal("Post", state.label)
    assert.are.equal("Select a Sell row to post it.", state.reason)
    assert.is_nil(state.call)
  end)

  it("posts a Holdings Sell row's units in one commodity post at its Price, rounded to whole copper", function()
    local row = { record = { action = "Sell", itemKey = "2589", quantity = 5, price = 449.6 } }

    local state = PostButton.state(row, ctx())

    assert.is_true(state.enabled)
    assert.are.equal("Post 5 @ 4s 50c", state.label)
    assert.are.same({ kind = "commodity", quantity = 5, price = 450, duration = 3 }, state.call)
  end)

  it("posts a Flip to Sell at its Post at, not the Max price it was bought under", function()
    local row = { record = { action = "Sell", itemKey = "2589", quantity = 5, price = 300, postAt = 450 } }

    assert.are.equal(450, PostButton.state(row, ctx()).call.price)
  end)

  it("posts no other kind of row", function()
    local records = {
      { action = "Vendor", itemKey = "2589", quantity = 5, price = 10 },
      { action = "Craft", itemKey = "2589", quantity = 5, price = 300, postAt = 450 },
      { action = "Disenchant", itemKey = "2589", quantity = 1 },
      { action = "Hold", itemKey = "2589", quantity = 5, price = 300 },
      { way = "Sell", itemKey = "2589", price = 300 }, -- a Buy Under
    }
    for _, record in ipairs(records) do
      local state = PostButton.state({ record = record }, ctx())
      assert.is_false(state.enabled)
      assert.are.equal("Select a Sell row to post it.", state.reason)
    end
  end)

  it("posts gear one unit per click, at its Post at as the buyout", function()
    local row = { record = { action = "Sell", itemKey = "2488:0:0:0:0", quantity = 3, price = 1247 } }

    local state = PostButton.state(row, ctx({ commodity = false, bagUnits = 3 }))

    assert.are.equal("Post 1 @ 12s 47c", state.label)
    assert.are.same({ kind = "item", quantity = 1, price = 1247, duration = 3 }, state.call)
  end)

  it("posts only the units not yet posted, and no more than the bags hold", function()
    local row = { record = { action = "Sell", itemKey = "2589", quantity = 20, price = 450 } }

    assert.are.equal(12, PostButton.state(row, ctx({ posted = 8, bagUnits = 30 })).call.quantity)
    assert.are.equal(7, PostButton.state(row, ctx({ posted = 8, bagUnits = 7 })).call.quantity)
  end)

  it("says Posted once every unit of the row is posted", function()
    local row = { record = { action = "Sell", itemKey = "2589", quantity = 5, price = 450 } }

    local state = PostButton.state(row, ctx({ posted = 5 }))

    assert.is_false(state.enabled)
    assert.are.equal("Posted", state.label)
    assert.is_nil(state.call)
  end)

  it("says when the live lowest ask is below Post at, and still posts", function()
    local row = { record = { action = "Sell", itemKey = "2589", quantity = 5, price = 450 } }

    local state = PostButton.state(row, ctx({ lowest = 420 }))

    assert.is_true(state.enabled)
    assert.are.equal("Lowest is now 4s 20c, below 4s 50c", state.undercut)
  end)

  it("says nothing when the lowest ask is at or over Post at, or unknown", function()
    local row = { record = { action = "Sell", itemKey = "2589", quantity = 5, price = 450 } }

    assert.is_nil(PostButton.state(row, ctx({ lowest = 450 })).undercut)
    assert.is_nil(PostButton.state(row, ctx()).undercut)
  end)

  describe("is disabled with the reason in its tooltip", function()
    local row = { record = { action = "Sell", itemKey = "2589", quantity = 5, price = 450 } }

    local function disabled(overrides)
      local state = PostButton.state(row, ctx(overrides))
      assert.is_false(state.enabled)
      assert.is_nil(state.call)
      return state
    end

    it("while the Auction House is closed", function()
      assert.are.equal("Open the Auction House to post.", disabled({ ahOpen = false }).reason)
    end)

    it("while this Character's bags hold none of it", function()
      assert.are.equal("None in this Character's bags (bound units can't be posted).", disabled({ bagUnits = 0 }).reason)
    end)

    it("until the client has loaded the item, so whether it's a commodity is known", function()
      local unknown = ctx()
      unknown.commodity = nil

      local state = PostButton.state(row, unknown)

      assert.is_false(state.enabled)
      assert.are.equal("Loading the item: try again in a moment.", state.reason)
    end)

    it("while a post waits for the Auction House to confirm it", function()
      local state = disabled({ pending = true })

      assert.are.equal("Posting...", state.label)
      assert.are.equal("Waiting for the Auction House to confirm the post.", state.reason)
    end)

    it("when the Brain's post duration isn't one the Auction House offers", function()
      assert.are.equal("Post duration 12h isn't one the Auction House offers.", disabled({ durationHours = 12 }).reason)
    end)

    it("when Recommendations.lua predates the post duration", function()
      local old = ctx()
      old.durationHours = nil

      local state = PostButton.state(row, old)

      assert.is_false(state.enabled)
      assert.are.equal("No post duration from the Brain yet: Reload after its next import.", state.reason)
    end)
  end)
end)
