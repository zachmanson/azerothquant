-- The fixed hover texts on the Recommendation frame (tabs, columns, buttons, boxes) and the
-- AH's Scan button, in one place so the wording is easy to review (#163). Texts that say why
-- a button is off come with its state (PostButton.lua, SearchButton.lua). Plain words for
-- guildies: short, no jargon.
--
-- Plain Lua with no WoW API calls, so it runs under busted.
local _, ns = ...
ns = ns or {}

local Tips = {}

-- By tab title (a section's title in RecommendationTable.build).
Tips.TABS = {
  ["Holdings"] = "What you already own, and the best way to turn each into gold.",
  ["Shopping List"] = "Things to buy on the Auction House right now and sell again for a profit. Best at the top.",
  ["Flips to Craft"] = "Buy the materials, craft the item, and sell it for more than the materials cost.",
  ["Flips to Disenchant"] = "Buy gear, disenchant it, and sell the materials for more than the gear cost.",
  ["Prediction buys"] = "Items expected to go up in price soon. Riskier: these are guesses.",
  ["Buy Under"] = "Price limits: if you see one of these on the Auction House at or under this price, it's a good buy.",
}

-- By column name, on whichever tab it shows. The side pane names hidden columns the same way.
Tips.COLUMNS = {
  ["Item"] = "The item. Hover a row for the details on the right.",
  ["Action"] = "What to do with it: Buy it or Sell it on the Auction House, Vendor it (sell to a merchant), "
    .. "Craft something with it, Disenchant it, Hold it (keep it for later), or Wait (someone's selling "
    .. "it cheap: check again after the next Scan).",
  ["Qty"] = "How many to buy. On Holdings: how many to sell, vendor, craft or keep.",
  ["Price"] = "What one sells for, on the Auction House or to a merchant.",
  ["Max price"] = "The most to pay for one. Skip any listing above this.",
  ["Post at"] = "The price to list each one at when you sell it.",
  ["Profit"] = "Gold you should make in total, after the Auction House's cut.",
  ["Per click"] = "Profit for each listing you buy. Big numbers here mean less clicking.",
  ["Per day"] = "Profit per day, counting how long it takes to sell. \"now\" means a merchant buys it right away.",
  ["ROI"] = "Profit as a share of what you spend. 38% means 38g profit on every 100g spent.",
  ["Cost"] = "Gold you need to buy it all.",
  ["Way out"] = "How it turns into gold: sell it, vendor it, craft something with it, or disenchant it.",
  ["Listings"] = "How many listings to buy.",
  ["Prediction"] = "Why its price is expected to go up.",
  ["Max Loss"] = "The most you could lose if the guess is wrong.",
  ["Buy Under"] = "The most to pay for one. Anything at or under this is a good buy.",
  ["Units"] = "How many to buy at this price.",
  ["Seen"] = "How many recent Scans saw one at or under this price, and over how many days.",
  ["Beta"] = "What it went for on the Beta, just for reference. Never used to decide anything. "
    .. "A * means it was only listed there, never sold.",
}

-- The banner's button, by NextStep.of's action.
Tips.STEPS = {
  scan = "Scan reads every listing on the Auction House. You can Scan once every 15 minutes.",
  reload = "Reload hands any new Scan to the Brain app (WoW only saves on a reload or logout) "
    .. "and shows its newest recommendations.",
  busy = "Wait for the Scan to finish: reloading now would lose it.",
}

-- The setting boxes under the banner.
Tips.BUDGET = "The most gold to spend on any one buy. Leave it blank to use all your gold. "
  .. "Buys that cost more hide right away. Reload to fit the rest to it."
Tips.DAYS_TO_SELL = "The most days you'll wait for something you buy to sell. "
  .. "Leave it blank for the longest wait AzerothQuant allows. Reload to fit the buys to it."

-- The side pane's buttons, when nothing stops them (they say why when something does).
Tips.POST = "Post the selected row on the Auction House at its Post at price."
Tips.SEARCH = "Search the Auction House for the selected row's item."

-- The rest of the frame.
Tips.SORT = "Click to sort."
Tips.RESIZE = "Drag to resize."

ns.Tips = Tips
return Tips
