-- WoW glue for the full Scan: a "Scan" button on the Auction House that runs
-- C_AuctionHouse.ReplicateItems and saves the result to AzerothQuantDB.scans.
-- All shaping happens in Scan.lua; this file only talks to the WoW API.
-- On load it also deletes the Scans the Brain has imported (Prune.lua). While
-- the AH is open the button pulses whenever a Scan can run, and it says in chat when a
-- Scan would complete an Observation Window (Nudge.lua).
-- ns.Scanner.busy() says whether a Scan is in flight, and reloadReady() whether the Brain
-- should have imported the Scans saved at load (#71). At logout it stamps each Scan with
-- when it was first saved, so the next load can tell the Brain is behind (#104). It also
-- lends the Scan button's pulse (addPulse, setPulsing) to the Reload button.
--
-- Read-only: nothing here buys, posts or cancels (ADR-0003).
local _, ns = ...
local Scan = ns.Scan
local Prune = ns.Prune
local Nudge = ns.Nudge
local Chat = ns.Chat
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
local button, pulse, ticker
local checkedAt -- last Nudge check while the AH is open
local savedAtLoad = 0 -- Scans left after pruning on load: saved, not imported by the Brain
local reloadReady = false -- the Brain should have imported them by now (Nudge.lua, #71)
local behindAtLoad = false -- it should have imported some long ago, so brain watch is off (#104)

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

-- A pulsing glow over a button (the Scan button here, Reload in RecommendationFrame.lua),
-- off until setPulsing turns it on. Our own glow rather than ActionButton_ShowOverlayGlow:
-- the Beta's modern UI has already dropped Blizzard helpers we relied on.
local function addPulse(target)
  local glow = target:CreateTexture(nil, "OVERLAY")
  glow:SetTexture("Interface\\Buttons\\UI-Panel-Button-Highlight")
  glow:SetTexCoord(0, 0.625, 0, 0.6875)
  glow:SetBlendMode("ADD")
  glow:SetAllPoints()
  glow:Hide()
  local group = glow:CreateAnimationGroup()
  group:SetLooping("BOUNCE")
  local fade = group:CreateAnimation("Alpha")
  fade:SetFromAlpha(0.3)
  fade:SetToAlpha(1)
  fade:SetDuration(0.8)
  group.glow = glow
  return group
end

-- Callers run every second or frame, so only start or stop the pulse on a change.
local function setPulsing(group, on)
  if on and not group:IsPlaying() then
    group.glow:Show()
    group:Play()
  elseif not on and group:IsPlaying() then
    group:Stop()
    group.glow:Hide()
  end
end

-- The button pulses exactly while it's enabled: whenever a Scan can run (#48).
local function refreshButton()
  if not button then
    return
  end
  local remaining = cooldownRemaining()
  if pending then
    button:SetText("Scanning...")
    button:Disable()
    setPulsing(pulse, false)
  elseif remaining > 0 then
    button:SetText(string.format("Scan (%d:%02d)", math.floor(remaining / 60), remaining % 60))
    button:Disable()
    setPulsing(pulse, false)
  else
    button:SetText("Scan")
    button:Enable()
    setPulsing(pulse, true)
  end
end

local function tick()
  local now = time()
  if Nudge.due(db.lastScanAt, checkedAt, now) then
    Chat.debug("Scan ready: a second Scan now completes an Observation Window.")
  end
  checkedAt = now
  refreshButton()
end

-- C_Item on newer clients (the Beta has no global GetItemInfo), the old global otherwise.
local getItemInfo = C_Item and C_Item.GetItemInfo or GetItemInfo

-- The Vendor Price: GetItemInfo's 11th return. nil until the client has loaded the item.
local function sellPrice(itemID)
  return (select(11, getItemInfo(itemID)))
end

-- The Item Info a Disenchant source group needs (#76). nil until the client has loaded it.
local function itemInfo(itemID)
  return Scan.fromGetItemInfo(getItemInfo(itemID))
end

local function finish(rows)
  cancel(noResponseTimer)
  pending.readAt = time()
  local scan = Scan.build(pending, rows, UnitName("player"), sellPrice, itemInfo)
  table.insert(db.scans, scan)
  db.nextScanId = db.nextScanId + 1
  pending, reading = nil, false
  refreshButton()
  Chat.say(string.format("Scan #%d saved: %d Listings, %d dropped for missing item data, %d items with no Vendor Price yet."
    .. " /reload to hand it to the Brain.",
    scan.id, #scan.listings, scan.droppedRows, scan.vendorPricesMissing))
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
  Chat.say(reason)
end

local function requestScan()
  if pending or cooldownRemaining() > 0 then
    return
  end
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
  Chat.debug("Scan requested. Keep the Auction House open.")
end

local function createButton()
  button = CreateFrame("Button", "AzerothQuantScanButton", AuctionHouseFrame, "UIPanelButtonTemplate")
  button:SetSize(110, 22)
  button:SetPoint("BOTTOMRIGHT", AuctionHouseFrame, "TOPRIGHT", -25, 2)
  button:SetScript("OnClick", requestScan)
  pulse = addPulse(button)
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGOUT")
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
        Chat.debug(string.format("Deleted %d Scans the Brain has imported (or has newer ones for their Market).", pruned))
      end
      -- What's left is newer than the Brain's last import, so it isn't in the table yet.
      savedAtLoad = #db.scans
      behindAtLoad = Nudge.afterLoad(db.scans, time(), C_Timer.After, function()
        reloadReady = true
      end, Chat.say)
      if savedAtLoad > 0 and not behindAtLoad then
        Chat.debug(string.format("%d saved Scan%s not imported by the Brain yet. With brain watch running"
          .. " (scripts\\play.bat), Reload again in a few seconds.", savedAtLoad, savedAtLoad == 1 and "" or "s"))
      end
    end
  elseif event == "PLAYER_LOGOUT" then
    -- SavedVariables is written right after this, on a /reload too.
    if db then
      Nudge.stampSaved(db.scans, time())
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
    if pending then
      abort("Auction House closed before the Scan finished; nothing was saved.")
    end
  elseif event == "REPLICATE_ITEM_LIST_UPDATE" then
    -- Ignore updates when we haven't asked. (While we have, another addon's scan is
    -- indistinguishable from ours, but it's the same list, so that's harmless.)
    if not pending or reading then
      return
    end
    pending.firstUpdateAt = pending.firstUpdateAt or time()
    cancel(noResponseTimer)
    cancel(debounceTimer)
    debounceTimer = C_Timer.NewTimer(QUIET_SECONDS, readRows)
  end
end)

-- True from the Scan request until it's saved or aborted. A reload then would lose the
-- Scan, so the Reload button and /aq reload wait (#47).
ns.Scanner = {
  busy = function()
    return pending ~= nil
  end,
  -- Scans the Recommendation Table doesn't reflect yet: those taken since the last reload
  -- (unsaved), and those saved then that the Brain hadn't imported (unimported). Then
  -- whether the Brain was behind at load (Nudge.brainBehind): waitingNote's arguments.
  waiting = function()
    return (db and #db.scans or 0) - savedAtLoad, savedAtLoad, behindAtLoad
  end,
  -- True once the Brain should have imported the Scans saved at load, so Reload pulses.
  reloadReady = function()
    return reloadReady
  end,
  addPulse = addPulse,
  setPulsing = setPulsing,
}
