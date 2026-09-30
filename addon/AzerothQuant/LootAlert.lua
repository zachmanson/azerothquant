-- Loot Alerts (#54): a drop worth at least the Brain's threshold for one unit, named in
-- chat as "AQ: [link] x3: 45g each, 135g (Sell)". The Brain writes which Item Keys clear
-- it, and at what Best Exit Value, as each Market's lootAlert (see Recommendations.lua).
-- The glue (Character.lua) feeds it CHAT_MSG_LOOT and shows what it returns.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for
-- the namespace fallback.
local _, ns = ...
ns = ns or {}

local Money = ns.Money or require("Money")
local TooltipLines = ns.TooltipLines or require("TooltipLines")

local LootAlert = {}

local DAY_SECONDS = 24 * 3600

-- A client format string ("You receive loot: %s.") as an anchored Lua pattern that
-- captures its %s and %d. A locale whose strings reorder them ("%1$s") never matches.
local function pattern(format)
  local escaped = format:gsub("[%^%$%(%)%.%[%]%*%+%-%?]", "%%%0")
  return "^" .. escaped:gsub("%%s", "(.+)"):gsub("%%d", "(%%d+)") .. "$"
end

-- The link and quantity in a loot line of the player's own, or nil for any other line.
-- formats is the client's { single = LOOT_ITEM_SELF, multiple = LOOT_ITEM_SELF_MULTIPLE }.
local function parse(msg, formats)
  local link, quantity = msg:match(pattern(formats.multiple))
  if link then
    return link, tonumber(quantity)
  end
  link = msg:match(pattern(formats.single))
  return link, 1
end

-- The chat line for a loot message, or nil if it isn't the player's own loot of an Item
-- Key the Market's lootAlert lists. now is the time (time()), to say when the prices
-- are over a day old.
function LootAlert.forMessage(recommendations, realm, faction, msg, formats, now)
  local entry = recommendations and recommendations[realm] and recommendations[realm][faction]
  local items = entry and entry.lootAlert and entry.lootAlert.items
  local link, quantity = parse(msg, formats)
  local item = items and link and items[TooltipLines.itemKey(link)]
  if not item then
    return nil
  end
  local worth = Money.format(item.value)
  if quantity > 1 then
    link = link .. " x" .. quantity
    worth = worth .. " each, " .. Money.format(item.value * quantity)
  end
  local line = "AQ: " .. link .. ": " .. worth .. " (" .. item.action .. ")"
  local age = now - (entry.asOf or now)
  if age > DAY_SECONDS then
    line = line .. string.format(" (prices %dd old)", math.floor(age / DAY_SECONDS))
  end
  return line
end

ns.LootAlert = LootAlert
return LootAlert
