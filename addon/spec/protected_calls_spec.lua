-- The Addon's guardrails on protected Auction House calls (ADR-0016, #81, ADR-0044):
--   * it never buys or bids, and never calls a Confirm step, since one Post call posts on
--     Forever;
--   * PostItem and PostCommodity appear only inside `local function onPostClick` or
--     `local function onWritClick` in RecommendationFrame.lua, and CancelAuction only
--     inside `local function onCancelClick`, at most once. Each is wired only as its
--     button's click script (the Writs button's PostClick, after its secure action), so a
--     protected call is only ever made from a click, one per click.
--
-- Reads every file the .toc loads, so run busted from addon/ (CI does, with --directory).

local FORBIDDEN = {
  "PlaceBid",
  "StartCommoditiesPurchase",
  "ConfirmCommoditiesPurchase",
  "ConfirmPostItem",
  "ConfirmPostCommodity",
}
local GLUE = "RecommendationFrame.lua"
-- Each protected call the Addon makes, the one click handler in the glue it may appear in,
-- and whether that handler may make it more than once (Post's has one call per branch).
local HANDLERS = {
  { name = "onPostClick", calls = { "PostItem", "PostCommodity" } },
  { name = "onWritClick", calls = { "PostItem", "PostCommodity" }, script = "PostClick" },
  { name = "onCancelClick", calls = { "CancelAuction" }, once = true },
}

-- The handlers allowed to make call, by name.
local function allowed(call)
  local names = {}
  for _, handler in ipairs(HANDLERS) do
    for _, c in ipairs(handler.calls) do
      if c == call then
        names[#names + 1] = handler.name
      end
    end
  end
  return names
end

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

-- The handler's body (to the first `end` at column 0) and the source without it.
local function splitHandler(source, name)
  local start = source:find("\nlocal function " .. name .. "%(")
  if not start then
    return "", source
  end
  local _, stop = source:find("\nend", start + 1, true)
  stop = stop or #source
  return source:sub(start, stop), source:sub(1, start) .. source:sub(stop + 1)
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
    local reported = {}
    for _, handler in ipairs(HANDLERS) do
      local body = ""
      if name == GLUE then
        body = splitHandler(source, handler.name)
      end
      for _, call in ipairs(handler.calls) do
        -- The source without every handler allowed to make the call.
        local names = allowed(call)
        local outside = source
        if name == GLUE then
          for _, allowedName in ipairs(names) do
            local _, rest = splitHandler(outside, allowedName)
            outside = rest
          end
        end
        if not reported[call] and outside:find(word(call)) then
          reported[call] = true
          out[#out + 1] = name .. " calls " .. call .. " outside " .. table.concat(names, " or ")
        end
        if handler.once and count(body, word(call)) > 1 then
          out[#out + 1] = name .. " calls " .. call .. " more than once in " .. handler.name
        end
      end
      local refs = count(source, word(handler.name))
      if name == GLUE then
        local script = handler.script or "OnClick"
        local defined = count(source, "\nlocal function " .. handler.name .. "%(")
        local wired = count(source, 'SetScript%("' .. script .. '", ' .. handler.name .. "%)")
        if defined ~= 1 or wired ~= 1 or refs ~= 2 then
          out[#out + 1] = name .. " must define " .. handler.name .. " once and use it only in one SetScript(\""
            .. script .. "\", " .. handler.name .. ")"
        end
      elseif refs > 0 then
        out[#out + 1] = name .. " uses " .. handler.name
      end
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

local CANCEL_SOURCE = table.concat({
  "local function onCancelClick(self)",
  "  C_AuctionHouse.CancelAuction(id)",
  "end",
  "cancelButton:SetScript(\"OnClick\", onCancelClick)",
}, "\n")

local WRIT_SOURCE = table.concat({
  "local function onWritClick(self)",
  "  C_AuctionHouse.PostCommodity(self.location, 3, 1, 100)",
  "end",
  "writButton:SetScript(\"PostClick\", onWritClick)",
}, "\n")

-- A glue file whose Post, Writs and Cancel undercut handlers each make their call.
local HANDLER_SOURCE = table.concat({
  "local function onPostClick(self)",
  "  C_AuctionHouse.PostItem(self.location, 3, 1, nil, 100)",
  "end",
  "postButton:SetScript(\"OnClick\", onPostClick)",
  WRIT_SOURCE,
  CANCEL_SOURCE,
}, "\n")

describe("the protected-call guardrails", function()
  it("pass on a glue file that posts only inside its click handler", function()
    assert.are.same({}, violations({ [GLUE] = "\n" .. HANDLER_SOURCE }))
  end)

  it("catch a post outside the click handler", function()
    local source = "\n" .. HANDLER_SOURCE .. "\nC_Timer.After(1, function() C_AuctionHouse.PostCommodity(l, 3, 5, 100) end)"

    assert.are.same({ GLUE .. " calls PostCommodity outside onPostClick or onWritClick" }, violations({ [GLUE] = source }))
  end)

  it("catch a post in any other file", function()
    assert.are.same(
      { "Scanner.lua calls PostItem outside onPostClick or onWritClick" },
      violations({ [GLUE] = "\n" .. HANDLER_SOURCE, ["Scanner.lua"] = "C_AuctionHouse.PostItem(l, 1, 1, nil, 1)" })
    )
  end)

  it("catch a buy, a bid or a Confirm anywhere, even in the handler", function()
    local source = "\nlocal function onPostClick(self)\n  C_AuctionHouse.ConfirmPostItem(l)\nend\n"
      .. "postButton:SetScript(\"OnClick\", onPostClick)\nC_AuctionHouse.PlaceBid(1, 1)\n" .. WRIT_SOURCE .. "\n" .. CANCEL_SOURCE

    assert.are.same({
      GLUE .. " calls PlaceBid",
      GLUE .. " calls ConfirmPostItem",
    }, violations({ [GLUE] = source }))
  end)

  it("pass on a glue file that cancels only inside its Cancel undercut click handler", function()
    assert.are.same({}, violations({ [GLUE] = "\n" .. HANDLER_SOURCE }))
  end)

  it("catch a cancel outside the Cancel undercut click handler, even in Post's", function()
    local source = "\nlocal function onPostClick(self)\n  C_AuctionHouse.CancelAuction(1)\nend\n"
      .. "postButton:SetScript(\"OnClick\", onPostClick)\n" .. WRIT_SOURCE .. "\n" .. CANCEL_SOURCE

    assert.are.same({ GLUE .. " calls CancelAuction outside onCancelClick" }, violations({ [GLUE] = source }))
  end)

  it("catch a cancel in any other file", function()
    assert.are.same(
      { "Scanner.lua calls CancelAuction outside onCancelClick" },
      violations({
        [GLUE] = "\n" .. HANDLER_SOURCE,
        ["Scanner.lua"] = "C_AuctionHouse.CancelAuction(1)",
      })
    )
  end)

  it("catch more than one cancel in the handler", function()
    local twice = HANDLER_SOURCE:gsub("CancelAuction%(id%)", "CancelAuction(id)\n  C_AuctionHouse.CancelAuction(id2)")

    assert.are.same(
      { GLUE .. " calls CancelAuction more than once in onCancelClick" },
      violations({ [GLUE] = "\n" .. twice })
    )
  end)

  it("catch the Cancel undercut handler called from anywhere but its OnClick", function()
    local source = "\n" .. HANDLER_SOURCE .. "\nC_Timer.After(1, function() onCancelClick(cancelButton) end)"

    assert.are.equal(1, #violations({ [GLUE] = source }))
  end)

  it("catch the handler called from anywhere but its OnClick", function()
    local source = "\n" .. HANDLER_SOURCE .. "\nC_Timer.After(1, function() onPostClick(postButton) end)"

    assert.are.equal(1, #violations({ [GLUE] = source }))
  end)

  it("catch a post outside both post handlers", function()
    local source = "\n" .. HANDLER_SOURCE .. "\nwriteButton = function() C_AuctionHouse.PostItem(l, 1, 1, nil, 1) end"

    assert.are.same({ GLUE .. " calls PostItem outside onPostClick or onWritClick" }, violations({ [GLUE] = source }))
  end)

  it("catch the Writs handler wired as OnClick instead of PostClick", function()
    local source = ("\n" .. HANDLER_SOURCE):gsub('SetScript%("PostClick", onWritClick%)', 'SetScript("OnClick", onWritClick)')

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
