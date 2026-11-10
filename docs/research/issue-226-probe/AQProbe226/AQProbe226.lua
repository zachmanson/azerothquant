-- #226 step 1 probe: why do Live Scans drop rows for items the client already knows?
-- Reads the AH replicate list itself, records each row whose link is nil, then tries to
-- bring those links back: once each item's ContinueOnItemLoad fires, and by re-reading at
-- 2, 5, 10 and 30 s. Saves a tally per run to AQProbe226DB.runs (read after a /reload).
--
-- Read-only: it never buys, bids, posts or cancels. It only calls ReplicateItems itself on
-- `/aqp226 run` when no replicate list is loaded (that request starts the server's ~15 min
-- throttle, and the AzerothQuant Scan button won't know). Its own SavedVariables, so the
-- Brain's import never sees it.
local _, ns = ...
local Tally = ns.Tally
local AH = C_AuctionHouse

local QUIET_SECONDS = 2 -- as Scanner.lua: read once REPLICATE_ITEM_LIST_UPDATE goes quiet
local ROWS_PER_FRAME = 2000
local REREADS = { 2, 5, 10, 30 } -- seconds after the read; the last one ends the run
local SAMPLES = 40 -- never-read rows kept in full, for a look at what they are

local getItemInfo = C_Item and C_Item.GetItemInfo or GetItemInfo
local isCached = C_Item and C_Item.IsItemDataCachedByID

local ahOpen = false
local armed = false -- read on the next replicate list that goes quiet
local quietTimer
local run -- the run in progress, or nil
local loginAt

local function say(text)
  print("|cff66ccffAQProbe226|r: " .. text)
end

local function linkItemID(link)
  local id = type(link) == "string" and link:match("item:(%d+)")
  return id and tonumber(id)
end

-- GetReplicateItemLink, or nil if it errors (the list can go when the AH closes).
local function readLink(index)
  local ok, link = pcall(AH.GetReplicateItemLink, index)
  return ok and link or nil
end

local function elapsed()
  return GetTime() - run.startedAt
end

-- Re-reads every still-dropped row (or only itemID's), marking those that now read.
local function reread(label, itemID)
  local list = itemID and run.byItem[itemID] or run.records
  local got = 0
  for _, r in ipairs(list) do
    if not r.firstRead then
      local link = readLink(r.index)
      if linkItemID(link) == r.itemID then
        r.firstRead, r.readAfter, r.link = label, elapsed(), link
        got = got + 1
      end
    end
  end
  return got
end

local function finishRun(closedEarly)
  if not run or run.done then
    return
  end
  run.done = true
  for _, t in ipairs(run.timers) do
    t:Cancel()
  end
  -- Did the client come to know the never-read items by the end?
  for _, r in ipairs(run.records) do
    if not r.firstRead then
      r.infoKnownAtEnd = getItemInfo(r.itemID) ~= nil
    end
  end
  local tally = Tally.count(run.records)
  local samples, knownAtEnd = {}, 0
  for _, r in ipairs(run.records) do
    if not r.firstRead then
      if r.infoKnownAtEnd then
        knownAtEnd = knownAtEnd + 1
      end
      if #samples < SAMPLES then
        samples[#samples + 1] = r
      end
    end
  end
  local itemLoads = 0
  for _ in pairs(run.itemLoaded) do
    itemLoads = itemLoads + 1
  end
  local saved = {
    at = GetServerTime(),
    loginAt = loginAt,
    note = run.note,
    source = run.source,
    closedEarly = closedEarly or nil,
    listRows = run.listRows,
    readSeconds = run.readSeconds,
    droppedItems = tally.items,
    itemLoadsFired = itemLoads,
    neverButKnownAtEnd = knownAtEnd,
    tally = tally,
    samples = samples,
    siblingLinks = run.siblingLinks, -- itemID -> a link of the same item that did read
  }
  table.insert(AQProbe226DB.runs, saved)
  local f = tally.firstRead
  say(string.format("run %d done%s: %d rows, %d dropped (%d items). Back on item load %d, 2s %d, 5s %d,"
    .. " 10s %d, 30s %d, never %d (%d items; %d rows whose item the client knows by now)."
    .. " /reload to save.", #AQProbe226DB.runs, closedEarly and " (AH closed early)" or "", run.listRows,
    tally.rows, tally.items, f.itemLoad or 0, f["2s"] or 0, f["5s"] or 0, f["10s"] or 0, f["30s"] or 0,
    f.never or 0, tally.itemsNever, knownAtEnd))
  run = nil
end

-- After the read: ask for each dropped item and time the re-reads.
local function startRereads()
  local itemIDs = {}
  for itemID in pairs(run.byItem) do
    itemIDs[#itemIDs + 1] = itemID
  end
  say(string.format("read %d rows in %.1f s: %d dropped (%d items). Re-reading for 30 s, keep the AH open.",
    run.listRows, run.readSeconds, #run.records, #itemIDs))
  if #run.records == 0 then
    finishRun()
    return
  end
  local thisRun = run
  if Item and Item.CreateFromItemID then
    for _, itemID in ipairs(itemIDs) do
      Item:CreateFromItemID(itemID):ContinueOnItemLoad(function()
        if run ~= thisRun or run.done then
          return
        end
        run.itemLoaded[itemID] = elapsed()
        reread("itemLoad", itemID)
      end)
    end
  else
    run.note = (run.note or "") .. " [no Item mixin]"
  end
  for _, seconds in ipairs(REREADS) do
    run.timers[#run.timers + 1] = C_Timer.NewTimer(seconds, function()
      if run ~= thisRun then
        return
      end
      reread(seconds .. "s")
      if seconds == REREADS[#REREADS] then
        finishRun()
      end
    end)
  end
end

local function readList(source)
  local n = AH.GetNumReplicateItems()
  run = {
    source = source,
    note = AQProbe226DB.nextNote,
    startedAt = GetTime(),
    listRows = n,
    records = {},
    byItem = {},
    siblingLinks = {},
    itemLoaded = {},
    timers = {},
  }
  AQProbe226DB.nextNote = nil
  local readIDs = {} -- itemID -> a link that read, this pass
  local i = 0
  local thisRun = run
  local function step()
    if run ~= thisRun then
      return
    end
    local last = math.min(i + ROWS_PER_FRAME, n) - 1
    for index = i, last do
      local info = { AH.GetReplicateItemInfo(index) }
      local itemID = info[17]
      local link = readLink(index)
      if linkItemID(link) then
        if itemID and not readIDs[itemID] then
          readIDs[itemID] = link
        end
      elseif itemID then
        local r = {
          index = index,
          itemID = itemID,
          infoKnown = getItemInfo(itemID) ~= nil,
          cached = isCached and (isCached(itemID) and true or false) or nil, -- nil: no such API
          hasAllInfo = info[18] and true or false,
          nameRead = info[1] ~= nil,
          count = info[3],
          buyout = info[10],
        }
        run.records[#run.records + 1] = r
        run.byItem[itemID] = run.byItem[itemID] or {}
        table.insert(run.byItem[itemID], r)
      end
    end
    i = last + 1
    if i < n then
      C_Timer.After(0, step)
      return
    end
    run.readSeconds = elapsed()
    for itemID in pairs(run.byItem) do
      if readIDs[itemID] then
        run.siblingLinks[itemID] = readIDs[itemID]
      end
    end
    for _, r in ipairs(run.records) do
      r.siblingRead = readIDs[r.itemID] ~= nil
    end
    startRereads()
  end
  step()
end

local frame = CreateFrame("Frame")
frame:SetScript("OnEvent", function(_, event, ...)
  if event == "ADDON_LOADED" then
    if ... == "AQProbe226" then
      AQProbe226DB = AQProbe226DB or {}
      AQProbe226DB.runs = AQProbe226DB.runs or {}
    end
  elseif event == "PLAYER_LOGIN" then
    loginAt = GetServerTime()
  elseif event == "AUCTION_HOUSE_SHOW" then
    ahOpen = true
  elseif event == "AUCTION_HOUSE_CLOSED" then
    ahOpen = false
    armed = false
    if quietTimer then
      quietTimer:Cancel()
    end
    finishRun(true)
  elseif event == "REPLICATE_ITEM_LIST_UPDATE" then
    if not armed then
      return
    end
    if quietTimer then
      quietTimer:Cancel()
    end
    quietTimer = C_Timer.NewTimer(QUIET_SECONDS, function()
      armed = false
      readList("replicate")
    end)
  end
end)
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")
frame:RegisterEvent("AUCTION_HOUSE_SHOW")
frame:RegisterEvent("AUCTION_HOUSE_CLOSED")
frame:RegisterEvent("REPLICATE_ITEM_LIST_UPDATE")

SLASH_AQPROBE2261 = "/aqp226"
SlashCmdList.AQPROBE226 = function(msg)
  local command, rest = msg:match("^(%S*)%s*(.-)$")
  if command == "arm" then
    -- Read alongside the next Scan, at the same moment Scanner.lua reads.
    armed = true
    say("armed: click Scan in AzerothQuant now. I'll read the same list when it arrives.")
  elseif command == "run" then
    if not ahOpen then
      say("open the Auction House first.")
    elseif run then
      say("a run is already going.")
    elseif AH.GetNumReplicateItems() > 0 then
      readList("loaded")
    else
      armed = true
      AH.ReplicateItems()
      say("no list loaded, so I asked for one (this starts the ~15 min throttle).")
    end
  elseif command == "note" then
    AQProbe226DB.nextNote = rest
    say("the next run is noted \"" .. rest .. "\".")
  elseif command == "clear" then
    AQProbe226DB.runs = {}
    say("runs cleared.")
  else
    say(#AQProbe226DB.runs .. " runs saved. /aqp226 arm (then Scan), /aqp226 run (read the list now),"
      .. " /aqp226 note <text>, /aqp226 clear.")
  end
end
