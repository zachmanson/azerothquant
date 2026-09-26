-- Decides when to tell the player a Scan is ready: the moment the Scan cooldown
-- ends while the Auction House is open, if a Scan then would complete an
-- Observation Window with the previous one (ADR-0004).
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

ns.Nudge = Nudge
return Nudge
