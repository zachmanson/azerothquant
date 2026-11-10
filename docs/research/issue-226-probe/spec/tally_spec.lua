local Tally = require("Tally")

-- One dropped row as the probe records it: whether GetItemInfo knew the item and what
-- GetReplicateItemInfo's 18th return (hasAllInfo) said at the main read, and the first
-- re-read that brought its link back ("itemLoad", "2s", "5s", "10s", "30s"), or nil.
local function dropped(fields)
  local r = { itemID = 2589, infoKnown = true, hasAllInfo = false }
  for k, v in pairs(fields or {}) do
    r[k] = v
  end
  return r
end

describe("Tally.count", function()
  it("counts each dropped row under when its link came back", function()
    local t = Tally.count({
      dropped({ firstRead = "2s" }),
      dropped({ firstRead = "2s" }),
      dropped({ firstRead = "itemLoad" }),
      dropped({ firstRead = nil }),
    })
    assert.are.equal(4, t.rows)
    assert.are.same({ itemLoad = 1, ["2s"] = 2, never = 1 }, t.firstRead)
  end)

  it("splits the rows by what the client knew of them at the main read", function()
    local t = Tally.count({
      dropped({ infoKnown = true, hasAllInfo = false, firstRead = nil }),
      dropped({ infoKnown = true, hasAllInfo = false, firstRead = "10s" }),
      dropped({ infoKnown = false, hasAllInfo = false, firstRead = "itemLoad" }),
      dropped({ infoKnown = true, hasAllInfo = true, firstRead = nil }),
    })
    assert.are.same({
      ["infoKnown,notAllInfo"] = { rows = 2, firstRead = { never = 1, ["10s"] = 1 } },
      ["infoMissing,notAllInfo"] = { rows = 1, firstRead = { itemLoad = 1 } },
      ["infoKnown,hasAllInfo"] = { rows = 1, firstRead = { never = 1 } },
    }, t.groups)
  end)

  it("counts distinct items, overall and among rows that never came back", function()
    local t = Tally.count({
      dropped({ itemID = 1, firstRead = nil }),
      dropped({ itemID = 1, firstRead = "2s" }),
      dropped({ itemID = 2, firstRead = "2s" }),
      dropped({ itemID = 3, firstRead = nil }),
    })
    assert.are.equal(3, t.items)
    assert.are.equal(2, t.itemsNever)
  end)
end)
