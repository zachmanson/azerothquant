local CraftChain = require("CraftChain")

local NAMES = {
  ["item:2841"] = "Bronze Bar",
  ["item:2840"] = "Copper Bar",
  ["item:2770"] = "Copper Ore",
  ["item:3576"] = "Tin Bar",
  ["item:3466"] = "Strong Flux",
}

local function names(itemString)
  return NAMES[itemString]
end

-- The spec's example chain (#77), as the Brain writes it (brain/src/brain/recommendations.py).
local function bronzeRow()
  return {
    itemKey = "2841",
    action = "Craft",
    quantity = 20,
    profit = 4540,
    chain = {
      {
        kind = "sell",
        itemKey = "2841",
        quantity = 20,
        gold = 8500,
        postAt = 450,
        cut = 450,
        deposit = 50,
        children = {
          {
            kind = "craft",
            itemKey = "2841",
            quantity = 20,
            crafts = 20,
            character = "Kash-Patel",
            gold = -3960,
            children = {
              {
                kind = "craft",
                itemKey = "2840",
                quantity = 20,
                crafts = 20,
                character = "Zed",
                gold = -1800,
                children = {
                  { kind = "use", itemKey = "2770", quantity = 20, gold = -1800 },
                },
              },
              { kind = "buy", itemKey = "3576", quantity = 20, gold = -2140, maxUnitPrice = 110, effort = 20 },
              { kind = "merchant", itemKey = "3466", quantity = 1, gold = -20 },
            },
          },
        },
      },
    },
  }
end

-- Just the fields a test looks at, one table per line.
local function pick(lines, ...)
  local keys = { ... }
  local out = {}
  for i, line in ipairs(lines) do
    local picked = {}
    for _, k in ipairs(keys) do
      picked[k] = line[k]
    end
    out[i] = picked
  end
  return out
end

describe("CraftChain.build", function()
  it("draws the chain top-down: exits, the craft under them, each source under what it feeds", function()
    local chain = CraftChain.build(bronzeRow(), names)
    assert.are.same({
      { text = "Sell 20 Bronze Bar", tag = "@ 4s 50c", guides = {} },
      { text = "Craft 20 Bronze Bar", tag = "on Kash-Patel, 20 crafts", guides = { "last" } },
      { text = "Craft 20 Copper Bar", tag = "on Zed, 20 crafts", guides = { "space", "branch" } },
      { text = "Use 20 Copper Ore", tag = "held", guides = { "space", "pipe", "last" } },
      { text = "Buy 20 Tin Bar", tag = "AH @ max 1s 10c", guides = { "space", "branch" } },
      { text = "Buy 1 Strong Flux", tag = "merchant", guides = { "space", "last" } },
    }, pick(chain.lines, "text", "tag", "guides"))
  end)

  -- A craft's gold is the sum of the sources under it, so it's a subtotal: every other
  -- line adds up to the Profit.
  it("signs each line's gold, marks a craft's as a subtotal, and ends with the Profit", function()
    local chain = CraftChain.build(bronzeRow(), names)
    assert.are.same({
      { gold = "+85s", color = "gain" },
      { gold = "-39s 60c", color = "subtotal" },
      { gold = "-18s", color = "subtotal" },
      { gold = "-18s", color = "loss" },
      { gold = "-21s 40c", color = "loss" },
      { gold = "-20c", color = "loss" },
    }, pick(chain.lines, "gold", "color"))
    assert.are.same({ text = "Profit", gold = "+45s 40c", color = "gain" }, chain.profit)
  end)

  -- The Brain writes the breakdown parts as positive costs, already taken out of the gold.
  it("links each line to its item and breaks down its gold for the hover", function()
    local chain = CraftChain.build(bronzeRow(), names)
    assert.are.same({
      {
        itemString = "item:2841",
        tooltip = { "Posted: +90s", "Auction House cut: -4s 50c", "Deposits: -50c" },
      },
      { itemString = "item:2841", tooltip = {} },
      { itemString = "item:2840", tooltip = {} },
      { itemString = "item:2770", tooltip = {} },
      { itemString = "item:3576", tooltip = { "Effort cost: -20c" } },
      { itemString = "item:3466", tooltip = {} },
    }, pick(chain.lines, "itemString", "tooltip"))
  end)

  it("shows no sign or colour for nothing", function()
    local r = bronzeRow()
    r.profit = 0
    assert.are.same({ text = "Profit", gold = "0c" }, CraftChain.build(r, names).profit)
  end)

  -- A blocked row's chain is one craft, as it would be sourced, with no exit.
  it("marks the node that blocks the row with why, and its unknown gold as a dash", function()
    local chain = CraftChain.build({
      itemKey = "2841",
      action = "Craft",
      quantity = 5,
      character = "Kash-Patel",
      blocked = { reason = "noData", itemKey = "2770" },
      chain = {
        {
          kind = "craft",
          itemKey = "2841",
          quantity = 5,
          crafts = 5,
          character = "Kash-Patel",
          children = {
            { kind = "use", itemKey = "2770", quantity = 5, blocked = { reason = "noData", itemKey = "2770" } },
            { kind = "use", itemKey = "3576", quantity = 5, gold = -500 },
          },
        },
        {
          kind = "craft",
          itemKey = "2840",
          quantity = 1,
          crafts = 1,
          character = "Zed",
          gold = -300, -- the Brain keeps it for an unknown bind type
          blocked = { reason = "unknownBindType" },
        },
      },
    }, names)
    assert.are.same({
      { gold = "\226\128\148" },
      { gold = "\226\128\148", blocked = "no market data" },
      { gold = "-5s", color = "loss" },
      { gold = "\226\128\148", blocked = "unknown bind type" },
    }, pick(chain.lines, "gold", "color", "blocked"))
    assert.is_nil(chain.profit)
  end)

  it("names a node kind it doesn't know yet by its kind", function()
    local chain = CraftChain.build({
      itemKey = "2841",
      profit = 100,
      chain = { { kind = "salvage", itemKey = "2841", quantity = 2, gold = 100 } },
    }, names)
    assert.are.equal("salvage 2 Bronze Bar", chain.lines[1].text)
  end)

  -- A blocked row whose other reagents can't be sourced has no chain to draw.
  it("says so when there's no chain, with the row's note", function()
    local chain = CraftChain.build({
      itemKey = "2841",
      action = "Craft",
      quantity = 5,
      character = "Kash-Patel",
      blocked = { reason = "noData", itemKey = "2770" },
    }, names)
    assert.are.same({}, chain.lines)
    assert.are.equal("No chain to show: on Kash-Patel: no market data for Copper Ore", chain.empty)
  end)
end)
