-- What the Recommendation Table's Post button shows and does for the selected row (#81,
-- ADR-0016): its label, whether it's enabled and why not, the undercut line, and the one
-- protected call a click makes. The glue in RecommendationFrame.lua makes that call.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for the
-- namespace fallback.
local _, ns = ...
ns = ns or {}

-- In game Money.lua loads first (see the .toc), so require, which WoW lacks, isn't reached.
local Money = ns.Money or require("Money")

local PostButton = {}

local NO_ROW = "Select a Sell row to post it."

-- The Auction House's duration index for each post length it offers.
local DURATIONS = { [2] = 1, [8] = 2, [24] = 3 }

-- The Post at of a row the button can post, in whole copper, or nil for any other row.
local function postAt(row)
  local r = row and row.record
  if not r or r.action ~= "Sell" then
    return nil
  end
  local price = r.postAt or r.price
  return math.max(1, math.floor(price + 0.5))
end

-- row is a RecommendationTable row, or nil. ctx is what the glue knows right now:
-- { ahOpen, bagUnits, posted, pending, commodity (true/false, nil until the item loads),
-- durationHours, lowest (the lowest other-player unit price, or nil) }.
-- Returns { enabled, label, reason, undercut, call }.
function PostButton.state(row, ctx)
  local price = postAt(row)
  if not price then
    return { enabled = false, label = "Post", reason = NO_ROW }
  end
  -- ADR-0016: an undercut is shown, never blocked, so the player decides.
  local undercut
  if ctx.lowest and ctx.lowest < price then
    undercut = "Lowest is now " .. Money.format(ctx.lowest) .. ", below " .. Money.format(price)
  end
  local function off(label, reason)
    return { enabled = false, label = label, reason = reason, undercut = undercut }
  end
  if ctx.pending then
    return off("Posting...", "Waiting for the Auction House to confirm the post.")
  end
  if not ctx.durationHours then
    return off("Post", "No post duration from the Brain yet: Reload after its next import.")
  end
  local duration = DURATIONS[ctx.durationHours]
  if not duration then
    return off("Post", "Post duration " .. ctx.durationHours .. "h isn't one the Auction House offers.")
  end
  if ctx.posted >= row.record.quantity then
    return off("Posted", "Every unit of this row is posted.")
  end
  if not ctx.ahOpen then
    return off("Post", "Open the Auction House to post.")
  end
  if ctx.bagUnits <= 0 then
    return off("Post", "None in this Character's bags (bound units can't be posted).")
  end
  if ctx.commodity == nil then
    return off("Post", "Loading the item: try again in a moment.")
  end
  -- A commodity posts every unit in one Listing; gear is one Listing per unit, so one
  -- per click.
  local kind = ctx.commodity and "commodity" or "item"
  local left = math.min(row.record.quantity - ctx.posted, ctx.bagUnits)
  local quantity = ctx.commodity and left or 1
  return {
    enabled = true,
    label = "Post " .. quantity .. " @ " .. Money.format(price),
    undercut = undercut,
    call = { kind = kind, quantity = quantity, price = price, duration = duration },
  }
end

-- The lowest unit price another player asks, from one search's results as
-- { unitPrice, quantity, ownUnits }, or nil when there's none. A Listing that's all the
-- player's own isn't an undercut to warn about.
function PostButton.lowestOther(results)
  local lowest
  for _, r in ipairs(results) do
    if r.ownUnits < r.quantity and (not lowest or r.unitPrice < lowest) then
      lowest = r.unitPrice
    end
  end
  return lowest
end

ns.PostButton = PostButton
return PostButton
