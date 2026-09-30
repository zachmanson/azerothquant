local CraftCapture = require("CraftCapture")

local LINEN = "|cffffffff|Hitem:2589::::::::20:1490:::::::::|h[Linen Cloth]|h|r"
local BOLT = "|cffffffff|Hitem:2996::::::::20:1490:::::::::|h[Bolt of Linen Cloth]|h|r"

local TAILORING = 197
local BOLT_RECIPE = 2963

-- Known Recipes by professionID, as Professions.latest() keeps them.
local function professions(recipes)
  return { [TAILORING] = { professionID = TAILORING, recipes = recipes } }
end

local BOLT_OF_LINEN = {
  recipeID = BOLT_RECIPE,
  outputItemID = 2996,
  quantityMin = 1,
  quantityMax = 1,
  reagents = { { itemID = 2589, quantity = 2, reagentType = 1 } },
}

-- One bag slot as Character.lua reads it; slot(n) alone is an empty one.
local function slot(n, link, count)
  return { bag = 0, slot = n, info = link and { hyperlink = link, stackCount = count } }
end

describe("CraftCapture", function()
  it("records a Known Recipe's craft with the output units that reached the bags", function()
    local capture = CraftCapture.new(professions({ BOLT_OF_LINEN }))

    capture:castStarted(BOLT_RECIPE, { slot(1, LINEN, 20), slot(2, BOLT, 3) }, 1790449998)
    capture:castSucceeded(BOLT_RECIPE, { slot(1, LINEN, 18), slot(2, BOLT, 3) }, 1790450000)
    capture:bagsRead({ slot(1, LINEN, 18), slot(2, BOLT, 4) }, 1790450001)

    assert.are.same({ { recipeID = BOLT_RECIPE, at = 1790450000, quantity = 1 } }, capture.results)
  end)

  it("counts an instant craft's output from the bags as it succeeded, having no cast start", function()
    local capture = CraftCapture.new(professions({ BOLT_OF_LINEN }))

    capture:castSucceeded(BOLT_RECIPE, { slot(1, LINEN, 18), slot(2, BOLT, 3) }, 1790450000)
    capture:bagsRead({ slot(1, LINEN, 18), slot(2, BOLT, 4) }, 1790450001)

    assert.are.same({ { recipeID = BOLT_RECIPE, at = 1790450000, quantity = 1 } }, capture.results)
  end)

  it("keeps both of two instant crafts, the first settled by the bags as the second succeeds", function()
    local capture = CraftCapture.new(professions({ BOLT_OF_LINEN }))

    capture:castSucceeded(BOLT_RECIPE, { slot(1, LINEN, 18) }, 1790450000)
    capture:castSucceeded(BOLT_RECIPE, { slot(1, LINEN, 16), slot(2, BOLT, 1) }, 1790450001)
    capture:bagsRead({ slot(1, LINEN, 16), slot(2, BOLT, 2) }, 1790450002)

    assert.are.same({
      { recipeID = BOLT_RECIPE, at = 1790450000, quantity = 1 },
      { recipeID = BOLT_RECIPE, at = 1790450001, quantity = 1 },
    }, capture.results)
  end)

  it("records a recipe that makes no item (most Enchanting) with no output, and ignores other spells", function()
    local ENCHANT = 7418 -- Enchant Bracer - Minor Health
    local capture = CraftCapture.new({
      [333] = { professionID = 333, recipes = { { recipeID = ENCHANT, reagents = {} } } },
    })
    local bags = { slot(1, LINEN, 20) }

    capture:castStarted(13262, bags, 1790449998) -- Disenchant: not a Known Recipe
    capture:castSucceeded(13262, bags, 1790450000)
    capture:castStarted(ENCHANT, bags, 1790450008)
    capture:castSucceeded(ENCHANT, bags, 1790450010)

    assert.are.same({ { recipeID = ENCHANT, at = 1790450010 } }, capture.results)
  end)

  it("records no output count when the output hasn't reached the bags within a few seconds", function()
    local capture = CraftCapture.new(professions({ BOLT_OF_LINEN }))
    local bags = { slot(1, LINEN, 20) }

    capture:castStarted(BOLT_RECIPE, bags, 1790449998)
    capture:castSucceeded(BOLT_RECIPE, bags, 1790450000)
    -- A minute on: a Bolt the player bought or took from the mail isn't this craft's.
    capture:bagsRead({ slot(1, LINEN, 18), slot(2, BOLT, 5) }, 1790450060)

    assert.are.same({ { recipeID = BOLT_RECIPE, at = 1790450000 } }, capture.results)
  end)

  it("records one Result per craft of a batch, each with its own output", function()
    local capture = CraftCapture.new(professions({ BOLT_OF_LINEN }))

    capture:castStarted(BOLT_RECIPE, { slot(1, LINEN, 20) }, 1790450000)
    capture:castSucceeded(BOLT_RECIPE, { slot(1, LINEN, 18) }, 1790450002)
    -- The first Bolt shows up only in the bags read as the next cast starts.
    capture:castStarted(BOLT_RECIPE, { slot(1, LINEN, 18), slot(2, BOLT, 1) }, 1790450002)
    capture:castSucceeded(BOLT_RECIPE, { slot(1, LINEN, 16), slot(2, BOLT, 1) }, 1790450004)
    capture:bagsRead({ slot(1, LINEN, 16), slot(2, BOLT, 2) }, 1790450004)

    assert.are.same({
      { recipeID = BOLT_RECIPE, at = 1790450002, quantity = 1 },
      { recipeID = BOLT_RECIPE, at = 1790450004, quantity = 1 },
    }, capture.results)
  end)

  it("records no output count when the bags gained more than the recipe makes", function()
    local capture = CraftCapture.new(professions({ BOLT_OF_LINEN }))

    capture:castStarted(BOLT_RECIPE, { slot(1, LINEN, 20) }, 1790450000)
    capture:castSucceeded(BOLT_RECIPE, { slot(1, LINEN, 18) }, 1790450002)
    capture:castStarted(BOLT_RECIPE, { slot(1, LINEN, 18) }, 1790450002)
    capture:castSucceeded(BOLT_RECIPE, { slot(1, LINEN, 16) }, 1790450004)
    -- The first craft's Bolt arrived with the second's, after the second cast started.
    capture:bagsRead({ slot(1, LINEN, 16), slot(2, BOLT, 2) }, 1790450004)

    assert.are.same({
      { recipeID = BOLT_RECIPE, at = 1790450002 },
      { recipeID = BOLT_RECIPE, at = 1790450004 },
    }, capture.results)
  end)
end)
