-- WoW glue for Character Reads: on every logout or /reload (PLAYER_LOGOUT fires for
-- both), records the Character's gold, bags and, if the bank was opened this session,
-- the bank to AzerothQuantDB.characterReads, along with the Known Recipes and profession
-- list Professions.lua has kept, the Merchant Costs Merchant.lua has and this session's
-- Disenchant Results (DisenchantCapture.lua) and Craft Results (CraftCapture.lua, #44),
-- both fed here since they need the bags. All shaping
-- happens in CharacterRead.lua; this file only talks to the WoW API. On load it also deletes the Reads the Brain has
-- imported (Prune.lua).
--
-- It also shows Loot Alerts (#54, LootAlert.lua): a drop the Brain says is worth at least
-- its threshold gets raid-warning text, a sound and a chat line. A Disenchant's mats get
-- none, which is why it lives here, beside the Disenchant capture.
--
-- Gold and bags are read while in the world and kept in memory, like the bank: on a
-- real logout (not /reload) the client has already emptied them by PLAYER_LOGOUT, so
-- reading them there records 0 gold and empty bags.
--
-- Read-only (ADR-0003): only calls that read gold, containers, item info, the loot window
-- and who the player is, and the Loot Alert's display. Nothing that moves, uses, loots or
-- deletes items.
local _, ns = ...
local CharacterRead = ns.CharacterRead
local Scan = ns.Scan
local RecommendationTable = ns.RecommendationTable
local Prune = ns.Prune
local Chat = ns.Chat
local Professions = ns.Professions
local Merchant = ns.Merchant
local DisenchantCapture = ns.DisenchantCapture
local CraftCapture = ns.CraftCapture
local LootAlert = ns.LootAlert
local ContainerIds = ns.ContainerIds

local DISENCHANT_SPELL = 13262

-- The bank can only be read while it's open. Bag updates come in bursts (one per bag
-- touched), so read once they have been quiet this long.
local QUIET_SECONDS = 0.5

-- Container IDs, from the client's constants where it defines them (ContainerIds.lua).
local BACKPACK = BACKPACK_CONTAINER or 0
local BANK = BANK_CONTAINER or -1
local CONTAINER_CONSTANTS = {
  BACKPACK_CONTAINER = BACKPACK_CONTAINER,
  NUM_BAG_SLOTS = NUM_BAG_SLOTS,
  -- The Classic Beta has the Reagent Bag but not this global, only the enum (#133).
  REAGENTBAG_CONTAINER = REAGENTBAG_CONTAINER or (Enum and Enum.BagIndex and Enum.BagIndex.ReagentBag),
  NUM_REAGENTBAG_SLOTS = NUM_REAGENTBAG_SLOTS,
  NUM_TOTAL_EQUIPPED_BAG_SLOTS = NUM_TOTAL_EQUIPPED_BAG_SLOTS,
  BANK_CONTAINER = BANK_CONTAINER,
  NUM_BANKBAGSLOTS = NUM_BANKBAGSLOTS,
}

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
local disenchants = DisenchantCapture.new()
-- Professions.latest() is the live table Professions.lua fills as windows are read.
local crafts = CraftCapture.new(Professions.latest())

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
  return ContainerIds.bags(CONTAINER_CONSTANTS)
end

local function bankIds()
  return ContainerIds.bank(CONTAINER_CONSTANTS)
end

-- The Post button finds what it posts in the same bags (#81).
ns.Character = { bagIds = bagIds }

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
  -- The Disenchanted item may leave the bags only after its loot window opens.
  disenchants:bagsRead(carried.slots, time())
  -- So may a craft's output.
  crafts:bagsRead(carried.slots, time())
end

-- The loot window's item slots, { link, quantity } each. Money has no link.
local function lootSlots()
  local loot = {}
  for i = 1, GetNumLootItems() do
    local link = GetLootSlotLink(i)
    if link then
      loot[#loot + 1] = { link = link, quantity = select(3, GetLootSlotInfo(i)) or 1 }
    end
  end
  return loot
end

-- A Loot Alert for a CHAT_MSG_LOOT line, if it's the player's own drop and worth one.
local function alertLoot(msg)
  local now = time()
  if disenchants:isDisenchantLoot(now) then
    return
  end
  local saved = AzerothQuantRecommendations
  local formats = { single = LOOT_ITEM_SELF, multiple = LOOT_ITEM_SELF_MULTIPLE }
  local realm, faction = GetRealmName(), UnitFactionGroup("player")
  local line = LootAlert.forMessage(saved and saved.recommendations, realm, faction, msg, formats, now)
  if not line then
    return
  end
  RaidNotice_AddMessage(RaidWarningFrame, line, ChatTypeInfo["RAID_WARNING"])
  PlaySound(SOUNDKIT.RAID_WARNING)
  -- Not Chat.say: the line carries its own "AQ:" prefix, like the tooltip lines.
  print(line)
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
frame:RegisterEvent("LOOT_READY")
frame:RegisterEvent("LOOT_CLOSED")
frame:RegisterEvent("CHAT_MSG_LOOT")
frame:RegisterUnitEvent("UNIT_SPELLCAST_START", "player")
frame:RegisterUnitEvent("UNIT_SPELLCAST_SUCCEEDED", "player")
frame:SetScript("OnEvent", function(_, event, arg1, _, arg3)
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
  elseif event == "UNIT_SPELLCAST_START" then
    -- The item is still in the bags while the cast runs (unit, castGUID, spellID).
    if arg3 == DISENCHANT_SPELL then
      disenchants:castStarted(readContainers(bagIds(), {}))
    elseif crafts:knownRecipe(arg3) then
      crafts:castStarted(arg3, readContainers(bagIds(), {}), time())
    end
  elseif event == "UNIT_SPELLCAST_SUCCEEDED" then
    if arg3 == DISENCHANT_SPELL then
      disenchants:castSucceeded()
    elseif crafts:knownRecipe(arg3) then
      crafts:castSucceeded(arg3, readContainers(bagIds(), {}), time())
    end
  elseif event == "LOOT_READY" then
    disenchants:lootReady(lootSlots(), readContainers(bagIds(), {}), time())
  elseif event == "LOOT_CLOSED" then
    disenchants:lootClosed(time())
  elseif event == "CHAT_MSG_LOOT" then
    alertLoot(arg1)
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
      -- No Read this logout, so none for the next load's freshness check to wait on.
      db.lastSavedRead = nil
      return
    end
    disenchants:flush()
    crafts:flush()
    local realm, faction = GetRealmName(), UnitFactionGroup("player")
    local market = faction and RecommendationTable.marketKey(realm, faction)
    local read = CharacterRead.build({
      readAt = time(),
      realm = realm,
      character = table.concat({ UnitFullName("player") }, "-"),
      faction = faction,
      money = carried.money,
      budget = market and db.budgets and db.budgets[market],
      daysToSell = market and db.daysToSell and db.daysToSell[market],
    }, carried.slots, bank, Professions.latest(), Professions.list(), Merchant.costs(), disenchants.results,
      crafts.results
    )
    table.insert(db.characterReads, read)
    -- Kept apart from characterReads (pruned) so the next load can tell whether a copy of
    -- Recommendations.lua has caught up with this logout (Freshness.lua, #106).
    db.lastSavedRead = { realm = read.realm, character = read.character, readAt = read.readAt }
  end
end)
