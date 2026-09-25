local Money = require("Money")

describe("Money.format", function()
  it("shows gold, silver and copper", function()
    assert.are.equal("12g 34s 56c", Money.format(123456))
  end)

  it("leaves out zero parts", function()
    assert.are.equal("1g 5c", Money.format(10005))
    assert.are.equal("50s", Money.format(5000))
  end)

  it("shows 0c for nothing", function()
    assert.are.equal("0c", Money.format(0))
  end)

  it("rounds fractional copper down", function()
    -- Unit buyouts come from a Listing's total buyout / quantity and can be fractional.
    assert.are.equal("97c", Money.format(97.9))
  end)

  it("keeps the sign on negative amounts", function()
    -- Expected profit can be negative.
    assert.are.equal("-1g 50s", Money.format(-15000))
  end)

  it("does not show a sign on less than one copper", function()
    assert.are.equal("0c", Money.format(-0.5))
  end)
end)
