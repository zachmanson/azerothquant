-- The one next step in the Scan, Reload, Load loop, for the banner under the
-- Recommendation frame's tabs (#161, #158 layout D): what to do now, and the one button
-- that does it.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for
-- the namespace fallback.
local _, ns = ...
ns = ns or {}
-- In game Nudge.lua loads first (see the .toc), so require, which WoW lacks, isn't reached.
local Nudge = ns.Nudge or require("Nudge")

local NextStep = {}

-- loop: what the Addon knows, as RecommendationFrame.lua gathers it each frame:
--   scanning (Scanner.busy), ahOpen, unsaved and unimported and behind (Scanner.waiting),
--   catchingUp (Nudge.catchingUp), brainRan (Recommendations.lua has a brain table),
--   trying and tookLonger (DataAddon: Data slots still to try, every slot tried stale),
--   reloadReady (Scanner.reloadReady), lastScanAt.
-- now: GetServerTime(), the clock lastScanAt is on. Returns the banner:
-- { title, line, button ("Scan", "Scanning...", "Reload" or nil for none), action
-- (what the button does: "scan", "busy" or "reload"), enabled, pulse, warn (orange),
-- quiet (one line, no title or button) }.
function NextStep.of(loop, now)
  -- A reload now would lose the Scan, so this comes before every other step.
  if loop.scanning then
    return {
      title = "Scanning...",
      line = "Keep the Auction House open until the Scan is saved.",
      button = "Scanning...",
      action = "busy",
      enabled = false,
      pulse = false,
    }
  end
  -- A Scan taken since the last reload reaches the Brain only on the next one.
  if loop.unsaved > 0 then
    return {
      title = "Send your Scan to the Brain",
      line = "Scan saved. Reload to hand it to the Brain app.",
      button = "Reload",
      action = "reload",
      enabled = true,
      pulse = true,
    }
  end
  -- A long pull keeps the Brain from importing for minutes, and it isn't behind (#159).
  if loop.catchingUp then
    return {
      title = "Downloading guild Scans",
      line = "The Brain is downloading recent Scans. This takes a few minutes. Reload after that.",
      button = "Reload",
      action = "reload",
      enabled = true,
      pulse = false,
    }
  end
  -- Nudge.atLogin and Nudge.afterLoad say the same in chat.
  if not loop.brainRan or loop.behind then
    return {
      title = "Brain not running",
      line = loop.brainRan
          and "Your Scan hasn't reached the Brain. Start AzerothQuant Brain from the Start menu, then Reload."
        or "AzerothQuant needs its Brain app. Start it from the Start menu (see the setup guide), then Reload.",
      button = "Reload",
      action = "reload",
      enabled = true,
      pulse = false,
      warn = true,
    }
  end
  if loop.unimported > 0 and loop.trying then
    return {
      title = "The Brain is working",
      line = "New recommendations will show by themselves. About a minute.",
    }
  end
  if loop.unimported > 0 and loop.tookLonger then
    return {
      title = "The Brain took longer than usual",
      line = "Reload to try again.",
      button = "Reload",
      action = "reload",
      enabled = true,
      pulse = true,
      warn = true,
    }
  end
  -- No Data slots (the first run before a client restart): Reload once the Brain should be done.
  if loop.unimported > 0 and not loop.reloadReady then
    return { title = "The Brain is working", line = "The Brain is reading your Scan. About a minute." }
  end
  if loop.unimported > 0 then
    return {
      title = "New recommendations should be ready",
      line = "Reload to see them.",
      button = "Reload",
      action = "reload",
      enabled = true,
      pulse = true,
    }
  end
  local cooldown = loop.lastScanAt and loop.lastScanAt + Nudge.COOLDOWN_SECONDS - now or 0
  if cooldown > 0 then
    local minutes = math.max(1, math.floor((now - loop.lastScanAt) / 60))
    return {
      line = string.format("These are from your Scan %d min ago. You can Scan again in %d:%02d.",
        minutes, math.floor(cooldown / 60), cooldown % 60),
      quiet = true,
    }
  end
  if not loop.ahOpen then
    return { title = "Scan the Auction House", line = "Open the Auction House to Scan." }
  end
  return {
    title = "Scan the Auction House",
    line = "Click Scan and keep the Auction House open for about a minute.",
    button = "Scan",
    action = "scan",
    enabled = true,
    pulse = true,
  }
end

ns.NextStep = NextStep
return NextStep
