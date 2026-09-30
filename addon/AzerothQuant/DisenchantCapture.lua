-- Captures Disenchant Results (#76): what each Disenchant the player casts yields, and
-- which item it was. The glue (Character.lua) feeds it the Disenchant cast's events and
-- the bags read at each; the item Disenchanted is the one that left the bags between the
-- cast starting and its loot.
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for
-- the namespace fallback.
local _, ns = ...
ns = ns or {}

local Scan = ns.Scan or require("Scan")

local DisenchantCapture = {}
DisenchantCapture.__index = DisenchantCapture

-- How long after its loot a Result waits for its item to leave the bags. Any longer and
-- an item the player sells or mails could be taken for it.
local WAIT_SECONDS = 5

local function itemID(link)
  return link and tonumber(link:match("|Hitem:(%d+)"))
end

-- Units held by itemID, and the Disenchant Item Info of each (nil if it can't be one).
local function held(bags)
  local counts, infos = {}, {}
  for _, s in ipairs(bags) do
    local id = s.info and itemID(s.info.hyperlink)
    if id then
      counts[id] = (counts[id] or 0) + (s.info.stackCount or 1)
      infos[id] = infos[id] or (s.itemInfo and Scan.disenchantInfo(s.itemInfo))
    end
  end
  return { counts = counts, infos = infos }
end

-- The Disenchantable itemIDs held fewer of now than before.
local function gone(before, now)
  local ids = {}
  for id, count in pairs(before.counts) do
    if before.infos[id] and (now.counts[id] or 0) < count then
      ids[#ids + 1] = id
    end
  end
  return ids
end

local function mats(loot)
  local qty = {}
  for _, l in ipairs(loot) do
    local id = itemID(l.link)
    if id then
      qty[id] = (qty[id] or 0) + l.quantity
    end
  end
  return qty
end

function DisenchantCapture.new()
  return setmetatable({ results = {} }, DisenchantCapture)
end

-- The Result for a Disenchant's mats. With one item gone it names that item; with several
-- alike ones (same quality, item level and class) only their group; otherwise just the mats.
local function result(p, ids)
  local r = { mats = p.mats, at = p.at }
  local info = p.before.infos[ids[1]]
  if #ids == 1 then
    r.itemID = ids[1]
  end
  for _, id in ipairs(ids) do
    local other = p.before.infos[id]
    if other.quality ~= info.quality or other.itemLevel ~= info.itemLevel or other.classID ~= info.classID then
      return r
    end
  end
  if info then
    r.itemLevel, r.quality, r.classID = info.itemLevel, info.quality, info.classID
  end
  return r
end

-- bags: every bag slot, as Character.lua reads them ({ info, itemInfo } each).
function DisenchantCapture:castStarted(bags)
  self:flush()
  self.before = held(bags)
  self.succeeded = false
end

function DisenchantCapture:castSucceeded()
  self.succeeded = true
end

-- loot: the loot window's slots, { link, quantity } each. The Result waits for a later
-- bagsRead if the item is still in the bags.
function DisenchantCapture:lootReady(loot, bags, at)
  -- Only a Disenchant's own loot; LOOT_READY also fires for mobs, chests and fishing.
  if not self.succeeded then
    -- A new window once the Disenchant's has closed; LOOT_READY can fire twice for one.
    if self.window and self.window.closedAt then
      self.window = nil
    end
    return
  end
  self.succeeded = false
  self.window = {} -- the Disenchant's loot window, open until lootClosed
  self.pending = { before = self.before, mats = mats(loot), at = at }
  self:bagsRead(bags, at)
end

-- LOOT_CLOSED, at the time it closed.
function DisenchantCapture:lootClosed(at)
  if self.window and not self.window.closedAt then
    self.window.closedAt = at
  end
end

-- Whether loot the player receives at `at` is a Disenchant's mats: its loot window is
-- open (without autoloot, the player takes them when they like), or closed within the
-- wait, since a loot line can come after the window closes. A Loot Alert (#54) skips
-- those, since they were chosen, not dropped.
function DisenchantCapture:isDisenchantLoot(at)
  local w = self.window
  return w ~= nil and (w.closedAt == nil or at - w.closedAt <= WAIT_SECONDS)
end

-- Every bag read while a Result waits for its item, at the time it was read.
function DisenchantCapture:bagsRead(bags, at)
  local p = self.pending
  if not p then
    return
  end
  if at - p.at > WAIT_SECONDS then
    self:flush()
    return
  end
  local ids = gone(p.before, held(bags))
  if #ids > 0 then
    self.results[#self.results + 1] = result(p, ids)
    self.pending = nil
  end
end

-- Records a Result still waiting for its item with the mats alone: at the next cast, at
-- logout, and once it has waited too long.
function DisenchantCapture:flush()
  if self.pending then
    self.results[#self.results + 1] = result(self.pending, {})
    self.pending = nil
  end
end

ns.DisenchantCapture = DisenchantCapture
return DisenchantCapture
