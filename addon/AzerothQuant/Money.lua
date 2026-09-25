-- Formats copper amounts for display, e.g. 123456 -> "12g 34s 56c".
--
-- Plain Lua with no WoW API calls, so it runs under busted. In game, WoW passes
-- (addonName, namespace) as the file's varargs; under require() the namespace
-- is absent, so the module falls back to a fresh table and is returned instead.
local _, ns = ...
ns = ns or {}

local Money = {}

local COPPER_PER_SILVER = 100
local COPPER_PER_GOLD = 100 * COPPER_PER_SILVER

function Money.format(copper)
  local amount = math.floor(math.abs(copper))
  local sign = (copper < 0 and amount > 0) and "-" or ""

  local gold = math.floor(amount / COPPER_PER_GOLD)
  local silver = math.floor(amount % COPPER_PER_GOLD / COPPER_PER_SILVER)
  local rest = amount % COPPER_PER_SILVER

  local parts = {}
  if gold > 0 then
    parts[#parts + 1] = gold .. "g"
  end
  if silver > 0 then
    parts[#parts + 1] = silver .. "s"
  end
  if rest > 0 or #parts == 0 then
    parts[#parts + 1] = rest .. "c"
  end

  return sign .. table.concat(parts, " ")
end

ns.Money = Money
return Money
