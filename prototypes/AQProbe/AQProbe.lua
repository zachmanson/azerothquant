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

local function captureStats()
    local n = AH.GetNumReplicateItems()
    local st = {
        total = n, withOwner = 0, withoutAllInfo = 0, withBid = 0, withMinBid = 0,
        noBuyout = 0, stacked = 0, maxStack = 0, linenListings = 0, linenUnits = 0,
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
            if count > st.maxStack then st.maxStack = count end
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
    log("event " .. event .. (arg1 ~= nil and (" " .. tostring(arg1)) or ""))
    if event == "REPLICATE_ITEM_LIST_UPDATE" then captureReplicateSample() end
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
    elseif arg == "clear" then
        AQProbeDB = { log = {} }
        print("AQProbe cleared")
    else
        staticChecks()
        print("AQProbe: open the AH, then /aqprobe scan. Wait 60s, /aqprobe count, then /reload.")
    end
end
