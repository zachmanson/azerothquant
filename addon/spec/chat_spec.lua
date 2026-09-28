local Chat = require("Chat")

describe("Chat", function()
  local lines, realPrint

  before_each(function()
    lines = {}
    realPrint = _G.print
    _G.print = function(line)
      lines[#lines + 1] = line
    end
    _G.AzerothQuantDB = {}
  end)

  after_each(function()
    _G.print = realPrint
    _G.AzerothQuantDB = nil
  end)

  it("always says a line, after the AzerothQuant prefix", function()
    Chat.say("Scan #3 saved.")

    assert.are.same({ "|cff33ff99AzerothQuant|r Scan #3 saved." }, lines)
  end)

  it("keeps debug lines out of chat by default", function()
    Chat.debug("Read 12 Tailoring recipes.")

    assert.are.same({}, lines)
  end)

  it("shows debug lines once toggled on, saved so it outlives a reload", function()
    Chat.toggleDebug()
    Chat.debug("Read 12 Tailoring recipes.")

    assert.is_true(AzerothQuantDB.debug)
    assert.are.same({
      "|cff33ff99AzerothQuant|r Debug messages on.",
      "|cff33ff99AzerothQuant|r Read 12 Tailoring recipes.",
    }, lines)
  end)

  it("hides them again when toggled off", function()
    AzerothQuantDB.debug = true
    Chat.toggleDebug()
    Chat.debug("Read 12 Tailoring recipes.")

    assert.is_false(AzerothQuantDB.debug)
    assert.are.same({ "|cff33ff99AzerothQuant|r Debug messages off." }, lines)
  end)
end)
