-- Shapes one Character Read (a Character's gold and bag contents at logout or /reload,
-- plus its bank and Known Recipes if the player opened them that session) into the table stored in
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

-- Vendor Price by itemID for every filled slot, and how many distinct items had none
-- (not loaded by the client when read). 0 means a vendor won't buy it and is kept.
local function vendorPrices(slotLists)
  local prices, unpriced = {}, {}
  for _, slots in ipairs(slotLists) do
    for _, s in ipairs(slots) do
      local itemID = s.info and tonumber(s.info.hyperlink:match("|Hitem:(%d+)"))
      if itemID and s.sellPrice then
        prices[itemID] = s.sellPrice
      elseif itemID then
        unpriced[itemID] = true
      end
    end
  end
  local missing = 0
  for itemID in pairs(unpriced) do
    if prices[itemID] == nil then
      missing = missing + 1
    end
  end
  return prices, missing
end

-- who: { readAt, realm, character, faction, money }.
-- bagSlots: one per slot, { bag, slot, info, sellPrice }, where info is what
-- C_Container.GetContainerItemInfo returns (nil for an empty slot) and sellPrice is
-- the item's Vendor Price, read along with it (nil if the client hadn't loaded it).
-- bank: { readAt, slots } from the last time the bank was read while open this
-- session, or nil if it wasn't opened. Stale bank contents are never carried forward.
-- professions: KnownRecipes entries by professionID, the latest read of each profession
-- whose window was opened this session. Left out of the Read when there are none.
-- professionList: the professions the Character has, { professionID, professionName }
-- each, or nil if the client couldn't say.
function CharacterRead.build(who, bagSlots, bank, professions, professionList)
  local prices, missing = vendorPrices({ bagSlots, bank and bank.slots or {} })
  return {
    readAt = who.readAt,
    realm = who.realm,
    character = who.character,
    faction = who.faction,
    money = who.money,
    bags = items(bagSlots),
    bankReadAt = bank and bank.readAt,
    bank = bank and items(bank.slots),
    vendorPrices = prices,
    vendorPricesMissing = missing,
    professions = professions and next(professions) and professions or nil,
    professionList = professionList,
  }
end

ns.CharacterRead = CharacterRead
return CharacterRead
