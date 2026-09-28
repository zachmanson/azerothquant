local Nudge = require("Nudge")

local MIN = 60
local SCAN = 1000000 -- when the previous Scan was requested

describe("Nudge.due", function()
  it("nudges on the tick where the cooldown ends, when a Scan now would complete an Observation Window", function()
    assert.is_true(Nudge.due(SCAN, SCAN + 15 * MIN - 1, SCAN + 15 * MIN))
  end)

  it("doesn't nudge while the cooldown is still running", function()
    assert.is_false(Nudge.due(SCAN, SCAN + 15 * MIN - 2, SCAN + 15 * MIN - 1))
  end)

  it("doesn't nudge for a cooldown that ended before the last check", function()
    -- Covers both an Auction House opened after the cooldown ended (since = the time
    -- it opened) and a cooldown already nudged on an earlier tick.
    assert.is_false(Nudge.due(SCAN, SCAN + 15 * MIN, SCAN + 15 * MIN + 1))
    assert.is_false(Nudge.due(SCAN, SCAN + 20 * MIN, SCAN + 20 * MIN))
  end)

  it("doesn't nudge when the previous Scan is older than the Observation Window cap", function()
    -- The cooldown end hasn't been checked since before it passed (e.g. a long freeze),
    -- but by now a Scan would be too late to complete an Observation Window.
    assert.is_false(Nudge.due(SCAN, SCAN + 14 * MIN, SCAN + 60 * MIN + 1))
  end)

  it("still nudges at exactly the cap", function()
    assert.is_true(Nudge.due(SCAN, SCAN + 14 * MIN, SCAN + 60 * MIN))
  end)

  it("doesn't nudge when there is no previous Scan", function()
    assert.is_false(Nudge.due(nil, SCAN, SCAN + 1))
  end)
end)

describe("Nudge.whenReloadReady", function()
  -- Fakes for C_Timer.After, starting the Reload button pulse and a chat line.
  local function world()
    local w = { timers = {}, pulses = 0, lines = {} }
    w.after = function(seconds, fn)
      table.insert(w.timers, { seconds = seconds, fn = fn })
    end
    w.pulse = function()
      w.pulses = w.pulses + 1
    end
    w.say = function(text)
      table.insert(w.lines, text)
    end
    return w
  end

  it("after a load with unimported Scans, pulses Reload and says so once the Brain should be done", function()
    local w = world()

    Nudge.whenReloadReady(2, w.after, w.pulse, w.say)

    assert.are.equal(1, #w.timers)
    assert.are.equal(10, w.timers[1].seconds)
    assert.are.equal(0, w.pulses)
    assert.are.same({}, w.lines)

    w.timers[1].fn()

    assert.are.equal(1, w.pulses)
    assert.are.same({ "The Brain should be done: Reload to see the new Scan." }, w.lines)
  end)

  it("sets no timer when every saved Scan was imported", function()
    local w = world()

    Nudge.whenReloadReady(0, w.after, w.pulse, w.say)

    assert.are.same({}, w.timers)
  end)
end)
