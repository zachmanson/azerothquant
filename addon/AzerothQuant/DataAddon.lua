-- WoW glue for the Data slots (ADR-0030). The Brain writes Recommendations.lua into this
-- Addon, read at startup, and into three LoadOnDemand slots, AzerothQuant_Data1..3, each
-- read from disk the first time it's loaded. So when the startup copy is stale (the Brain
-- hadn't finished when the client read it), loading a slot picks up the Brain's latest
-- without a second reload, and each slot is one try. Scanner.lua runs the tries
-- (LoadTries.lua says when); whether a copy is stale is Freshness.lua's call. This file
-- only talks to the WoW API.
--
-- Read-only: nothing here buys, posts or cancels (ADR-0003).
local _, ns = ...
local Freshness = ns.Freshness
local Prune = ns.Prune
local Chat = ns.Chat

local SLOTS = { "AzerothQuant_Data1", "AzerothQuant_Data2", "AzerothQuant_Data3" }
local MISSING_LINE = "Restart the client once so new recommendations show without a second reload."

local db
-- The slots installed (the Brain creates them; the client only finds a new addon folder
-- when it starts), and whether the startup copy was stale.
local slots, stale = {}, false

local function slotExists(slot)
  local _, _, _, _, reason = C_AddOns.GetAddOnInfo(slot)
  return reason ~= "MISSING"
end

ns.DataAddon = {
  -- At ADDON_LOADED, with AzerothQuantDB. The same answer before or after the other files
  -- prune at load: they only delete what this copy has imported.
  atLoad = function(savedVariables)
    db = savedVariables
    stale = not Freshness.isFresh(AzerothQuantRecommendations, db.scans or {}, db.lastSavedRead)
    slots = {}
    for _, slot in ipairs(SLOTS) do
      if slotExists(slot) then
        table.insert(slots, slot)
      end
    end
    if #slots == 0 then
      Chat.debug(MISSING_LINE)
    end
  end,
  -- The slots to try, in order: none when the startup copy is fresh.
  slotsToTry = function()
    return stale and slots or {}
  end,
  -- Loads a slot, which overwrites AzerothQuantRecommendations with its copy. Keeps that
  -- copy only if it's newer than the one shown (Freshness.covers), then prunes again with
  -- its stamps. Returns whether the copy is fresh, or nil if the slot didn't load.
  load = function(slot)
    local shown = AzerothQuantRecommendations
    local ok, reason = C_AddOns.LoadAddOn(slot)
    if not ok then
      AzerothQuantRecommendations = shown
      -- DISABLED when it's unticked in the AddOns list.
      Chat.say(string.format("Couldn't load %s (%s). Tick it in the AddOns list, or Reload instead.",
        slot, tostring(reason)))
      return nil
    end
    if not Freshness.covers(AzerothQuantRecommendations, shown) then
      AzerothQuantRecommendations = shown
    end
    local recommendations = AzerothQuantRecommendations
    Prune.importedScans(db.scans, recommendations)
    Prune.importedMailboxReads(db.mailboxReads, recommendations)
    Prune.importedCharacterReads(db.characterReads, recommendations)
    return Freshness.isFresh(recommendations, db.scans, db.lastSavedRead)
  end,
}
