-- WoW glue for Character Reads: on every logout or /reload (PLAYER_LOGOUT fires for
-- both), records the Character's gold, bags and, if the bank was opened this session,
-- the bank to AzerothQuantDB.characterReads, along with the Known Recipes and profession
-- list Professions.lua has kept and the Merchant Costs Merchant.lua has. All shaping
-- happens in CharacterRead.lua; this file only talks to the WoW API. On load it also deletes the Reads the Brain has
-- imported (Prune.lua).
--
-- Gold and bags are read while in the world and kept in memory, like the bank: on a
-- real logout (not /reload) the client has already emptied them by PLAYER_LOGOUT, so
-- reading them there records 0 gold and empty bags.
--
-- Read-only (ADR-0003): only calls that read gold, containers, item info and who the player is.
-- Nothing that moves, uses or deletes items.
local _, ns = ...
local CharacterRead = ns.CharacterRead
local Scan = ns.Scan
local RecommendationTable = ns.RecommendationTable
local Prune = ns.Prune
local Chat = ns.Chat
local Professions = ns.Professions
local Merchant = ns.Merchant

-- The bank can only be read while it's open. Bag updates come in bursts (one per bag
-- touched), so read once they have been quiet this long.
local QUIET_SECONDS = 0.5

-- Container IDs, from the client's constants where it defines them.
local BACKPACK = BACKPACK_CONTAINER or 0
local BAG_SLOTS = NUM_BAG_SLOTS or 4
local BANK = BANK_CONTAINER or -1
local BANK_BAG_SLOTS = NUM_BANKBAGSLOTS or 6

-- C_Container on newer clients, the old globals otherwise.
local numSlots, itemInfo
if C_Container then
  numSlots = C_Container.GetContainerNumSlots
  itemInfo = C_Container.GetContainerItemInfo
else
  numSlots = GetContainerNumSlots
  -- Packed into the table C_Container returns, so CharacterRead sees one shape.
  itemInfo = function(bag, slot)
    local _, count, _, _, _, _, link, _, _, _, isBound = GetContainerItemInfo(bag, slot)
    if not link then
      return nil
    end
    return { hyperlink = link, stackCount = count, isBound = isBound }
  end
end

-- C_Item on newer clients (the Beta has no global GetItemInfo), the old global otherwise.
local getItemInfo = C_Item and C_Item.GetItemInfo or GetItemInfo

local db
local atBank = false
local bank -- { readAt, slots }: the latest read while the bank was open this session
local carried -- { money, slots }: the latest read of gold and bags while in the world
local timer
local carriedTimer

local function readContainers(bags, into)
  for _, bag in ipairs(bags) do
    for slot = 1, numSlots(bag) or 0 do
      local info = itemInfo(bag, slot)
      -- The Vendor Price is read now, with the item, rather than at logout. GetItemInfo's
      -- 11th return; nil until the client has loaded the item.
      local sellPrice = info and select(11, getItemInfo(info.hyperlink))
      -- For its Disenchant source group (#76): a bound item never shows up in a Scan.
      local disenchant = info and Scan.fromGetItemInfo(getItemInfo(info.hyperlink))
      into[#into + 1] = { bag = bag, slot = slot, info = info, sellPrice = sellPrice, itemInfo = disenchant }
    end
  end
  return into
end

local function bagIds()
  local ids = {}
  for bag = BACKPACK, BACKPACK + BAG_SLOTS do
    ids[#ids + 1] = bag
  end
  return ids
end

local function bankIds()
  local ids = { BANK }
  for bag = BAG_SLOTS + 1, BAG_SLOTS + BANK_BAG_SLOTS do
    ids[#ids + 1] = bag
  end
  return ids
end

local function readBank()
  timer = nil
  -- The main bank reports no slots once it can't be read; keep the last good read then.
  if (numSlots(BANK) or 0) == 0 then
    return
  end
  bank = { readAt = time(), slots = readContainers(bankIds(), {}) }
end

local function readCarried()
  carriedTimer = nil
  -- The backpack reports no slots once it can't be read; keep the last good read then.
  if (numSlots(BACKPACK) or 0) == 0 then
    return
  end
  carried = { money = GetMoney(), slots = readContainers(bagIds(), {}) }
end

local function readCarriedSoon()
  if carriedTimer then
    carriedTimer:Cancel()
  end
  carriedTimer = C_Timer.NewTimer(QUIET_SECONDS, readCarried)
end

local function cancel()
  if timer then
    timer:Cancel()
    timer = nil
  end
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("BANKFRAME_OPENED")
frame:RegisterEvent("BANKFRAME_CLOSED")
frame:RegisterEvent("BAG_UPDATE")
frame:RegisterEvent("PLAYERBANKSLOTS_CHANGED")
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:RegisterEvent("PLAYER_MONEY")
frame:RegisterEvent("PLAYER_LOGOUT")
frame:SetScript("OnEvent", function(_, event, arg1)
  if event == "ADDON_LOADED" then
    if arg1 == "AzerothQuant" then
      AzerothQuantDB = AzerothQuantDB or {}
      db = AzerothQuantDB
      db.characterReads = db.characterReads or {}
      -- Recommendations.lua has loaded by now (it's in the TOC), as has SavedVariables.
      local pruned = Prune.importedCharacterReads(db.characterReads, AzerothQuantRecommendations)
      if pruned > 0 then
        Chat.debug(string.format("Deleted %d Character Reads the Brain has imported.", pruned))
      end
    end
  elseif event == "BANKFRAME_OPENED" then
    atBank = true
    cancel()
    readBank()
  elseif event == "PLAYER_ENTERING_WORLD" then
    readCarried()
  elseif event == "PLAYER_MONEY" then
    readCarriedSoon()
  elseif event == "BAG_UPDATE" or event == "PLAYERBANKSLOTS_CHANGED" then
    readCarriedSoon()
    if atBank then
      cancel()
      timer = C_Timer.NewTimer(QUIET_SECONDS, readBank)
    end
  elseif event == "BANKFRAME_CLOSED" then
    -- Catch a change still waiting out the quiet time before the bank closes for good.
    if atBank and timer then
      cancel()
      readBank()
    end
    atBank = false
  elseif event == "PLAYER_LOGOUT" then
    -- Anything added to SavedVariables here is saved, on logout and on /reload alike.
    -- Never read gold or bags here (see top); with no good read this session, skip it.
    if not carried then
      return
    end
    local realm, faction = GetRealmName(), UnitFactionGroup("player")
    local read = CharacterRead.build({
      readAt = time(),
      realm = realm,
      character = table.concat({ UnitFullName("player") }, "-"),
      faction = faction,
      money = carried.money,
      budget = faction and db.budgets and db.budgets[RecommendationTable.budgetKey(realm, faction)],
    }, carried.slots, bank, Professions.latest(), Professions.list(), Merchant.costs())
    table.insert(db.characterReads, read)
  end
end)
