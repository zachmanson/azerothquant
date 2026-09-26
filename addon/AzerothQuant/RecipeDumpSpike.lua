-- SPIKE (#18), throwaway: delete this file (and its TOC line) once the spike's answers
-- are on the issue. Not part of the Addon's design and not tested.
--
-- Questions for the live Forever client: which GetTradeSkill* / GetCraft* calls exist
-- and what they return, whether collapsed headers or the "have materials" filter hide
-- recipes, how to tell Beast Training from Enchanting, and how the SHOW / UPDATE
-- events are timed.
--
-- Usage: open a profession window, type /aq recipedump, then /reload (or log out) and
-- paste AzerothQuantDB.recipeDumpSpike from the SavedVariables file. Dump a trade skill
-- (e.g. Tailoring) and Enchanting with every header expanded and no filters, then the
-- same trade skill again with a header collapsed and "Have Materials" ticked. Beast
-- Training too, if you have a Hunter.
--
-- Read-only (ADR-0003): only calls that read the open window. Never DoTradeSkill /
-- DoCraft, never expands, collapses or filters, never closes the window.

-- Every call the spike tries, so the dump shows which exist on this client.
local API = {
  "GetTradeSkillLine", "GetNumTradeSkills", "GetTradeSkillInfo", "GetTradeSkillItemLink",
  "GetTradeSkillRecipeLink", "GetTradeSkillNumMade", "GetTradeSkillNumReagents",
  "GetTradeSkillReagentInfo", "GetTradeSkillReagentItemLink", "GetTradeSkillCooldown",
  "GetTradeSkillSubClassFilter", "GetTradeSkillInvSlotFilter",
  "GetCraftDisplaySkillLine", "GetCraftSkillLine", "GetCraftName", "GetNumCrafts",
  "GetCraftInfo", "GetCraftItemLink", "GetCraftRecipeLink", "GetCraftNumMade",
  "GetCraftNumReagents", "GetCraftReagentInfo", "GetCraftReagentItemLink",
  "GetCraftCooldown", "GetCraftDescription",
}

-- Every return value by position, with nil spelled out so the gaps are visible
-- (a Lua table would silently drop them).
local function allReturns(...)
  local out = { n = select("#", ...) }
  for i = 1, out.n do
    local v = select(i, ...)
    out[i] = v == nil and "<nil>" or v
  end
  return out
end

-- Calls a global by name, so a call the client lacks is recorded instead of erroring.
-- "<missing>" if it doesn't exist; otherwise pcall's returns, so [1] is false and [2]
-- the error if it threw.
local function call(name, ...)
  local f = _G[name]
  if type(f) ~= "function" then
    return "<missing>"
  end
  return allReturns(pcall(f, ...))
end

-- The first real return value of call(), or nil if missing or it threw.
local function first(result)
  if type(result) == "table" and result[1] == true and result[2] ~= "<nil>" then
    return result[2]
  end
  return nil
end

local function say(msg)
  print("|cff33ff99AzerothQuant spike|r " .. msg)
end

-- Event log since the last TRADE_SKILL_SHOW / CRAFT_SHOW: event, seconds since that
-- SHOW, and how many rows each window reported then (is the data ready at SHOW?).
local events = {}
local shownAt -- GetTime() at the last SHOW

local function logEvent(event)
  local now = GetTime()
  if event == "TRADE_SKILL_SHOW" or event == "CRAFT_SHOW" then
    events = {}
    shownAt = now
  end
  events[#events + 1] = {
    event = event,
    t = shownAt and (now - shownAt) or "<no SHOW yet>",
    numTradeSkills = call("GetNumTradeSkills"),
    numCrafts = call("GetNumCrafts"),
  }
end

local function isShown(frameName)
  local frame = _G[frameName]
  return frame and frame:IsShown() or false
end

local function tradeSkillRows()
  local rows = {}
  for i = 1, tonumber(first(call("GetNumTradeSkills"))) or 0 do
    local numReagents = tonumber(first(call("GetTradeSkillNumReagents", i))) or 0
    local reagents = {}
    for r = 1, numReagents do
      reagents[r] = {
        info = call("GetTradeSkillReagentInfo", i, r),
        link = call("GetTradeSkillReagentItemLink", i, r),
      }
    end
    rows[i] = {
      index = i,
      info = call("GetTradeSkillInfo", i),
      itemLink = call("GetTradeSkillItemLink", i),
      recipeLink = call("GetTradeSkillRecipeLink", i),
      numMade = call("GetTradeSkillNumMade", i),
      cooldown = call("GetTradeSkillCooldown", i),
      numReagents = numReagents,
      reagents = reagents,
    }
  end
  return rows
end

local function craftRows()
  local rows = {}
  for i = 1, tonumber(first(call("GetNumCrafts"))) or 0 do
    local numReagents = tonumber(first(call("GetCraftNumReagents", i))) or 0
    local reagents = {}
    for r = 1, numReagents do
      reagents[r] = {
        info = call("GetCraftReagentInfo", i, r),
        link = call("GetCraftReagentItemLink", i, r),
      }
    end
    rows[i] = {
      index = i,
      info = call("GetCraftInfo", i),
      itemLink = call("GetCraftItemLink", i),
      recipeLink = call("GetCraftRecipeLink", i),
      numMade = call("GetCraftNumMade", i),
      cooldown = call("GetCraftCooldown", i),
      description = call("GetCraftDescription", i),
      numReagents = numReagents,
      reagents = reagents,
    }
  end
  return rows
end

local function dump()
  local tradeShown, craftShown = isShown("TradeSkillFrame"), isShown("CraftFrame")
  if not (tradeShown or craftShown) then
    say("Open a profession window first.")
    return
  end

  local apis = {}
  for _, name in ipairs(API) do
    apis[name] = type(_G[name])
  end

  local availableFilter = _G.TradeSkillFrameAvailableFilterCheckButton
  local entry = {
    dumpedAt = time(),
    dumpedAfterShow = shownAt and (GetTime() - shownAt) or nil,
    realm = GetRealmName(),
    character = table.concat({ UnitFullName("player") }, "-"),
    class = allReturns(UnitClass("player")),
    tradeSkillFrameShown = tradeShown,
    craftFrameShown = craftShown,
    apis = apis,
    events = events,
    tradeSkill = {
      line = call("GetTradeSkillLine"),
      subClassFilter = call("GetTradeSkillSubClassFilter", 0),
      invSlotFilter = call("GetTradeSkillInvSlotFilter", 0),
      haveMaterialsChecked = availableFilter and (availableFilter:GetChecked() and true or false)
        or "<no checkbox>",
      rows = tradeSkillRows(),
    },
    craft = {
      displaySkillLine = call("GetCraftDisplaySkillLine"),
      skillLine = call("GetCraftSkillLine", 1),
      name = call("GetCraftName"),
      rows = craftRows(),
    },
  }

  local db = AzerothQuantDB
  db.recipeDumpSpike = db.recipeDumpSpike or {}
  table.insert(db.recipeDumpSpike, entry)

  local missing = {}
  for _, name in ipairs(API) do
    if apis[name] ~= "function" then
      missing[#missing + 1] = name
    end
  end
  say(string.format("Trade skill: %s, %d rows. Craft: %s, %d rows.",
    tostring(first(entry.tradeSkill.line)), #entry.tradeSkill.rows,
    tostring(first(entry.craft.displaySkillLine) or first(entry.craft.name)), #entry.craft.rows))
  say("Missing calls: " .. (#missing > 0 and table.concat(missing, ", ") or "none"))
  say(string.format("Events since SHOW: %d.", #events))
  for _, e in ipairs(events) do
    say(string.format("  %s at +%.2fs (trade %s, craft %s)", e.event, tonumber(e.t) or -1,
      tostring(first(e.numTradeSkills)), tostring(first(e.numCrafts))))
  end
  say(string.format("Saved as dump #%d. /reload, then paste AzerothQuantDB.recipeDumpSpike.", #db.recipeDumpSpike))
end

local frame = CreateFrame("Frame")
for _, event in ipairs({
  "TRADE_SKILL_SHOW", "TRADE_SKILL_UPDATE", "TRADE_SKILL_CLOSE",
  "CRAFT_SHOW", "CRAFT_UPDATE", "CRAFT_CLOSE",
}) do
  -- pcall: an event this client doesn't know would otherwise stop the file loading.
  pcall(frame.RegisterEvent, frame, event)
end
frame:SetScript("OnEvent", function(_, event)
  logEvent(event)
end)

-- /aq is shared with the mail spike (#15): handle recipedump, hand anything else to
-- whichever handler was registered before, so either spike can be deleted on its own.
local previous = SlashCmdList.AZEROTHQUANT
SLASH_AZEROTHQUANT1 = "/aq"
SlashCmdList.AZEROTHQUANT = function(msg)
  if msg:match("^%s*recipedump%s*$") then
    dump()
  elseif previous then
    previous(msg)
  else
    say("Usage: /aq recipedump (with a profession window open)")
  end
end
