-- WoW glue for the Load button (#106, ADR-0021). The Brain writes Recommendations.lua
-- twice: into this Addon, read at startup, and into AzerothQuant_Data, a LoadOnDemand
-- addon the client reads from disk when it's loaded. So when the startup copy is stale
-- (the Brain hadn't finished when the client read it), loading AzerothQuant_Data picks up
-- the Brain's latest without a second reload. It loads at most once per session.
-- Whether a copy is stale is Freshness.lua's call; this file only talks to the WoW API.
--
-- Read-only: nothing here buys, posts or cancels (ADR-0003).
local _, ns = ...
local Freshness = ns.Freshness
local Prune = ns.Prune
local Chat = ns.Chat

local DATA_ADDON = "AzerothQuant_Data"
local MISSING_LINE = "Restart the client once so Load can skip the second reload."
local STALE_LINE = "The Brain wasn't done: these Recommendations are from before your last reload."
  .. " Reload to try again."

local db
-- Whether AzerothQuant_Data is installed (the Brain creates it; the client only finds a
-- new addon folder when it starts), whether the startup copy was stale, and whether Load
-- has been used this session.
local exists, stale, loaded = false, false, false

local function dataAddonExists()
  local _, _, _, _, reason = C_AddOns.GetAddOnInfo(DATA_ADDON)
  return reason ~= "MISSING"
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:SetScript("OnEvent", function(_, event, arg1)
  if event == "ADDON_LOADED" and arg1 == "AzerothQuant" then
    AzerothQuantDB = AzerothQuantDB or {}
    db = AzerothQuantDB
    -- The same answer before or after the other files prune at load: they only delete
    -- what this copy has imported.
    stale = not Freshness.isFresh(AzerothQuantRecommendations, db.scans or {}, db.lastSavedRead)
    exists = dataAddonExists()
    if not exists then
      Chat.debug(MISSING_LINE)
    end
  end
end)

ns.DataAddon = {
  -- True while Load would bring something newer: the startup copy is stale, the Data
  -- addon is there, and Load hasn't been used yet. Otherwise the button is Reload.
  canLoad = function()
    return exists and stale and not loaded
  end,
  loaded = function()
    return loaded
  end,
  -- Loads AzerothQuant_Data, which overwrites AzerothQuantRecommendations with its copy.
  -- Keeps that copy only if it's newer than the startup one (Freshness.covers), then
  -- prunes again with its stamps. Returns whether the copy is fresh, or nil if nothing
  -- loaded.
  load = function()
    if not ns.DataAddon.canLoad() then
      return nil
    end
    loaded = true
    local startup = AzerothQuantRecommendations
    local ok, reason = C_AddOns.LoadAddOn(DATA_ADDON)
    if not ok then
      AzerothQuantRecommendations = startup
      Chat.say(string.format("Couldn't load %s (%s): Reload instead.", DATA_ADDON, tostring(reason)))
      return nil
    end
    if not Freshness.covers(AzerothQuantRecommendations, startup) then
      AzerothQuantRecommendations = startup
    end
    local recommendations = AzerothQuantRecommendations
    Prune.importedScans(db.scans, recommendations)
    Prune.importedMailboxReads(db.mailboxReads, recommendations)
    Prune.importedCharacterReads(db.characterReads, recommendations)
    local fresh = Freshness.isFresh(recommendations, db.scans, db.lastSavedRead)
    if not fresh then
      Chat.say(STALE_LINE)
    end
    return fresh
  end,
}
