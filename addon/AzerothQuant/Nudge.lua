-- Decides when a Scan is ready (a debug chat line since #53): the moment the
-- Scan cooldown ends while the Auction House is open, if a Scan then would
-- complete an Observation Window with the previous one (ADR-0004). Separately,
-- the Scan button pulses whenever a Scan can run, which is exactly when it's
-- enabled: AH open, cooldown over, no Scan pending (Scanner.lua, #48). And after a
-- load with unimported Scans, it decides when to say the Brain should be done (#71),
-- or that it's behind: Scans saved long ago are still waiting, so brain watch is off (#104).
-- It also times the Scan-ready ping and keeps its /aq ping setting (#180).
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

-- The Scan-ready ping (#180): a chat line and a sound when the cooldown ends, wherever the
-- player is, so a guildie who walked off doesn't forget to Scan. Seconds from `now` until
-- it's due, or nil with no cooldown running: so no ping for someone just questing.
function Nudge.pingIn(lastScanAt, now)
  local left = lastScanAt and lastScanAt + Nudge.COOLDOWN_SECONDS - now
  if left and left > 0 then
    return left
  end
  return nil
end

Nudge.PING_LINE = "You can Scan again at the Auction House."

-- db is AzerothQuantDB. The ping is on unless pingOff is set, so older saves get it too.
function Nudge.pingOn(db)
  return not db.pingOff
end

-- /aq ping.
function Nudge.togglePing(db, say)
  db.pingOff = Nudge.pingOn(db) or nil
  say(Nudge.pingOn(db) and "You'll get a ping when you can Scan again."
    or "No more ping when you can Scan again. /aq ping turns it back on.")
end

-- How long after a load `brain watch` should have imported the Scans it saved and
-- rewritten Recommendations.lua: a guess, since the Addon can't see that file change.
-- Tune it by the "Import took Xs" lines `brain watch` logs, plus its 3 s
-- settle time (#71). A cold pass on the Beta took 59 s (2026-09-29, after #90's Beta
-- Prior): that plus the settle plus a margin. Since ADR-0030 it only times Reload for
-- when the Data slots are missing (LoadTries.lua times the tries), and the clock
-- BRAIN_BEHIND_AFTER runs on.
Nudge.RELOAD_READY_AFTER = 70
Nudge.READY_LINE = "The Brain should be done: Reload to see the new Scan."

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
-- %d: the oldest behind Scan's age in whole minutes. Plain words: guildies read it (#115).
Nudge.BRAIN_BEHIND_LINE = "Your Scan from %d min ago hasn't reached the Brain. Is AzerothQuant Brain running?"
  .. " Start it from the Start menu."

-- The chat line for a Brain behind by `behind` seconds (Nudge.brainBehind).
function Nudge.behindLine(behind)
  return string.format(Nudge.BRAIN_BEHIND_LINE, math.max(1, math.floor(behind / 60)))
end

-- The earliest savedAt among scans, or nil if none has one.
local function oldestSaved(scans)
  local oldest
  for _, scan in ipairs(scans) do
    if scan.savedAt then
      oldest = math.min(oldest or scan.savedAt, scan.savedAt)
    end
  end
  return oldest
end

-- scans: those left after Prune.importedScans at load. Returns how many seconds ago the
-- oldest Scan the Brain should have imported by now was saved, or nil if there's none.
-- A Scan with no savedAt (saved by an older build) never counts.
function Nudge.brainBehind(scans, now)
  local oldest = oldestSaved(scans)
  if oldest and oldest <= now - Nudge.BRAIN_BEHIND_AFTER then
    return now - oldest
  end
  return nil
end

-- How many seconds until the oldest saved Scan counts as behind (Nudge.brainBehind): 0 if
-- one already does, nil with no saved Scans. After every Data slot try came back stale,
-- the Addon checks again then, so a Brain that's off says so in the same session (#176).
function Nudge.behindIn(scans, now)
  local oldest = oldestSaved(scans)
  return oldest and math.max(0, oldest + Nudge.BRAIN_BEHIND_AFTER - now)
end

-- At load, with the Scans left after Prune.importedScans. If the Brain is behind, says so
-- in chat and asks after the Brain app. Otherwise, if any Scans are waiting, waits
-- RELOAD_READY_AFTER seconds, then calls `ready` (which starts Reload's pulse and returns
-- whether chat should say so: not while the Data slots are tried (ADR-0030), nor while
-- the Recommendation frame is open and its banner says it, #161) and says so once (#71).
-- "The Brain should be done" would be a false promise when it's behind, so it's one or
-- the other. `after` and `say` are C_Timer.After
-- and the chat line. While the Brain is catchingUp (Nudge.catchingUp), it does neither:
-- the Scans wait behind its pull, and atLogin already said so. Returns whether the Brain
-- is behind.
function Nudge.afterLoad(scans, now, after, ready, say, catchingUp)
  if catchingUp then
    return false
  end
  local behind = Nudge.brainBehind(scans, now)
  if behind then
    say(Nudge.behindLine(behind))
    return true
  end
  if #scans > 0 then
    after(Nudge.RELOAD_READY_AFTER, function()
      if ready() then
        say(Nudge.READY_LINE)
      end
    end)
  end
  return false
end

-- The Brain's status rides along in Recommendations.lua as brain = { version, problem }
-- (#115). The shipped stub has none, so with no brain table the Brain has never run.
Nudge.NEVER_RUN_LINE = "AzerothQuant needs its Brain app to make recommendations. See the setup guide."
Nudge.PROBLEM_TAIL = " If this keeps happening, send the Brain log (Start menu > AzerothQuant Brain log)"
  .. " to whoever gave you the Brain."

-- A long pull from the Scan Pool (a guildie's first) keeps the Brain from importing for
-- minutes, so it writes brain.catchingUpSince when one starts (#159). One older than this
-- is from a Brain closed mid-pull: past it, the Addon checks on the Brain as usual.
Nudge.CATCHING_UP_FOR = 15 * 60
Nudge.CATCHING_UP_LINE = "AzerothQuant is downloading recent Scans. This takes a few minutes."
  .. " Type /reload after that to see recommendations."

-- With AzerothQuantRecommendations (nil if it didn't load): whether the Brain is busy
-- with a long pull at `now`.
function Nudge.catchingUp(recommendations, now)
  local since = recommendations and recommendations.brain and recommendations.brain.catchingUpSince
  return since ~= nil and now - since < Nudge.CATCHING_UP_FOR
end

-- At login (and /reload), with AzerothQuantRecommendations (nil if it didn't load): says
-- in chat that the Brain has never run, or that it's catching up, or the problem it
-- wrote, or nothing.
function Nudge.atLogin(recommendations, say, now)
  local brain = recommendations and recommendations.brain
  if not brain then
    say(Nudge.NEVER_RUN_LINE)
    return
  end
  if Nudge.catchingUp(recommendations, now) then
    say(Nudge.CATCHING_UP_LINE)
  end
  if brain.problem then
    say(brain.problem .. Nudge.PROBLEM_TAIL)
  end
end

ns.Nudge = Nudge
return Nudge
