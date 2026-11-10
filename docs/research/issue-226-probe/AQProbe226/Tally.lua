-- Counts the probe's dropped-row records (#226). Plain Lua, so it runs under busted.
local _, ns = ...
ns = ns or {}

local Tally = {}

local function bump(counts, key)
  counts[key] = (counts[key] or 0) + 1
end

-- "infoKnown,notAllInfo" and the like: what the client knew of the row at the main read.
local function groupOf(r)
  return (r.infoKnown and "infoKnown" or "infoMissing") .. "," .. (r.hasAllInfo and "hasAllInfo" or "notAllInfo")
end

-- records: one per dropped row, { itemID, infoKnown, hasAllInfo, firstRead }, where
-- firstRead is the first re-read that brought the link back, or nil if none did.
-- Returns { rows, items, itemsNever, firstRead = {when = rows}, groups = {group = {rows, firstRead}} }.
function Tally.count(records)
  local t = { rows = #records, items = 0, itemsNever = 0, firstRead = {}, groups = {} }
  local seen, seenNever = {}, {}
  for _, r in ipairs(records) do
    local when = r.firstRead or "never"
    bump(t.firstRead, when)
    local g = groupOf(r)
    t.groups[g] = t.groups[g] or { rows = 0, firstRead = {} }
    t.groups[g].rows = t.groups[g].rows + 1
    bump(t.groups[g].firstRead, when)
    if not seen[r.itemID] then
      seen[r.itemID] = true
      t.items = t.items + 1
    end
    if when == "never" and not seenNever[r.itemID] then
      seenNever[r.itemID] = true
      t.itemsNever = t.itemsNever + 1
    end
  end
  return t
end

ns.Tally = Tally
return Tally
