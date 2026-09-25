-- azerothquant spike #1: read-only probe of the Auction House API.
-- Never buys, posts or cancels (ADR-0003). Results land in AQProbeDB.

local AH = C_AuctionHouse

local EVENTS = {
    "AUCTION_HOUSE_SHOW",
    "AUCTION_HOUSE_CLOSED",
    "REPLICATE_ITEM_LIST_UPDATE",
    "AUCTION_HOUSE_THROTTLED_MESSAGE_SENT",
    "AUCTION_HOUSE_THROTTLED_MESSAGE_RESPONSE_RECEIVED",
    "AUCTION_HOUSE_THROTTLED_MESSAGE_DROPPED",
    "AUCTION_HOUSE_THROTTLED_MESSAGE_QUEUED",
    "AUCTION_HOUSE_THROTTLED_SYSTEM_READY",
    "AUCTION_HOUSE_BROWSE_RESULTS_UPDATED",
    "AUCTION_ITEM_LIST_UPDATE",
    "UI_ERROR_MESSAGE",
    "ITEM_SEARCH_RESULTS_UPDATED",
    "COMMODITY_SEARCH_RESULTS_UPDATED",
}

local function log(msg)
    local line = string.format("%.1f %s", GetTime(), msg)
    table.insert(AQProbeDB.log, line)
    print("|cff33ff99AQProbe|r " .. msg)
end

local function exists(fn) return fn ~= nil end

local function safe(fn, ...)
    if not fn then return "missing" end
    local ok, a, b, c = pcall(fn, ...)
    if not ok then return "error: " .. tostring(a) end
    return tostring(a) .. (b ~= nil and (", " .. tostring(b)) or "") .. (c ~= nil and (", " .. tostring(c)) or "")
end

local function captureReplicateSample()
    local n = AH.GetNumReplicateItems()
    AQProbeDB.replicateCount = n
    AQProbeDB.replicateSample = {}
    for i = 0, math.min(n, 10) - 1 do
        table.insert(AQProbeDB.replicateSample, {
            index = i,
            info = { AH.GetReplicateItemInfo(i) },
            link = AH.GetReplicateItemLink(i),
            timeLeft = AH.GetReplicateItemTimeLeft(i),
        })
    end
    log("replicate count=" .. n .. ", sampled " .. #AQProbeDB.replicateSample)
end

-- Aggregate over the whole replicate list. Field order per retail:
-- name, texture, count, quality, usable, level, levelType, minBid, minIncrement,
-- buyout, bidAmount, highBidder, bidder, owner, ownerFullName, saleStatus, itemID, hasAllInfo
local LINEN_CLOTH = 2589

-- "commodity", "item" or "unknown" (item data not loaded yet). Retail enum: 0 unknown, 1 item, 2 commodity.
local statusCache = {}
local function commodityStatus(itemID)
    if not itemID then return "unknown" end
    if statusCache[itemID] then return statusCache[itemID] end
    local ok, s = pcall(AH.GetItemCommodityStatus, itemID)
    local name = (not ok and "missing") or (s == 2 and "commodity") or (s == 1 and "item") or "unknown"
    if name ~= "unknown" then statusCache[itemID] = name end
    return name
end

local function captureStats()
    local n = AH.GetNumReplicateItems()
    local st = {
        total = n, withOwner = 0, withoutAllInfo = 0, withBid = 0, withMinBid = 0,
        noBuyout = 0, stacked = 0, maxStack = 0, maxStackLink = nil, maxStackStatus = nil,
        linenListings = 0, linenUnits = 0,
        distinctItems = 0, ownerExamples = {}, stackExamples = {}, linenExamples = {},
    }
    local seen = {}
    for i = 0, n - 1 do
        local _, _, count, _, _, _, _, minBid, _, buyout, bidAmount, _, _, owner, ownerFull, _, itemID, hasAll =
            AH.GetReplicateItemInfo(i)
        if itemID and not seen[itemID] then seen[itemID] = true; st.distinctItems = st.distinctItems + 1 end
        if owner or ownerFull then
            st.withOwner = st.withOwner + 1
            if #st.ownerExamples < 5 then table.insert(st.ownerExamples, tostring(owner) .. " / " .. tostring(ownerFull)) end
        end
        if not hasAll then st.withoutAllInfo = st.withoutAllInfo + 1 end
        if bidAmount and bidAmount > 0 then st.withBid = st.withBid + 1 end
        if minBid and minBid > 0 then st.withMinBid = st.withMinBid + 1 end
        if not buyout or buyout == 0 then st.noBuyout = st.noBuyout + 1 end
        if count and count > 1 then
            st.stacked = st.stacked + 1
            if count > st.maxStack then
                st.maxStack = count
                st.maxStackLink = AH.GetReplicateItemLink(i) .. " @" .. tostring(buyout)
                st.maxStackStatus = commodityStatus(itemID)
            end
            if #st.stackExamples < 5 then table.insert(st.stackExamples, AH.GetReplicateItemLink(i) .. " x" .. count .. " @" .. tostring(buyout)) end
        end
        if itemID == LINEN_CLOTH then
            st.linenListings = st.linenListings + 1
            st.linenUnits = st.linenUnits + (count or 0)
            if #st.linenExamples < 5 then table.insert(st.linenExamples, "x" .. tostring(count) .. " @" .. tostring(buyout)) end
        end
    end
    AQProbeDB.stats = st
    log(string.format("stats: %d listings, %d distinct items, %d with owner, %d stacked, linen %d listings",
        n, st.distinctItems, st.withOwner, st.stacked, st.linenListings))
end

-- Test 3: do full-scan owners fill in if we keep asking? Owner names resolve lazily
-- (GUID -> name, rate-limited), so re-read every row on a ticker and log the fill curve,
-- split by commodity vs item.
local sellerTicker
local SELLER_INTERVAL = 5
local SELLER_MAX_TICKS = 180 -- 15 min

local function sellerTick()
    local n = AH.GetNumReplicateItems()
    local p = { t = GetTime(), total = n, filled = 0,
        commodity = 0, commodityFilled = 0, item = 0, itemFilled = 0, unknown = 0 }
    local out = AQProbeDB.sellerFill
    for i = 0, n - 1 do
        local _, _, _, _, _, _, _, _, _, _, _, _, _, owner, ownerFull, _, itemID = AH.GetReplicateItemInfo(i)
        local has = (owner ~= nil and owner ~= "") or (ownerFull ~= nil and ownerFull ~= "")
        local s = commodityStatus(itemID)
        if has then p.filled = p.filled + 1 end
        if s == "commodity" then
            p.commodity = p.commodity + 1
            if has then
                p.commodityFilled = p.commodityFilled + 1
                if #out.commodityOwnerExamples < 5 then
                    table.insert(out.commodityOwnerExamples, AH.GetReplicateItemLink(i) .. " / " .. tostring(ownerFull or owner))
                end
            end
        elseif s == "item" then
            p.item = p.item + 1
            if has then p.itemFilled = p.itemFilled + 1 end
        else
            p.unknown = p.unknown + 1
        end
    end
    table.insert(out.points, p)
    log(string.format("sellers: %d/%d filled (commodity %d/%d, item %d/%d, unknown %d)",
        p.filled, n, p.commodityFilled, p.commodity, p.itemFilled, p.item, p.unknown))
end

local function stopSellers(reason)
    if sellerTicker then
        sellerTicker:Cancel()
        sellerTicker = nil
        log("seller fill stopped: " .. reason)
    end
end

local function startSellers()
    stopSellers("restarted")
    AQProbeDB.sellerFill = { interval = SELLER_INTERVAL, points = {}, commodityOwnerExamples = {} }
    sellerTick()
    sellerTicker = C_Timer.NewTicker(SELLER_INTERVAL, sellerTick, SELLER_MAX_TICKS)
    log("seller fill started, every " .. SELLER_INTERVAL .. "s; keep the AH open")
end

-- Test 1: snapshot every full-scan row for one item, to diff before/after a partial buy.
local function snapshot(itemID)
    local n = AH.GetNumReplicateItems()
    local snap = { t = GetTime(), date = date("%Y-%m-%d %H:%M:%S"), itemID = itemID, rows = {} }
    for i = 0, n - 1 do
        local _, _, count, _, _, _, _, _, _, buyout, _, _, _, owner, ownerFull, _, id = AH.GetReplicateItemInfo(i)
        if id == itemID then
            table.insert(snap.rows, {
                count = count, buyout = buyout,
                unit = (count and count > 0 and buyout) and (buyout / count) or nil,
                timeLeft = AH.GetReplicateItemTimeLeft(i),
                owner = ownerFull or owner,
            })
        end
    end
    AQProbeDB.snapshots = AQProbeDB.snapshots or {}
    table.insert(AQProbeDB.snapshots, snap)
    log(string.format("snapshot #%d: item %d, %d rows (of %d total)", #AQProbeDB.snapshots, itemID, #snap.rows, n))
end

-- Per-item search (what the default UI uses when you click an item).
-- Retail returns owners and auctionID here even though the replicate list hides them.
local searchKey

local function captureItemSearch()
    local n = AH.GetNumItemSearchResults(searchKey)
    local out = { count = n, results = {} }
    AQProbeDB["itemSearch_" .. searchKey.itemID] = out
    for i = 1, math.min(n, 15) do
        local r = AH.GetItemSearchResultInfo(searchKey, i)
        if r then
            table.insert(out.results, {
                auctionID = r.auctionID,
                owners = r.owners,
                quantity = r.quantity,
                buyoutAmount = r.buyoutAmount,
                bidAmount = r.bidAmount,
                timeLeft = r.timeLeft,
                containsOwnerItem = r.containsOwnerItem,
            })
        end
    end
    log("item search results=" .. n .. ", saved " .. #out.results)

    local id = searchKey.itemID
    local cn = AH.GetNumCommoditySearchResults(id)
    local cout = { count = cn, results = {} }
    AQProbeDB["commoditySearch_" .. id] = cout
    for i = 1, math.min(cn, 15) do
        local r = AH.GetCommoditySearchResultInfo(id, i)
        if r then
            table.insert(cout.results, {
                auctionID = r.auctionID,
                owners = r.owners,
                totalNumberOfOwners = r.totalNumberOfOwners,
                quantity = r.quantity,
                unitPrice = r.unitPrice,
                timeLeftSeconds = r.timeLeftSeconds,
                containsOwnerItem = r.containsOwnerItem,
            })
        end
    end
    log("commodity search results=" .. cn .. " for item " .. id)
end

local function staticChecks()
    local s = {}
    local _, build, date, toc = GetBuildInfo()
    s.build, s.buildDate, s.toc = build, date, toc
    s.realm = GetRealmName()
    s.normalizedRealm = GetNormalizedRealmName and GetNormalizedRealmName()
    s.faction = UnitFactionGroup("player")
    s.name, s.nameRealm = UnitName("player")
    s.fullName = UnitFullName and table.concat({ UnitFullName("player") }, "-")
    s.api = {
        C_AuctionHouse = exists(AH),
        ReplicateItems = exists(AH and AH.ReplicateItems),
        GetNumReplicateItems = exists(AH and AH.GetNumReplicateItems),
        SendBrowseQuery = exists(AH and AH.SendBrowseQuery),
        IsThrottledMessageSystemReady = exists(AH and AH.IsThrottledMessageSystemReady),
        QueryAuctionItems = exists(QueryAuctionItems),
        CanSendAuctionQuery = exists(CanSendAuctionQuery),
        GetNumAuctionItems = exists(GetNumAuctionItems),
    }
    s.throttleReady = safe(AH and AH.IsThrottledMessageSystemReady)
    s.canSendAuctionQuery = safe(CanSendAuctionQuery)
    AQProbeDB.static = s
    log("static checks saved (toc " .. tostring(toc) .. ", realm " .. tostring(s.realm) .. ")")
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:SetScript("OnEvent", function(_, event, arg1)
    if event == "ADDON_LOADED" then
        if arg1 ~= "AQProbe" then return end
        AQProbeDB = AQProbeDB or {}
        AQProbeDB.log = AQProbeDB.log or {}
        for _, e in ipairs(EVENTS) do pcall(frame.RegisterEvent, frame, e) end
        return
    end
    if event == "REPLICATE_ITEM_LIST_UPDATE" and sellerTicker then return end -- too noisy while names resolve
    log("event " .. event .. (arg1 ~= nil and (" " .. tostring(arg1)) or ""))
    if event == "REPLICATE_ITEM_LIST_UPDATE" then captureReplicateSample() end
    if event == "AUCTION_HOUSE_CLOSED" then stopSellers("AH closed") end
end)

SLASH_AQPROBE1 = "/aqprobe"
SlashCmdList.AQPROBE = function(arg)
    if arg == "scan" then
        log("throttleReady=" .. safe(AH.IsThrottledMessageSystemReady) .. ", requesting ReplicateItems")
        AH.ReplicateItems()
        log("count right after request=" .. AH.GetNumReplicateItems())
    elseif arg == "count" then
        captureReplicateSample()
    elseif arg == "stats" then
        captureStats()
    elseif arg == "owners" or arg:match("^owners %d+$") then
        local id = tonumber(arg:match("%d+")) or LINEN_CLOTH
        searchKey = AH.MakeItemKey(id)
        AH.SendSearchQuery(searchKey, { { sortOrder = 0, reverseSort = false } }, true)
        log("item search sent for item " .. id)
    elseif arg == "ownersread" then
        captureItemSearch()
    elseif arg == "sellers" then
        startSellers()
    elseif arg == "sellersstop" then
        stopSellers("by command")
    elseif arg == "snap" or arg:match("^snap %d+$") then
        snapshot(tonumber(arg:match("%d+")) or LINEN_CLOTH)
    elseif arg == "clear" then
        stopSellers("clear")
        AQProbeDB = { log = {} }
        print("AQProbe cleared")
    else
        staticChecks()
        print("AQProbe: open the AH, then /aqprobe scan. Wait 60s, /aqprobe count, then /reload.")
    end
end
