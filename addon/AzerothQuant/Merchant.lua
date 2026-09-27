-- WoW glue for Merchant Costs: while a merchant window is open, reads what it sells and
-- keeps the session's Merchant Costs in memory for Character.lua to record at
-- PLAYER_LOGOUT, like the bank and Known Recipes. All shaping happens in MerchantCosts.lua.
--
-- Which merchant API Forever has is a needs-pc check on #29, so this reads
-- C_MerchantFrame.GetItemInfo where the client has it and GetMerchantItemInfo otherwise.
--
-- Read-only (ADR-0003): only calls that read the merchant window. Nothing that buys,
-- sells or repairs.
local _, ns = ...
local MerchantCosts = ns.MerchantCosts

-- Merchant updates can come in bursts, so read once they have been quiet this long.
local QUIET_SECONDS = 0.5

local isOpen = false
local timer
local costs = {} -- itemID -> copper per unit, every merchant visited this session

-- { price, stackCount, numAvailable, hasExtendedCost } for one merchant slot, or nil.
local function slotInfo(index)
  if C_MerchantFrame and C_MerchantFrame.GetItemInfo then
    return C_MerchantFrame.GetItemInfo(index)
  end
  local _, _, price, stackCount, numAvailable, _, _, extendedCost = GetMerchantItemInfo(index)
  if price == nil then
    return nil
  end
  return { price = price, stackCount = stackCount, numAvailable = numAvailable, hasExtendedCost = extendedCost }
end

-- The itemID doesn't need the item cached; the link does, so it's only the fallback.
local function slotItemID(index)
  if GetMerchantItemID then
    return GetMerchantItemID(index)
  end
  local link = GetMerchantItemLink(index)
  return link and tonumber(link:match("|Hitem:(%d+)"))
end

local function readWindow()
  timer = nil
  local items = {}
  for index = 1, GetMerchantNumItems() or 0 do
    local info = slotInfo(index)
    local itemID = slotItemID(index)
    -- Anything the client can't fully say is skipped rather than guessed at.
    if info and itemID and info.price and info.stackCount and info.stackCount > 0 then
      items[#items + 1] = {
        itemID = itemID,
        price = info.price,
        stackCount = info.stackCount,
        numAvailable = info.numAvailable,
        hasExtendedCost = info.hasExtendedCost and true or false,
      }
    end
  end
  MerchantCosts.read(items, costs)
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("MERCHANT_SHOW")
frame:RegisterEvent("MERCHANT_UPDATE")
frame:RegisterEvent("MERCHANT_CLOSED")
frame:SetScript("OnEvent", function(_, event)
  if event == "MERCHANT_SHOW" then
    isOpen = true
    readWindow()
  elseif event == "MERCHANT_UPDATE" then
    if isOpen then
      if timer then
        timer:Cancel()
      end
      timer = C_Timer.NewTimer(QUIET_SECONDS, readWindow)
    end
  elseif event == "MERCHANT_CLOSED" then
    -- Catch a change still waiting out the quiet time before the window closes for good.
    if timer then
      timer:Cancel()
      readWindow()
    end
    isOpen = false
  end
end)

ns.Merchant = {
  -- Merchant Costs of every merchant visited this session.
  costs = function()
    return costs
  end,
}
