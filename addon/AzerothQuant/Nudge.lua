-- Decides when to tell the player in chat that a Scan is ready: the moment the
-- Scan cooldown ends while the Auction House is open, if a Scan then would
-- complete an Observation Window with the previous one (ADR-0004). Separately,
-- the Scan button pulses whenever a Scan can run, which is exactly when it's
-- enabled: AH open, cooldown over, no Scan pending (Scanner.lua, #48).
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
-- Tune it by the "Imported N new Scans in Xs" lines `brain watch` logs, plus its 3 s
-- settle time (#71).
Nudge.RELOAD_READY_AFTER = 10
Nudge.RELOAD_READY_LINE = "The Brain should be done: Reload to see the new Scan."

-- On a load with `unimported` saved Scans, waits RELOAD_READY_AFTER seconds, then
-- starts the Reload button's pulse and says so in chat once. `after`, `pulse` and `say`
-- are C_Timer.After, the pulse and the chat line.
function Nudge.whenReloadReady(unimported, after, pulse, say)
  if unimported == 0 then
    return
  end
  after(Nudge.RELOAD_READY_AFTER, function()
    pulse()
    say(Nudge.RELOAD_READY_LINE)
  end)
end

ns.Nudge = Nudge
return Nudge
