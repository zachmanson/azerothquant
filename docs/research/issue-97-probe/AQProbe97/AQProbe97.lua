-- #97 slice 2 probe (steps on #85): which events fire on an AH buy, in what order, and
-- what they carry. Logs to AQProbe97DB.log, read from SavedVariables after a /reload.
--
-- Read-only: it registers events and post-hooks the AH buy calls with hooksecurefunc,
-- which runs after Blizzard's call and can't change or block it. It calls no buy,
-- bid, post or cancel function itself.
--
-- Its own SavedVariables, not AzerothQuantDB, so the Brain's import never sees it. Named
-- apart from the old #39 AQProbe, whose save file is still in the game folders.

-- Past this the oldest entries go, so browsing before a buy can't push the buy out.
local MAX_ENTRIES = 3000

-- Logged only while the AH is open: the search-results ones fire on every search.
local AH_EVENTS = {
  "AUCTION_HOUSE_PURCHASE_COMPLETED",
  "COMMODITY_PURCHASE_SUCCEEDED",
  "COMMODITY_PURCHASE_FAILED",
  "COMMODITY_PRICE_UPDATED",
  "COMMODITY_PRICE_UNAVAILABLE",
  "AUCTION_HOUSE_SHOW_NOTIFICATION",
  "AUCTION_HOUSE_SHOW_FORMATTED_NOTIFICATION",
  "AUCTION_HOUSE_SHOW_ERROR",
  "UI_ERROR_MESSAGE",
  "UI_INFO_MESSAGE",
  "BAG_UPDATE_DELAYED",
  "AUCTION_ITEM_LIST_UPDATE",
  "COMMODITY_SEARCH_RESULTS_UPDATED",
  "ITEM_SEARCH_RESULTS_UPDATED",
}

-- Logged at any time: a buy's chat line or money change may land after the AH closes.
local ALWAYS_EVENTS = {
  "CHAT_MSG_SYSTEM",
  "PLAYER_MONEY",
}

-- The AH calls Blizzard's buy UI makes: they carry what the player asked for.
local HOOKS = {
  "StartCommoditiesPurchase",   -- (itemID, quantity)
  "ConfirmCommoditiesPurchase", -- (itemID, quantity)
  "CancelCommoditiesPurchase",
  "PlaceBid",                   -- (auctionID, bidAmount): an item buyout goes through here
}

-- A copy SavedVariables can hold: tables to a few levels, functions and userdata as text.
local function copy(value, depth)
  local kind = type(value)
  if kind == "table" then
    if depth >= 4 then
      return "<table>"
    end
    local out = {}
    for k, v in pairs(value) do
      if type(k) == "string" or type(k) == "number" then
        out[k] = copy(v, depth + 1)
      end
    end
    return out
  elseif kind == "function" or kind == "userdata" or kind == "thread" then
    return "<" .. kind .. ">"
  end
  return value
end

-- The args by position, nil kept as "<nil>" so positions line up.
local function pack(...)
  local args = { n = select("#", ...) }
  for i = 1, args.n do
    local v = select(i, ...)
    if v == nil then
      args[i] = "<nil>"
    else
      args[i] = copy(v, 0)
    end
  end
  return args
end

local function log(name, args, auction)
  local entries = AQProbe97DB.log
  if #entries >= MAX_ENTRIES then
    table.remove(entries, 1)
    AQProbe97DB.dropped = (AQProbe97DB.dropped or 0) + 1
  end
  entries[#entries + 1] = {
    t = GetTime(),
    server = GetServerTime(),
    name = name,
    args = args,
    money = GetMoney(),
    auction = auction,
  }
end

-- The Item Key of the last item (not commodity) search, to find a bought auction's
-- search row by its auctionID.
local lastItemKey

-- What the client still knows about an auction, which may be nothing once it's bought:
-- GetAuctionInfoByID, and the matching row of the last item search. The link is where
-- gear's suffix and bonus IDs show.
local function auctionInfo(auctionID)
  if type(auctionID) ~= "number" then
    return nil
  end
  local found = {}
  local ok, info = pcall(C_AuctionHouse.GetAuctionInfoByID, auctionID)
  if not ok then
    found.byID = "error: " .. tostring(info)
  elseif info == nil then
    found.byID = "<nil>"
  else
    found.byID = copy(info, 0)
  end
  if lastItemKey then
    local okCount, count = pcall(C_AuctionHouse.GetNumItemSearchResults, lastItemKey)
    for i = 1, (okCount and count or 0) do
      local okRow, row = pcall(C_AuctionHouse.GetItemSearchResultInfo, lastItemKey, i)
      if okRow and row and row.auctionID == auctionID then
        found.searchRow = copy(row, 0)
        break
      end
    end
  end
  return found
end

local ahOpen = false
local missing = {} -- events and hooks this client doesn't have
local frame = CreateFrame("Frame")

local function isAlways(event)
  for _, e in ipairs(ALWAYS_EVENTS) do
    if e == event then
      return true
    end
  end
  return false
end

frame:SetScript("OnEvent", function(_, event, ...)
  if event == "ADDON_LOADED" then
    if ... == "AQProbe97" then
      AQProbe97DB = AQProbe97DB or {}
      AQProbe97DB.log = AQProbe97DB.log or {}
      log("loaded", pack(GetBuildInfo()), nil)
      AQProbe97DB.log[#AQProbe97DB.log].missing = missing
    end
    return
  end
  if event == "AUCTION_HOUSE_SHOW" then
    ahOpen = true
  elseif event == "AUCTION_HOUSE_CLOSED" then
    ahOpen = false
  elseif not ahOpen and not isAlways(event) then
    return
  end
  if event == "ITEM_SEARCH_RESULTS_UPDATED" then
    lastItemKey = ...
  end
  local auction
  if event == "AUCTION_HOUSE_PURCHASE_COMPLETED" then
    auction = auctionInfo(...)
  end
  log(event, pack(...), auction)
end)

frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("AUCTION_HOUSE_SHOW")
frame:RegisterEvent("AUCTION_HOUSE_CLOSED")

-- An event this client doesn't have errors on RegisterEvent (or returns false), so note
-- it and go on. AQProbe97DB isn't loaded yet (SavedVariables come after the file runs):
-- ADDON_LOADED logs the list.
local function register(events)
  for _, event in ipairs(events) do
    local ok, result = pcall(frame.RegisterEvent, frame, event)
    if not ok or result == false then
      missing[#missing + 1] = event
    end
  end
end
register(AH_EVENTS)
register(ALWAYS_EVENTS)

for _, name in ipairs(HOOKS) do
  if C_AuctionHouse and type(C_AuctionHouse[name]) == "function" then
    hooksecurefunc(C_AuctionHouse, name, function(...)
      local auction
      if name == "PlaceBid" then
        auction = auctionInfo(...)
      end
      log("hook:" .. name, pack(...), auction)
    end)
  else
    missing[#missing + 1] = "hook:" .. name
  end
end

SLASH_AQPROBE971 = "/aqp"
SlashCmdList.AQPROBE97 = function(msg)
  local command, rest = msg:match("^(%S*)%s*(.-)$")
  if command == "note" then
    log("note", { n = 1, rest }, nil)
    print("AQProbe97: noted \"" .. rest .. "\"")
  elseif command == "clear" then
    AQProbe97DB.log = {}
    AQProbe97DB.dropped = nil
    print("AQProbe97: log cleared")
  else
    print("AQProbe97: " .. #AQProbe97DB.log .. " entries (" .. (AQProbe97DB.dropped or 0) .. " dropped)."
      .. " /aqp note <text> marks the log, /aqp clear empties it.")
  end
end
