local LootAlert = require("LootAlert")

local REALM, FACTION = "Classic Beta PvP", "Alliance"
local NOW = 1790000000
local DAY = 24 * 3600
-- The client's global format strings (enUS).
local FORMATS = { single = "You receive loot: %s.", multiple = "You receive loot: %sx%d." }
local LINK = "|cff1eff00|Hitem:1482::::::::20:1490:::::::::|h[Shadowfang]|h|r"

-- Recommendations shaped like the Brain writes them (see Recommendations.lua).
local function recs(lootAlert, asOf)
  return { [REALM] = { [FACTION] = { asOf = asOf or NOW, lootAlert = lootAlert } } }
end

local ALERT = { threshold = 100000, items = { ["1482"] = { value = 450000, action = "Sell" } } }

local function alert(recommendations, msg, now)
  return LootAlert.forMessage(recommendations, REALM, FACTION, msg, FORMATS, now or NOW)
end

describe("LootAlert.forMessage", function()
  it("names a single unit the player loots, with its value and Action", function()
    assert.are.equal("AQ: " .. LINK .. ": 45g (Sell)", alert(recs(ALERT), "You receive loot: " .. LINK .. "."))
  end)

  it("names a stack the player loots, each unit's value and the stack's", function()
    assert.are.equal(
      "AQ: " .. LINK .. " x3: 45g each, 135g (Sell)",
      alert(recs(ALERT), "You receive loot: " .. LINK .. "x3.")
    )
  end)

  it("ignores another player's loot and what the player creates", function()
    assert.is_nil(alert(recs(ALERT), "Bob receives loot: " .. LINK .. "."))
    assert.is_nil(alert(recs(ALERT), "You create: " .. LINK .. "."))
  end)

  it("ignores an Item Key the lootAlert doesn't list", function()
    local cheap = "|cffffffff|Hitem:2589::::::::20:1490:::::::::|h[Linen Cloth]|h|r"
    assert.is_nil(alert(recs(ALERT), "You receive loot: " .. cheap .. "x20."))
  end)

  it("gives nothing without a lootAlert or Recommendations for the Market", function()
    local msg = "You receive loot: " .. LINK .. "."
    assert.is_nil(alert(recs(nil), msg))
    assert.is_nil(alert({}, msg))
    assert.is_nil(alert(nil, msg))
  end)

  it("says how old the prices are once they're over a day old", function()
    local msg = "You receive loot: " .. LINK .. "."
    local line = "AQ: " .. LINK .. ": 45g (Sell)"
    assert.are.equal(line, alert(recs(ALERT, NOW - DAY), msg))
    assert.are.equal(line .. " (prices 1d old)", alert(recs(ALERT, NOW - DAY - 1), msg))
    assert.are.equal(line .. " (prices 3d old)", alert(recs(ALERT, NOW - 3 * DAY - 3600), msg))
  end)
end)
