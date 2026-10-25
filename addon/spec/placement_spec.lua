local Placement = require("Placement")

describe("Placement.firstOpen", function()
  it("opens beside the AH at its own width when the room right of it fits that", function()
    assert.are.same({ side = "right", width = 1100 }, Placement.firstOpen(1200, 1100, 1000))
  end)

  it("narrows to the room right of the AH, down to the least width", function()
    assert.are.same({ side = "right", width = 1040 }, Placement.firstOpen(1040, 1100, 1000))
    assert.are.same({ side = "right", width = 1000 }, Placement.firstOpen(1000, 1100, 1000))
  end)

  it("opens below the AH at its own width when even the least width doesn't fit beside it", function()
    assert.are.same({ side = "below", width = 1100 }, Placement.firstOpen(550, 1100, 1000))
    assert.are.same({ side = "below", width = 1100 }, Placement.firstOpen(999, 1100, 1000))
  end)
end)
