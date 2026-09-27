-- WoW glue for Known Recipes: while one of the Character's own profession windows is
-- open, reads its learned recipes and keeps the latest read of each profession in
-- memory for Character.lua to record at PLAYER_LOGOUT, like the bank. Also keeps which
-- professions the Character has. All shaping happens in KnownRecipes.lua.
--
-- On Forever the window is the modern ProfessionsFrame, backed by C_TradeSkillUI; the
-- Classic GetTradeSkill*/GetCraft* calls don't exist (spike results on #18).
--
-- Read-only (ADR-0003): only calls that read the profession window and skill lines.
-- Nothing that crafts, learns or changes a recipe.
local _, ns = ...
local KnownRecipes = ns.KnownRecipes

-- Recipe list updates come in bursts, so read once they have been quiet this long.
local QUIET_SECONDS = 0.5

local ui = C_TradeSkillUI

local isOpen = false
local timer
local latest = {} -- professionID -> KnownRecipes entry, the latest read this session
local announced = {} -- professionID -> true once its chat line has been printed
local professionList -- { professionID, professionName } each, nil until read

local function say(msg)
  print("|cff33ff99AzerothQuant|r " .. msg)
end

-- A linked, guild or NPC crafting window shows someone else's recipes. If the client
-- can't tell us, don't risk it.
local function isOwnWindow()
  if not (ui.IsTradeSkillLinked and ui.IsTradeSkillGuild and ui.IsNPCCrafting) then
    return false
  end
  return not (ui.IsTradeSkillLinked() or ui.IsTradeSkillGuild() or ui.IsNPCCrafting())
end

local function readWindow()
  timer = nil
  if not (ui and ui.IsTradeSkillReady and ui.IsTradeSkillReady()) or not isOwnWindow() then
    return
  end
  local profession = ui.GetBaseProfessionInfo()
  if not (profession and profession.professionID) then
    return
  end
  local recipes = {}
  -- Unfiltered: collapsed headers and the window's filters don't hide anything.
  for _, id in ipairs(ui.GetAllRecipeIDs() or {}) do
    local info = ui.GetRecipeInfo(id)
    if info and info.learned then
      recipes[#recipes + 1] = {
        info = info,
        schematic = ui.GetRecipeSchematic(id, false),
        link = ui.GetRecipeItemLink(id),
        cooldown = (ui.GetRecipeCooldown(id)),
      }
    else
      -- Unlearned: KnownRecipes leaves it out, so skip the other calls.
      recipes[#recipes + 1] = { info = info }
    end
  end
  local entry = KnownRecipes.build(time(), profession, recipes)
  latest[entry.professionID] = entry
  if not announced[entry.professionID] then
    announced[entry.professionID] = true
    say(string.format("Read %d %s recipes.", #entry.recipes, entry.professionName or "?"))
  end
end

local function readWindowSoon()
  if timer then
    timer:Cancel()
  end
  timer = C_Timer.NewTimer(QUIET_SECONDS, readWindow)
end

-- GetProfessions returns up to five indices (primary, primary, archaeology, fishing,
-- cooking), any of them nil, so walk them by position.
local function readProfessionList()
  if not (GetProfessions and GetProfessionInfo) then
    return
  end
  local list = {}
  local indices = { GetProfessions() }
  for i = 1, select("#", GetProfessions()) do
    if indices[i] then
      local name, _, _, _, _, _, skillLine = GetProfessionInfo(indices[i])
      list[#list + 1] = { professionID = skillLine, professionName = name }
    end
  end
  professionList = list
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:RegisterEvent("SKILL_LINES_CHANGED")
if ui then
  frame:RegisterEvent("TRADE_SKILL_SHOW")
  frame:RegisterEvent("TRADE_SKILL_LIST_UPDATE")
  frame:RegisterEvent("NEW_RECIPE_LEARNED")
  frame:RegisterEvent("TRADE_SKILL_CLOSE")
end
frame:SetScript("OnEvent", function(_, event)
  if event == "PLAYER_ENTERING_WORLD" or event == "SKILL_LINES_CHANGED" then
    readProfessionList()
  elseif event == "TRADE_SKILL_SHOW" then
    isOpen = true
    -- Not ready yet means a TRADE_SKILL_LIST_UPDATE is on its way.
    readWindow()
  elseif event == "TRADE_SKILL_LIST_UPDATE" or event == "NEW_RECIPE_LEARNED" then
    if isOpen then
      readWindowSoon()
    end
  elseif event == "TRADE_SKILL_CLOSE" then
    -- Catch a change still waiting out the quiet time before the window closes for good.
    if timer then
      timer:Cancel()
      readWindow()
    end
    isOpen = false
  end
end)

ns.Professions = {
  -- Latest read of each profession whose window was opened this session.
  latest = function()
    return latest
  end,
  -- The professions the Character has, or nil if the client couldn't say.
  list = function()
    return professionList
  end,
}
