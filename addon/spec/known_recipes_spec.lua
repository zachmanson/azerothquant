local KnownRecipes = require("KnownRecipes")

-- What GetBaseProfessionInfo returns with the Tailoring window open (trimmed).
local TAILORING = {
  professionID = 197,
  professionName = "Tailoring",
  skillLevel = 103,
  maxSkillLevel = 150,
  isPrimaryProfession = true,
}

local BOLT_LINK = "|cnIQ1:|Hitem:2996::::::::20:1490:::::::::|h[Bolt of Linen Cloth]|h|r"

-- One recipe as Professions.lua reads it: GetRecipeInfo, GetRecipeSchematic(id, false),
-- GetRecipeItemLink and GetRecipeCooldown for that recipe ID, plus the output item's
-- bind type (GetItemInfo's 14th return).
local BOLT_OF_LINEN = {
  info = { recipeID = 2963, name = "Bolt of Linen Cloth", learned = true, categoryID = 1, hyperlink = "..." },
  schematic = {
    recipeID = 2963,
    recipeType = 1,
    outputItemID = 2996,
    quantityMin = 1,
    quantityMax = 1,
    reagentSlotSchematics = {
      { reagentType = 1, quantityRequired = 2, reagents = { { itemID = 2589 } } },
    },
  },
  link = BOLT_LINK,
  bindType = 0,
}

describe("KnownRecipes.build", function()
  it("records the profession, when it was read, and each learned recipe raw", function()
    local entry = KnownRecipes.build(1790450000, TAILORING, { BOLT_OF_LINEN })

    assert.are.same({
      readAt = 1790450000,
      professionID = 197,
      professionName = "Tailoring",
      skillLevel = 103,
      maxSkillLevel = 150,
      recipes = {
        {
          recipeID = 2963,
          name = "Bolt of Linen Cloth",
          recipeType = 1,
          outputItemID = 2996,
          link = BOLT_LINK,
          quantityMin = 1,
          quantityMax = 1,
          bindType = 0,
          reagents = { { itemID = 2589, quantity = 2, reagentType = 1 } },
        },
      },
    }, entry)
  end)

  it("leaves out recipes the Character hasn't learned", function()
    local unlearned = {
      info = { recipeID = 3914, name = "Brown Linen Pants", learned = false },
      schematic = {
        recipeType = 1,
        outputItemID = 4343,
        quantityMin = 1,
        quantityMax = 1,
        reagentSlotSchematics = { { reagentType = 1, quantityRequired = 2, reagents = { { itemID = 2996 } } } },
      },
      link = "|cnIQ1:|Hitem:4343::::::::20:1490:::::::::|h[Brown Linen Pants]|h|r",
    }

    local entry = KnownRecipes.build(1790450000, TAILORING, { unlearned, BOLT_OF_LINEN })

    assert.are.equal(1, #entry.recipes)
    assert.are.equal(2963, entry.recipes[1].recipeID)
  end)

  it("keeps enchants, which have no output item, and flattens every reagent slot", function()
    local enchanting = { professionID = 333, professionName = "Enchanting", skillLevel = 150, maxSkillLevel = 150 }
    local ENCHANT_LINK = "|cffffd000|Henchant:7867|h[Enchanting: Enchant Boots - Minor Agility]|h|r"
    local minorAgility = {
      info = { recipeID = 7867, name = "Enchant Boots - Minor Agility", learned = true, isEnchantingRecipe = true },
      schematic = {
        recipeType = 3,
        quantityMin = 1,
        quantityMax = 1,
        reagentSlotSchematics = {
          { reagentType = 1, quantityRequired = 6, reagents = { { itemID = 10940 } } },
          { reagentType = 1, quantityRequired = 2, reagents = { { itemID = 10938 } } },
        },
      },
      link = ENCHANT_LINK,
      cooldown = 3600,
    }

    local entry = KnownRecipes.build(1790450000, enchanting, { minorAgility })

    assert.are.same({
      {
        recipeID = 7867,
        name = "Enchant Boots - Minor Agility",
        recipeType = 3,
        link = ENCHANT_LINK,
        quantityMin = 1,
        quantityMax = 1,
        cooldown = 3600,
        reagents = {
          { itemID = 10940, quantity = 6, reagentType = 1 },
          { itemID = 10938, quantity = 2, reagentType = 1 },
        },
      },
    }, entry.recipes)
  end)

  it("keeps a learned recipe with no schematic, reagents unknown rather than none", function()
    local noSchematic = { info = { recipeID = 2963, name = "Bolt of Linen Cloth", learned = true }, link = BOLT_LINK }
    local noInfo = { schematic = BOLT_OF_LINEN.schematic, link = BOLT_LINK }

    local entry = KnownRecipes.build(1790450000, TAILORING, { noSchematic, noInfo })

    assert.are.same({ { recipeID = 2963, name = "Bolt of Linen Cloth", link = BOLT_LINK } }, entry.recipes)
  end)

  it("records the output's bind type, and leaves it unknown when the item wasn't cached", function()
    local PANTS_LINK = "|cnIQ1:|Hitem:4343::::::::20:1490:::::::::|h[Brown Linen Pants]|h|r"
    local uncached = {
      info = { recipeID = 3914, name = "Brown Linen Pants", learned = true },
      schematic = { recipeType = 1, outputItemID = 4343, quantityMin = 1, quantityMax = 1 },
      link = PANTS_LINK,
    }
    local soulbound = {
      info = { recipeID = 12000, name = "Some Bind on Pickup Robe", learned = true },
      schematic = { recipeType = 1, outputItemID = 10000, quantityMin = 1, quantityMax = 1 },
      bindType = 1,
    }

    local entry = KnownRecipes.build(1790450000, TAILORING, { BOLT_OF_LINEN, uncached, soulbound })

    assert.are.equal(0, entry.recipes[1].bindType)
    assert.is_nil(entry.recipes[2].bindType)
    assert.are.equal(1, entry.recipes[3].bindType)
  end)
end)
