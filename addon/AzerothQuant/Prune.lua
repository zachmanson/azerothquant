-- Deletes the Scans, Mailbox Reads and Character Reads the Brain no longer needs from
-- SavedVariables, so the file (rewritten whole on every /reload) doesn't keep growing.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for
-- the namespace fallback.
local _, ns = ...
ns = ns or {}

local Prune = {}

-- Removes, in place, every entry of the sequence that isImported says yes to, keeping
-- the rest in order with no gaps. Returns how many were removed.
local function removeImported(list, isImported)
  local kept = 0
  local n = #list
  for i = 1, n do
    local entry = list[i]
    if not isImported(entry) then
      kept = kept + 1
      list[kept] = entry
    end
  end
  for i = kept + 1, n do
    list[i] = nil
  end
  return n - kept
end

-- Removes every Read taken at or before lastRead[realm][character]; nil lastRead
-- (the Brain hasn't imported any yet) removes nothing.
local function removeReadsUpTo(reads, lastRead)
  if not lastRead then
    return 0
  end
  return removeImported(reads, function(r)
    local byCharacter = r.realm and lastRead[r.realm]
    local cutoff = byCharacter and r.character and byCharacter[r.character]
    return cutoff and r.readAt and r.readAt <= cutoff
  end)
end

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

  return removeImported(scans, function(s)
    local byFaction = s.realm and lastImported[s.realm]
    local cutoff = byFaction and s.faction and byFaction[s.faction]
    return cutoff and s.requestedAt and s.requestedAt <= cutoff
  end)
end

-- reads: AzerothQuantDB.mailboxReads. Deletes every Read taken at or before its
-- Character's lastMailboxRead time. The Brain imports Reads whatever their order, so
-- all of those are archived already. Returns how many were deleted.
function Prune.importedMailboxReads(reads, recommendations)
  return removeReadsUpTo(reads, recommendations and recommendations.lastMailboxRead)
end

-- reads: AzerothQuantDB.characterReads. Deletes every Read taken at or before its
-- Character's lastCharacterRead time, which are all archived already. Returns how many
-- were deleted.
function Prune.importedCharacterReads(reads, recommendations)
  return removeReadsUpTo(reads, recommendations and recommendations.lastCharacterRead)
end

ns.Prune = Prune
return Prune
