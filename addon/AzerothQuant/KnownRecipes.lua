-- Shapes one read of a profession window into the Known Recipes entry stored on the
-- Character Read (professions[professionID]). Everything is kept raw; the Brain
-- decides what matters once the Craft Action needs it (ADR-0005, #18 amendment).
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for
-- the namespace fallback.
local _, ns = ...
ns = ns or {}

local KnownRecipes = {}

-- Every reagent slot, flattened to { itemID, quantity, reagentType }. nil when the
-- client gave no schematic: unknown, which an empty list would misstate as "none".
local function reagents(schematic)
  if not schematic then
    return nil
  end
  local kept = {}
  for _, slot in ipairs(schematic.reagentSlotSchematics or {}) do
    for _, reagent in ipairs(slot.reagents or {}) do
      kept[#kept + 1] = {
        itemID = reagent.itemID,
        quantity = slot.quantityRequired,
        reagentType = slot.reagentType,
      }
    end
  end
  return kept
end

-- readAt: when the window was read.
-- profession: what C_TradeSkillUI.GetBaseProfessionInfo returned.
-- recipes: one per recipe ID, { info, schematic, link, cooldown }, where info is
-- GetRecipeInfo, schematic is GetRecipeSchematic(id, false), link is GetRecipeItemLink
-- and cooldown is GetRecipeCooldown (seconds left, nil if none). Any of them can be
-- nil; with no info there's no telling whether it's learned, so it's left out.
function KnownRecipes.build(readAt, profession, recipes)
  local kept = {}
  for _, r in ipairs(recipes) do
    if r.info and r.info.learned then
      local schematic = r.schematic or {}
      kept[#kept + 1] = {
        recipeID = r.info.recipeID,
        name = r.info.name,
        recipeType = schematic.recipeType,
        outputItemID = schematic.outputItemID,
        link = r.link,
        quantityMin = schematic.quantityMin,
        quantityMax = schematic.quantityMax,
        cooldown = r.cooldown,
        reagents = reagents(r.schematic),
      }
    end
  end
  return {
    readAt = readAt,
    professionID = profession.professionID,
    professionName = profession.professionName,
    skillLevel = profession.skillLevel,
    maxSkillLevel = profession.maxSkillLevel,
    recipes = kept,
  }
end

ns.KnownRecipes = KnownRecipes
return KnownRecipes
