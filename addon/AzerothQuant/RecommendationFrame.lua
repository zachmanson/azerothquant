-- WoW glue for the Recommendation Table: one movable Blizzard portrait panel showing the
-- Market's Recommendations from AzerothQuantRecommendations, one section per bottom tab.
-- All shaping happens in RecommendationTable.lua; this file only draws it and talks to the
-- WoW API. It opens next to a faction Auction House (not a Neutral one, whose Market the
-- Brain doesn't recommend for) and /aq recs toggles it anywhere. Its position, the tab
-- last picked and each Market's Budget are saved in AzerothQuantDB; open/closed is not.
--
-- Read-only: hover shows a tooltip and shift-click links the item. Nothing else (ADR-0003).
-- The Budget box (#86) only saves what the player will spend: the table hides options over
-- it at once, and Character.lua hands it to the Brain in the next Character Read.
local _, ns = ...
local RecommendationTable = ns.RecommendationTable
local Money = ns.Money
local Scan = ns.Scan
local Scanner = ns.Scanner
local Chat = ns.Chat

-- Templates below were probed on the Beta client (#46): ButtonFrameTemplate (portrait
-- panel with an inset), PanelTabButtonTemplate, ColumnDisplayButtonTemplate (the AH's
-- column headers). The Classic-era names (CharacterFrameTabButtonTemplate,
-- WhoFrameColumnHeaderTemplate) are missing there.
local WIDTH, HEIGHT = 915, 540
local PORTRAIT = "Interface\\Icons\\INV_Misc_Coin_01"
local INSET_TOP = -64 -- leaves room for the two header lines under the title bar
local LINE_HEIGHT = 22
local ICON_SIZE = 20
local ICON_GAP = 6
local HEADER_HEIGHT = 24
local SCROLL_LEFT = 6
local SCROLLBAR_WIDTH = 30
-- The inset spans x 4 .. WIDTH-6; rows sit inside it, left of the scroll bar.
local CONTENT_WIDTH = WIDTH - 10 - SCROLL_LEFT - SCROLLBAR_WIDTH
-- Per section, the width of each column after the icon but the last, which (Note, mostly)
-- gets the leftover width. The first is the item name.
local COLUMN_WIDTHS = {
  ["Holdings"] = { 230, 70, 50, 110, 110, 80 },
  -- Per click, Per day and ROI after Profit (#98).
  ["Shopping List"] = { 170, 45, 40, 80, 80, 80, 70, 70, 50, 80 },
  ["Flips to Craft"] = { 190, 60, 45, 95, 95, 95, 95 },
  ["Prediction buys"] = { 230, 150, 50, 120 },
}
local MAX_COLUMNS = 11
local STRIPE_ALPHA = 0.04

local db
local frame, scroll, content
local lines = {} -- pooled line buttons, reused on every redraw
local headers = {} -- pooled column header buttons
local tabs = {}
local selected -- the title of the section on show
local shown -- the section on show, as built, so a header click knows its columns
local sorts = {} -- per section title, the sort picked by header clicks; empty on each open
local openedByAuctionHouse = false
local redrawQueued = false

-- C_Item on newer clients (the Beta has no global GetItemInfo), the old globals otherwise.
local getItemInfo = C_Item and C_Item.GetItemInfo or GetItemInfo
local getItemInfoInstant = C_Item and C_Item.GetItemInfoInstant or GetItemInfoInstant

-- Where the logged-in Character's Market's Budget is saved in AzerothQuantDB.budgets.
local function budgetKey()
  return RecommendationTable.budgetKey(GetRealmName(), UnitFactionGroup("player") or "")
end

-- That Budget in copper, or nil for all the gold.
local function savedBudget()
  return db.budgets and db.budgets[budgetKey()]
end

-- The item's name, or nil until the client has loaded it (GET_ITEM_INFO_RECEIVED follows).
local function nameOf(itemString)
  return (getItemInfo(itemString))
end

-- A section's column widths, the last one taking what's left of the row.
local function widthsFor(title)
  local widths = {}
  local used = ICON_SIZE + ICON_GAP
  for c, w in ipairs(COLUMN_WIDTHS[title]) do
    widths[c] = w
    used = used + w
  end
  widths[#widths + 1] = CONTENT_WIDTH - used
  return widths
end

-- The item, the row's tooltip lines, and any cell text clipped by its column.
local function showTooltip(line)
  GameTooltip:SetOwner(line, "ANCHOR_RIGHT")
  GameTooltip:SetHyperlink(line.itemString)
  -- The hyperlink's item-tooltip hook (Tooltip.lua) already added the holder and
  -- reagent lines this row also has, so skip those (#94).
  local shown = {}
  for i = 1, GameTooltip:NumLines() do
    local left = _G["GameTooltipTextLeft" .. i]
    local text = left and left:GetText()
    if text then
      shown[text] = true
    end
  end
  for _, text in ipairs(line.tooltip) do
    if not shown[text] then
      GameTooltip:AddLine(text, 1, 1, 1, true)
      shown[text] = true
    end
  end
  -- The first cell is the item name, which the hyperlink already shows in full.
  for c = 2, MAX_COLUMNS do
    local cell = line.cells[c]
    local text = cell:IsShown() and cell:GetText()
    if text and not shown[text] and cell:IsTruncated() then
      GameTooltip:AddLine(text, 1, 1, 1, true)
    end
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
  line.stripe = line:CreateTexture(nil, "BACKGROUND")
  line.stripe:SetAllPoints()
  line.stripe:SetColorTexture(1, 1, 1, STRIPE_ALPHA)
  line.icon = line:CreateTexture(nil, "ARTWORK")
  line.icon:SetSize(ICON_SIZE, ICON_SIZE)
  line.icon:SetPoint("LEFT", 2, 0)
  line.cells = {}
  for c = 1, MAX_COLUMNS do
    local cell = line:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
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

-- Lays out one line: for an item, its icon and then its cells in columns of the given
-- widths, striped on every other row. Otherwise one text spans the line (the empty-tab
-- line, "N more").
local function drawLine(i, texts, widths, font, item, justify)
  local line = getLine(i)
  line:ClearAllPoints()
  line:SetPoint("TOPLEFT", content, "TOPLEFT", 0, -(i - 1) * LINE_HEIGHT)
  line:SetPoint("TOPRIGHT", content, "TOPRIGHT", 0, -(i - 1) * LINE_HEIGHT)
  line.itemString = item and item.itemString
  line.tooltip = item and item.tooltip
  line:EnableMouse(item ~= nil)
  line.stripe:SetShown(item ~= nil and i % 2 == 0)
  if item then
    line.icon:SetTexture(select(5, getItemInfoInstant(item.itemString)))
    line.icon:Show()
  else
    line.icon:Hide()
  end
  local x = ICON_SIZE + ICON_GAP
  for c, cell in ipairs(line.cells) do
    local text = texts[c]
    if text then
      cell:SetFontObject(font)
      cell:SetJustifyH(justify or "LEFT")
      cell:ClearAllPoints()
      if widths then
        cell:SetPoint("LEFT", line, "LEFT", x, 0)
        cell:SetWidth(widths[c] - 6)
        x = x + widths[c]
      else
        cell:SetPoint("LEFT", line, "LEFT", 0, 0)
        cell:SetWidth(CONTENT_WIDTH)
      end
      cell:SetText(text)
      cell:Show()
    else
      cell:Hide()
    end
  end
  line:Show()
end

local redraw

-- The sort the section on show is in: the last header click, or its default.
local function activeSort(section)
  return sorts[section.title] or section.sort
end

-- Gold column headers over the rows. A click sorts by that column (see nextSort).
local function getHeader(c)
  local header = headers[c]
  if header then
    return header
  end
  header = CreateFrame("Button", nil, frame.Inset, "ColumnDisplayButtonTemplate")
  header:SetHeight(HEADER_HEIGHT)
  header:SetNormalFontObject("GameFontNormal")
  header.arrow = header:CreateTexture(nil, "OVERLAY")
  header.arrow:SetTexture("Interface\\Buttons\\UI-SortArrow")
  header.arrow:SetSize(9, 8)
  header:SetScript("OnClick", function()
    if not shown then
      return
    end
    PlaySound(SOUNDKIT.IG_MAINMENU_OPTION_CHECKBOX_ON)
    sorts[shown.title] = RecommendationTable.nextSort(shown, activeSort(shown), c)
    redraw()
  end)
  headers[c] = header
  return header
end

-- The Item header also spans the icon, so headers line up with the cells below them. The
-- sorted column's header gets an arrow: down for largest (or Z) first, up for smallest.
local function drawHeaders(columns, widths, sort)
  local x = SCROLL_LEFT
  for c = 1, MAX_COLUMNS do
    if columns and columns[c] then
      local header = getHeader(c)
      local width = widths[c] + (c == 1 and (ICON_SIZE + ICON_GAP) or 0)
      header:ClearAllPoints()
      header:SetPoint("TOPLEFT", frame.Inset, "TOPLEFT", x, -4)
      header:SetWidth(width)
      header:SetText(columns[c])
      if sort and sort.column == c then
        header.arrow:ClearAllPoints()
        header.arrow:SetPoint("LEFT", header:GetFontString(), "RIGHT", 3, -2)
        if sort.descending then
          header.arrow:SetTexCoord(0, 0.5625, 0, 1)
        else
          header.arrow:SetTexCoord(0, 0.5625, 1, 0)
        end
        header.arrow:Show()
      else
        header.arrow:Hide()
      end
      header:Show()
      x = x + width
    elseif headers[c] then
      headers[c]:Hide()
    end
  end
end

local function drawTabs(view)
  for i, tab in ipairs(tabs) do
    local section = view.sections and view.sections[i]
    if section then
      tab:SetText(section.tab)
      PanelTemplates_TabResize(tab, 0)
      tab:Show()
      if section.title == selected then
        PanelTemplates_SetTab(frame, i)
      end
    else
      tab:Hide()
    end
  end
end

function redraw()
  if not frame or not frame:IsShown() then
    return
  end
  local view = RecommendationTable.build(
    AzerothQuantRecommendations and AzerothQuantRecommendations.recommendations,
    GetRealmName(),
    UnitFactionGroup("player"),
    time(),
    nameOf,
    table.concat({ UnitFullName("player") }, "-"),
    savedBudget()
  )
  local n = 0
  local function add(texts, widths, font, item, justify)
    n = n + 1
    drawLine(n, texts, widths, font, item, justify)
  end

  drawTabs(view)
  shown = nil
  if view.empty then
    frame:SetTitle("Recommendations")
    frame.header1:SetText("")
    frame.header2:SetText("")
    drawHeaders(nil)
    add({ view.empty }, nil, "GameFontHighlight", nil, "CENTER")
  else
    frame:SetTitle("Recommendations: " .. view.title)
    frame.header1:SetText(view.header[1])
    frame.header2:SetText(view.header[2])
    for _, section in ipairs(view.sections) do
      if section.title == selected then
        shown = section
        local widths = widthsFor(section.title)
        local sort = activeSort(section)
        RecommendationTable.sort(section, sort)
        drawHeaders(section.columns, widths, sort)
        if section.empty then
          add({ section.empty }, nil, "GameFontDisable", nil, "CENTER")
        end
        for _, row in ipairs(section.rows) do
          add(row.cells, widths, "GameFontHighlight", row)
        end
        if section.more then
          add({ section.more }, nil, "GameFontDisable")
        end
      end
    end
  end

  for i = n + 1, #lines do
    lines[i]:Hide()
  end
  content:SetHeight(math.max(n, 1) * LINE_HEIGHT)
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

local function selectTab(title)
  selected = title
  scroll:SetVerticalScroll(0)
  redraw()
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

-- Bottom tabs, one per section, in the order RecommendationTable.build gives them. A click
-- is remembered, so /aq recs reopens that tab.
local TAB_TITLES = { "Holdings", "Shopping List", "Flips to Craft", "Prediction buys" }

local function createTabs()
  for i, title in ipairs(TAB_TITLES) do
    local tab = CreateFrame("Button", "AzerothQuantRecommendationFrameTab" .. i, frame, "PanelTabButtonTemplate")
    tab:SetID(i)
    tab:SetText(title)
    if i == 1 then
      tab:SetPoint("TOPLEFT", frame, "BOTTOMLEFT", 11, 2)
    else
      tab:SetPoint("TOPLEFT", tabs[i - 1], "TOPRIGHT", 3, 0)
    end
    tab:SetScript("OnClick", function()
      PlaySound(SOUNDKIT.IG_CHARACTER_INFO_TAB)
      db.recommendationTab = title
      selectTab(title)
    end)
    tabs[i] = tab
  end
  frame.Tabs = tabs
  PanelTemplates_SetNumTabs(frame, #tabs)
end

-- Reloading flushes SavedVariables (new Scans reach the Brain) and rereads
-- Recommendations.lua (a Brain import reaches the table). Not mid-Scan, which would lose it.
local RELOAD_TIP = "Reload the UI: saves new Scans for the Brain and loads its latest Recommendations."
local BUSY_TIP = "Wait for the Scan to finish: reloading now would lose it."

local function reload()
  if Scanner.busy() then
    Chat.say(BUSY_TIP)
    return
  end
  ReloadUI()
end

local BUDGET_TIP = "Most gold to spend on each Shopping List option, and on Prediction buys. "
  .. "Blank for all your gold. Options over it hide now; Reload to re-size the rest."

-- Left of the Reload button. Enter saves it (blank clears it); Escape puts it back.
local function createBudgetBox(button)
  local box = CreateFrame("EditBox", nil, frame, "InputBoxTemplate")
  box:SetSize(60, 20)
  box:SetAutoFocus(false)
  box:SetMaxLetters(10)
  box:SetPoint("RIGHT", button, "LEFT", -10, 0)
  box.label = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  box.label:SetPoint("RIGHT", box, "LEFT", -8, 0)
  box.label:SetText("Budget (g)")
  box:SetScript("OnEnterPressed", function(self)
    local copper, ok = Money.parseGold(self:GetText())
    if ok then
      db.budgets = db.budgets or {}
      db.budgets[budgetKey()] = copper
      redraw()
    else
      Chat.say("Budget: type gold, like 250 or 12.5, or leave it blank for all your gold.")
    end
    self:SetText(Money.goldText(savedBudget()))
    self:ClearFocus()
  end)
  box:SetScript("OnEscapePressed", function(self)
    self:SetText(Money.goldText(savedBudget()))
    self:ClearFocus()
  end)
  box:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText(BUDGET_TIP, 1, 1, 1, 1, true)
    GameTooltip:Show()
  end)
  box:SetScript("OnLeave", GameTooltip_Hide)
  box:SetScript("OnShow", function(self)
    self:SetText(Money.goldText(savedBudget()))
  end)
  frame.budget = box
end

local function createReloadButton()
  local button = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
  button:SetSize(70, 22)
  button:SetText("Reload")
  button:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -10, -30)
  button:SetScript("OnClick", reload)
  -- Disabled buttons get no OnEnter unless told to, and the tooltip must say why it's off.
  button:SetMotionScriptsWhileDisabled(true)
  button:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText(Scanner.busy() and BUSY_TIP or RELOAD_TIP, 1, 1, 1, 1, true)
    GameTooltip:Show()
  end)
  button:SetScript("OnLeave", GameTooltip_Hide)
  createBudgetBox(button)

  -- Scans the table doesn't reflect yet, in orange left of the Budget box, and the button
  -- lights up.
  local note = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  note:SetPoint("RIGHT", frame.budget.label, "LEFT", -8, 0)
  note:SetTextColor(1, 0.5, 0.25)

  -- Pulses once the Brain should have imported the Scans saved at load (#71).
  local pulse = Scanner.addPulse(button)

  -- A Scan starts and ends on its own clock, so follow it while the frame is shown.
  button:SetScript("OnUpdate", function(self)
    local busy = Scanner.busy()
    self:SetEnabled(not busy)
    Scanner.setPulsing(pulse, Scanner.reloadReady() and not busy)
    local text = RecommendationTable.waitingNote(Scanner.waiting())
    if text ~= note:GetText() then
      note:SetText(text)
      if text then
        self:LockHighlight()
      else
        self:UnlockHighlight()
      end
    end
  end)
end

local function createFrame()
  frame = CreateFrame("Frame", "AzerothQuantRecommendationFrame", UIParent, "ButtonFrameTemplate")
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
  frame:SetPortraitToAsset(PORTRAIT)

  -- No button bar: the inset runs to the bottom edge, where the tabs hang.
  frame.Inset:ClearAllPoints()
  frame.Inset:SetPoint("TOPLEFT", frame, "TOPLEFT", 4, INSET_TOP)
  frame.Inset:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -6, 6)

  -- The two header lines, right of the portrait.
  frame.header1 = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  frame.header1:SetPoint("TOPLEFT", frame, "TOPLEFT", 66, -32)
  frame.header2 = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  frame.header2:SetPoint("TOPLEFT", frame.header1, "BOTTOMLEFT", 0, -4)

  createReloadButton()

  scroll = CreateFrame("ScrollFrame", nil, frame.Inset, "UIPanelScrollFrameTemplate")
  scroll:SetPoint("TOPLEFT", frame.Inset, "TOPLEFT", SCROLL_LEFT, -4 - HEADER_HEIGHT - 2)
  scroll:SetPoint("BOTTOMRIGHT", frame.Inset, "BOTTOMRIGHT", -SCROLLBAR_WIDTH, 6)
  content = CreateFrame("Frame", nil, scroll)
  content:SetSize(CONTENT_WIDTH, 1)
  scroll:SetScrollChild(content)

  createTabs()
end

-- An AH open always lands on the Shopping List; /aq recs reopens the tab last picked.
local function show(byAuctionHouse)
  if not frame then
    createFrame()
  end
  selected = RecommendationTable.openingTab(db.recommendationTab, byAuctionHouse)
  if frame:IsShown() then
    selectTab(selected)
    return
  end
  restorePosition()
  scroll:SetVerticalScroll(0)
  sorts = {} -- each open starts on the default sorts
  frame:Show()
end

local function toggle()
  if frame and frame:IsShown() then
    frame:Hide()
  else
    openedByAuctionHouse = false
    show(false)
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
    if market == "Neutral" then
      return
    end
    -- Already open via /aq recs: switch to the Shopping List but leave it open after the AH.
    if not (frame and frame:IsShown()) then
      openedByAuctionHouse = true
    end
    show(true)
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

SLASH_AZEROTHQUANT1 = "/aq"
SlashCmdList.AZEROTHQUANT = function(msg)
  if msg:match("^%s*recs%s*$") then
    toggle()
  elseif msg:match("^%s*reload%s*$") then
    reload()
  elseif msg:match("^%s*debug%s*$") then
    Chat.toggleDebug()
  else
    Chat.say("Usage: /aq recs (toggle the Recommendation Table), /aq reload,"
      .. " /aq debug (toggle chat lines you don't need to act on)")
  end
end
