-- WoW glue for the full Scan: a "Scan" button on the Auction House that runs
-- C_AuctionHouse.ReplicateItems and saves the result to AzerothQuantDB.scans.
-- All shaping happens in Scan.lua; this file only talks to the WoW API.
-- On load it also deletes the Scans the Brain has imported (Prune.lua). While
-- the AH is open the button pulses whenever a Scan can run, and it says in chat when a
-- Scan would complete an Observation Window (Nudge.lua).
-- ns.Scanner.busy() says whether a Scan is in flight, and reloadReady() whether the Brain
-- should have imported the Scans saved at load (#71). At logout it stamps each Scan with
-- when it was first saved, so the next load can tell the Brain is behind (#104). It also
-- lends the Scan button's pulse (addPulse, setPulsing) to the banner's button, which can
-- Scan too (requestScan, #161). After a load with a stale copy it tries the Brain's Data
-- slots by itself (DataAddon.lua, LoadTries.lua, ADR-0030). "Scan saved", "should be done"
-- and "are ready" go to chat only while the Recommendation frame is closed: open, its
-- banner says so.
--
-- Every stamp here is GetServerTime(), not time(), so Scans from different players'
-- clients order on one clock in the Scan Pool (#117). The cooldown and Nudge checks
-- compare against the same clock.
--
-- Read-only: nothing here buys, posts or cancels (ADR-0003).
local _, ns = ...
local Scan = ns.Scan
local Prune = ns.Prune
local Nudge = ns.Nudge
local Chat = ns.Chat
local DataAddon = ns.DataAddon
local LoadTries = ns.LoadTries
local Tips = ns.Tips
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
-- How long to wait for the items of dropped rows to load before reading those rows again
-- (#156). The chat line says how many came back, so this can be tuned.
local REREAD_CAP_SECONDS = 15

local db
local marketFaction -- decided on AUCTION_HOUSE_SHOW, while the auctioneer is the "npc" unit
local ahOpen = false
local pending -- the in-flight Scan request, or nil
local reading = false
local rereading -- while waiting to re-read dropped rows: { rows, waitingFor, startedAt, capTimer }
local debounceTimer, noResponseTimer
local button, pulse, ticker
local checkedAt -- last Nudge check while the AH is open
local savedAtLoad = 0 -- Scans left after pruning on load: saved, not imported by the Brain
local reloadReady = false -- the Brain should have imported them by now (Nudge.lua, #71)
local behindAtLoad = false -- it should have imported some long ago, so brain watch is off (#104)
-- The Data slot tries since load (ADR-0030): nil when none were started, else "trying",
-- "fresh" (one caught up) or "stale" (every slot was).
local tryState
local onDataLoad -- the Recommendation frame's redraw, after a try kept a newer copy

local READY_LINE = "New recommendations are ready. /aq recs to see them."
local TOOK_LONGER_LINE = "The Brain took longer than usual. Reload to try again."

local function cancel(timer)
  if timer then
    timer:Cancel()
  end
end

-- The banner says what chat would (#161).
local function windowShown()
  return AzerothQuantRecommendationFrame ~= nil and AzerothQuantRecommendationFrame:IsShown()
end

local function cooldownRemaining()
  if not db.lastScanAt then
    return 0
  end
  return math.max(0, db.lastScanAt + COOLDOWN_SECONDS - GetServerTime())
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
  local now = GetServerTime()
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

-- rereadNote: "re-read N of M dropped rows in X s", or nil when the main read dropped none.
local function finish(rows, rereadNote)
  cancel(noResponseTimer)
  pending.readAt = GetServerTime()
  local scan = Scan.build(pending, rows, UnitName("player"), sellPrice, itemInfo)
  table.insert(db.scans, scan)
  db.nextScanId = db.nextScanId + 1
  pending, reading = nil, false
  refreshButton()
  local say = windowShown() and Chat.debug or Chat.say
  say(string.format("Scan #%d saved: %d Listings%s, %d dropped for missing item data (%d items),"
    .. " %d items with no Vendor Price yet. /reload to hand it to the Brain.",
    scan.id, Scan.listingCount(scan), rereadNote and (" (" .. rereadNote .. ")") or "", scan.droppedRows,
    #scan.droppedItemIDs, scan.vendorPricesMissing))
end

-- GetReplicateItemLink, or nil if it errors: after the AH closes the list may be gone, and
-- an error then would lose a Scan that's already read (#156).
local function readLink(index)
  local ok, link = pcall(AH.GetReplicateItemLink, index)
  return ok and link or nil
end

-- Reads the dropped rows again in one pass and saves the Scan (#156). Runs once every
-- requested item has reported, at the cap, or when the AH closes mid-wait. A row that still
-- doesn't read stays dropped and recorded.
local function rereadAndFinish(rows, startedAt)
  local reread, dropped = Scan.reread(rows, readLink)
  finish(rows, string.format("re-read %d of %d dropped rows in %.1f s", reread, dropped, GetTime() - startedAt))
end

-- Ends the wait for dropped rows' items and re-reads them.
local function stopWaiting()
  local state = rereading
  rereading = nil
  cancel(state.capTimer)
  rereadAndFinish(state.rows, state.startedAt)
end

-- Asks the game to load the items of the rows the main read dropped (#156), then waits
-- for them before reading those rows again. With none dropped, saves right away.
local function rereadDropped(rows)
  local itemIDs = Scan.missingItemIDs(rows)
  if #itemIDs == 0 then
    finish(rows)
    return
  end
  local waitingFor, count = {}, 0
  for _, itemID in ipairs(itemIDs) do
    -- GetItemInfo returns nil for an item not loaded yet and asks the server for it;
    -- GET_ITEM_INFO_RECEIVED fires when it arrives.
    if getItemInfo(itemID) == nil then
      waitingFor[itemID] = true
      count = count + 1
    end
  end
  if count == 0 then
    rereadAndFinish(rows, GetTime())
    return
  end
  rereading = { rows = rows, waitingFor = waitingFor, startedAt = GetTime() }
  rereading.capTimer = C_Timer.NewTimer(REREAD_CAP_SECONDS, stopWaiting)
  Chat.debug(string.format("Waiting up to %d s for %d items to load, to re-read their dropped rows.",
    REREAD_CAP_SECONDS, count))
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
      -- Return 17 is the itemID, there even when the link isn't loaded yet (#150).
      local _, _, count, _, _, _, _, _, _, buyout, _, _, _, owner, _, _, itemID = AH.GetReplicateItemInfo(index)
      rows[#rows + 1] = {
        link = AH.GetReplicateItemLink(index),
        count = count,
        buyout = buyout,
        timeLeft = AH.GetReplicateItemTimeLeft(index),
        owner = owner,
        itemID = itemID,
      }
    end
    i = last + 1
    if i < n then
      C_Timer.After(0, step)
    else
      rereadDropped(rows)
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
  if not ahOpen or pending or cooldownRemaining() > 0 then
    return
  end
  pending = {
    id = db.nextScanId,
    requestedAt = GetServerTime(),
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
  -- Disabled while Scanning or cooling down, when the tip matters most.
  button:SetMotionScriptsWhileDisabled(true)
  button:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText(Tips.STEPS.scan, 1, 1, 1, 1, true)
    GameTooltip:Show()
  end)
  button:SetScript("OnLeave", GameTooltip_Hide)
  pulse = addPulse(button)
end

-- After a try loaded a copy (DataAddon.load), which pruned by its stamps: fresh is whether
-- it caught up. Recounts what's waiting, and whether the Brain is behind, from what's left.
-- Saved Scans are the ones with savedAt; the rest were taken since the load. A stale copy
-- leaves Reload due.
local function afterDataLoad(fresh)
  savedAtLoad = 0
  for _, scan in ipairs(db.scans) do
    if scan.savedAt then
      savedAtLoad = savedAtLoad + 1
    end
  end
  local now = GetServerTime()
  -- While the Brain is catching up, Reload would only show the same table (#159).
  local catchingUp = Nudge.catchingUp(AzerothQuantRecommendations, now)
  behindAtLoad = not catchingUp and Nudge.brainBehind(db.scans, now) ~= nil
  reloadReady = not fresh and not catchingUp
  if onDataLoad then
    onDataLoad()
  end
end

-- Tries the Data slots by itself when the startup copy is stale (ADR-0030). Not while the
-- Brain catches up: its Scans wait behind the pull, and every try would be stale. Only
-- Scans waiting at load are news for chat: a Character Read is saved on every reload, so
-- the copy is stale after most of them. When the Brain is behind, Nudge's "is the Brain
-- running?" line already said what to do.
local function tryDataSlots()
  local slots = DataAddon.slotsToTry()
  if #slots == 0 or Nudge.catchingUp(AzerothQuantRecommendations, GetServerTime()) then
    return
  end
  local news = savedAtLoad > 0
  tryState = "trying"
  LoadTries.run(slots, C_Timer.After, function(slot)
    local fresh = DataAddon.load(slot)
    if fresh ~= nil then
      afterDataLoad(fresh)
    end
    return fresh
  end, function(fresh)
    tryState = fresh and "fresh" or "stale"
    if not news or behindAtLoad then
      return
    end
    -- The Scans are in even if the Character Read isn't.
    if savedAtLoad == 0 then
      if not windowShown() then
        Chat.say(READY_LINE)
      end
    else
      -- A problem line: chat too, whether the banner shows it or not.
      Chat.say(TOOK_LONGER_LINE)
    end
  end)
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGOUT")
frame:RegisterEvent("AUCTION_HOUSE_SHOW")
frame:RegisterEvent("AUCTION_HOUSE_CLOSED")
frame:RegisterEvent("REPLICATE_ITEM_LIST_UPDATE")
frame:RegisterEvent("GET_ITEM_INFO_RECEIVED")
frame:SetScript("OnEvent", function(_, event, arg1)
  if event == "ADDON_LOADED" then
    if arg1 == "AzerothQuant" then
      AzerothQuantDB = AzerothQuantDB or {}
      db = AzerothQuantDB
      db.scans = db.scans or {}
      db.nextScanId = db.nextScanId or 1
      -- Recommendations.lua has loaded by now (it's in the TOC), as has SavedVariables.
      DataAddon.atLoad(db)
      Nudge.atLogin(AzerothQuantRecommendations, Chat.say, GetServerTime())
      local pruned = Prune.importedScans(db.scans, AzerothQuantRecommendations)
      if pruned > 0 then
        Chat.debug(string.format("Deleted %d Scans the Brain has imported (or has newer ones for their Market).", pruned))
      end
      -- What's left is newer than the Brain's last import, so it isn't in the table yet.
      savedAtLoad = #db.scans
      tryDataSlots()
      behindAtLoad = Nudge.afterLoad(db.scans, GetServerTime(), C_Timer.After, function()
        -- The Data slots are tried instead: their outcome sets reloadReady and says so.
        if tryState then
          return false
        end
        reloadReady = true
        return not windowShown()
      end, Chat.say, Nudge.catchingUp(AzerothQuantRecommendations, GetServerTime()))
      -- While the Brain catches up, afterLoad waits for nothing. Once its pull should be over,
      -- Reload is the step, or the banner would say the Brain is working until the next
      -- reload (#161).
      if Nudge.catchingUp(AzerothQuantRecommendations, GetServerTime()) then
        local endsAt = AzerothQuantRecommendations.brain.catchingUpSince + Nudge.CATCHING_UP_FOR
        C_Timer.After(endsAt - GetServerTime(), function()
          reloadReady = true
        end)
      end
      if savedAtLoad > 0 and not behindAtLoad then
        Chat.debug(string.format("%d saved Scan%s not imported by the Brain yet. With brain watch running"
          .. " (scripts\\play.bat), they show by themselves once it's done.", savedAtLoad, savedAtLoad == 1 and "" or "s"))
      end
    end
  elseif event == "PLAYER_LOGOUT" then
    -- SavedVariables is written right after this, on a /reload too.
    if db then
      Nudge.stampSaved(db.scans, GetServerTime())
    end
  elseif event == "AUCTION_HOUSE_SHOW" then
    ahOpen = true
    marketFaction = Scan.marketFaction(UnitGUID("npc"), UnitFactionGroup("player"))
    if not button then
      createButton()
    end
    refreshButton()
    -- Start checking from now, so a cooldown that ended while the AH was closed
    -- doesn't nudge on open.
    checkedAt = GetServerTime()
    cancel(ticker)
    ticker = C_Timer.NewTicker(1, tick)
  elseif event == "AUCTION_HOUSE_CLOSED" then
    ahOpen = false
    cancel(ticker)
    ticker = nil
    if rereading then
      -- The rows are read; save with whatever reads now rather than lose the Scan (#156).
      stopWaiting()
    elseif pending then
      abort("Auction House closed before the Scan finished; nothing was saved.")
    end
  elseif event == "GET_ITEM_INFO_RECEIVED" then
    -- arg1 is the itemID. It reports even when the item failed to load (arg2 false), and
    -- then there's nothing more to wait for either.
    if rereading and rereading.waitingFor[arg1] then
      rereading.waitingFor[arg1] = nil
      if next(rereading.waitingFor) == nil then
        stopWaiting()
      end
    end
  elseif event == "REPLICATE_ITEM_LIST_UPDATE" then
    -- Ignore updates when we haven't asked. (While we have, another addon's scan is
    -- indistinguishable from ours, but it's the same list, so that's harmless.)
    if not pending or reading then
      return
    end
    pending.firstUpdateAt = pending.firstUpdateAt or GetServerTime()
    cancel(noResponseTimer)
    cancel(debounceTimer)
    debounceTimer = C_Timer.NewTimer(QUIET_SECONDS, readRows)
  end
end)

-- True from the Scan request until it's saved or aborted. A reload then would lose the
-- Scan, so Reload and /aq reload wait (#47).
ns.Scanner = {
  busy = function()
    return pending ~= nil
  end,
  -- Scans the Recommendation Table doesn't reflect yet: those taken since the last reload
  -- (unsaved), and those saved then that the Brain hadn't imported (unimported). Then
  -- whether the Brain was behind at load (Nudge.brainBehind): for NextStep.of.
  waiting = function()
    return (db and #db.scans or 0) - savedAtLoad, savedAtLoad, behindAtLoad
  end,
  -- True once the Brain should have imported the Scans saved at load, so Reload pulses.
  reloadReady = function()
    return reloadReady
  end,
  -- The Data slot tries (ADR-0030): some still to come, and every one was stale.
  trying = function()
    return tryState == "trying"
  end,
  tookLonger = function()
    return tryState == "stale"
  end,
  -- fn runs after each try that loaded a copy: the Recommendation frame redraws.
  setOnDataLoad = function(fn)
    onDataLoad = fn
  end,
  -- The AH's Scan button's click, for the banner's (a click is the hardware event it needs).
  requestScan = requestScan,
  ahOpen = function()
    return ahOpen
  end,
  addPulse = addPulse,
  setPulsing = setPulsing,
}
