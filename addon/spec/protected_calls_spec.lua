-- The Addon's guardrails on protected Auction House calls (ADR-0016, #81):
--   * it never buys, bids, or cancels (Cancel waits on #134), and never calls a Confirm
--     step, since one Post call posts on Forever;
--   * PostItem and PostCommodity appear only inside `local function onPostClick` in
--     RecommendationFrame.lua, which is wired only as the Post button's OnClick, so a
--     protected call is only ever made from a click, one per click.
--
-- Reads every file the .toc loads, so run busted from addon/ (CI does, with --directory).

local FORBIDDEN = {
  "PlaceBid",
  "StartCommoditiesPurchase",
  "ConfirmCommoditiesPurchase",
  "ConfirmPostItem",
  "ConfirmPostCommodity",
  "CancelAuction",
}
local POSTS = { "PostItem", "PostCommodity" }
local GLUE = "RecommendationFrame.lua"
local HANDLER = "\nlocal function onPostClick%("

local function word(name)
  return "%f[%w_]" .. name .. "%f[^%w_]"
end

local function count(source, pattern)
  local n = 0
  for _ in source:gmatch(pattern) do
    n = n + 1
  end
  return n
end

-- The source without its comments, so a comment can name a call.
local function code(source)
  source = source:gsub("%-%-%[(=*)%[.-%]%1%]", "")
  return (source:gsub("%-%-[^\n]*", ""))
end

-- The glue without onPostClick's body, which runs to the first `end` at column 0.
local function outsideHandler(source)
  local start = source:find(HANDLER)
  if not start then
    return source
  end
  local _, stop = source:find("\nend", start + 1, true)
  return source:sub(1, start) .. source:sub((stop or #source) + 1)
end

-- What breaks a guardrail in files ({ [file name] = source }), as one line each.
local function violations(files)
  local out = {}
  local names = {}
  for name in pairs(files) do
    names[#names + 1] = name
  end
  table.sort(names)
  for _, name in ipairs(names) do
    local source = code(files[name])
    for _, call in ipairs(FORBIDDEN) do
      if source:find(word(call)) then
        out[#out + 1] = name .. " calls " .. call
      end
    end
    local outside = name == GLUE and outsideHandler(source) or source
    for _, call in ipairs(POSTS) do
      if outside:find(word(call)) then
        out[#out + 1] = name .. " calls " .. call .. " outside onPostClick"
      end
    end
    local refs = count(source, word("onPostClick"))
    if name == GLUE then
      local defined = count(source, HANDLER)
      local wired = count(source, 'SetScript%("OnClick", onPostClick%)')
      if defined ~= 1 or wired ~= 1 or refs ~= 2 then
        out[#out + 1] = name .. " must define onPostClick once and use it only in one SetScript(\"OnClick\", onPostClick)"
      end
    elseif refs > 0 then
      out[#out + 1] = name .. " uses onPostClick"
    end
  end
  return out
end

-- Every file the .toc loads, by name.
local function addonFiles()
  local files = {}
  for line in io.lines("AzerothQuant/AzerothQuant.toc") do
    local name = line:match("^([%w_]+%.lua)%s*$")
    if name then
      local file = assert(io.open("AzerothQuant/" .. name, "rb"))
      files[name] = file:read("*a")
      file:close()
    end
  end
  return files
end

local HANDLER_SOURCE = table.concat({
  "local function onPostClick(self)",
  "  C_AuctionHouse.PostItem(self.location, 3, 1, nil, 100)",
  "end",
  "postButton:SetScript(\"OnClick\", onPostClick)",
}, "\n")

describe("the protected-call guardrails", function()
  it("pass on a glue file that posts only inside its click handler", function()
    assert.are.same({}, violations({ [GLUE] = "\n" .. HANDLER_SOURCE }))
  end)

  it("catch a post outside the click handler", function()
    local source = "\n" .. HANDLER_SOURCE .. "\nC_Timer.After(1, function() C_AuctionHouse.PostCommodity(l, 3, 5, 100) end)"

    assert.are.same({ GLUE .. " calls PostCommodity outside onPostClick" }, violations({ [GLUE] = source }))
  end)

  it("catch a post in any other file", function()
    assert.are.same(
      { "Scanner.lua calls PostItem outside onPostClick" },
      violations({ [GLUE] = "\n" .. HANDLER_SOURCE, ["Scanner.lua"] = "C_AuctionHouse.PostItem(l, 1, 1, nil, 1)" })
    )
  end)

  it("catch a buy, a bid, a cancel or a Confirm anywhere, even in the handler", function()
    local source = "\nlocal function onPostClick(self)\n  C_AuctionHouse.CancelAuction(1)\n  C_AuctionHouse.ConfirmPostItem(l)\nend\n"
      .. "postButton:SetScript(\"OnClick\", onPostClick)\nC_AuctionHouse.PlaceBid(1, 1)"

    assert.are.same({
      GLUE .. " calls PlaceBid",
      GLUE .. " calls ConfirmPostItem",
      GLUE .. " calls CancelAuction",
    }, violations({ [GLUE] = source }))
  end)

  it("catch the handler called from anywhere but its OnClick", function()
    local source = "\n" .. HANDLER_SOURCE .. "\nC_Timer.After(1, function() onPostClick(postButton) end)"

    assert.are.equal(1, #violations({ [GLUE] = source }))
  end)

  it("ignore calls named in comments", function()
    local source = "\n" .. HANDLER_SOURCE .. "\n-- never PlaceBid or CancelAuction here\n--[[ nor PostItem ]]"

    assert.are.same({}, violations({ [GLUE] = source }))
  end)

  it("hold for every file the Addon loads", function()
    assert.are.same({}, violations(addonFiles()))
  end)
end)
