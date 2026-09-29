-- Disenchant source groups as the Brain writes them on a Buy Under (#88): { quality,
-- class = "armor"|"weapon", minLevel, maxLevel }. Which items are in one, and what to call it.
--
-- Plain Lua with no WoW API calls, so it runs under busted.
local _, ns = ...
ns = ns or {}

local DisenchantGroup = {}

-- GetItemInfo's classID for each class the Brain names.
local CLASS_IDS = { armor = 4, weapon = 2 }
local QUALITY_NAMES = { [2] = "Green", [3] = "Blue", [4] = "Purple" }
local CLASS_NAMES = { armor = "armor", weapon = "weapons" }

-- e.g. "Green weapons ilvl 16-20".
function DisenchantGroup.name(group)
  return (QUALITY_NAMES[group.quality] or ("Quality " .. group.quality)) .. " "
    .. (CLASS_NAMES[group.class] or group.class) .. " ilvl " .. group.minLevel .. "-" .. group.maxLevel
end

-- Whether an item is in the group. info is what the client says about it ({ quality,
-- itemLevel, classID, equipLoc }, nil until it's loaded), and excluded the Brain's
-- disenchantExcluded ({ itemIDs, equipLocs }): an item that can't be Disenchanted is in no
-- group, and so is one that can't be equipped.
function DisenchantGroup.contains(group, itemID, info, excluded)
  if not info or not info.equipLoc or info.equipLoc == "" then
    return false
  end
  excluded = excluded or {}
  if (excluded.itemIDs or {})[itemID] or (excluded.equipLocs or {})[info.equipLoc] then
    return false
  end
  return info.quality == group.quality
    and info.classID == CLASS_IDS[group.class]
    and info.itemLevel ~= nil
    and info.itemLevel >= group.minLevel
    and info.itemLevel <= group.maxLevel
end

ns.DisenchantGroup = DisenchantGroup
return DisenchantGroup
