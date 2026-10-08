-- When to try the Brain's Data slots after a reload (ADR-0030). The Brain writes the same
-- Recommendations.lua into three LoadOnDemand slots, and the client reads a slot's file
-- from disk only the first time it loads, so each slot is one try. DataAddon.lua (glue)
-- runs the tries; this file only decides when, and when to stop.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for
-- the namespace fallback.
local _, ns = ...
ns = ns or {}

local LoadTries = {}

-- Seconds after load to try slot 1, 2 and 3. A guess: the Brain needs its 3 s settle
-- plus a warm import pass, which the "Import took Xs" lines `brain watch` logs will tell.
-- Tune from those (#162).
LoadTries.AFTER = { 20, 45, 90 }

-- slots: the Data slot names that exist, in order (at most #AFTER). after(seconds, fn):
-- C_Timer.After. try(slot): loads it, and returns whether the copy is fresh now.
-- done(fresh): called once, true at the first fresh try, false when every slot was stale.
function LoadTries.run(slots, after, try, done)
  local function attempt(i)
    after(LoadTries.AFTER[i] - (LoadTries.AFTER[i - 1] or 0), function()
      if try(slots[i]) then
        done(true)
      elseif i < #slots then
        attempt(i + 1)
      else
        done(false)
      end
    end)
  end
  if #slots > 0 then
    attempt(1)
  end
end

ns.LoadTries = LoadTries
return LoadTries
