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

describe("Money.parseGold", function()
  it("reads whole or part gold as copper, with or without a g", function()
    assert.are.equal(2500000, Money.parseGold("250"))
    assert.are.equal(2500000, Money.parseGold(" 250g "))
    assert.are.equal(125000, Money.parseGold("12.5"))
    assert.are.equal(1, Money.parseGold("0.0001"))
  end)

  it("reads a blank box as no Budget", function()
    local copper, ok = Money.parseGold("  ")
    assert.is_nil(copper)
    assert.is_true(ok)
  end)

  it("refuses anything else", function()
    for _, text in ipairs({ "abc", "-5", "1g 50s", "1.2.3" }) do
      local copper, ok = Money.parseGold(text)
      assert.is_nil(copper)
      assert.is_false(ok)
    end
  end)
end)

describe("Money.goldText", function()
  it("shows copper as the gold a player would type back", function()
    assert.are.equal("250", Money.goldText(2500000))
    assert.are.equal("12.5", Money.goldText(125000))
    assert.are.equal("0.0001", Money.goldText(1))
    assert.are.equal("", Money.goldText(nil))
  end)
end)
