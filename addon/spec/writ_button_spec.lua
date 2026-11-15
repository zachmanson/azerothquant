local WritButton = require("WritButton")

local SEALED = { item = "item:262889", count = 5 }

-- The AH is open, there's room and Sealed Writs are in the bags.
local function ctx(overrides)
  local out = { ahOpen = true, freeSlots = 4, sealed = SEALED }
  for k, v in pairs(overrides or {}) do
    out[k] = v
  end
  return out
end

describe("WritButton.isSealed", function()
  it("knows each Sealed Writ by name", function()
    assert.is_true(WritButton.isSealed("Sealed Journeyman's Writ"))
    assert.is_true(WritButton.isSealed("Sealed Expert's Writ"))
    assert.is_true(WritButton.isSealed("Sealed Artisan's Writ"))
  end)

  it("is false for anything else, the writs they give included", function()
    assert.is_false(WritButton.isSealed("Craftsman's Writ: Fire Goggles"))
    assert.is_false(WritButton.isSealed("Seahorn's Sealed Letter"))
    assert.is_false(WritButton.isSealed(nil))
  end)
end)

describe("WritButton.state", function()
  it("hides away from the AH, or with no Sealed Writ in the bags", function()
    assert.is_false(WritButton.state(ctx({ ahOpen = false })).shown)
    assert.is_false(WritButton.state(ctx({ sealed = false })).shown)
  end)

  it("opens the next Sealed Writ, counting what's left", function()
    local state = WritButton.state(ctx())

    assert.is_true(state.enabled)
    assert.are.equal("item:262889", state.open)
    assert.are.equal("Open writ (5)", state.label)
  end)

  it("says the bags are full instead of opening", function()
    local state = WritButton.state(ctx({ freeSlots = 0 }))

    assert.is_true(state.shown)
    assert.is_false(state.enabled)
    assert.is_nil(state.open)
    assert.are.equal("Bags full", state.label)
  end)
end)
