-- Formats copper amounts for display, e.g. 123456 -> "12g 34s 56c", and reads gold typed
-- by the player back as copper.
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

-- What the player typed in a gold box, e.g. "250", "250g" or "12.5", as whole copper.
-- A blank box is nil (no amount) and still ok; anything else is nil and not ok.
function Money.parseGold(text)
  local trimmed = text:lower():match("^%s*(.-)%s*$")
  if trimmed == "" then
    return nil, true
  end
  local number = trimmed:match("^(%d+%.?%d*)%s*g?$") or trimmed:match("^(%.%d+)%s*g?$")
  if not number then
    return nil, false
  end
  return math.floor(tonumber(number) * COPPER_PER_GOLD + 0.5), true
end

-- Copper as the gold a player would type, e.g. 125000 -> "12.5"; "" for nil.
function Money.goldText(copper)
  if not copper then
    return ""
  end
  return (string.format("%.4f", copper / COPPER_PER_GOLD):gsub("0+$", ""):gsub("%.$", ""))
end

ns.Money = Money
return Money
