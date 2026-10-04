-- Which containers Character.lua reads for the bags and for the bank (#133), from the
-- client's constants. Passed in as a table so this runs under busted.
--
-- Plain Lua with no WoW API calls. See Money.lua for the namespace fallback.
local _, ns = ...
ns = ns or {}

local ContainerIds = {}

-- The Reagent Bag's first and last container, or nil on a client without one.
local function reagentBags(constants)
  local first = constants.REAGENTBAG_CONTAINER
  if not first then
    return nil
  end
  return first, first + (constants.NUM_REAGENTBAG_SLOTS or 1) - 1
end

-- The backpack, the bag slots and the Reagent Bag. constants holds the client globals
-- of the same names; a missing one takes its old default.
function ContainerIds.bags(constants)
  local backpack = constants.BACKPACK_CONTAINER or 0
  local ids = {}
  for bag = backpack, backpack + (constants.NUM_BAG_SLOTS or 4) do
    ids[#ids + 1] = bag
  end
  -- Reagents go into the Reagent Bag by themselves, so it has to be read too.
  local first, last = reagentBags(constants)
  if first then
    for bag = first, last do
      ids[#ids + 1] = bag
    end
  end
  return ids
end

-- The main bank and the bank bags, from the same constants as bags.
function ContainerIds.bank(constants)
  local ids = { constants.BANK_CONTAINER or -1 }
  -- Bank bags are numbered after every equipped bag, the Reagent Bag included.
  local lastEquipped = constants.NUM_TOTAL_EQUIPPED_BAG_SLOTS or constants.NUM_BAG_SLOTS or 4
  local _, lastReagent = reagentBags(constants)
  if lastReagent and lastReagent > lastEquipped then
    lastEquipped = lastReagent
  end
  for bag = lastEquipped + 1, lastEquipped + (constants.NUM_BANKBAGSLOTS or 6) do
    ids[#ids + 1] = bag
  end
  return ids
end

ns.ContainerIds = ContainerIds
return ContainerIds
