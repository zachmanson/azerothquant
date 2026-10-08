local Tips = require("Tips")
local RecommendationTable = require("RecommendationTable")
local NextStep = require("NextStep")

local REALM, FACTION = "Classic Beta PvP", "Alliance"

-- A Market with no rows but a Beta Prior, so every tab and every column is built.
local function view()
  local recommendations = {
    [REALM] = {
      [FACTION] = {
        asOf = 1790524206,
        gold = 175471,
        windowHours = 0.2975,
        predictionCost = 0,
        holdings = {},
        shoppingList = {},
        predictionBuys = {},
        beta = { prices = {} },
      },
    },
  }
  return RecommendationTable.build(recommendations, REALM, FACTION, 0, function() end)
end

describe("Tips", function()
  it("has a tip for every tab", function()
    local missing = {}
    for _, section in ipairs(view().sections) do
      if not Tips.TABS[section.title] then
        missing[#missing + 1] = section.title
      end
    end
    assert.are.same({}, missing)
  end)

  it("has a tip for every column on every tab", function()
    local missing = {}
    for _, section in ipairs(view().sections) do
      for _, column in ipairs(section.columns) do
        if not Tips.COLUMNS[column] then
          missing[#missing + 1] = section.title .. ": " .. column
        end
      end
    end
    assert.are.same({}, missing)
  end)

  it("has a tip for every banner button", function()
    local base = {
      scanning = false, ahOpen = false, unsaved = 0, unimported = 0, behind = false, catchingUp = false,
      brainRan = true, trying = false, tookLonger = false, reloadReady = false,
    }
    local function step(changes)
      local loop = {}
      for k, v in pairs(base) do
        loop[k] = v
      end
      for k, v in pairs(changes) do
        loop[k] = v
      end
      return NextStep.of(loop, 0)
    end
    local missing = {}
    for _, changes in ipairs({ { scanning = true }, { unsaved = 1 }, { ahOpen = true } }) do
      local action = step(changes).action
      if not Tips.STEPS[action] then
        missing[#missing + 1] = action
      end
    end
    assert.are.same({}, missing)
  end)
end)
