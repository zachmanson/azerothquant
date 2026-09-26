-- WoW glue for the full Scan: a "Scan" button on the Auction House that runs
-- C_AuctionHouse.ReplicateItems and saves the result to AzerothQuantDB.scans.
-- All shaping happens in Scan.lua; this file only talks to the WoW API.
-- On load it also deletes the Scans the Brain has imported (Prune.lua). While
-- the AH is open it nudges when a Scan would complete an Observation Window (Nudge.lua).
--
-- Read-only: nothing here buys, posts or cancels (ADR-0003).
local _, ns = ...
local Scan = ns.Scan
local Prune = ns.Prune
local Nudge = ns.Nudge
local AH = C_AuctionHouse

-- The throttle is silent (spike #1): a re-scan inside ~15 min gets no response
-- at all, so the Addon keeps its own clock and disables the button.
local COOLDOWN_SECONDS = Nudge.COOLDOWN_SECONDS
-- REPLICATE_ITEM_LIST_UPDATE keeps firing while item data loads. Read once it
-- has been quiet this long.
local QUIET_SECONDS = 2
-- The first update arrived ~4-6s after the request in the beta; give up well after.
local NO_RESPONSE_SECONDS = 60
-- ~58k rows per Scan; read them over several frames to avoid a long freeze.
local ROWS_PER_FRAME = 2000

local db
local marketFaction -- decided on AUCTION_HOUSE_SHOW, while the auctioneer is the "npc" unit
local pending -- the in-flight Scan request, or nil
local reading = false
local debounceTimer, noResponseTimer
local button, ticker
local checkedAt -- last Nudge check while the AH is open

local function say(msg)
  print("|cff33ff99AzerothQuant|r " .. msg)
end

local function cancel(timer)
  if timer then
    timer:Cancel()
  end
end

local function cooldownRemaining()
  if not db.lastScanAt then
    return 0
  end
  return math.max(0, db.lastScanAt + COOLDOWN_SECONDS - time())
end

local function refreshButton()
  if not button then
    return
  end
  local remaining = cooldownRemaining()
  if pending then
    button:SetText("Scanning...")
    button:Disable()
  elseif remaining > 0 then
    button:SetText(string.format("Scan (%d:%02d)", math.floor(remaining / 60), remaining % 60))
    button:Disable()
  else
    button:SetText("Scan")
    button:Enable()
  end
end

local function setNudged(on)
  if not button then
    return
  end
  if on then
    button:LockHighlight()
  else
    button:UnlockHighlight()
  end
end

local function tick()
  local now = time()
  if Nudge.due(db.lastScanAt, checkedAt, now) then
    say("Scan ready: a second Scan now completes an Observation Window.")
    setNudged(true)
  end
  checkedAt = now
  refreshButton()
end

local function finish(rows)
  cancel(noResponseTimer)
  local scan = Scan.build(pending, rows, UnitName("player"))
  table.insert(db.scans, scan)
  db.nextScanId = db.nextScanId + 1
  pending, reading = nil, false
  refreshButton()
  say(string.format("Scan #%d saved: %d Listings, %d dropped for missing item data. /reload to hand it to the Brain.",
    scan.id, #scan.listings, scan.droppedRows))
end

local function readRows()
  reading = true
  local n = AH.GetNumReplicateItems()
  local rows = {}
  local i = 0 -- replicate indices are 0-based (spike #1)

  local function step()
    if not pending then
      return -- aborted (AH closed) mid-read
    end
    local last = math.min(i + ROWS_PER_FRAME, n) - 1
    for index = i, last do
      local _, _, count, _, _, _, _, _, _, buyout, _, _, _, owner = AH.GetReplicateItemInfo(index)
      rows[#rows + 1] = {
        link = AH.GetReplicateItemLink(index),
        count = count,
        buyout = buyout,
        timeLeft = AH.GetReplicateItemTimeLeft(index),
        owner = owner,
      }
    end
    i = last + 1
    if i < n then
      C_Timer.After(0, step)
    else
      finish(rows)
    end
  end

  step()
end

local function abort(reason)
  cancel(debounceTimer)
  cancel(noResponseTimer)
  pending, reading = nil, false
  refreshButton()
  say(reason)
end

local function requestScan()
  if pending or cooldownRemaining() > 0 then
    return
  end
  setNudged(false)
  pending = {
    id = db.nextScanId,
    requestedAt = time(),
    realm = GetRealmName(),
    character = table.concat({ UnitFullName("player") }, "-"), -- e.g. "Kash-Patel" (spike #1)
    faction = marketFaction,
  }
  -- The server's throttle starts at the request, so the cooldown does too.
  db.lastScanAt = pending.requestedAt
  AH.ReplicateItems()
  noResponseTimer = C_Timer.NewTimer(NO_RESPONSE_SECONDS, function()
    abort("No response from the Auction House (probably throttled). Try again when the button unlocks.")
  end)
  refreshButton()
  say("Scan requested. Keep the Auction House open.")
end

local function createButton()
  button = CreateFrame("Button", "AzerothQuantScanButton", AuctionHouseFrame, "UIPanelButtonTemplate")
  button:SetSize(110, 22)
  button:SetPoint("BOTTOMRIGHT", AuctionHouseFrame, "TOPRIGHT", -25, 2)
  button:SetScript("OnClick", requestScan)
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("AUCTION_HOUSE_SHOW")
frame:RegisterEvent("AUCTION_HOUSE_CLOSED")
frame:RegisterEvent("REPLICATE_ITEM_LIST_UPDATE")
frame:SetScript("OnEvent", function(_, event, arg1)
  if event == "ADDON_LOADED" then
    if arg1 == "AzerothQuant" then
      AzerothQuantDB = AzerothQuantDB or {}
      db = AzerothQuantDB
      db.scans = db.scans or {}
      db.nextScanId = db.nextScanId or 1
      -- Recommendations.lua has loaded by now (it's in the TOC), as has SavedVariables.
      local pruned = Prune.importedScans(db.scans, AzerothQuantRecommendations)
      if pruned > 0 then
        say(string.format("Deleted %d Scans the Brain has imported (or has newer ones for their Market).", pruned))
      end
    end
  elseif event == "AUCTION_HOUSE_SHOW" then
    marketFaction = Scan.marketFaction(UnitGUID("npc"), UnitFactionGroup("player"))
    if not button then
      createButton()
    end
    refreshButton()
    -- Start checking from now, so a cooldown that ended while the AH was closed
    -- doesn't nudge on open.
    checkedAt = time()
    cancel(ticker)
    ticker = C_Timer.NewTicker(1, tick)
  elseif event == "AUCTION_HOUSE_CLOSED" then
    cancel(ticker)
    ticker = nil
    setNudged(false)
    if pending then
      abort("Auction House closed before the Scan finished; nothing was saved.")
    end
  elseif event == "REPLICATE_ITEM_LIST_UPDATE" then
    -- Ignore updates when we haven't asked. (While we have, another addon's scan is
    -- indistinguishable from ours, but it's the same list, so that's harmless.)
    if not pending or reading then
      return
    end
    cancel(noResponseTimer)
    cancel(debounceTimer)
    debounceTimer = C_Timer.NewTimer(QUIET_SECONDS, readRows)
  end
end)
