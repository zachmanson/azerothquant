-- Where the Recommendation Table opens the first time, with the AH up and no saved spot
-- (#164).
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for the
-- namespace fallback.
local _, ns = ...
ns = ns or {}

local Placement = {}

-- Right of the AH, at width or the room there (room, right of it), whichever is less. When
-- not even minWidth fits there, below the AH at width instead: under minWidth the side pane
-- and the columns that never hide don't fit.
function Placement.firstOpen(room, width, minWidth)
  if room < minWidth then
    return { side = "below", width = width }
  end
  return { side = "right", width = math.min(width, room) }
end

ns.Placement = Placement
return Placement
