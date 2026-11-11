-- What the Recommendation Table's Cancel undercut button shows and does (#177, ADR-0044):
-- which of the logged-in Character's own Listings are Undercut, the order they're
-- cancelled in, the label, whether it's enabled and why not, the hover line and the one
-- protected call a click makes. The glue in RecommendationFrame.lua makes that call.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for the
-- namespace fallback.
local _, ns = ...
ns = ns or {}

-- In game these load first (see the .toc), so require, which WoW lacks, isn't reached.
local Money = ns.Money or require("Money")
local PostButton = ns.PostButton or require("PostButton")

local CancelButton = {}

-- The lowest other-player unit price that sells ahead of own (a Listing { unitPrice }),
-- from one search's results as PostButton.lowestOther takes them, or nil when own isn't
-- Undercut. At one price the AH sells the newest first, and the player posts under the
-- cheapest other, so another player at the same price posted after them: equal counts.
function CancelButton.undercut(own, results)
  local lowest = PostButton.lowestOther(results)
  if lowest and lowest <= own.unitPrice then
    return lowest
  end
  return nil
end

-- The Undercut Listings among listings (see state), as { listing, lowest }, the most gold
-- tied up (units x own unit price) first, so stopping partway has freed the most. A
-- Listing whose Item Key isn't checked yet isn't among them.
function CancelButton.targets(listings, checks)
  local out = {}
  for _, listing in ipairs(listings) do
    local results = checks[listing.key]
    local lowest = results and CancelButton.undercut(listing, results)
    if lowest then
      out[#out + 1] = { listing = listing, lowest = lowest }
    end
  end
  table.sort(out, function(a, b)
    local ga, gb = a.listing.quantity * a.listing.unitPrice, b.listing.quantity * b.listing.unitPrice
    if ga ~= gb then
      return ga > gb
    end
    return a.listing.auctionID < b.listing.auctionID
  end)
  return out
end

-- "Medium Hide ×20 at 4s 50c, lowest other 4s 20c": a target, for the hover and chat.
function CancelButton.describe(target)
  local listing = target.listing
  return listing.name .. " ×" .. listing.quantity .. " at " .. Money.format(listing.unitPrice)
    .. ", lowest other " .. Money.format(target.lowest)
end

-- How the cancel of target (a targets entry) went, given the owned list read after it and
-- the error the AH showed since, if any: "cancelled" once the Listing is off the list,
-- "failed" if it's still up after an error, nil while it waits. A commodity cancel's
-- AUCTION_CANCELED doesn't carry the auctionID (#81 probe), so the owned list decides.
function CancelButton.outcome(listings, target, err)
  for _, listing in ipairs(listings) do
    if listing.auctionID == target.listing.auctionID then
      return err and "failed" or nil
    end
  end
  return "cancelled"
end

-- listings are the logged-in Character's active Listings (nil until the AH lists them) as
-- { auctionID, key, name, unitPrice, quantity }, key naming the Item Key searched. checks
-- maps a key to its search's results (as undercut takes them), nil until they land.
-- ctx is { pending (a cancel waits for the AH to confirm it), fresh (after a cancel, the
-- set of keys searched since; nil before any cancel) }.
-- Returns { enabled, label, reason, tip, target, call, recheck (the key to search again) }.
function CancelButton.state(listings, checks, ctx)
  if ctx.pending then
    return { enabled = false, label = "Cancelling...", reason = "Waiting for the Auction House to confirm the cancel." }
  end
  if not listings then
    return { enabled = false, label = "Checking...", reason = "Waiting for the Auction House to show what you have up." }
  end
  local keys, seen, checked = 0, {}, 0
  for _, listing in ipairs(listings) do
    if not seen[listing.key] then
      seen[listing.key] = true
      keys = keys + 1
      if checks[listing.key] then
        checked = checked + 1
      end
    end
  end
  if checked < keys then
    return {
      enabled = false,
      label = "Checking " .. checked .. "/" .. keys .. "...",
      reason = "Checking the Auction House for each item you have up.",
    }
  end
  local targets = CancelButton.targets(listings, checks)
  local target = targets[1]
  -- After a cancel the other searches are older than it, so the next target's Item Key
  -- is searched again first; if it's no longer Undercut, the one after it is next.
  if target and ctx.fresh and not ctx.fresh[target.listing.key] then
    return {
      enabled = false,
      label = "Checking...",
      reason = "Searching again for the next Listing to cancel.",
      recheck = target.listing.key,
    }
  end
  if target then
    return {
      enabled = true,
      label = "Cancel undercut (" .. #targets .. ")",
      tip = CancelButton.describe(target),
      target = target,
      call = { auctionID = target.listing.auctionID },
    }
  end
  return {
    enabled = false,
    label = "No undercut Listings",
    reason = "Nobody else is selling at or under your price on anything you have up.",
  }
end

ns.CancelButton = CancelButton
return CancelButton
