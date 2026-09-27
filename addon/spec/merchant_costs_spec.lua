local MerchantCosts = require("MerchantCosts")

-- One merchant item as Merchant.lua reads it: the itemID, the price of one purchase in
-- copper, how many units one purchase gives, how many the merchant has left (-1 for
-- unlimited) and whether it costs anything besides gold.
local function sold(itemID, price, fields)
  local item = { itemID = itemID, price = price, stackCount = 1, numAvailable = -1, hasExtendedCost = false }
  for k, v in pairs(fields or {}) do
    item[k] = v
  end
  return item
end

local COARSE_THREAD = 2320
local EMPTY_VIAL = 3371

describe("MerchantCosts.read", function()
  it("records what one unit costs, dividing by how many one purchase gives", function()
    local costs = MerchantCosts.read({
      sold(COARSE_THREAD, 10),
      sold(EMPTY_VIAL, 20, { stackCount = 5 }),
    }, {})

    assert.are.same({ [COARSE_THREAD] = 10, [EMPTY_VIAL] = 4 }, costs)
  end)

  it("leaves out items in limited stock and items that cost more than gold", function()
    local PATTERN = 6272 -- a recipe the merchant has one of
    local HONOR_CLOAK = 18427 -- bought with gold and honor

    local costs = MerchantCosts.read({
      sold(COARSE_THREAD, 10),
      sold(PATTERN, 1200, { numAvailable = 1 }),
      sold(HONOR_CLOAK, 5000, { hasExtendedCost = true }),
    }, {})

    assert.are.same({ [COARSE_THREAD] = 10 }, costs)
  end)

  it("adds each merchant visited to the session's costs, keeping the lowest for an item", function()
    local FINE_THREAD = 2321
    local session = MerchantCosts.read({ sold(COARSE_THREAD, 10), sold(FINE_THREAD, 100) }, {})
    -- A second merchant, where this Character has a reputation discount on fine thread.
    MerchantCosts.read({ sold(COARSE_THREAD, 12), sold(FINE_THREAD, 90), sold(EMPTY_VIAL, 20) }, session)
    -- Back at the first, which hasn't changed.
    local costs = MerchantCosts.read({ sold(COARSE_THREAD, 10), sold(FINE_THREAD, 100) }, session)

    assert.are.same({ [COARSE_THREAD] = 10, [FINE_THREAD] = 90, [EMPTY_VIAL] = 20 }, costs)
  end)
end)
