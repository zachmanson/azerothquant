local SearchButton = require("SearchButton")

-- The AH is open, the search throttle is ready, none of the item is in this Character's
-- bags and the client has the item loaded. Each test overrides what it's about.
local function ctx(overrides)
  local out = { section = "Shopping List", ahOpen = true, throttled = false, bagUnits = 0, loaded = true }
  for k, v in pairs(overrides or {}) do
    out[k] = v
  end
  return out
end

describe("SearchButton.liveLine", function()
  it("is the cheapest live price, how many are at it, and how it sits against the buy price", function()
    -- The Wool Cloth probe on #39: 37 results, cheapest 59c x73.
    local results = {
      { unitPrice = 59, quantity = 73, ownUnits = 0 },
      { unitPrice = 64, quantity = 200, ownUnits = 0 },
    }

    assert.are.equal("Live: 59c x73, under your 62c buy", SearchButton.liveLine(results, 62))
  end)

  it("says when the cheapest is above or at the buy price", function()
    assert.are.equal(
      "Live: 71c x12, above your 62c buy",
      SearchButton.liveLine({ { unitPrice = 71, quantity = 12, ownUnits = 0 } }, 62)
    )
    assert.are.equal(
      "Live: 62c x4, at your 62c buy",
      SearchButton.liveLine({ { unitPrice = 62, quantity = 4, ownUnits = 0 } }, 62)
    )
  end)

  it("says when nothing is listed", function()
    assert.are.equal("Live: none listed", SearchButton.liveLine({}, 62))
  end)

  it("counts every other player's unit at the cheapest price, in any order, and skips the player's own", function()
    -- Gear: one unit per Listing, so two at 4s are x2.
    local results = {
      { unitPrice = 500, quantity = 1, ownUnits = 0 },
      { unitPrice = 400, quantity = 1, ownUnits = 0 },
      { unitPrice = 350, quantity = 1, ownUnits = 1 }, -- the player's own: not to buy
      { unitPrice = 400, quantity = 1, ownUnits = 0 },
    }

    assert.are.equal("Live: 4s x2, under your 4s 50c buy", SearchButton.liveLine(results, 450))
    assert.are.equal("Live: none listed", SearchButton.liveLine({ results[3] }, 450))
  end)

  it("compares against the buy price in whole copper, the most that can be paid", function()
    assert.are.equal(
      "Live: 61c x5, at your 61c buy",
      SearchButton.liveLine({ { unitPrice = 61, quantity = 5, ownUnits = 0 } }, 61.6)
    )
  end)
end)

describe("SearchButton.state", function()
  it("searches a Shopping List Flip with its full Item Key", function()
    local row = { record = { action = "Vendor", itemKey = "9768:6362", quantity = 3, price = 62 } }

    local state = SearchButton.state(row, ctx())

    assert.is_true(state.enabled)
    assert.are.equal("Search", state.label)
    assert.are.same({ itemKey = "9768:6362" }, state.call)
  end)

  it("searches Prediction buys and single-item Buy Unders too", function()
    local prediction = { record = { itemKey = "2589", quantity = 20, price = 62, prediction = "Patch 1.2" } }
    local buyUnder = { record = { itemKey = "2589", way = "Sell", price = 62 } }

    assert.are.equal("Search", SearchButton.state(prediction, ctx({ section = "Predictions" })).label)
    assert.are.equal("Search", SearchButton.state(buyUnder, ctx({ section = "Buy Under" })).label)
  end)

  it("leaves the slot to Post for rows that aren't one item to buy", function()
    local holding = { record = { action = "Sell", itemKey = "2589", quantity = 5, price = 450 } }
    local craft = { record = { action = "Craft", itemKey = "2580", quantity = 1, price = 900 } }
    local group = { record = { group = { quality = 2, class = "armor", minLevel = 5, maxLevel = 15 }, way = "Disenchant", price = 300 } }

    -- A Prediction's line with no buy (#207) has no price to search against.
    local noBuy = { record = { itemKey = "2447", held = 0, reason = "would lose 37%" } }

    assert.is_nil(SearchButton.state(nil, ctx()))
    assert.is_nil(SearchButton.state(noBuy, ctx({ section = "Predictions" })))
    assert.is_nil(SearchButton.state(holding, ctx({ section = "Holdings" })))
    assert.is_nil(SearchButton.state(craft, ctx({ section = "Flips to Craft" })))
    assert.is_nil(SearchButton.state(group, ctx({ section = "Buy Under" })))
  end)

  it("leaves a Flip to Sell to Post once some of it is in this Character's bags", function()
    local flip = { record = { action = "Sell", itemKey = "2589", quantity = 5, price = 300, postAt = 450 } }

    assert.are.equal("Search", SearchButton.state(flip, ctx({ bagUnits = 0 })).label)
    assert.is_nil(SearchButton.state(flip, ctx({ bagUnits = 2 })))
  end)

  it("waits, disabled, for the AH, its search throttle, and the item to load", function()
    local row = { record = { action = "Vendor", itemKey = "2589", quantity = 3, price = 62 } }
    local cases = {
      { ctx({ ahOpen = false }), "Open the Auction House to search." },
      { ctx({ throttled = true }), "Waiting for the Auction House to take another search." },
      { ctx({ loaded = false }), "Loading the item: try again in a moment." },
    }

    for _, case in ipairs(cases) do
      local state = SearchButton.state(row, case[1])
      assert.is_false(state.enabled)
      assert.are.equal("Search", state.label)
      assert.are.equal(case[2], state.reason)
      assert.is_nil(state.call)
    end
  end)
end)
