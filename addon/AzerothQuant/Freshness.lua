-- Says whether a copy of Recommendations.lua has caught up with what the last logout (or
-- /reload) saved for the Brain, from the stamps the file already carries (ADR-0021). The
-- startup copy that isn't fresh is what the Load button (DataAddon.lua) is for.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for
-- the namespace fallback.
local _, ns = ...
ns = ns or {}

local Freshness = {}

local function stamp(stamps, realm, key)
  local byKey = stamps and realm and stamps[realm]
  return byKey and key and byKey[key]
end

-- recommendations: AzerothQuantRecommendations (a copy of Recommendations.lua), or nil.
-- scans: AzerothQuantDB.scans. Only those with savedAt were saved; the rest were taken
-- since the load and are still only in memory. lastSavedRead: { realm, character, readAt }
-- of the Character Read the last logout saved, or nil if there wasn't one. A Character
-- Read is saved on every reload, so it's what shows the Brain ran after it.
function Freshness.isFresh(recommendations, scans, lastSavedRead)
  local recs = recommendations or {}
  if lastSavedRead then
    local read = stamp(recs.lastCharacterRead, lastSavedRead.realm, lastSavedRead.character)
    if not (read and read >= lastSavedRead.readAt) then
      return false
    end
  end
  for _, scan in ipairs(scans) do
    if scan.savedAt then
      local imported = stamp(recs.lastImported, scan.realm, scan.faction)
      if not (imported and imported >= scan.requestedAt) then
        return false
      end
    end
  end
  return true
end

local STAMPS = { "lastImported", "lastMailboxRead", "lastCharacterRead" }

-- Whether newer has imported at least as far as older in every Market and Character
-- older has a stamp for, so switching the table to newer can't undo an import. This is
-- how the Data copy counts as newer than the startup one. A nil newer covers nothing.
function Freshness.covers(newer, older)
  if not newer then
    return false
  end
  for _, name in ipairs(STAMPS) do
    for realm, byKey in pairs(older and older[name] or {}) do
      for key, at in pairs(byKey) do
        local newAt = stamp(newer[name], realm, key)
        if not (newAt and newAt >= at) then
          return false
        end
      end
    end
  end
  return true
end

ns.Freshness = Freshness
return Freshness
