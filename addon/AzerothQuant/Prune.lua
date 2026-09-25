-- Deletes the Scans the Brain no longer needs from SavedVariables, so the file
-- (rewritten whole on every /reload) doesn't keep growing.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for
-- the namespace fallback.
local _, ns = ...
ns = ns or {}

local Prune = {}

-- scans: AzerothQuantDB.scans. recommendations: AzerothQuantRecommendations as the
-- Brain wrote it (Recommendations.lua), or nil if the Brain has never run.
--
-- Deletes every Scan requested at or before its Market's lastImported time. Each
-- of those is either imported already or older than one that is, which the Brain
-- rejects, so none can be of any more use. Scans are keyed by time, not id: the id
-- counts per WoW account, but Recommendations.lua is shared by every account.
-- Returns how many were deleted.
function Prune.importedScans(scans, recommendations)
  local lastImported = recommendations and recommendations.lastImported
  if not lastImported then
    return 0
  end

  local kept = 0
  local n = #scans
  for i = 1, n do
    local s = scans[i]
    local byFaction = s.realm and lastImported[s.realm]
    local cutoff = byFaction and s.faction and byFaction[s.faction]
    if not (cutoff and s.requestedAt and s.requestedAt <= cutoff) then
      kept = kept + 1
      scans[kept] = s
    end
  end
  for i = kept + 1, n do
    scans[i] = nil
  end
  return n - kept
end

ns.Prune = Prune
return Prune
