-- Shapes a read of a merchant window into Merchant Costs: copper per unit by itemID,
-- kept on the Character Read (merchantCosts). Recorded raw, as this Character was
-- charged, reputation discount included; the Brain takes the lowest across Characters.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for
-- the namespace fallback.
local _, ns = ...
ns = ns or {}

local MerchantCosts = {}

-- merchantItems: one per item the merchant sells, { itemID, price, stackCount,
-- numAvailable, extraCosts }, where price is the copper for one purchase, stackCount
-- the units it gives and extraCosts how many costs it has besides gold. Only items sold
-- for gold alone (extraCosts 0) in unlimited stock (numAvailable -1) count: limited
-- stock (mostly recipes) can't be relied on to be there.
-- into: the Merchant Costs read so far this session. Updated and returned. When two
-- merchants sell an item, the lower cost is kept: this Character can buy it at that.
function MerchantCosts.read(merchantItems, into)
  for _, item in ipairs(merchantItems) do
    if item.numAvailable == -1 and item.extraCosts == 0 then
      local cost = item.price / item.stackCount
      if into[item.itemID] == nil or cost < into[item.itemID] then
        into[item.itemID] = cost
      end
    end
  end
  return into
end

ns.MerchantCosts = MerchantCosts
return MerchantCosts
