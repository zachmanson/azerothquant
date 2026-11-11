-- WoW glue for the Recommendation Table: one movable Blizzard portrait panel showing the
-- Market's Recommendations from AzerothQuantRecommendations, one section per tab along the
-- top. Under the tabs a banner shows the one next step in the Scan, Reload, Load loop
-- (NextStep.lua, #161), with the one button that does it.
-- All shaping happens in RecommendationTable.lua; this file only draws it and talks to the
-- WoW API. It opens next to a faction Auction House (not a Neutral one, whose Market the
-- Brain doesn't recommend for) and /aq recs toggles it anywhere. Its position, size, the tab
-- last picked and each Market's Budget and Days to Sell are saved in AzerothQuantDB;
-- open/closed is not.
--
-- The side pane on the right (#160) shows the row under the mouse, or else the selected
-- (pinned) row: its Action, Note, what to do, its details and any values the table was too
-- narrow to show. A click selects the row and shift-click links the item (ADR-0016). With
-- the AH open, the pane's Post button posts the selected Sell row (#81): one protected call
-- per click, made only in onPostClick (spec/protected_calls_spec.lua). On a Shopping List,
-- Prediction buy or single-item Buy Under row not yet in the bags, the Search button takes
-- its slot (#39): a click searches the AH for the row's Item Key and a line under it shows
-- the cheapest Listing. Under them, the Cancel undercut button (#177, ADR-0044) cancels the
-- Character's next Undercut Listing, one CancelAuction per click, only in onCancelClick.
-- Every AH search goes through one throttle-respecting queue (SearchQueue.lua).
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
local ColumnLayout = ns.ColumnLayout
local Money = ns.Money
local Tips = ns.Tips
local Scan = ns.Scan
local Scanner = ns.Scanner
local Chat = ns.Chat
local PostButton = ns.PostButton
local SearchButton = ns.SearchButton
local CancelButton = ns.CancelButton
local SearchQueue = ns.SearchQueue
local Character = ns.Character
local TooltipLines = ns.TooltipLines
local NextStep = ns.NextStep
local Nudge = ns.Nudge
local Placement = ns.Placement

-- Templates below were probed on the Beta client (#46): ButtonFrameTemplate (portrait
-- panel with an inset), PanelTabButtonTemplate, ColumnDisplayButtonTemplate (the AH's
-- column headers). The Classic-era names (CharacterFrameTabButtonTemplate,
-- WhoFrameColumnHeaderTemplate) are missing there.
-- The frame is resizable from its bottom-right corner, and its size is saved (#136). It
-- opens at WIDTH, narrowed to the room beside the AH, or below the AH when MIN_WIDTH doesn't
-- fit there (#164). At MIN_WIDTH the Shopping List's rows get 690 beside the side pane, which
-- ColumnLayout fits by hiding Beta, Cost, ROI and Per click.
local WIDTH, HEIGHT = 1100, 540
local MIN_WIDTH, MIN_HEIGHT = 1000, 400
local AH_GAP = 10 -- between the AH and the frame on first open
local PORTRAIT = "Interface\\Icons\\INV_Misc_Coin_01"
local INSET_TOP = -64 -- the Craft Chain panel's: room for a header under the title bar
-- Top to bottom under the title bar: the tabs, the banner (BANNER_HEIGHT, or QUIET_HEIGHT
-- when up to date), then the two header lines beside the Budget and Days to Sell boxes
-- (HEADER_ROW), then the inset.
local TABS_TOP = -26
local BANNER_TOP = -60 -- clear of the portrait
local BANNER_HEIGHT, QUIET_HEIGHT = 40, 20
local HEADER_ROW = 34
local LINE_HEIGHT = 22
local ICON_SIZE = 20
local ICON_GAP = ColumnLayout.ICON_WIDTH - ICON_SIZE
local HEADER_HEIGHT = 24
local SCROLL_LEFT = 6
local SCROLLBAR_WIDTH = 30
-- The side pane, at the inset's right edge (#160).
local PANE_WIDTH, PANE_GAP = 260, 4
-- The inset spans x 4 .. width-6; rows sit inside it, left of the scroll bar and the pane.
local CONTENT_INSET = 10 + SCROLL_LEFT + SCROLLBAR_WIDTH + PANE_GAP + PANE_WIDTH
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
-- That row as the last redraw built it, from whichever tab has it, that tab's title, and
-- the section (as built) it's in.
local selectedRow
local selectedSection
local selectedRowSection
local pane -- the side pane (#160)
local hovered -- the line under the mouse, which the pane shows over the selected row

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

-- The width the rows get at the frame's current size.
local function contentWidth()
  return frame:GetWidth() - CONTENT_INSET
end

local redraw, refreshPost, refreshCancel, drawPane

-- A plain hover text (Tips.lua, #163): a gold title when there is one, then the text and
-- a grey footnote.
local function showTip(owner, title, text, footnote)
  GameTooltip:SetOwner(owner, "ANCHOR_RIGHT")
  if title then
    GameTooltip:SetText(title)
    GameTooltip:AddLine(text, 1, 1, 1, true)
  else
    GameTooltip:SetText(text, 1, 1, 1, 1, true)
  end
  if footnote then
    GameTooltip:AddLine(footnote, 0.7, 0.7, 0.7, true)
  end
  GameTooltip:Show()
end

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
  -- The pane follows the mouse, and goes back to the selected row once it leaves the rows.
  line:SetScript("OnEnter", function(self)
    if self.row then
      hovered = self
      drawPane()
    end
  end)
  line:SetScript("OnLeave", function(self)
    if hovered == self then
      hovered = nil
      drawPane()
    end
  end)
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

-- Lays out one line: for an item, its icon and then its cells in the columns of layout
-- (ColumnLayout.fit over section), striped on every other row; an item's span (#207) is the
-- column whose text runs over the empty cells after it. Otherwise one text spans the line
-- (the empty-tab line, "N more", a Prediction's header). marks, for a row of a buy-side tab, are the
-- Market's Bought marks.
local function drawLine(i, texts, layout, font, item, justify, marks, section)
  local line = getLine(i)
  line:ClearAllPoints()
  line:SetPoint("TOPLEFT", content, "TOPLEFT", 0, -(i - 1) * LINE_HEIGHT)
  line:SetPoint("TOPRIGHT", content, "TOPRIGHT", 0, -(i - 1) * LINE_HEIGHT)
  line.itemString = item and item.itemString
  line.row = item
  line.layout, line.section = layout, section
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
  -- Each cell's text, and its width (nil for one text across the line).
  local placed, widths = {}, {}
  if layout then
    for k, p in ipairs(layout) do
      placed[k], widths[k] = texts[p.column], p.width
    end
    -- A Prediction's reason (#207) runs over the empty buy cells after it. A cell with no
    -- text takes no room, so the cells after those stay in their columns.
    local from
    for k, p in ipairs(layout) do
      if item and p.column == item.span then
        from = k
      elseif from and placed[k] == nil then
        widths[from] = widths[from] + p.width
      else
        from = nil
      end
    end
  else
    placed[1] = texts[1]
  end
  local x = ICON_SIZE + ICON_GAP
  for c, cell in ipairs(line.cells) do
    local text = placed[c]
    if text then
      cell:SetFontObject(font)
      cell:SetJustifyH(justify or "LEFT")
      cell:ClearAllPoints()
      if layout then
        cell:SetPoint("LEFT", line, "LEFT", x, 0)
        cell:SetWidth(widths[c] - 6)
        x = x + widths[c]
      else
        cell:SetPoint("LEFT", line, "LEFT", 0, 0)
        cell:SetWidth(contentWidth())
      end
      cell:SetText(text)
      cell:Show()
    else
      cell:Hide()
    end
  end
  line:Show()
end

-- The side pane (#160): the row under the mouse, else the selected row. Its item hovers to
-- the game's item tooltip and shift-clicks into chat. Post and Search sit at its bottom, in
-- pane.actions, and act on the selected row only, so they hide while it shows another.
local EMPTY_PANE = "|cffb0b0b0Hover a row to see more about it here.|r"

local function createPane()
  pane = CreateFrame("Frame", nil, frame.Inset)
  pane:SetPoint("TOPRIGHT", frame.Inset, "TOPRIGHT", -4, -4)
  pane:SetPoint("BOTTOMRIGHT", frame.Inset, "BOTTOMRIGHT", -4, 4)
  pane:SetWidth(PANE_WIDTH)
  local background = pane:CreateTexture(nil, "BACKGROUND")
  background:SetAllPoints()
  background:SetColorTexture(0, 0, 0, 0.25)
  local edge = pane:CreateTexture(nil, "BORDER")
  edge:SetPoint("TOPLEFT")
  edge:SetPoint("BOTTOMLEFT")
  edge:SetWidth(1)
  edge:SetColorTexture(1, 0.82, 0, 0.25)

  local item = CreateFrame("Button", nil, pane)
  item:SetPoint("TOPLEFT", 10, -10)
  item:SetPoint("RIGHT", -10, 0)
  item:SetHeight(32)
  item.icon = item:CreateTexture(nil, "ARTWORK")
  item.icon:SetSize(28, 28)
  item.icon:SetPoint("LEFT")
  item.name = item:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  item.name:SetPoint("LEFT", item.icon, "RIGHT", 6, 0)
  item.name:SetPoint("RIGHT")
  item.name:SetJustifyH("LEFT")
  item.name:SetMaxLines(2)
  item:SetScript("OnEnter", function(self)
    if self.itemString then
      GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
      GameTooltip:SetHyperlink(self.itemString)
      GameTooltip:Show()
    end
  end)
  item:SetScript("OnLeave", GameTooltip_Hide)
  item:SetScript("OnClick", function(self)
    if self.itemString and IsModifiedClick("CHATLINK") then
      linkInChat(self)
    end
  end)
  pane.item = item

  -- Post or Search and the line under it.
  pane.actions = CreateFrame("Frame", nil, pane)
  pane.actions:SetPoint("BOTTOMLEFT", 10, 4)
  pane.actions:SetPoint("BOTTOMRIGHT", -10, 4)
  pane.actions:SetHeight(46)

  pane.body = pane:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  pane.body:SetPoint("TOPLEFT", pane, "TOPLEFT", 10, -50)
  pane.body:SetPoint("BOTTOMRIGHT", pane.actions, "TOPRIGHT", 0, 6)
  pane.body:SetJustifyH("LEFT")
  pane.body:SetJustifyV("TOP")
  pane.body:SetSpacing(2)
end

-- The row the pane shows, the section and layout it's drawn in (the selected row's may be
-- on another tab), and its line when one is on show, for the cells clipped there.
local function paneRow()
  if hovered and hovered:IsShown() and hovered.row then
    return hovered.row, hovered.section, hovered.layout, hovered
  end
  if not selectedRow then
    return nil
  end
  local layout = ColumnLayout.fit(selectedRowSection, contentWidth())
  for _, line in ipairs(lines) do
    if line:IsShown() and line.id == selectedRow.id then
      return selectedRow, selectedRowSection, layout, line
    end
  end
  return selectedRow, selectedRowSection, layout, nil
end

function drawPane()
  if not pane then
    return
  end
  local row, section, layout, line = paneRow()
  pane.item:SetShown(row ~= nil)
  pane.actions:SetShown(row ~= nil and row == selectedRow)
  if not row then
    pane.body:SetText(EMPTY_PANE)
    return
  end
  pane.item.itemString = row.itemString
  pane.item.icon:SetTexture(row.itemString and select(5, getItemInfoInstant(row.itemString)) or nil)
  pane.item.name:SetText(row.name)
  -- What the table hid (#136), then what it clipped; the first cell is the item, named in
  -- full above.
  local values = ColumnLayout.hiddenValues(section, layout, row)
  if line then
    for k = 2, #layout do
      local cell = line.cells[k]
      if cell:IsShown() and cell:IsTruncated() then
        values[#values + 1] = { name = section.columns[layout[k].column], text = cell:GetText() }
      end
    end
  end
  pane.body:SetText(RecommendationTable.paneText(row, values))
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

-- Gold column headers over the rows, pooled by place. A click sorts by the column the
-- header is over (header.column, its place in the section's columns; see nextSort).
local function getHeader(k)
  local header = headers[k]
  if header then
    return header
  end
  header = CreateFrame("Button", nil, frame.Inset, "ColumnDisplayButtonTemplate")
  header:SetHeight(HEADER_HEIGHT)
  header:SetNormalFontObject("GameFontNormal")
  header.arrow = header:CreateTexture(nil, "OVERLAY")
  header.arrow:SetTexture("Interface\\Buttons\\UI-SortArrow")
  header.arrow:SetSize(9, 8)
  header:SetScript("OnClick", function(self)
    if not shown then
      return
    end
    PlaySound(SOUNDKIT.IG_MAINMENU_OPTION_CHECKBOX_ON)
    local sort = RecommendationTable.nextSort(shown, activeSort(shown), self.column)
    db.recommendationSorts = db.recommendationSorts or {}
    db.recommendationSorts[shown.title] = RecommendationTable.savedSort(shown, sort)
    redraw()
  end)
  header:HookScript("OnEnter", function(self)
    local name = shown and shown.columns[self.column]
    if name then
      showTip(self, name, Tips.COLUMNS[name] or "", Tips.SORT)
    end
  end)
  header:HookScript("OnLeave", GameTooltip_Hide)
  headers[k] = header
  return header
end

-- The Item header also spans the icon, so headers line up with the cells below them. The
-- sorted column's header gets an arrow: down for largest (or Z) first, up for smallest.
local function drawHeaders(columns, layout, sort)
  local x = SCROLL_LEFT
  for k = 1, MAX_COLUMNS do
    local p = layout and layout[k]
    if p then
      local header = getHeader(k)
      local width = p.width + (k == 1 and (ICON_SIZE + ICON_GAP) or 0)
      header.column = p.column
      header:ClearAllPoints()
      header:SetPoint("TOPLEFT", frame.Inset, "TOPLEFT", x, -4)
      header:SetWidth(width)
      header:SetText(columns[p.column])
      if sort and sort.column == p.column then
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
    elseif headers[k] then
      headers[k]:Hide()
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
  local function add(texts, layout, font, item, justify, rowMarks, section)
    n = n + 1
    drawLine(n, texts, layout, font, item, justify, rowMarks, section)
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
        local layout = ColumnLayout.fit(section, contentWidth())
        local sort = activeSort(section)
        RecommendationTable.sort(section, sort)
        drawHeaders(section.columns, layout, sort)
        if section.empty then
          add({ section.empty }, nil, "GameFontDisable", nil, "CENTER")
        end
        for _, row in ipairs(section.rows) do
          if row.header then
            -- A Prediction's header (#207): one line, not an item to select, mark or search.
            add({ row.text }, nil, "GameFontNormal")
          else
            local font = row.bought and "GameFontDisable" or "GameFontHighlight"
            add(row.cells, layout, font, row, nil, row.markable and marks or nil, section)
          end
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
  selectedRow, selectedSection, selectedRowSection = nil, nil, nil
  for _, section in ipairs(view.sections or {}) do
    if not selectedRow then
      selectedRow = selectedId and RecommendationTable.find(section, selectedId)
      selectedSection = selectedRow and section.title
      selectedRowSection = selectedRow and section
    end
  end
  local row = shown and selectedId and RecommendationTable.find(shown, selectedId)
  drawChain(row and row.record.action == "Craft" and row.record or nil)
  drawPane()
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
-- A Data slot the Addon loaded by itself may hold newer Recommendations (ADR-0030).
Scanner.setOnDataLoad(queueRedraw)

local function selectTab(title)
  selected = title
  scroll:SetVerticalScroll(0)
  redraw()
end

-- From the frame's corner, not GetPoint: a resize before the first drag may leave it
-- anchored to the AH, and restorePosition anchors to UIParent.
local function savePosition()
  db.recommendationFrame = { point = "TOPLEFT", relativePoint = "BOTTOMLEFT", x = frame:GetLeft(), y = frame:GetTop() }
end

local function saveSize()
  db.recommendationFrameSize = { width = frame:GetWidth(), height = frame:GetHeight() }
end

-- The widest the frame gets: the Craft Chain panel docked on its left still fits on screen,
-- unless the screen is too narrow for even MIN_WIDTH beside it.
local function maxWidth()
  return math.max(MIN_WIDTH, UIParent:GetWidth() - PANEL_WIDTH - 2)
end

-- The saved size, kept inside the bounds and the screen, or WIDTH x HEIGHT.
local function restoreSize()
  local saved = db.recommendationFrameSize or { width = WIDTH, height = HEIGHT }
  local width = math.max(MIN_WIDTH, math.min(saved.width, maxWidth()))
  local height = math.max(MIN_HEIGHT, math.min(saved.height, UIParent:GetHeight()))
  frame:SetSize(width, height)
end

local function restorePosition()
  restoreSize()
  frame:ClearAllPoints()
  local saved = db.recommendationFrame
  if saved then
    frame:SetPoint(saved.point, UIParent, saved.relativePoint, saved.x, saved.y)
  elseif AuctionHouseFrame and AuctionHouseFrame:IsShown() then
    -- Next to the AH until first dragged; dragging re-anchors to UIParent before saving.
    -- Narrowed to the room right of it, or below it when that's too narrow (#164).
    local room = UIParent:GetRight() - AuctionHouseFrame:GetRight() - AH_GAP
    local place = Placement.firstOpen(room, frame:GetWidth(), MIN_WIDTH)
    frame:SetWidth(place.width)
    if place.side == "right" then
      frame:SetPoint("TOPLEFT", AuctionHouseFrame, "TOPRIGHT", AH_GAP, 0)
    else
      frame:SetPoint("TOPLEFT", AuctionHouseFrame, "BOTTOMLEFT", 0, -AH_GAP)
    end
  else
    frame:SetPoint("CENTER")
  end
end

-- Tabs along the top, right of the portrait, one per section, in the order
-- RecommendationTable.build gives them, each with its row count. A click is remembered, so
-- /aq recs reopens that tab.
local TAB_TITLES = {
  "Holdings", "Shopping List", "Flips to Craft", "Flips to Disenchant", "Predictions", "Buy Under",
}

-- Retail's top tab, if this client has it (checked by name, since CreateFrame with a missing
-- template doesn't fail cleanly); the bottom tab otherwise, which then hangs upside down.
local function tabTemplate()
  local top = "PanelTopTabButtonTemplate"
  if C_XMLUtil and C_XMLUtil.GetTemplateInfo and C_XMLUtil.GetTemplateInfo(top) then
    return top
  end
  return "PanelTabButtonTemplate"
end

local function createTabs()
  local template = tabTemplate()
  for i, title in ipairs(TAB_TITLES) do
    local tab = CreateFrame("Button", "AzerothQuantRecommendationFrameTab" .. i, frame, template)
    tab:SetID(i)
    tab:SetText(title)
    if i == 1 then
      tab:SetPoint("TOPLEFT", frame, "TOPLEFT", 66, TABS_TOP)
    else
      tab:SetPoint("TOPLEFT", tabs[i - 1], "TOPRIGHT", 3, 0)
    end
    tab:SetScript("OnClick", function()
      PlaySound(SOUNDKIT.IG_CHARACTER_INFO_TAB)
      db.recommendationTab = title
      selectTab(title)
    end)
    tab:HookScript("OnEnter", function(self)
      showTip(self, title, Tips.TABS[title])
    end)
    tab:HookScript("OnLeave", GameTooltip_Hide)
    tabs[i] = tab
  end
  frame.Tabs = tabs
  PanelTemplates_SetNumTabs(frame, #tabs)
end

-- Reloading flushes SavedVariables (new Scans reach the Brain) and rereads
-- Recommendations.lua. Not mid-Scan, which would lose it. The Brain imports what the
-- reload saved and writes a new Recommendations.lua a minute or so later; when the
-- startup copy missed it, Scanner.lua tries the Brain's Data slots by itself and the
-- table redraws when one catches up (ADR-0030). The banner's button does Scan or Reload
-- by step; /aq reload does the last.
local function reload()
  if Scanner.busy() then
    Chat.say(Tips.STEPS.busy)
    return
  end
  ReloadUI()
end

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
    showTip(self, setting.label, setting.tip)
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

local function createBudgetBox(anchor)
  frame.budget = createSettingBox(anchor, {
    label = "Budget (g)",
    width = 60,
    tip = Tips.BUDGET,
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
    tip = Tips.DAYS_TO_SELL,
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

-- What the banner's button does, by NextStep.of's action (its tooltip is in Tips.STEPS).
local STEP_CLICKS = {
  scan = function()
    Scanner.requestScan()
  end,
  reload = function()
    reload()
  end,
}
local GOLD, ORANGE = { 1, 0.82, 0 }, { 1, 0.6, 0.23 }
local CHECK = "|TInterface\\RaidFrame\\ReadyCheck-Ready:0|t "

-- The loop as NextStep.of takes it, from what Scanner and the Brain's file say.
local function loopState()
  local unsaved, unimported, behind = Scanner.waiting()
  local now = GetServerTime()
  return {
    scanning = Scanner.busy(),
    ahOpen = Scanner.ahOpen(),
    unsaved = unsaved,
    unimported = unimported,
    behind = behind,
    catchingUp = Nudge.catchingUp(AzerothQuantRecommendations, now),
    brainRan = AzerothQuantRecommendations ~= nil and AzerothQuantRecommendations.brain ~= nil,
    trying = Scanner.trying(),
    reloadReady = Scanner.reloadReady(),
    lastScanAt = db.lastScanAt,
  }, now
end

-- The banner under the tabs (#161). It follows the loop every frame while the frame is
-- shown: a Scan starts and ends on its own clock, the cooldown counts down, and the Data
-- slots are tried on theirs. Up to date, it shrinks to one line and the rows move up.
local function createBanner()
  local banner = CreateFrame("Frame", nil, frame)
  banner:SetPoint("TOPLEFT", frame, "TOPLEFT", 8, BANNER_TOP)
  banner:SetPoint("RIGHT", frame, "RIGHT", -10, 0)
  banner:SetHeight(BANNER_HEIGHT)
  banner.background = banner:CreateTexture(nil, "BACKGROUND")
  banner.background:SetAllPoints()
  banner.background:SetColorTexture(1, 1, 1, 1)

  banner.button = CreateFrame("Button", nil, banner, "UIPanelButtonTemplate")
  banner.button:SetSize(100, 24)
  banner.button:SetPoint("RIGHT", -8, 0)
  banner.button:SetScript("OnClick", function(self)
    local click = STEP_CLICKS[self.action]
    if click then
      click()
    end
  end)
  -- Disabled buttons get no OnEnter unless told to, and the tooltip must say why it's off.
  banner.button:SetMotionScriptsWhileDisabled(true)
  banner.button:SetScript("OnEnter", function(self)
    showTip(self, nil, Tips.STEPS[self.action] or "")
  end)
  banner.button:SetScript("OnLeave", GameTooltip_Hide)
  -- Pulses when the step is one to take now: a Scan can run, a Scan is saved, or the
  -- Brain should be done (#71).
  banner.pulse = Scanner.addPulse(banner.button)

  banner.title = banner:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  banner.title:SetPoint("TOPLEFT", 10, -5)
  banner.title:SetPoint("RIGHT", banner.button, "LEFT", -10, 0)
  banner.title:SetJustifyH("LEFT")
  banner.line = banner:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  banner.line:SetJustifyH("LEFT")
  banner.line:SetWordWrap(false)

  -- Up to date: no title, button or tint, and the line takes the width.
  local function setQuiet(quiet)
    banner.quiet = quiet
    banner:SetHeight(quiet and QUIET_HEIGHT or BANNER_HEIGHT)
    banner.title:SetShown(not quiet)
    banner.line:ClearAllPoints()
    if quiet then
      banner.background:SetColorTexture(0, 0, 0, 0)
      banner.button:Hide()
      banner.line:SetPoint("LEFT", 10, 0)
      banner.line:SetPoint("RIGHT", -10, 0)
    else
      banner.line:SetPoint("BOTTOMLEFT", 10, 6)
      banner.line:SetPoint("RIGHT", banner.button, "LEFT", -10, 0)
    end
  end
  setQuiet(false)

  banner:SetScript("OnUpdate", function(self)
    local step = NextStep.of(loopState())
    local quiet = step.quiet == true
    if quiet ~= self.quiet then
      setQuiet(quiet)
    end
    if step.quiet then
      if self.line:GetText() ~= CHECK .. step.line then
        self.line:SetText(CHECK .. step.line)
      end
      Scanner.setPulsing(self.pulse, false)
      return
    end
    local color = step.warn and ORANGE or GOLD
    self.background:SetColorTexture(color[1], color[2], color[3], 0.12)
    self.title:SetTextColor(color[1], color[2], color[3])
    if self.title:GetText() ~= step.title then
      self.title:SetText(step.title)
    end
    if self.line:GetText() ~= step.line then
      self.line:SetText(step.line)
    end
    if step.button then
      self.button.action = step.action
      if self.button:GetText() ~= step.button then
        self.button:SetText(step.button)
      end
      self.button:SetEnabled(step.enabled)
      self.button:Show()
    else
      self.button:Hide()
    end
    Scanner.setPulsing(self.pulse, step.button ~= nil and step.pulse)
  end)
  frame.banner = banner
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
-- { id, key, itemKey, results, lowest }: the selected row's last search, for Post's undercut
-- line or Search's live line. itemKey is set only by Search (#39); results are nil until
-- they land.
local search
-- Every AH search and the owned-auctions query, one at a time as the throttle allows
-- (#177). A request is { key, match, itemID, queryKey, itemKey } or OWNED_QUERY.
local queue = SearchQueue.new()
local OWNED_QUERY = { key = "owned", match = "owned", owned = true }
-- The Cancel undercut button (#177, ADR-0044). owned is the Character's active Listings
-- (nil until the AH lists them), checks each searched key's results, fresh the keys searched
-- since the last cancel (nil before one), cancelling the target a cancel waits on and
-- cancelError the error the AH showed since that cancel.
local cancelButton, cancelState
local owned, checks, fresh, cancelling, cancelError

-- Forgets the Cancel undercut checks (each AH visit starts afresh).
local function resetCancel()
  owned, checks, fresh, cancelling, cancelError = nil, {}, nil, nil, nil
end
resetCancel()

-- A key's search results landed: Cancel undercut's check of it, fresh since any cancel.
local function recordCheck(key, results)
  checks[key] = results
  if fresh then
    fresh[key] = true
  end
end
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

-- A search key as a string, so the queue can tell two searches of it apart from others.
local function keyString(queryKey)
  return table.concat({
    queryKey.itemID,
    queryKey.itemLevel or 0,
    queryKey.itemSuffix or 0,
    queryKey.battlePetSpeciesID or 0,
  }, ":")
end

-- Sends the queue's next request if the throttle takes it. A request whose results never
-- landed is given up on: a check counts as no other Listing (even one searched before a
-- cancel), so it can't cause a cancel, and the owned list is asked for again.
local function pumpSearches()
  if not ahOpen then
    return
  end
  local request, lost = SearchQueue.next(queue, C_AuctionHouse.IsThrottledMessageSystemReady(), GetTime())
  if lost and lost.owned then
    SearchQueue.push(queue, OWNED_QUERY)
    request = request or SearchQueue.next(queue, C_AuctionHouse.IsThrottledMessageSystemReady(), GetTime())
  elseif lost then
    Chat.debug("No search results for " .. lost.key .. "; taken as no other Listing.")
    recordCheck(lost.key, {})
    refreshCancel()
  end
  if not request then
    return
  end
  if request.owned then
    C_AuctionHouse.QueryOwnedAuctions({})
  else
    C_AuctionHouse.SendSearchQuery(request.queryKey, {}, false)
  end
  -- Wakes the queue when results never land (it's otherwise woken by events).
  C_Timer.After(SearchQueue.STALE, pumpSearches)
end

-- Queues a search of queryKey. itemKey, given by Search, keeps only that Item Key's
-- Listings of gear (searchResults). urgent puts it ahead of the Cancel undercut checks.
local function queueSearch(itemID, queryKey, itemKey, urgent)
  local key = keyString(queryKey) .. (itemKey and ("|" .. itemKey) or "")
  SearchQueue.push(queue, { key = key, match = itemID, itemID = itemID, queryKey = queryKey, itemKey = itemKey }, urgent)
  pumpSearches()
  return key
end

-- One search for the selected row, ahead of the checks: the player is waiting on it.
local function sendSearch(row, itemID, queryKey, itemKey)
  search = { id = row.id, itemKey = itemKey }
  search.key = queueSearch(itemID, queryKey, itemKey, true)
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

-- A search request's results as PostButton.lowestOther and SearchButton.liveLine take them.
-- commodity says which results landed (the event that fired).
local function searchResults(request, commodity)
  local results = {}
  if commodity then
    for i = 1, C_AuctionHouse.GetNumCommoditySearchResults(request.itemID) do
      local r = C_AuctionHouse.GetCommoditySearchResultInfo(request.itemID, i)
      if r then
        results[#results + 1] = { unitPrice = r.unitPrice, quantity = r.quantity, ownUnits = r.numOwnerItems }
      end
    end
  else
    for i = 1, C_AuctionHouse.GetNumItemSearchResults(request.queryKey) do
      local r = C_AuctionHouse.GetItemSearchResultInfo(request.queryKey, i)
      -- A bid-only Listing has no buyout to undercut or buy at.
      local wanted = r and (not request.itemKey or (r.itemLink and TooltipLines.itemKey(r.itemLink) == request.itemKey))
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
  -- A new import (a reload, or a Data slot loaded) starts the counts over.
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

-- The Character's active Listings from the AH's owned list, as CancelButton takes them.
-- buyoutAmount is taken as the unit price: gear Listings are one unit each, and the AH's
-- own owned list shows a commodity's unit price (unchecked in game: see #177's check).
local function readOwned()
  local listings = {}
  for i = 1, C_AuctionHouse.GetNumOwnedAuctions() do
    local a = C_AuctionHouse.GetOwnedAuctionInfo(i)
    -- status 0 is active (#81 probe); a sold one waits in the mail.
    if a and a.status == 0 and a.buyoutAmount and a.itemKey then
      local name = a.itemLink and a.itemLink:match("%[(.-)%]") or ("item " .. a.itemKey.itemID)
      listings[#listings + 1] = {
        auctionID = a.auctionID,
        key = keyString(a.itemKey),
        itemKey = a.itemKey,
        name = name,
        unitPrice = a.buyoutAmount,
        quantity = a.quantity,
      }
      Chat.debug("Own Listing " .. a.auctionID .. ": " .. name .. " x" .. a.quantity .. ", buyoutAmount " .. a.buyoutAmount)
    end
  end
  return listings
end

-- Queues a check of every owned Item Key not searched yet.
local function queueChecks()
  for _, listing in ipairs(owned or {}) do
    if not checks[listing.key] then
      queueSearch(listing.itemKey.itemID, listing.itemKey)
    end
  end
end

function refreshCancel()
  if not cancelButton then
    return
  end
  cancelButton:SetShown(ahOpen)
  -- Post or Search sits above Cancel undercut while it shows.
  pane.actions:ClearAllPoints()
  local bottom = ahOpen and 32 or 4
  pane.actions:SetPoint("BOTTOMLEFT", 10, bottom)
  pane.actions:SetPoint("BOTTOMRIGHT", -10, bottom)
  if not ahOpen then
    cancelState = nil
    return
  end
  cancelState = CancelButton.state(owned, checks, { pending = cancelling ~= nil, fresh = fresh })
  cancelButton:SetText(cancelState.label)
  cancelButton:SetWidth(math.max(90, cancelButton:GetTextWidth() + 30))
  cancelButton:SetEnabled(cancelState.enabled)
  -- After a cancel, the next target's Item Key is searched again before the next click.
  if cancelState.recheck then
    for _, listing in ipairs(owned) do
      if listing.key == cancelState.recheck then
        queueSearch(listing.itemKey.itemID, listing.itemKey)
        break
      end
    end
  end
  if GameTooltip:IsOwned(cancelButton) then
    cancelButton:GetScript("OnEnter")(cancelButton)
  end
end

-- Cancels the next Undercut Listing, only when clicked (ADR-0044): one call per click, on
-- the target CancelButton named, with no row selected.
local function onCancelClick(self)
  local call = cancelState and cancelState.call
  if not call then
    return
  end
  C_AuctionHouse.CancelAuction(call.auctionID)
  cancelling = cancelState.target
  refreshCancel()
end

local function createCancelButton()
  cancelButton = CreateFrame("Button", nil, pane, "UIPanelButtonTemplate")
  cancelButton:SetSize(90, 22)
  cancelButton:SetPoint("BOTTOMLEFT", 10, 4)
  cancelButton:SetScript("OnClick", onCancelClick)
  cancelButton:SetMotionScriptsWhileDisabled(true)
  cancelButton:SetScript("OnEnter", function(self)
    showTip(self, nil, cancelState and (cancelState.tip or cancelState.reason) or Tips.CANCEL)
  end)
  cancelButton:SetScript("OnLeave", GameTooltip_Hide)
  cancelButton:Hide()
end

-- Post and Search share one slot at the top of the pane's actions, with a line under it.
local function createPaneButton()
  local button = CreateFrame("Button", nil, pane.actions, "UIPanelButtonTemplate")
  button:SetSize(90, 22)
  button:SetPoint("TOPLEFT")
  return button
end

local function paneButtonLine(button, font)
  local line = button:CreateFontString(nil, "OVERLAY", font)
  line:SetPoint("TOPLEFT", button, "BOTTOMLEFT", 0, -4)
  line:SetPoint("RIGHT", pane.actions, "RIGHT")
  line:SetJustifyH("LEFT")
  line:SetMaxLines(2)
  return line
end

local function createPostButton()
  postButton = createPaneButton()
  postButton:SetScript("OnClick", onPostClick)
  postButton:SetMotionScriptsWhileDisabled(true)
  postButton:SetScript("OnEnter", function(self)
    local failed = postError and selectedRow and postError.id == selectedRow.id and postError.text
    showTip(self, nil, failed or (postState and postState.reason) or Tips.POST)
  end)
  postButton:SetScript("OnLeave", GameTooltip_Hide)
  postButton.undercut = paneButtonLine(postButton, "GameFontNormalSmall")
  postButton.undercut:SetTextColor(1, 0.5, 0.25)
  postButton:Hide()

  -- Search takes the same slot on a buy-side row (#39).
  searchButton = createPaneButton()
  searchButton:SetText("Search")
  searchButton:SetScript("OnClick", onSearchClick)
  searchButton:SetMotionScriptsWhileDisabled(true)
  searchButton:SetScript("OnEnter", function(self)
    showTip(self, nil, searchState and searchState.reason or Tips.SEARCH)
  end)
  searchButton:SetScript("OnLeave", GameTooltip_Hide)
  searchButton.live = paneButtonLine(searchButton, "GameFontHighlightSmall")
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
  -- Resizable from the corner grip (#136); the columns refit as it goes.
  frame:SetResizable(true)
  if frame.SetResizeBounds then
    frame:SetResizeBounds(MIN_WIDTH, MIN_HEIGHT, maxWidth(), UIParent:GetHeight())
  else
    frame:SetMinResize(MIN_WIDTH, MIN_HEIGHT)
  end
  frame:SetScript("OnSizeChanged", function()
    if not content then
      return
    end
    content:SetWidth(contentWidth())
    queueRedraw()
  end)
  local grip = CreateFrame("Button", nil, frame)
  grip:SetSize(14, 14)
  grip:SetPoint("BOTTOMRIGHT", -1, 1) -- on the border, clear of the scroll bar
  grip:SetFrameLevel(frame:GetFrameLevel() + 10)
  grip:SetNormalTexture("Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Up")
  grip:SetHighlightTexture("Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Highlight")
  grip:SetPushedTexture("Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Down")
  grip:SetScript("OnMouseDown", function()
    frame:StartSizing("BOTTOMRIGHT")
  end)
  grip:SetScript("OnMouseUp", function()
    frame:StopMovingOrSizing()
    saveSize()
    savePosition()
  end)
  grip:SetScript("OnEnter", function(self)
    showTip(self, nil, Tips.RESIZE)
  end)
  grip:SetScript("OnLeave", GameTooltip_Hide)
  frame:Hide()
  tinsert(UISpecialFrames, "AzerothQuantRecommendationFrame") -- Escape closes it
  frame:SetPortraitToAsset(PORTRAIT)

  createBanner()

  -- The setting boxes ride under the banner, right of the header lines, so they move with it.
  local settingsAnchor = CreateFrame("Frame", nil, frame)
  settingsAnchor:SetSize(1, 20)
  settingsAnchor:SetPoint("TOPRIGHT", frame.banner, "BOTTOMRIGHT", 0, -6)
  createBudgetBox(settingsAnchor)
  createDaysToSellBox()

  -- No button bar: the inset runs to the bottom edge. Its top follows the banner.
  frame.Inset:ClearAllPoints()
  frame.Inset:SetPoint("TOPLEFT", frame.banner, "BOTTOMLEFT", -4, -HEADER_ROW)
  frame.Inset:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -6, 6)

  -- The two header lines, under the banner.
  frame.header1 = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  frame.header1:SetPoint("TOPLEFT", frame.banner, "BOTTOMLEFT", 4, -6)
  frame.header2 = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  frame.header2:SetPoint("TOPLEFT", frame.header1, "BOTTOMLEFT", 0, -4)

  scroll = CreateFrame("ScrollFrame", nil, frame.Inset, "UIPanelScrollFrameTemplate")
  scroll:SetPoint("TOPLEFT", frame.Inset, "TOPLEFT", SCROLL_LEFT, -4 - HEADER_HEIGHT - 2)
  scroll:SetPoint("BOTTOMRIGHT", frame.Inset, "BOTTOMRIGHT", -(SCROLLBAR_WIDTH + PANE_GAP + PANE_WIDTH), 6)
  content = CreateFrame("Frame", nil, scroll)
  content:SetSize(contentWidth(), 1)
  scroll:SetScrollChild(content)

  createTabs()
  createPane()
  createPostButton()
  createCancelButton()

  -- After the boxes exist (the frame:Hide() above would otherwise fire it first).
  -- A box left focused while hidden would swallow the next Enter meant for chat.
  frame:SetScript("OnHide", function()
    hovered = nil
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
-- The search queue waits for the AH to take another search (#39, #177).
events:RegisterEvent("AUCTION_HOUSE_THROTTLED_SYSTEM_READY")
-- Cancel undercut: the owned list, and a cancel confirmed (#177).
events:RegisterEvent("OWNED_AUCTIONS_UPDATED")
events:RegisterEvent("AUCTION_CANCELED")
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
    -- Cancel undercut checks the Character's own Listings afresh at each visit.
    resetCancel()
    SearchQueue.clear(queue)
    SearchQueue.push(queue, OWNED_QUERY)
    pumpSearches()
    refreshCancel()
  elseif event == "AUCTION_HOUSE_CLOSED" then
    -- Close what the AH opened; leave it if the player opened it with /aq recs.
    if openedByAuctionHouse and frame then
      frame:Hide()
    end
    openedByAuctionHouse = false
    ahOpen, pending, lastPost, postError, search = false, false, nil, nil, nil
    resetCancel()
    SearchQueue.clear(queue)
    refreshPost()
    refreshCancel()
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
  elseif (event == "UI_ERROR_MESSAGE" or event == "AUCTION_CANCELED") and cancelling then
    -- The error may not be the cancel's: the owned list read next tells whether the
    -- Listing is still up (CancelButton.outcome).
    if event == "UI_ERROR_MESSAGE" then
      cancelError = tostring(arg2)
    end
    SearchQueue.push(queue, OWNED_QUERY)
    pumpSearches()
  elseif event == "COMMODITY_SEARCH_RESULTS_UPDATED" or event == "ITEM_SEARCH_RESULTS_UPDATED" then
    -- arg1 is the itemID (commodity) or the item key searched. Another item's results
    -- (Blizzard's own searches) aren't ours.
    local itemID = type(arg1) == "table" and arg1.itemID or arg1
    local request = SearchQueue.landed(queue, itemID)
    if request then
      local results = searchResults(request, event == "COMMODITY_SEARCH_RESULTS_UPDATED")
      -- Any search of a key serves Cancel undercut's check of it too.
      recordCheck(request.key, results)
      if search and search.key == request.key then
        search.results, search.lowest = results, PostButton.lowestOther(results)
      end
      refreshPost()
      refreshCancel()
      pumpSearches()
    end
  elseif event == "OWNED_AUCTIONS_UPDATED" and ahOpen then
    SearchQueue.landed(queue, "owned")
    owned = readOwned()
    if cancelling then
      local outcome = CancelButton.outcome(owned, cancelling, cancelError)
      if outcome == "cancelled" then
        Chat.say("Cancelled " .. CancelButton.describe(cancelling) .. ".")
        cancelling, cancelError, fresh = nil, nil, {}
      elseif outcome == "failed" then
        Chat.say("The cancel failed: " .. cancelError)
        cancelling, cancelError = nil, nil
      end
    end
    queueChecks()
    refreshCancel()
    pumpSearches()
  elseif event == "AUCTION_HOUSE_THROTTLED_SYSTEM_READY" then
    pumpSearches()
    refreshPost()
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
  elseif msg:match("^%s*ping%s*$") then
    Nudge.togglePing(AzerothQuantDB, Chat.say)
  else
    Chat.say("Usage: /aq recs (toggle the Recommendation Table), /aq reload,"
      .. " /aq ping (toggle the ping when you can Scan again), /aq debug (toggle chat lines you don't need to act on)")
  end
end
