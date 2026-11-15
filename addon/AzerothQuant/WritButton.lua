-- The Writs button at the Auction House (a stopgap, may be removed later): each click posts
-- the next Craftsman's Writ in the bags 1 copper under the lowest other player's Listing,
-- and opens the next Sealed Writ in the same click. A writ nobody else lists stays in the
-- bags. The glue in RecommendationFrame.lua reads the bags and searches, and makes the
-- post (onWritClick) and the open (a secure "item" action) this state names.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for the
-- namespace fallback.
local _, ns = ...
ns = ns or {}

-- In game these load first (see the .toc), so require, which WoW lacks, isn't reached.
local Money = ns.Money or require("Money")
local PostButton = ns.PostButton or require("PostButton")

local WritButton = {}

-- The Auction House's duration index for each post length it offers.
local DURATIONS = { [2] = 1, [8] = 2, [24] = 3 }

WritButton.TIP = "Posts the next Craftsman's Writ in your bags 1c under the lowest other"
  .. " player's Listing, and opens the next Sealed Writ in the same click. A writ nobody"
  .. " else lists stays in your bags."

-- "writ" for a Craftsman's Writ, "sealed" for a Sealed Writ, nil for anything else.
function WritButton.kind(name)
  if not name then
    return nil
  end
  if name:find("^Craftsman's Writ: ") then
    return "writ"
  end
  if name:find("^Sealed %a+'s Writ$") then
    return "sealed"
  end
  return nil
end

-- ctx is what the glue read just now:
--   ahOpen, pending (a writ post waits on the AH), freeSlots (empty general bag slots),
--   durationHours (the Brain's post length, nil for 24h),
--   sealed = { item, count } (item is what the secure button uses) or nil,
--   writs = { { key, name, units, commodity (nil until the item loads), results (nil
--     until searched, as PostButton.lowestOther takes them) } } in bag order.
-- Returns { shown, enabled, label, tip, open (the item to use, or nil), post (the call,
-- or nil), search (the writ key to search, or nil) }.
function WritButton.state(ctx)
  if not ctx.ahOpen or (not ctx.sealed and #ctx.writs == 0) then
    return { shown = false, enabled = false, label = "Writs" }
  end
  local ready, search, waiting, skipped = nil, nil, false, 0
  for _, writ in ipairs(ctx.writs) do
    if writ.commodity == nil then
      waiting = true
    elseif not writ.results then
      waiting = true
      search = search or writ.key
    else
      local lowest = PostButton.lowestOther(writ.results)
      if not lowest then
        skipped = skipped + writ.units
      elseif not ready then
        ready = { writ = writ, price = math.max(1, math.ceil(lowest) - 1) }
      end
    end
  end

  local tip = WritButton.TIP
  if skipped > 0 then
    tip = tip .. "\n\n" .. skipped .. " writ(s) left in your bags: no other player lists them."
  end
  local function off(label, why)
    return { shown = true, enabled = false, label = label, tip = why and (why .. "\n\n" .. tip) or tip, search = search }
  end
  if ctx.pending then
    return off("Posting...", "Waiting for the Auction House to confirm the post.")
  end

  local post
  if ready then
    local writ = ready.writ
    post = {
      key = writ.key,
      name = writ.name,
      kind = writ.commodity and "commodity" or "item",
      -- A commodity posts every unit in one Listing; gear is one Listing per unit.
      quantity = writ.commodity and writ.units or 1,
      price = ready.price,
      duration = DURATIONS[ctx.durationHours or 24] or 3,
    }
  end
  -- Opens only once every other writ is priced, so the bags don't fill with unsearched ones.
  local open
  if ctx.sealed and ctx.freeSlots > 0 and not waiting then
    open = ctx.sealed.item
  end

  if post then
    local label = "Post " .. Money.format(post.price) .. (open and " + open" or "")
    local what = post.name .. ": post " .. post.quantity .. " @ " .. Money.format(post.price)
    return { shown = true, enabled = true, label = label, tip = what .. "\n\n" .. tip, post = post, open = open, search = search }
  end
  if open then
    local label = "Open writ (" .. ctx.sealed.count .. ")"
    return { shown = true, enabled = true, label = label, tip = tip, open = open, search = search }
  end
  if waiting then
    return off("Searching...", "Pricing the writs in your bags.")
  end
  if ctx.sealed then
    return off("Bags full", "Free a bag slot to open the next Sealed Writ.")
  end
  return off("No writs", "No Sealed Writs left, and no writ in your bags another player lists.")
end

ns.WritButton = WritButton
return WritButton
