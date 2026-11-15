local WritButton = require("WritButton")

local SEALED = { item = "item:262889", count = 5 }

-- A writ in the bags, gear, searched with one other player's Listing at 1000.
local function writ(overrides)
  local out = {
    key = "264087",
    name = "Craftsman's Writ: Fire Goggles",
    units = 1,
    commodity = false,
    results = { { unitPrice = 1000, quantity = 1, ownUnits = 0 } },
  }
  for k, v in pairs(overrides or {}) do
    out[k] = v
  end
  return out
end

-- The AH is open, nothing waits, there's room, Sealed Writs in the bags and no writ yet.
local function ctx(overrides)
  local out = { ahOpen = true, pending = false, freeSlots = 4, durationHours = 24, sealed = SEALED, writs = {} }
  for k, v in pairs(overrides or {}) do
    out[k] = v
  end
  return out
end

describe("WritButton.kind", function()
  it("knows a Craftsman's Writ and each Sealed Writ by name", function()
    assert.are.equal("writ", WritButton.kind("Craftsman's Writ: Greater Adept's Robe"))
    assert.are.equal("sealed", WritButton.kind("Sealed Journeyman's Writ"))
    assert.are.equal("sealed", WritButton.kind("Sealed Expert's Writ"))
    assert.are.equal("sealed", WritButton.kind("Sealed Artisan's Writ"))
  end)

  it("is nil for anything else", function()
    assert.is_nil(WritButton.kind("Seahorn's Sealed Letter"))
    assert.is_nil(WritButton.kind("Linen Cloth"))
    assert.is_nil(WritButton.kind(nil))
  end)
end)

describe("WritButton.state", function()
  it("hides away from the AH, or with no writ of either kind in the bags", function()
    assert.is_false(WritButton.state(ctx({ ahOpen = false })).shown)
    assert.is_false(WritButton.state(ctx({ sealed = false })).shown)
  end)

  it("opens a Sealed Writ when no writ is in the bags", function()
    local state = WritButton.state(ctx())

    assert.is_true(state.enabled)
    assert.are.equal("item:262889", state.open)
    assert.is_nil(state.post)
    assert.are.equal("Open writ (5)", state.label)
  end)

  it("posts a priced writ 1c under the lowest other Listing, and opens the next in the same click", function()
    local state = WritButton.state(ctx({ writs = { writ() } }))

    assert.are.same(
      { key = "264087", name = "Craftsman's Writ: Fire Goggles", kind = "item", quantity = 1, price = 999, duration = 3 },
      state.post
    )
    assert.are.equal("item:262889", state.open)
    assert.is_true(state.enabled)
  end)

  it("ignores the player's own Listings when pricing", function()
    local results = {
      { unitPrice = 500, quantity = 1, ownUnits = 1 },
      { unitPrice = 800, quantity = 1, ownUnits = 0 },
    }

    assert.are.equal(799, WritButton.state(ctx({ writs = { writ({ results = results }) } })).post.price)
  end)

  it("posts a commodity writ's whole stack in one Listing", function()
    local post = WritButton.state(ctx({ writs = { writ({ commodity = true, units = 3 }) } })).post

    assert.are.equal("commodity", post.kind)
    assert.are.equal(3, post.quantity)
  end)

  it("uses the Brain's post length", function()
    assert.are.equal(2, WritButton.state(ctx({ durationHours = 8, writs = { writ() } })).post.duration)
  end)

  it("leaves a writ nobody else lists in the bags and opens the next", function()
    local lonely = writ({ results = { { unitPrice = 500, quantity = 1, ownUnits = 1 } } })
    local state = WritButton.state(ctx({ writs = { lonely } }))

    assert.is_nil(state.post)
    assert.are.equal("item:262889", state.open)
    assert.is_not_nil(state.tip:find("1 writ%(s%) left in your bags"))
  end)

  it("asks for a search of an unsearched writ and opens nothing until it's priced", function()
    local state = WritButton.state(ctx({ writs = { writ({ results = false }) } }))

    assert.are.equal("264087", state.search)
    assert.is_nil(state.open)
    assert.is_false(state.enabled)
    assert.are.equal("Searching...", state.label)
  end)

  it("posts a priced writ while another is searched, without opening more", function()
    local state = WritButton.state(ctx({ writs = { writ({ key = "1", results = false }), writ({ key = "2" }) } }))

    assert.are.equal("2", state.post.key)
    assert.are.equal("1", state.search)
    assert.is_nil(state.open)
  end)

  it("waits for an item the client hasn't loaded", function()
    local loading = writ()
    loading.commodity = nil
    local state = WritButton.state(ctx({ writs = { loading } }))

    assert.is_nil(state.post)
    assert.is_nil(state.open)
    assert.is_false(state.enabled)
  end)

  it("does nothing while a post waits for the AH", function()
    local state = WritButton.state(ctx({ pending = true, writs = { writ() } }))

    assert.is_false(state.enabled)
    assert.is_nil(state.post)
    assert.is_nil(state.open)
  end)

  it("posts without opening when the bags are full", function()
    local state = WritButton.state(ctx({ freeSlots = 0, writs = { writ() } }))

    assert.is_not_nil(state.post)
    assert.is_nil(state.open)
  end)

  it("says the bags are full when there's only a Sealed Writ to open", function()
    local state = WritButton.state(ctx({ freeSlots = 0 }))

    assert.is_false(state.enabled)
    assert.are.equal("Bags full", state.label)
  end)

  it("is done once only writs nobody else lists are left", function()
    local lonely = writ({ results = {} })
    local state = WritButton.state(ctx({ sealed = false, writs = { lonely } }))

    assert.is_true(state.shown)
    assert.is_false(state.enabled)
    assert.are.equal("No writs", state.label)
  end)
end)
