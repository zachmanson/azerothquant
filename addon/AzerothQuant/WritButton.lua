-- The Writs button at the Auction House (a stopgap, may be removed later): each click
-- opens the next Sealed Writ in the bags, so the player can post the Craftsman's Writs it
-- gives with the AH's own window. It never posts. The glue in RecommendationFrame.lua
-- reads the bags and opens through a secure "item" action.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for the
-- namespace fallback.
local _, ns = ...
ns = ns or {}

local WritButton = {}

WritButton.TIP = "Opens the next Sealed Writ in your bags. Post the writs it gives with the"
  .. " Auction House's own window."

-- true for a Sealed Writ (Journeyman's, Expert's, Artisan's), by name.
function WritButton.isSealed(name)
  return name ~= nil and name:find("^Sealed %a+'s Writ$") ~= nil
end

-- ctx is { ahOpen, freeSlots (empty general bag slots), sealed = { item, count } or nil },
-- item being what the secure button uses. Returns { shown, enabled, label, tip, open (the
-- item to use, or nil) }.
function WritButton.state(ctx)
  if not ctx.ahOpen or not ctx.sealed then
    return { shown = false, enabled = false, label = "Writs", tip = WritButton.TIP }
  end
  if ctx.freeSlots <= 0 then
    return {
      shown = true,
      enabled = false,
      label = "Bags full",
      tip = "Free a bag slot to open the next Sealed Writ.\n\n" .. WritButton.TIP,
    }
  end
  return {
    shown = true,
    enabled = true,
    label = "Open writ (" .. ctx.sealed.count .. ")",
    tip = WritButton.TIP,
    open = ctx.sealed.item,
  }
end

ns.WritButton = WritButton
return WritButton
