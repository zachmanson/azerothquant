-- Captures Craft Results (#44): each craft the player makes with one of their Known
-- Recipes, and how many units it made. The glue (Character.lua) feeds it the craft's
-- casts and the bags read at each; the units made are how many more of the output item
-- the bags hold than when the cast started.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for
-- the namespace fallback.
local _, ns = ...
ns = ns or {}

local CraftCapture = {}
CraftCapture.__index = CraftCapture

-- How long after a craft its output may take to reach the bags. Any longer and an item
-- the player buys or takes from the mail could be taken for it.
local WAIT_SECONDS = 5

local function itemID(link)
  return link and tonumber(link:match("|Hitem:(%d+)"))
end

-- Units held of one itemID.
local function count(bags, id)
  local n = 0
  for _, s in ipairs(bags) do
    if s.info and itemID(s.info.hyperlink) == id then
      n = n + (s.info.stackCount or 1)
    end
  end
  return n
end

-- professions: Known Recipes entries by professionID, as Professions.latest() keeps them.
-- Only a spell that's one of their recipeIDs is a craft.
function CraftCapture.new(professions)
  return setmetatable({ professions = professions, results = {} }, CraftCapture)
end

-- The Known Recipe a spell crafts, or nil if it isn't one.
function CraftCapture:knownRecipe(spellID)
  for _, profession in pairs(self.professions) do
    for _, r in ipairs(profession.recipes or {}) do
      if r.recipeID == spellID then
        return r
      end
    end
  end
end

-- The craft before may still wait for its output (a batch, Craft All, or instant crafts
-- in a row), so the bags of the next cast settle it first.
local function settle(self, bags, at)
  if self.pending then
    self:bagsRead(bags, at)
    self:flush()
  end
end

-- bags: every bag slot, as Character.lua reads them ({ info } each).
function CraftCapture:castStarted(spellID, bags, at)
  settle(self, bags, at)
  local r = self:knownRecipe(spellID)
  self.started = r and r.outputItemID and { spellID = spellID, before = count(bags, r.outputItemID) }
end

function CraftCapture:castSucceeded(spellID, bags, at)
  local r = self:knownRecipe(spellID)
  if not r then
    return
  end
  settle(self, bags, at)
  if not r.outputItemID then
    self.results[#self.results + 1] = { recipeID = r.recipeID, at = at }
    return
  end
  -- An instant craft has no cast start, so it counts from the bags as it succeeded.
  local started = self.started
  self.started = nil
  local before = started and started.spellID == spellID and started.before or count(bags, r.outputItemID)
  self.pending = { recipe = r, before = before, at = at }
  self:bagsRead(bags, at)
end

-- Every bag read while a Result waits for its output, at the time it was read.
function CraftCapture:bagsRead(bags, at)
  local p = self.pending
  if not p then
    return
  end
  if at - p.at > WAIT_SECONDS then
    self:flush()
    return
  end
  local made = count(bags, p.recipe.outputItemID) - p.before
  -- More than the recipe makes means another craft's output came with it: no telling
  -- how much was this one's.
  if p.recipe.quantityMax and made > p.recipe.quantityMax then
    self:flush()
  elseif made > 0 then
    self.results[#self.results + 1] = { recipeID = p.recipe.recipeID, at = p.at, quantity = made }
    self.pending = nil
  end
end

-- Records a Result still waiting for its output with no count: at the next cast, at
-- logout, and once it has waited too long.
function CraftCapture:flush()
  if self.pending then
    self.results[#self.results + 1] = { recipeID = self.pending.recipe.recipeID, at = self.pending.at }
    self.pending = nil
  end
end

ns.CraftCapture = CraftCapture
return CraftCapture
