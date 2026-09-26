-- Shapes one Character Read (a Character's gold and bag contents at logout or /reload,
-- plus its bank if the player opened it that session) into the table stored in
-- SavedVariables. Items are kept raw; the Brain derives Item Keys from the links.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for
-- the namespace fallback.
local _, ns = ...
ns = ns or {}

local CharacterRead = {}

-- Filled slots only, each as { bag, slot, link, count, isBound }.
local function items(slots)
  local kept = {}
  for _, s in ipairs(slots) do
    if s.info then
      kept[#kept + 1] = {
        bag = s.bag,
        slot = s.slot,
        link = s.info.hyperlink,
        count = s.info.stackCount,
        isBound = s.info.isBound,
      }
    end
  end
  return kept
end

-- who: { readAt, realm, character, faction, money }.
-- bagSlots: one per slot, { bag, slot, info }, where info is what
-- C_Container.GetContainerItemInfo returns (nil for an empty slot).
-- bank: { readAt, slots } from the last time the bank was read while open this
-- session, or nil if it wasn't opened. Stale bank contents are never carried forward.
function CharacterRead.build(who, bagSlots, bank)
  return {
    readAt = who.readAt,
    realm = who.realm,
    character = who.character,
    faction = who.faction,
    money = who.money,
    bags = items(bagSlots),
    bankReadAt = bank and bank.readAt,
    bank = bank and items(bank.slots),
  }
end

ns.CharacterRead = CharacterRead
return CharacterRead
