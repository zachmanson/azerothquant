-- Decides when a Scan is ready (a debug chat line since #53): the moment the
-- Scan cooldown ends while the Auction House is open, if a Scan then would
-- complete an Observation Window with the previous one (ADR-0004). Separately,
-- the Scan button pulses whenever a Scan can run, which is exactly when it's
-- enabled: AH open, cooldown over, no Scan pending (Scanner.lua, #48). And after a
-- load with unimported Scans, it decides when to say the Brain should be done (#71),
-- or that it's behind: Scans saved long ago are still waiting, so brain watch is off (#104).
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for
-- the namespace fallback.
local _, ns = ...
ns = ns or {}

local Nudge = {}

-- The server silently ignores a re-scan inside ~15 min (spike #1).
Nudge.COOLDOWN_SECONDS = 15 * 60
-- Mirrors the Brain's default observation_window_max_minutes (brain/src/brain/config.py).
Nudge.WINDOW_CAP_SECONDS = 60 * 60

-- lastScanAt: when the previous Scan was requested, or nil if there wasn't one.
-- since: the last time this was checked while the Auction House was open (the
-- time it opened, on the first check), so a cooldown that ended before then, or
-- was already nudged, doesn't count. now: the current time.
function Nudge.due(lastScanAt, since, now)
  if not lastScanAt then
    return false
  end
  local readyAt = lastScanAt + Nudge.COOLDOWN_SECONDS
  -- The Brain counts a gap of exactly the cap as an Observation Window.
  return since < readyAt and readyAt <= now and now - lastScanAt <= Nudge.WINDOW_CAP_SECONDS
end

-- How long after a load `brain watch` should have imported the Scans it saved and
-- rewritten Recommendations.lua: a guess, since the Addon can't see that file change.
-- Tune it by the "Import took Xs" lines `brain watch` logs, plus its 3 s
-- settle time (#71). Real imports on the Beta took 33-42 s (2026-09-28).
Nudge.RELOAD_READY_AFTER = 50
Nudge.RELOAD_READY_LINE = "The Brain should be done: Reload to see the new Scan."

-- Called at PLAYER_LOGOUT (which a /reload fires too), as SavedVariables is written:
-- stamps every Scan saved for the first time with savedAt = now. One saved before keeps
-- its stamp, so savedAt is when the Scan first reached the file the Brain reads (#104).
function Nudge.stampSaved(scans, now)
  for _, scan in ipairs(scans) do
    scan.savedAt = scan.savedAt or now
  end
end

-- A Scan saved this long ago that's still in SavedVariables after pruning means the
-- Brain didn't import it: long enough for `brain watch` to have done it, with a margin.
Nudge.BRAIN_BEHIND_AFTER = Nudge.RELOAD_READY_AFTER + 60
-- %d: the oldest behind Scan's age in whole minutes.
Nudge.BRAIN_BEHIND_LINE = "The Brain hasn't imported Scans saved %d min ago. Is brain watch running?"
  .. " (scripts\\play.bat)"

-- scans: those left after Prune.importedScans at load. Returns how many seconds ago the
-- oldest Scan the Brain should have imported by now was saved, or nil if there's none.
-- A Scan with no savedAt (saved by an older build) never counts.
function Nudge.brainBehind(scans, now)
  local oldest
  for _, scan in ipairs(scans) do
    if scan.savedAt and scan.savedAt <= now - Nudge.BRAIN_BEHIND_AFTER then
      oldest = math.min(oldest or scan.savedAt, scan.savedAt)
    end
  end
  return oldest and now - oldest
end

-- At load, with the Scans left after Prune.importedScans. If the Brain is behind, says so
-- in chat and asks after brain watch. Otherwise, if any Scans are waiting, waits
-- RELOAD_READY_AFTER seconds, then calls `ready` (which starts the Reload button's pulse)
-- and says so in chat once (#71). "The Brain should be done" would be a false promise
-- when it's behind, so it's one or the other. `after` and `say` are C_Timer.After and the
-- chat line. Returns whether the Brain is behind.
function Nudge.afterLoad(scans, now, after, ready, say)
  local behind = Nudge.brainBehind(scans, now)
  if behind then
    local minutes = math.max(1, math.floor(behind / 60))
    say(string.format(Nudge.BRAIN_BEHIND_LINE, minutes))
    return true
  end
  if #scans > 0 then
    after(Nudge.RELOAD_READY_AFTER, function()
      ready()
      say(Nudge.RELOAD_READY_LINE)
    end)
  end
  return false
end

ns.Nudge = Nudge
return Nudge
