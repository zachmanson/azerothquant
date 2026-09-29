-- Turns a Craft row's Craft Chain (#77), the tree of nodes the Brain writes as chain, into
-- the lines the chain panel draws, top-down: the exits, the craft under the last one, and
-- each source indented under what it feeds.
--
-- Plain Lua with no WoW API calls, so it runs under busted.
local _, ns = ...
ns = ns or {}

-- In game Money.lua and RecommendationTable.lua load first (see the .toc).
local Money = ns.Money or require("Money")
local RecommendationTable = ns.RecommendationTable or require("RecommendationTable")

local CraftChain = {}

local VERBS = {
  sell = "Sell",
  vendor = "Vendor",
  craft = "Craft",
  use = "Use",
  buy = "Buy",
  merchant = "Buy",
  leftover = "Leftover",
  disenchant = "Disenchant",
}

local function tag(node)
  if node.kind == "sell" then
    return "@ " .. Money.format(node.postAt)
  elseif node.kind == "craft" then
    return "on " .. node.character .. ", " .. node.crafts .. " crafts"
  elseif node.kind == "use" then
    return "held"
  elseif node.kind == "buy" then
    return "AH @ max " .. Money.format(node.maxUnitPrice)
  elseif node.kind == "merchant" then
    return "merchant"
  end
  return nil
end

-- Gold the Brain couldn't value, on a blocked row.
CraftChain.UNKNOWN = "\226\128\148" -- an em dash, in UTF-8

-- Why a node blocks its row (#75). A reason the Addon doesn't know yet shows as it is.
local REASONS = {
  noData = "no market data",
  unknownBindType = "unknown bind type",
}

-- Signed gold, e.g. "+85s" or "-20c", and "gain" or "loss" so it's never colour alone.
local function signed(copper)
  if copper == nil then
    return CraftChain.UNKNOWN, nil
  end
  local text = Money.format(copper)
  if text == "0c" then
    return text, nil
  end
  if copper > 0 then
    return "+" .. text, "gain"
  end
  return text, "loss"
end

-- The hover's breakdown of a node's gold. The Brain writes the parts as positive costs,
-- already taken out of the gold, and a part of 0 isn't worth a line.
local function breakdown(node)
  local lines = {}
  local function add(label, copper)
    if copper and copper ~= 0 then
      lines[#lines + 1] = label .. ": " .. (signed(copper))
    end
  end
  if node.kind == "sell" then
    add("Posted", node.postAt * node.quantity)
    add("Auction House cut", -(node.cut or 0))
    add("Deposits", -(node.deposit or 0))
  end
  add("Effort cost", -(node.effort or 0))
  return lines
end

local function nameFor(itemKey, nameOf)
  local itemString = RecommendationTable.itemString(itemKey)
  return nameOf(itemString) or itemString
end

-- above with one more level, or as it is for a root (which has no elbow).
local function extend(above, connected, kind)
  local out = {}
  for d, g in ipairs(above) do
    out[d] = g
  end
  if connected then
    out[#out + 1] = kind
  end
  return out
end

-- guides says what to draw left of the node, one per level above it: "branch" (├) and
-- "last" (└) for its own elbow, and "pipe" (│) or "space" under each ancestor's elbow,
-- depending on whether that ancestor has siblings still to come. Roots get none.
local function walk(nodes, above, connected, nameOf, lines)
  for i, node in ipairs(nodes) do
    local last = i == #nodes
    local line = {
      guides = extend(above, connected, last and "last" or "branch"),
      itemString = RecommendationTable.itemString(node.itemKey),
      tooltip = breakdown(node),
      -- A kind the Addon doesn't know yet (#76's disenchant, say) shows as it is.
      text = (VERBS[node.kind] or node.kind) .. " " .. node.quantity .. " " .. nameFor(node.itemKey, nameOf),
      tag = tag(node),
    }
    line.gold, line.color = signed(node.gold)
    if node.blocked then
      -- Whatever gold the Brain kept, the node that blocks the row can't be valued.
      line.blocked = REASONS[node.blocked.reason] or node.blocked.reason
      line.gold, line.color = CraftChain.UNKNOWN, nil
    elseif node.kind == "craft" and node.gold then
      -- A craft's gold is the sum of the sources under it, already counted on their lines.
      line.color = "subtotal"
    end
    lines[#lines + 1] = line
    walk(node.children or {}, extend(above, connected, last and "space" or "pipe"), true, nameOf, lines)
  end
end

-- The row's lines, and its Profit (nil on a blocked row, which has none). With no chain,
-- empty says why instead. nameOf(itemString) gives an item's name, or nil until the client
-- has it.
function CraftChain.build(r, nameOf)
  local lines = {}
  walk(r.chain or {}, {}, false, nameOf, lines)
  local out = { lines = lines }
  if #lines == 0 then
    out.empty = "No chain to show: " .. RecommendationTable.note(r, nameOf)
  end
  if r.profit then
    local gold, color = signed(r.profit)
    out.profit = { text = "Profit", gold = gold, color = color }
  end
  return out
end

ns.CraftChain = CraftChain
return CraftChain
