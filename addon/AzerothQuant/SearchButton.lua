-- What the Recommendation Table's Search button shows for the selected row (#39, ADR-0016):
-- whether the slot under the frame is Search (not Post), its label, whether it's enabled
-- and why not, and what a click searches for. The glue in RecommendationFrame.lua sends
-- the search.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for the
-- namespace fallback.
local _, ns = ...
ns = ns or {}

-- In game Money.lua loads first (see the .toc), so require, which WoW lacks, isn't reached.
local Money = ns.Money or require("Money")

local SearchButton = {}

-- The line under the button after a search: results as { unitPrice, quantity, ownUnits },
-- against buyPrice, the row's most to pay per unit.
-- The player's own units can't be bought, so they don't count.
function SearchButton.liveLine(results, buyPrice)
  local cheapest, units
  for _, r in ipairs(results) do
    local others = r.quantity - r.ownUnits
    if others > 0 then
      if not cheapest or r.unitPrice < cheapest then
        cheapest, units = r.unitPrice, others
      elseif r.unitPrice == cheapest then
        units = units + others
      end
    end
  end
  if not cheapest then
    return "Live: none listed"
  end
  buyPrice = math.floor(buyPrice)
  local where = cheapest < buyPrice and "under" or cheapest > buyPrice and "above" or "at"
  return "Live: " .. Money.format(cheapest) .. " x" .. units .. ", " .. where .. " your " .. Money.format(buyPrice) .. " buy"
end

-- The tabs whose rows are bought on the Auction House. Flips to Craft and Flips to
-- Disenchant have their own tabs, so a Shopping List row is a Flip to Sell or to Vendor.
local BUY_TABS = { ["Shopping List"] = true, ["Predictions"] = true, ["Buy Under"] = true }

-- row is a RecommendationTable row, or nil. ctx is what the glue knows right now:
-- { section (the row's tab), ahOpen, throttled, bagUnits, loaded (the client has the item) }.
-- Returns nil when the slot is Post's, else { enabled, label, reason, call }.
function SearchButton.state(row, ctx)
  local r = row and row.record
  -- A Disenchant source group's Buy Under is for no one item (#88), and a Prediction's line
  -- with no buy has no price to search against (#207).
  if not r or not r.itemKey or r.reason or not BUY_TABS[ctx.section] then
    return nil
  end
  -- Bought, so posting it is next (#81).
  if r.action == "Sell" and ctx.bagUnits > 0 then
    return nil
  end
  local function off(reason)
    return { enabled = false, label = "Search", reason = reason }
  end
  if not ctx.ahOpen then
    return off("Open the Auction House to search.")
  end
  -- A search sent while throttled is dropped, so the button waits instead.
  if ctx.throttled then
    return off("Waiting for the Auction House to take another search.")
  end
  -- Gear's search key needs the item's level from the client.
  if not ctx.loaded then
    return off("Loading the item: try again in a moment.")
  end
  return { enabled = true, label = "Search", call = { itemKey = row.record.itemKey } }
end

ns.SearchButton = SearchButton
return SearchButton
