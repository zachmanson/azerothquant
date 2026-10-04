-- WoW glue for the Recommendation Table: one movable Blizzard portrait panel showing the
-- Market's Recommendations from AzerothQuantRecommendations, one section per bottom tab.
-- All shaping happens in RecommendationTable.lua; this file only draws it and talks to the
-- WoW API. It opens next to a faction Auction House (not a Neutral one, whose Market the
-- Brain doesn't recommend for) and /aq recs toggles it anywhere. Its position, the tab
-- last picked and each Market's Budget and Days to Sell are saved in AzerothQuantDB;
-- open/closed is not.
--
-- Hover shows a tooltip, a click selects the row and shift-click links the item
-- (ADR-0016). With the AH open, the Post button posts the selected Sell row (#81): one
-- protected call per click, made only in onPostClick (spec/protected_calls_spec.lua). On a
-- Shopping List, Prediction buys or single-item Buy Under row not yet in the bags, the Search button takes its slot (#39): a click
-- searches the AH for the row's Item Key and a line under it shows the cheapest Listing.
-- Selecting a Craft row opens its Craft Chain panel on the left (#77). A right-click on a
-- buy-side row toggles its Bought mark (#97), saved per Market in AzerothQuantDB.bought:
-- it greys out and the Budget fold runs on the gold left.
-- The Budget box (#86) only saves what the player will spend: the table hides options over
-- it at once, and Character.lua hands it to the Brain in the next Character Read. The Days
-- to Sell box (#109) is saved and handed over the same way, and changes nothing until then.
local _, ns = ...
local RecommendationTable = ns.RecommendationTable
local BoughtMarks = ns.BoughtMarks
local CraftChain = ns.CraftChain
local Money = ns.Money
local Scan = ns.Scan
local Scanner = ns.Scanner
local DataAddon = ns.DataAddon
local Chat = ns.Chat
local PostButton = ns.PostButton
local SearchButton = ns.SearchButton
local Character = ns.Character
local TooltipLines = ns.TooltipLines

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
  ["Shopping List"] = { 160, 45, 40, 80, 80, 90, 80, 80, 50, 80 },
  ["Flips to Craft"] = { 190, 60, 45, 95, 95, 95, 95 },
  -- Item, Way out, Listings, Profit, then Cost. It never has a Beta column (#89).
  ["Flips to Disenchant"] = { 200, 330, 70, 110 },
  ["Prediction buys"] = { 230, 150, 50, 120 },
  ["Buy Under"] = { 230, 90, 250, 70, 110 },
}
-- The same while the Brain writes a Beta Prior (#90): a Beta column before the Note (last
-- on Prediction buys, where it takes the leftover). "2g 74s 50c*" needs 85. The Shopping
-- List makes room from Item and the Note (a Flip's is mostly empty), and keeps Post at and
-- Cost at 85 too, since "5g 43s 99c" clipped at 75 in game; the Buy Under from its way out.
local BETA_COLUMN_WIDTHS = {
  ["Holdings"] = { 230, 70, 50, 110, 110, 80, 85 },
  ["Shopping List"] = { 120, 40, 35, 75, 85, 80, 75, 75, 45, 85, 85 },
  ["Flips to Craft"] = { 190, 60, 45, 95, 95, 95, 95, 85 },
  ["Prediction buys"] = { 230, 150, 50, 120, 120 },
  ["Buy Under"] = { 230, 90, 195, 70, 110, 85 },
}
local MAX_COLUMNS = 12
local STRIPE_ALPHA = 0.04

local db
local frame, scroll, content
local lines = {} -- pooled line buttons, reused on every redraw
local headers = {} -- pooled column header buttons
local tabs = {}
local selected -- the title of the section on show
local shown -- the section on show, as built, so a header click knows its columns
local openedByAuctionHouse = false
local redrawQueued = false
-- The selected row's id (RecommendationTable.find). It survives a redraw while a row with
-- the same Item Key and action is on show, and clears otherwise.
local selectedId
-- That row as the last redraw built it, from whichever tab has it, and that tab's title.
local selectedRow
local selectedSection

-- C_Item on newer clients (the Beta has no global GetItemInfo), the old globals otherwise.
local getItemInfo = C_Item and C_Item.GetItemInfo or GetItemInfo
local getItemInfoInstant = C_Item and C_Item.GetItemInfoInstant or GetItemInfoInstant
local getDetailedItemLevelInfo = C_Item and C_Item.GetDetailedItemLevelInfo or GetDetailedItemLevelInfo

-- The logged-in Character's Market's key in AzerothQuantDB.budgets and .daysToSell.
local function marketKey()
  return RecommendationTable.marketKey(GetRealmName(), UnitFactionGroup("player") or "")
end

-- That Budget in copper, or nil for all the gold.
local function savedBudget()
  return db.budgets and db.budgets[marketKey()]
end

-- The Market's Days to Sell, saved under the same key in AzerothQuantDB.daysToSell, or nil.
local function savedDaysToSell()
  return db.daysToSell and db.daysToSell[marketKey()]
end

-- The item's name, or nil until the client has loaded it (GET_ITEM_INFO_RECEIVED follows).
local function nameOf(itemString)
  return (getItemInfo(itemString))
end

-- A section's column widths, the last one taking what's left of the row.
local function widthsFor(section)
  local byTitle = COLUMN_WIDTHS
  for _, name in ipairs(section.columns) do
    if name == "Beta" then
      byTitle = BETA_COLUMN_WIDTHS
    end
  end
  local widths = {}
  local used = ICON_SIZE + ICON_GAP
  for c, w in ipairs(byTitle[section.title]) do
    widths[c] = w
    used = used + w
  end
  widths[#widths + 1] = CONTENT_WIDTH - used
  return widths
end

-- The item, the row's tooltip lines, and any cell text clipped by its column. A row for
-- no one item (a Disenchant source group's Buy Under, #88) is titled by its first cell.
local function showTooltip(line)
  GameTooltip:SetOwner(line, "ANCHOR_RIGHT")
  if line.itemString then
    GameTooltip:SetHyperlink(line.itemString)
  else
    GameTooltip:SetText(line.cells[1]:GetText())
  end
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

local redraw, refreshPost

local function linkInChat(line)
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
  line:RegisterForClicks("LeftButtonUp", "RightButtonUp")
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
    if self.tooltip then
      showTooltip(self)
    end
  end)
  line:SetScript("OnLeave", GameTooltip_Hide)
  line:SetScript("OnClick", function(self, button)
    if button == "RightButton" then
      if self.markable then
        BoughtMarks.toggle(self.marks, self.id, self.cost, time())
        redraw()
      end
    elseif IsModifiedClick("CHATLINK") then
      if self.itemString then
        linkInChat(self)
      end
    elseif self.id and not self.bought then
      selectedId = self.id
      redraw()
    end
  end)
  lines[i] = line
  return line
end

-- Lays out one line: for an item, its icon and then its cells in columns of the given
-- widths, striped on every other row. Otherwise one text spans the line (the empty-tab
-- line, "N more"). marks, for a row of a buy-side tab, are the Market's Bought marks.
local function drawLine(i, texts, widths, font, item, justify, marks)
  local line = getLine(i)
  line:ClearAllPoints()
  line:SetPoint("TOPLEFT", content, "TOPLEFT", 0, -(i - 1) * LINE_HEIGHT)
  line:SetPoint("TOPRIGHT", content, "TOPRIGHT", 0, -(i - 1) * LINE_HEIGHT)
  line.itemString = item and item.itemString
  line.tooltip = item and item.tooltip
  line.id = item and item.id
  line.bought = item and item.bought
  line.marks = marks
  line.markable = marks ~= nil and item ~= nil
  line.cost = item and item.record.cost or 0
  if line.id and line.id == selectedId then
    line:LockHighlight()
  else
    line:UnlockHighlight()
  end
  line:EnableMouse(item ~= nil)
  line.stripe:SetShown(item ~= nil and i % 2 == 0)
  if item and item.itemString then
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

-- The Craft Chain panel (#77): the selected Craft row's chain as a top-down tree, docked to
-- the frame's left edge (over the AH: on the right it ran off the screen). It's the frame's
-- child, so it closes with it. CraftChain.lua shapes the lines; here they're drawn. The elbows are textures, not ├ └ │, which the
-- game's fonts may not have.
local PANEL_WIDTH = 300
local CHAIN_LINE_HEIGHT = 20
local CHAIN_ICON_SIZE = 16
local INDENT = 14
local GOLD_WIDTH = 64
local GUIDE_COLOR = { 0.6, 0.6, 0.6, 0.6 }
local BLOCKED_ICON = "|TInterface\\RaidFrame\\ReadyCheck-NotReady:0|t"
local GOLD_COLORS = {
  gain = { 0.12, 1, 0 },
  loss = { 1, 0.13, 0.13 },
  subtotal = { 0.6, 0.6, 0.6 },
}

local chainPanel
local chainLines = {}

local function setGoldColor(fontString, color)
  local rgb = GOLD_COLORS[color] or { 1, 1, 1 }
  fontString:SetTextColor(rgb[1], rgb[2], rgb[3])
end

-- The item, its gold's breakdown, and the line's text if the panel clipped it.
local function showChainTooltip(line)
  GameTooltip:SetOwner(line, "ANCHOR_RIGHT")
  GameTooltip:SetHyperlink(line.itemString)
  if line.text:IsTruncated() then
    GameTooltip:AddLine(line.text:GetText(), 1, 1, 1, true)
  end
  for _, text in ipairs(line.tooltip) do
    GameTooltip:AddLine(text, 1, 1, 1, true)
  end
  GameTooltip:Show()
end

local function newGuide(line)
  local guide = { up = line:CreateTexture(nil, "ARTWORK"), across = line:CreateTexture(nil, "ARTWORK") }
  guide.up:SetColorTexture(unpack(GUIDE_COLOR))
  guide.across:SetColorTexture(unpack(GUIDE_COLOR))
  return guide
end

local function getChainLine(i)
  local line = chainLines[i]
  if line then
    return line
  end
  line = CreateFrame("Button", nil, chainPanel)
  line:SetHeight(CHAIN_LINE_HEIGHT)
  line:RegisterForClicks("LeftButtonUp")
  line:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
  line.guides = {}
  line.icon = line:CreateTexture(nil, "ARTWORK")
  line.icon:SetSize(CHAIN_ICON_SIZE, CHAIN_ICON_SIZE)
  line.text = line:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  line.text:SetJustifyH("LEFT")
  line.text:SetWordWrap(false)
  line.gold = line:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  line.gold:SetJustifyH("RIGHT")
  line.gold:SetWidth(GOLD_WIDTH)
  line.gold:SetPoint("RIGHT", line, "RIGHT", -4, 0)
  line:SetScript("OnEnter", function(self)
    if self.itemString then
      showChainTooltip(self)
    end
  end)
  line:SetScript("OnLeave", GameTooltip_Hide)
  line:SetScript("OnClick", function(self)
    if self.itemString and IsModifiedClick("CHATLINK") then
      linkInChat(self)
    end
  end)
  chainLines[i] = line
  return line
end

-- One level's elbow or pipe, centred in its INDENT-wide column. "last" stops halfway down.
local function drawGuide(line, level, kind)
  local guide = line.guides[level] or newGuide(line)
  line.guides[level] = guide
  local x = (level - 1) * INDENT + INDENT / 2
  guide.up:ClearAllPoints()
  guide.across:ClearAllPoints()
  guide.up:SetShown(kind ~= "space")
  guide.across:SetShown(kind == "branch" or kind == "last")
  guide.up:SetWidth(1)
  guide.up:SetPoint("TOPLEFT", line, "TOPLEFT", x, 0)
  guide.up:SetHeight(kind == "last" and CHAIN_LINE_HEIGHT / 2 or CHAIN_LINE_HEIGHT)
  guide.across:SetHeight(1)
  guide.across:SetWidth(INDENT / 2)
  guide.across:SetPoint("LEFT", line, "TOPLEFT", x, -CHAIN_LINE_HEIGHT / 2)
end

-- A tree line (with an item) or the Profit footer.
local function drawChainLine(i, entry)
  local line = getChainLine(i)
  line:ClearAllPoints()
  line:SetPoint("TOPLEFT", chainPanel.Inset, "TOPLEFT", 6, -6 - (i - 1) * CHAIN_LINE_HEIGHT)
  line:SetPoint("RIGHT", chainPanel.Inset, "RIGHT", -6, 0)
  local guides = entry.guides or {}
  for _, guide in ipairs(line.guides) do
    guide.up:SetShown(false)
    guide.across:SetShown(false)
  end
  for level, kind in ipairs(guides) do
    drawGuide(line, level, kind)
  end
  local x = #guides * INDENT
  line.itemString = entry.itemString
  line.tooltip = entry.tooltip
  line:EnableMouse(entry.itemString ~= nil)
  if entry.itemString then
    line.icon:SetTexture(select(5, getItemInfoInstant(entry.itemString)))
    line.icon:ClearAllPoints()
    line.icon:SetPoint("LEFT", line, "LEFT", x + 1, 0)
    line.icon:Show()
    x = x + CHAIN_ICON_SIZE + 4
  else
    line.icon:Hide()
  end
  local text = entry.text
  if entry.tag then
    text = text .. " |cffa0a0a0" .. entry.tag .. "|r"
  end
  if entry.blocked then
    text = BLOCKED_ICON .. " " .. text .. " |cffff2020" .. entry.blocked .. "|r"
  end
  line.text:ClearAllPoints()
  line.text:SetPoint("LEFT", line, "LEFT", x, 0)
  line.text:SetPoint("RIGHT", line.gold, "LEFT", -4, 0)
  line.text:SetText(text)
  line.gold:SetText(entry.gold or "")
  setGoldColor(line.gold, entry.color)
  line:Show()
end

local function createChainPanel()
  chainPanel = CreateFrame("Frame", "AzerothQuantCraftChainPanel", frame, "ButtonFrameTemplate")
  chainPanel:SetPoint("TOPRIGHT", frame, "TOPLEFT", -2, 0)
  chainPanel:SetPoint("BOTTOMRIGHT", frame, "BOTTOMLEFT", -2, 0)
  chainPanel:SetWidth(PANEL_WIDTH)
  chainPanel.Inset:ClearAllPoints()
  chainPanel.Inset:SetPoint("TOPLEFT", chainPanel, "TOPLEFT", 4, INSET_TOP)
  chainPanel.Inset:SetPoint("BOTTOMRIGHT", chainPanel, "BOTTOMRIGHT", -6, 6)
  -- Why a row has no chain to draw, wrapped across the panel.
  chainPanel.empty = chainPanel:CreateFontString(nil, "OVERLAY", "GameFontDisable")
  chainPanel.empty:SetPoint("TOPLEFT", chainPanel.Inset, "TOPLEFT", 10, -10)
  chainPanel.empty:SetPoint("RIGHT", chainPanel.Inset, "RIGHT", -10, 0)
  chainPanel.empty:SetJustifyH("LEFT")
  -- Closing it drops the selection, or the next redraw would open it again.
  chainPanel.CloseButton:SetScript("OnClick", function()
    selectedId = nil
    redraw()
  end)
end

-- Opens the panel on a Craft row, or closes it (nil).
local function drawChain(record)
  if not record then
    if chainPanel then
      chainPanel:Hide()
    end
    return
  end
  if not chainPanel then
    createChainPanel()
  end
  local chain = CraftChain.build(record, nameOf)
  local itemString = RecommendationTable.itemString(record.itemKey)
  chainPanel:SetTitle("Craft Chain: " .. (nameOf(itemString) or itemString))
  chainPanel:SetPortraitToAsset(select(5, getItemInfoInstant(itemString)) or PORTRAIT)
  local n = 0
  for _, entry in ipairs(chain.lines) do
    n = n + 1
    drawChainLine(n, entry)
  end
  chainPanel.empty:SetText(chain.empty or "")
  if chain.profit then
    n = n + 1
    drawChainLine(n, chain.profit)
  end
  for i = n + 1, #chainLines do
    chainLines[i]:Hide()
  end
  chainPanel:Show()
end

-- The sort the section on show is in: the last header click, saved across sessions (#98),
-- or its default.
local function activeSort(section)
  local saved = db.recommendationSorts and db.recommendationSorts[section.title]
  return RecommendationTable.restoredSort(section, saved) or section.sort
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
    local sort = RecommendationTable.nextSort(shown, activeSort(shown), c)
    db.recommendationSorts = db.recommendationSorts or {}
    db.recommendationSorts[shown.title] = RecommendationTable.savedSort(shown, sort)
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
  local recommendations = AzerothQuantRecommendations and AzerothQuantRecommendations.recommendations
  local realm, faction = GetRealmName(), UnitFactionGroup("player") or ""
  local marks = BoughtMarks.forMarket(db, recommendations, realm, faction)
  local view = RecommendationTable.build(
    recommendations,
    realm,
    faction,
    time(),
    nameOf,
    table.concat({ UnitFullName("player") }, "-"),
    savedBudget(),
    marks,
    GetMoney()
  )
  local n = 0
  local function add(texts, widths, font, item, justify, rowMarks)
    n = n + 1
    drawLine(n, texts, widths, font, item, justify, rowMarks)
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
        local widths = widthsFor(section)
        local sort = activeSort(section)
        RecommendationTable.sort(section, sort)
        drawHeaders(section.columns, widths, sort)
        if section.empty then
          add({ section.empty }, nil, "GameFontDisable", nil, "CENTER")
        end
        for _, row in ipairs(section.rows) do
          local font = row.bought and "GameFontDisable" or "GameFontHighlight"
          add(row.cells, widths, font, row, nil, section.markable and marks or nil)
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

  -- The selection clears once no tab has its row, or its row is marked Bought, so a tab
  -- switch keeps it. A selected Craft row on show opens its chain; any other row, or none,
  -- closes it.
  local kept = false
  for _, section in ipairs(view.sections or {}) do
    local row = selectedId and RecommendationTable.find(section, selectedId)
    kept = kept or (row ~= nil and not row.bought)
  end
  if not kept then
    selectedId = nil
  end
  selectedRow, selectedSection = nil, nil
  for _, section in ipairs(view.sections or {}) do
    if not selectedRow then
      selectedRow = selectedId and RecommendationTable.find(section, selectedId)
      selectedSection = selectedRow and section.title
    end
  end
  local row = shown and selectedId and RecommendationTable.find(shown, selectedId)
  drawChain(row and row.record.action == "Craft" and row.record or nil)
  refreshPost()
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
local TAB_TITLES = {
  "Holdings", "Shopping List", "Flips to Craft", "Flips to Disenchant", "Prediction buys", "Buy Under",
}

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
-- Recommendations.lua. Not mid-Scan, which would lose it. The Brain imports what the
-- reload saved and writes a new Recommendations.lua a minute or so later; when the
-- startup copy missed it, the button becomes Load, which reads the Brain's copy in
-- AzerothQuant_Data without a second reload (DataAddon.lua, #106). Load works once per
-- reload, and can run mid-Scan since it doesn't reload.
local RELOAD_TIP = "Reload the UI: saves new Scans for the Brain and loads its latest Recommendations."
local LOAD_TIP = "Load the Brain's latest Recommendations (once per reload)."
local BUSY_TIP = "Wait for the Scan to finish: reloading now would lose it."

local function reload()
  if Scanner.busy() then
    Chat.say(BUSY_TIP)
    return
  end
  ReloadUI()
end

local function loadRecommendations()
  if not DataAddon.canLoad() then
    Chat.say("Nothing new to load: /aq reload instead.")
    return
  end
  local fresh = DataAddon.load()
  if fresh ~= nil then
    Scanner.afterDataLoad(fresh)
    redraw()
  end
end

local BUDGET_TIP = "Most gold to spend on each Shopping List option, and on Prediction buys. "
  .. "Blank for all your gold. Options over it hide now; Reload to re-size the rest."

local DAYS_TIP = "Most days a unit you buy to Sell may take to sell: caps Flips to Sell, "
  .. "Flips to Craft and to Disenchant, and Buy Unders. Blank for the Sale Horizon, never more than it. "
  .. "Reload to re-size."

-- A box left of `anchor` for one per-Market setting. Enter saves it (blank clears it);
-- Escape puts it back. setting: { label, width, tip, hint, parse, text, saved, save },
-- where parse(text) returns the value and whether it's ok, and text(value) shows it.
local function createSettingBox(anchor, setting)
  local box = CreateFrame("EditBox", nil, frame, "InputBoxTemplate")
  box:SetSize(setting.width, 20)
  box:SetAutoFocus(false)
  box:SetMaxLetters(10)
  box:SetPoint("RIGHT", anchor, "LEFT", -10, 0)
  box.label = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  box.label:SetPoint("RIGHT", box, "LEFT", -8, 0)
  box.label:SetText(setting.label)
  box:SetScript("OnEnterPressed", function(self)
    local value, ok = setting.parse(self:GetText())
    if ok then
      setting.save(value)
    else
      Chat.say(setting.hint)
    end
    self:SetText(setting.text(setting.saved()))
    self:ClearFocus()
  end)
  box:SetScript("OnEscapePressed", function(self)
    self:SetText(setting.text(setting.saved()))
    self:ClearFocus()
  end)
  box:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText(setting.tip, 1, 1, 1, 1, true)
    GameTooltip:Show()
  end)
  box:SetScript("OnLeave", GameTooltip_Hide)
  -- Shows the saved value, unfocused. Called from the frame's OnShow: the box's own
  -- OnShow didn't fire on the first open after a /reload, so it stayed blank, and an
  -- Enter into that blank box then cleared the setting.
  function box.refresh()
    box:SetText(setting.text(setting.saved()))
    box:ClearFocus()
  end
  return box
end

local function createBudgetBox(button)
  frame.budget = createSettingBox(button, {
    label = "Budget (g)",
    width = 60,
    tip = BUDGET_TIP,
    hint = "Budget: type gold, like 250 or 12.5, or leave it blank for all your gold.",
    parse = Money.parseGold,
    text = Money.goldText,
    saved = savedBudget,
    save = function(copper)
      db.budgets = db.budgets or {}
      db.budgets[marketKey()] = copper
      redraw()
    end,
  })
end

local function createDaysToSellBox()
  frame.daysToSell = createSettingBox(frame.budget.label, {
    label = "Days to Sell",
    width = 36,
    tip = DAYS_TIP,
    hint = "Days to Sell: type days over 0, like 2 or 0.5, or leave it blank for the Sale Horizon.",
    parse = RecommendationTable.parseDays,
    text = RecommendationTable.daysText,
    saved = savedDaysToSell,
    save = function(days)
      db.daysToSell = db.daysToSell or {}
      db.daysToSell[marketKey()] = days
    end,
  })
end

local function createReloadButton()
  local button = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
  button:SetSize(70, 22)
  button:SetText("Reload")
  button:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -10, -30)
  button:SetScript("OnClick", function()
    if DataAddon.canLoad() then
      loadRecommendations()
    else
      reload()
    end
  end)
  -- Disabled buttons get no OnEnter unless told to, and the tooltip must say why it's off.
  button:SetMotionScriptsWhileDisabled(true)
  button:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    local tip = DataAddon.canLoad() and LOAD_TIP or Scanner.busy() and BUSY_TIP or RELOAD_TIP
    GameTooltip:SetText(tip, 1, 1, 1, 1, true)
    GameTooltip:Show()
  end)
  button:SetScript("OnLeave", GameTooltip_Hide)
  createBudgetBox(button)
  createDaysToSellBox()

  -- Scans the table doesn't reflect yet, in orange left of the Days to Sell box, and the
  -- button lights up.
  local note = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  note:SetPoint("RIGHT", frame.daysToSell.label, "LEFT", -8, 0)
  note:SetTextColor(1, 0.5, 0.25)

  -- Pulses once the Brain should have imported the Scans saved at load (#71).
  local pulse = Scanner.addPulse(button)

  -- A Scan starts and ends on its own clock, so follow it while the frame is shown. So
  -- does Load, which is used up once clicked.
  button:SetScript("OnUpdate", function(self)
    local canLoad = DataAddon.canLoad()
    local label = canLoad and "Load" or "Reload"
    if self:GetText() ~= label then
      self:SetText(label)
    end
    local enabled = canLoad or not Scanner.busy()
    self:SetEnabled(enabled)
    Scanner.setPulsing(pulse, Scanner.reloadReady() and enabled)
    local unsaved, unimported, behind = Scanner.waiting()
    local text = RecommendationTable.waitingNote(unsaved, unimported, behind, canLoad)
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

-- The Post button (#81, ADR-0016). It posts the selected row only when clicked, and never
-- moves on to the next row. Units posted are counted per row id for this session (until
-- the next import or /reload): the next Scan shows the Listings as the player's own.
local ahOpen = false
local postButton
local postState -- PostButton.state for the selected row; onPostClick makes its call
local posted = {} -- units posted by row id
local postedFor -- the AzerothQuantRecommendations the counts are against
local pending -- true while a post waits for the AH to confirm it
-- { id, quantity }: the last post sent. Counted when the AH confirms it, even after an
-- unrelated UI error ended the wait, so the same units can't be posted twice.
local lastPost
local postError -- { id, text }: why the last post of that row failed, for the tooltip
-- { id, itemID, queryKey, itemKey, results, lowest }: the last search sent, for Post's undercut
-- line or Search's live line. itemKey is set only by Search (#39); results are nil until
-- they land.
local search
local searchButton
local searchState -- SearchButton.state for the selected row, or nil when the slot is Post's

-- This Character's unbound units of the Item Key in its bags, and the first slot of them
-- that isn't locked (being moved), as an ItemLocation.
local function inBags(itemKey)
  local units, location = 0, nil
  for _, bag in ipairs(Character.bagIds()) do
    for slot = 1, C_Container.GetContainerNumSlots(bag) or 0 do
      local info = C_Container.GetContainerItemInfo(bag, slot)
      if info and not info.isBound and TooltipLines.itemKey(info.hyperlink) == itemKey then
        units = units + info.stackCount
        if not location and not info.isLocked then
          location = ItemLocation:CreateFromBagAndSlot(bag, slot)
        end
      end
    end
  end
  return units, location
end

-- true for a commodity, false for gear, nil until the client knows.
local function isCommodity(location)
  local status = C_AuctionHouse.GetItemCommodityStatus(location)
  if status == Enum.ItemCommodityStatus.Commodity then
    return true
  elseif status == Enum.ItemCommodityStatus.Item then
    return false
  end
  return nil
end

-- One search for the selected row. itemKey, given by Search, keeps only that Item Key's
-- Listings of gear (searchResults).
local function sendSearch(row, itemID, queryKey, itemKey)
  search = { id = row.id, itemID = itemID, queryKey = queryKey, itemKey = itemKey }
  C_AuctionHouse.SendSearchQuery(queryKey, {}, false)
end

-- The search key for an item in the bags. Gear needs its full key (item level, suffix)
-- from the item itself, a commodity only its itemID (#39).
local function bagKey(location, commodity)
  local itemID = C_Item.GetItemID(location)
  return itemID, commodity and C_AuctionHouse.MakeItemKey(itemID) or C_AuctionHouse.GetItemKeyFromItem(location)
end

-- The search key for a row's Item Key when none is in the bags, or nil until the client
-- has the item. Only an item in the bags gives a suffixed key, so gear searches by itemID
-- and item level, and searchResults keeps the Listings of the row's exact Item Key. A
-- stack of more than one is taken as a commodity, which searches by itemID alone.
-- Unchecked in game for suffixed gear: see #39 slice 1's in-game check.
local function buyKey(itemKey)
  local itemString = RecommendationTable.itemString(itemKey)
  local _, _, _, level, _, _, _, maxStack = getItemInfo(itemString)
  if not maxStack then
    return nil
  end
  local itemID = tonumber(itemKey:match("^(%d+)"))
  if maxStack > 1 then
    return itemID, C_AuctionHouse.MakeItemKey(itemID)
  end
  return itemID, C_AuctionHouse.MakeItemKey(itemID, getDetailedItemLevelInfo(itemString) or level)
end

-- The search's results as PostButton.lowestOther and SearchButton.liveLine take them.
-- commodity says which results landed (the event that fired).
local function searchResults(commodity)
  local results = {}
  if commodity then
    for i = 1, C_AuctionHouse.GetNumCommoditySearchResults(search.itemID) do
      local r = C_AuctionHouse.GetCommoditySearchResultInfo(search.itemID, i)
      if r then
        results[#results + 1] = { unitPrice = r.unitPrice, quantity = r.quantity, ownUnits = r.numOwnerItems }
      end
    end
  else
    for i = 1, C_AuctionHouse.GetNumItemSearchResults(search.queryKey) do
      local r = C_AuctionHouse.GetItemSearchResultInfo(search.queryKey, i)
      -- A bid-only Listing has no buyout to undercut or buy at.
      local wanted = r and (not search.itemKey or (r.itemLink and TooltipLines.itemKey(r.itemLink) == search.itemKey))
      if wanted and r.buyoutAmount and r.quantity > 0 then
        results[#results + 1] = {
          unitPrice = r.buyoutAmount / r.quantity,
          quantity = r.quantity,
          ownUnits = r.containsOwnerItem and r.quantity or 0,
        }
      end
    end
  end
  return results
end

function refreshPost()
  if not postButton then
    return
  end
  -- A new import (a reload, or the Load button) starts the counts over.
  if AzerothQuantRecommendations ~= postedFor then
    posted, postedFor = {}, AzerothQuantRecommendations
  end
  local row = selectedRow
  local units, location = 0, nil
  if ahOpen and row and row.record.itemKey then
    units, location = inBags(row.record.itemKey)
  end
  -- Search or Post share the slot under the frame (#39).
  searchState = SearchButton.state(row, {
    section = selectedSection,
    ahOpen = ahOpen,
    throttled = ahOpen and not C_AuctionHouse.IsThrottledMessageSystemReady(),
    bagUnits = units,
    loaded = ahOpen and row and row.record.itemKey and buyKey(row.record.itemKey) ~= nil,
  })
  searchButton:SetShown(ahOpen and searchState ~= nil)
  postButton:SetShown(ahOpen and searchState == nil)
  if searchState then
    postState = nil
    searchButton:SetText(searchState.label)
    searchButton:SetEnabled(searchState.enabled)
    local mine = search and search.id == row.id and search.itemKey
    local line = mine and (search.results and SearchButton.liveLine(search.results, row.record.price) or "Searching...")
    searchButton.live:SetText(line or "")
    return
  end
  local commodity
  if location then
    commodity = isCommodity(location)
  end
  postState = PostButton.state(row, {
    ahOpen = ahOpen,
    bagUnits = units,
    posted = row and posted[row.id] or 0,
    pending = pending,
    commodity = commodity,
    durationHours = AzerothQuantRecommendations and AzerothQuantRecommendations.postDurationHours,
    lowest = search and row and search.id == row.id and search.lowest or nil,
  })
  postButton:SetText(postState.label)
  postButton:SetWidth(math.max(90, postButton:GetTextWidth() + 30))
  postButton:SetEnabled(postState.enabled)
  postButton.undercut:SetText(postState.undercut or "")
  -- A Search's results predate the buy that made the row postable, so Post searches again.
  if postState.call and not (search and search.id == row.id and not search.itemKey) then
    sendSearch(row, bagKey(location, commodity))
  end
end

-- Searches the Auction House for the selected row's item, only when clicked (ADR-0016). A
-- search is a read: nothing here is protected.
local function onSearchClick()
  local call = searchState and searchState.call
  if not call then
    return
  end
  local itemID, key = buyKey(call.itemKey)
  if not key then
    return
  end
  sendSearch(selectedRow, itemID, key, call.itemKey)
  refreshPost()
end

local function onPostClick(self)
  local call = postState and postState.call
  if not call then
    return
  end
  local _, location = inBags(selectedRow.record.itemKey)
  if not location then
    return
  end
  if call.kind == "commodity" then
    C_AuctionHouse.PostCommodity(location, call.duration, call.quantity, call.price)
  else
    -- Returns false (retail would want a Confirm), but posts anyway on Forever.
    C_AuctionHouse.PostItem(location, call.duration, call.quantity, nil, call.price)
  end
  pending, lastPost, postError = true, { id = selectedRow.id, quantity = call.quantity }, nil
  refreshPost()
end

local function createPostButton()
  postButton = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
  postButton:SetSize(90, 22)
  -- Hangs under the frame's bottom right, level with the tabs.
  postButton:SetPoint("TOPRIGHT", frame, "BOTTOMRIGHT", -6, -2)
  postButton:SetScript("OnClick", onPostClick)
  postButton:SetMotionScriptsWhileDisabled(true)
  postButton:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    local failed = postError and selectedRow and postError.id == selectedRow.id and postError.text
    local tip = failed or (postState and postState.reason) or "Post the selected row at its Post at."
    GameTooltip:SetText(tip, 1, 1, 1, 1, true)
    GameTooltip:Show()
  end)
  postButton:SetScript("OnLeave", GameTooltip_Hide)
  postButton.undercut = postButton:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  postButton.undercut:SetPoint("TOPRIGHT", postButton, "BOTTOMRIGHT", 0, -4)
  postButton.undercut:SetTextColor(1, 0.5, 0.25)
  postButton:Hide()

  -- Search takes the same slot on a buy-side row (#39).
  searchButton = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
  searchButton:SetSize(90, 22)
  searchButton:SetPoint("TOPRIGHT", frame, "BOTTOMRIGHT", -6, -2)
  searchButton:SetText("Search")
  searchButton:SetScript("OnClick", onSearchClick)
  searchButton:SetMotionScriptsWhileDisabled(true)
  searchButton:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    local tip = searchState and searchState.reason or "Search the Auction House for the selected row's item."
    GameTooltip:SetText(tip, 1, 1, 1, 1, true)
    GameTooltip:Show()
  end)
  searchButton:SetScript("OnLeave", GameTooltip_Hide)
  searchButton.live = searchButton:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  searchButton.live:SetPoint("TOPRIGHT", searchButton, "BOTTOMRIGHT", 0, -4)
  searchButton:Hide()
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
  frame:SetScript("OnShow", function()
    frame.budget.refresh()
    frame.daysToSell.refresh()
    redraw()
  end)
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
  createPostButton()

  -- After the boxes exist (the frame:Hide() above would otherwise fire it first).
  -- A box left focused while hidden would swallow the next Enter meant for chat.
  frame:SetScript("OnHide", function()
    frame.budget:ClearFocus()
    frame.daysToSell:ClearFocus()
  end)
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
-- The gold on hand caps the gold left the fold runs on once a row is marked Bought (#97).
events:RegisterEvent("PLAYER_MONEY")
-- The Post button's bag counts, post confirmations and failures, and undercut search.
events:RegisterEvent("BAG_UPDATE_DELAYED")
events:RegisterEvent("AUCTION_HOUSE_AUCTION_CREATED")
events:RegisterEvent("UI_ERROR_MESSAGE")
events:RegisterEvent("COMMODITY_SEARCH_RESULTS_UPDATED")
events:RegisterEvent("ITEM_SEARCH_RESULTS_UPDATED")
-- Search waits for the AH to take another search (#39).
events:RegisterEvent("AUCTION_HOUSE_THROTTLED_SYSTEM_READY")
pcall(events.RegisterEvent, events, "AUCTION_HOUSE_POST_ERROR") -- not on every client
events:SetScript("OnEvent", function(_, event, arg1, arg2)
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
    -- Not at a Neutral AH: its Market isn't the one the Brain priced the Post at for.
    ahOpen = true
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
    ahOpen, pending, lastPost, postError, search = false, false, nil, nil, nil
    refreshPost()
  elseif event == "GET_ITEM_INFO_RECEIVED" or event == "PLAYER_MONEY" then
    queueRedraw()
  elseif event == "BAG_UPDATE_DELAYED" then
    refreshPost()
  elseif event == "AUCTION_HOUSE_AUCTION_CREATED" and lastPost then
    posted[lastPost.id] = (posted[lastPost.id] or 0) + lastPost.quantity
    pending, lastPost, postError = false, nil, nil
    refreshPost()
  elseif (event == "AUCTION_HOUSE_POST_ERROR" or event == "UI_ERROR_MESSAGE") and pending then
    pending = false
    -- UI_ERROR_MESSAGE carries (errorType, message).
    local why = event == "UI_ERROR_MESSAGE" and tostring(arg2) or "the Auction House refused it."
    postError = { id = lastPost.id, text = "The post failed: " .. why }
    refreshPost()
  elseif event == "COMMODITY_SEARCH_RESULTS_UPDATED" or event == "ITEM_SEARCH_RESULTS_UPDATED" then
    -- arg1 is the itemID (commodity) or the item key searched. Another item's results
    -- (Blizzard's own searches) aren't ours.
    local itemID = type(arg1) == "table" and arg1.itemID or arg1
    if search and (itemID == nil or itemID == search.itemID) then
      search.results = searchResults(event == "COMMODITY_SEARCH_RESULTS_UPDATED")
      search.lowest = PostButton.lowestOther(search.results)
      refreshPost()
    end
  elseif event == "AUCTION_HOUSE_THROTTLED_SYSTEM_READY" then
    refreshPost()
  end
end)

SLASH_AZEROTHQUANT1 = "/aq"
SlashCmdList.AZEROTHQUANT = function(msg)
  if msg:match("^%s*recs%s*$") then
    toggle()
  elseif msg:match("^%s*reload%s*$") then
    reload()
  elseif msg:match("^%s*load%s*$") then
    loadRecommendations()
  elseif msg:match("^%s*debug%s*$") then
    Chat.toggleDebug()
  else
    Chat.say("Usage: /aq recs (toggle the Recommendation Table), /aq reload, /aq load,"
      .. " /aq debug (toggle chat lines you don't need to act on)")
  end
end
