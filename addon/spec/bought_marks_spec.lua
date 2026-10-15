local BoughtMarks = require("BoughtMarks")

local SCAN = 1790524206

describe("BoughtMarks.toggle", function()
  it("marks a row Bought with its Cost and when, and a second toggle unmarks it", function()
    local marks = {}

    BoughtMarks.toggle(marks, "2589 Sell ", 4800, SCAN + 60)
    assert.are.same({ ["2589 Sell "] = { cost = 4800, at = SCAN + 60 } }, marks)

    BoughtMarks.toggle(marks, "2589 Sell ", 4800, SCAN + 90)
    assert.are.same({}, marks)
  end)
end)

describe("BoughtMarks.forMarket", function()
  local REALM, FACTION = "Classic Beta PvP", "Alliance"

  local function recs(asOf)
    return { [REALM] = { [FACTION] = { asOf = asOf } } }
  end

  it("keeps the Market's marks made after the imported Scan, and drops the older ones", function()
    local db = {
      bought = {
        ["Classic Beta PvP-Alliance"] = {
          ["2589 Sell "] = { cost = 4800, at = SCAN + 60 },
          ["2592 Vendor "] = { cost = 900, at = SCAN - 60 },
        },
        ["Classic Beta PvP-Horde"] = { ["2589 Sell "] = { cost = 1, at = SCAN - 60 } },
      },
    }

    local marks = BoughtMarks.forMarket(db, recs(SCAN), REALM, FACTION)

    assert.are.same({ ["2589 Sell "] = { cost = 4800, at = SCAN + 60 } }, marks)
    assert.are.equal(db.bought["Classic Beta PvP-Alliance"], marks)
    assert.are.same({ ["2589 Sell "] = { cost = 1, at = SCAN - 60 } }, db.bought["Classic Beta PvP-Horde"])
  end)

  it("keeps a mark made at the Scan's own time: a Brain run on that Scan still saw the Listings", function()
    local db = { bought = { ["Classic Beta PvP-Alliance"] = { ["2589 Sell "] = { cost = 4800, at = SCAN } } } }

    assert.are.same({ ["2589 Sell "] = { cost = 4800, at = SCAN } }, BoughtMarks.forMarket(db, recs(SCAN), REALM, FACTION))
  end)

  it("starts an empty store for a Market with none, and clears nothing without Recommendations", function()
    local db = {}

    local marks = BoughtMarks.forMarket(db, nil, REALM, FACTION)
    marks["x"] = { cost = 1, at = 0 }

    assert.are.same({ ["x"] = { cost = 1, at = 0 } }, db.bought["Classic Beta PvP-Alliance"])
  end)
end)

describe("BoughtMarks.spent", function()
  it("sums what the marks spend", function()
    local marks = { a = { cost = 4800, at = SCAN }, b = { cost = 900.5, at = SCAN } }

    assert.are.equal(5700.5, BoughtMarks.spent(marks))
    assert.are.equal(0, BoughtMarks.spent({}))
  end)
end)

describe("BoughtMarks.goldLeft", function()
  it("is the Budget unchanged while nothing is marked, all the gold being nil", function()
    assert.are.equal(100000, BoughtMarks.goldLeft(100000, 20000, 0))
    assert.is_nil(BoughtMarks.goldLeft(nil, 20000, 0))
  end)

  it("is what's left of the Budget, or the gold on hand if that's less", function()
    assert.are.equal(60000, BoughtMarks.goldLeft(100000, 70000, 40000))
    assert.are.equal(50000, BoughtMarks.goldLeft(100000, 50000, 40000))
  end)

  it("is the gold on hand with no Budget set", function()
    assert.are.equal(50000, BoughtMarks.goldLeft(nil, 50000, 40000))
  end)

  it("is what's left of the risk caps' room if that's less (#170)", function()
    assert.are.equal(20000, BoughtMarks.goldLeft(nil, 50000, 40000, 60000))
    assert.are.equal(50000, BoughtMarks.goldLeft(nil, 50000, 40000, 100000))
    assert.is_nil(BoughtMarks.goldLeft(nil, 50000, 0, 60000))
  end)
end)
