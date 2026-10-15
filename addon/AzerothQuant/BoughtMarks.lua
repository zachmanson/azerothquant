-- The buy-side rows the player has marked Bought (#97), so they can't be bought twice
-- before the next Brain run. The Brain never reads the marks: it learns about buys from
-- Mailbox Reads and the next Scan.
--
-- A Market's marks map a row's id (RecommendationTable.find) to { cost, at }: the copper
-- the mark spends and when it was made. They're kept per Market in AzerothQuantDB.bought.
--
-- Plain Lua with no WoW API calls, so it runs under busted. The Addon never buys (ADR-0016).
local _, ns = ...
ns = ns or {}

local BoughtMarks = {}

-- The Market's marks in db (AzerothQuantDB), made if it has none. Marks made before the
-- imported Recommendations' Scan are dropped: that Scan no longer saw the bought Listings.
-- A Brain run on an older Scan still sees them, so its rows stay marked.
function BoughtMarks.forMarket(db, recommendations, realm, faction)
  -- Looked up here, not at load: RecommendationTable.lua loads after this file (it folds
  -- on goldLeft), so require, which WoW lacks, is only reached under busted.
  local RecommendationTable = ns.RecommendationTable or require("RecommendationTable")
  db.bought = db.bought or {}
  local key = RecommendationTable.marketKey(realm, faction)
  db.bought[key] = db.bought[key] or {}
  local marks = db.bought[key]
  local entry = recommendations and recommendations[realm] and recommendations[realm][faction]
  if entry then
    for id, mark in pairs(marks) do
      if entry.asOf > mark.at then
        marks[id] = nil
      end
    end
  end
  return marks
end

-- Marks the row Bought, or unmarks it if it already was. A manual mark spends the row's Cost.
function BoughtMarks.toggle(marks, rowId, cost, now)
  if marks[rowId] then
    marks[rowId] = nil
  else
    marks[rowId] = { cost = cost, at = now }
  end
end

-- The copper the marks spend, all made since the table's Scan once forMarket has them.
function BoughtMarks.spent(marks)
  local total = 0
  for _, mark in pairs(marks) do
    total = total + mark.cost
  end
  return total
end

-- What the Budget fold (#86) runs on once something is marked: what's left of the Budget
-- (nil for all the gold), or the gold on hand if that's less, or what's left of the risk
-- caps' room (#170; nil without them) if that's less. The gold on hand already dropped by
-- what was bought. With nothing marked it's the Budget, as the Brain sized to.
function BoughtMarks.goldLeft(budget, gold, spent, room)
  if spent == 0 then
    return budget
  end
  local left = budget and math.min(budget - spent, gold) or gold
  return room and math.min(left, room - spent) or left
end

ns.BoughtMarks = BoughtMarks
return BoughtMarks
