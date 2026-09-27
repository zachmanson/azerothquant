-- WoW glue for the Recommendation Table: one movable frame showing the Market's
-- Recommendations from AzerothQuantRecommendations. All shaping happens in
-- RecommendationTable.lua; this file only draws it and talks to the WoW API.
-- It opens next to a faction Auction House (not a Neutral one, whose Market the Brain
-- doesn't recommend for) and /aq recs toggles it anywhere. Its position is saved in
-- AzerothQuantDB.recommendationFrame; open/closed is not.
--
-- Read-only: hover shows a tooltip and shift-click links the item. Nothing else (ADR-0003).
local _, ns = ...
local RecommendationTable = ns.RecommendationTable
local Scan = ns.Scan

local WIDTH, HEIGHT = 680, 460
local LINE_HEIGHT = 16
local ICON_SIZE = 14
local PADDING = 12
-- Per section, the width of each column after the icon; the first is the item name.
local COLUMN_WIDTHS = {
  ["Holdings"] = { 190, 50, 40, 90, 90, 150 },
  ["Shopping List"] = { 190, 40, 80, 80, 80, 140 },
  ["Prediction buys"] = { 190, 120, 40, 100, 100 },
}
local MAX_COLUMNS = 6

local db
local frame, content
local lines = {} -- pooled line buttons, reused on every redraw
local openedByAuctionHouse = false
local redrawQueued = false

-- C_Item on newer clients (the Beta has no global GetItemInfo), the old globals otherwise.
local getItemInfo = C_Item and C_Item.GetItemInfo or GetItemInfo
local getItemInfoInstant = C_Item and C_Item.GetItemInfoInstant or GetItemInfoInstant

local function say(msg)
  print("|cff33ff99AzerothQuant|r " .. msg)
end

-- The item's name, or nil until the client has loaded it (GET_ITEM_INFO_RECEIVED follows).
local function nameOf(itemString)
  return (getItemInfo(itemString))
end

local function showTooltip(line)
  GameTooltip:SetOwner(line, "ANCHOR_RIGHT")
  GameTooltip:SetHyperlink(line.itemString)
  for _, text in ipairs(line.tooltip) do
    GameTooltip:AddLine(text, 1, 1, 1, true)
  end
  GameTooltip:Show()
end

local function linkInChat(line)
  if not IsModifiedClick("CHATLINK") then
    return
  end
  local _, link = getItemInfo(line.itemString)
  if link then
    ChatEdit_InsertLink(link)
  end
end

local function getLine(i)
  local line = lines[i]
  if line then
    return line
  end
  line = CreateFrame("Button", nil, content)
  line:SetHeight(LINE_HEIGHT)
  line:RegisterForClicks("LeftButtonUp")
  line:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
  line.icon = line:CreateTexture(nil, "ARTWORK")
  line.icon:SetSize(ICON_SIZE, ICON_SIZE)
  line.icon:SetPoint("LEFT")
  line.cells = {}
  for c = 1, MAX_COLUMNS do
    local cell = line:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    cell:SetJustifyH("LEFT")
    cell:SetWordWrap(false)
    line.cells[c] = cell
  end
  line:SetScript("OnEnter", function(self)
    if self.itemString then
      showTooltip(self)
    end
  end)
  line:SetScript("OnLeave", GameTooltip_Hide)
  line:SetScript("OnClick", function(self)
    if self.itemString then
      linkInChat(self)
    end
  end)
  lines[i] = line
  return line
end

-- Lays out one line: an optional icon, then texts in columns of the given widths.
-- With no widths, the first text spans the line (titles, header, "N more").
local function drawLine(i, texts, widths, font, item)
  local line = getLine(i)
  line:ClearAllPoints()
  line:SetPoint("TOPLEFT", content, "TOPLEFT", 0, -(i - 1) * LINE_HEIGHT)
  line:SetPoint("TOPRIGHT", content, "TOPRIGHT", 0, -(i - 1) * LINE_HEIGHT)
  line.itemString = item and item.itemString
  line.tooltip = item and item.tooltip
  line:EnableMouse(item ~= nil)
  if item then
    line.icon:SetTexture(select(5, getItemInfoInstant(item.itemString)))
    line.icon:Show()
  else
    line.icon:Hide()
  end
  local x = ICON_SIZE + 4
  for c, cell in ipairs(line.cells) do
    local text = texts[c]
    if text then
      cell:SetFontObject(font)
      cell:ClearAllPoints()
      cell:SetPoint("LEFT", line, "LEFT", widths and x or 0, 0)
      cell:SetWidth(widths and (widths[c] - 6) or (WIDTH - 2 * PADDING - 30))
      cell:SetText(text)
      cell:Show()
      x = x + (widths and widths[c] or 0)
    else
      cell:Hide()
    end
  end
  line:Show()
end

local function redraw()
  if not frame or not frame:IsShown() then
    return
  end
  local view = RecommendationTable.build(
    AzerothQuantRecommendations and AzerothQuantRecommendations.recommendations,
    GetRealmName(),
    UnitFactionGroup("player"),
    time(),
    nameOf
  )
  local n = 0
  local function add(texts, widths, font, item)
    n = n + 1
    drawLine(n, texts, widths, font, item)
  end

  if view.empty then
    frame.title:SetText("Recommendations")
    add({ view.empty }, nil, "GameFontHighlight")
  else
    frame.title:SetText("Recommendations: " .. view.title)
    for _, text in ipairs(view.header) do
      add({ text }, nil, "GameFontHighlightSmall")
    end
    for _, section in ipairs(view.sections) do
      local widths = COLUMN_WIDTHS[section.title]
      add({}) -- a blank line between sections
      add({ section.title .. " (" .. #section.rows .. ")" }, nil, "GameFontNormal")
      add(section.columns, widths, "GameFontNormalSmall")
      for _, row in ipairs(section.rows) do
        add(row.cells, widths, "GameFontHighlightSmall", row)
      end
      if section.more then
        add({ section.more }, nil, "GameFontDisableSmall")
      end
    end
  end

  for i = n + 1, #lines do
    lines[i]:Hide()
  end
  content:SetHeight(n * LINE_HEIGHT)
end

-- GET_ITEM_INFO_RECEIVED fires once per item, often dozens at a time: redraw once after.
local function queueRedraw()
  if redrawQueued or not frame or not frame:IsShown() then
    return
  end
  redrawQueued = true
  C_Timer.After(0.2, function()
    redrawQueued = false
    redraw()
  end)
end

local function savePosition()
  local point, _, relativePoint, x, y = frame:GetPoint()
  db.recommendationFrame = { point = point, relativePoint = relativePoint, x = x, y = y }
end

local function restorePosition()
  frame:ClearAllPoints()
  local saved = db.recommendationFrame
  if saved then
    frame:SetPoint(saved.point, UIParent, saved.relativePoint, saved.x, saved.y)
  elseif AuctionHouseFrame and AuctionHouseFrame:IsShown() then
    -- Next to the AH until first dragged; dragging re-anchors to UIParent before saving.
    frame:SetPoint("TOPLEFT", AuctionHouseFrame, "TOPRIGHT", 10, 0)
  else
    frame:SetPoint("CENTER")
  end
end

local function createFrame()
  frame = CreateFrame("Frame", "AzerothQuantRecommendationFrame", UIParent, "BasicFrameTemplateWithInset")
  frame:SetSize(WIDTH, HEIGHT)
  frame:SetFrameStrata("HIGH")
  frame:SetClampedToScreen(true)
  frame:SetMovable(true)
  frame:EnableMouse(true)
  frame:RegisterForDrag("LeftButton")
  frame:SetScript("OnDragStart", frame.StartMoving)
  frame:SetScript("OnDragStop", function(self)
    self:StopMovingOrSizing()
    savePosition()
  end)
  frame:SetScript("OnShow", redraw)
  frame:Hide()
  tinsert(UISpecialFrames, "AzerothQuantRecommendationFrame") -- Escape closes it

  frame.title = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  frame.title:SetPoint("TOP", frame, "TOP", 0, -5)

  local scroll = CreateFrame("ScrollFrame", nil, frame, "UIPanelScrollFrameTemplate")
  scroll:SetPoint("TOPLEFT", frame, "TOPLEFT", PADDING, -32)
  scroll:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -PADDING - 22, PADDING)
  content = CreateFrame("Frame", nil, scroll)
  content:SetSize(WIDTH - 2 * PADDING - 22, 1)
  scroll:SetScrollChild(content)
end

local function show()
  if not frame then
    createFrame()
  end
  restorePosition()
  frame:Show()
end

local function toggle()
  if frame and frame:IsShown() then
    frame:Hide()
  else
    openedByAuctionHouse = false
    show()
  end
end

local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("AUCTION_HOUSE_SHOW")
events:RegisterEvent("AUCTION_HOUSE_CLOSED")
events:RegisterEvent("GET_ITEM_INFO_RECEIVED")
events:SetScript("OnEvent", function(_, event, arg1)
  if event == "ADDON_LOADED" then
    if arg1 == "AzerothQuant" then
      AzerothQuantDB = AzerothQuantDB or {}
      db = AzerothQuantDB
    end
  elseif event == "AUCTION_HOUSE_SHOW" then
    local market = Scan.marketFaction(UnitGUID("npc"), UnitFactionGroup("player"))
    if market ~= "Neutral" and not (frame and frame:IsShown()) then
      openedByAuctionHouse = true
      show()
    end
  elseif event == "AUCTION_HOUSE_CLOSED" then
    -- Close what the AH opened; leave it if the player opened it with /aq recs.
    if openedByAuctionHouse and frame then
      frame:Hide()
    end
    openedByAuctionHouse = false
  elseif event == "GET_ITEM_INFO_RECEIVED" then
    queueRedraw()
  end
end)

-- /aq is shared with other files (MailDumpSpike.lua, which loads first): handle "recs"
-- and pass anything else to the handler that was there before.
local previousSlash = SlashCmdList.AZEROTHQUANT
SLASH_AZEROTHQUANT1 = "/aq"
SlashCmdList.AZEROTHQUANT = function(msg)
  if msg:match("^%s*recs%s*$") then
    toggle()
  elseif previousSlash then
    previousSlash(msg)
  else
    say("Usage: /aq recs (toggle the Recommendation Table)")
  end
end
