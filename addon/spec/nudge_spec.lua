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

describe("Nudge.afterLoad", function()
  local NOW = SCAN + 60 * MIN

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

    local behind = Nudge.afterLoad({ { savedAt = NOW }, { savedAt = NOW } }, NOW, w.after, w.pulse, w.say)

    assert.is_false(behind)
    assert.are.equal(1, #w.timers)
    assert.are.equal(Nudge.RELOAD_READY_AFTER, w.timers[1].seconds)
    assert.are.equal(0, w.pulses)
    assert.are.same({}, w.lines)

    w.timers[1].fn()

    assert.are.equal(1, w.pulses)
    assert.are.same({ "The Brain should be done: Reload to see the new Scan." }, w.lines)
  end)

  it("sets no timer when every saved Scan was imported", function()
    local w = world()

    assert.is_false(Nudge.afterLoad({}, NOW, w.after, w.pulse, w.say))

    assert.are.same({}, w.timers)
    assert.are.same({}, w.lines)
  end)

  it("when the Brain is behind, asks whether brain watch is running instead of promising it's done", function()
    local w = world()

    local behind = Nudge.afterLoad({ { savedAt = NOW }, { savedAt = NOW - 7 * MIN - 59 } }, NOW, w.after, w.pulse, w.say)

    assert.is_true(behind)
    assert.are.same({}, w.timers)
    assert.are.same({ "The Brain hasn't imported Scans saved 7 min ago. Is brain watch running? (scripts\\play.bat)" },
      w.lines)
  end)
end)

describe("Nudge.stampSaved", function()
  it("stamps the Scans saved for the first time and keeps the stamp on ones saved before", function()
    local fresh = { id = 2 }
    local older = { id = 1, savedAt = SCAN }
    local scans = { older, fresh }

    Nudge.stampSaved(scans, SCAN + 5 * MIN)

    assert.are.equal(SCAN, older.savedAt)
    assert.are.equal(SCAN + 5 * MIN, fresh.savedAt)
  end)
end)

describe("Nudge.brainBehind", function()
  local NOW = SCAN + 60 * MIN

  it("isn't behind with no Scans waiting", function()
    assert.is_nil(Nudge.brainBehind({}, NOW))
  end)

  it("isn't behind while every Scan was saved too recently for brain watch to be done", function()
    local justUnder = NOW - Nudge.BRAIN_BEHIND_AFTER + 1
    assert.is_nil(Nudge.brainBehind({ { savedAt = justUnder }, { savedAt = NOW } }, NOW))
  end)

  it("is behind by the oldest Scan's age once one has waited the threshold or longer", function()
    local atThreshold = NOW - Nudge.BRAIN_BEHIND_AFTER
    local older = NOW - 10 * MIN
    assert.are.equal(Nudge.BRAIN_BEHIND_AFTER, Nudge.brainBehind({ { savedAt = atThreshold }, { savedAt = NOW } }, NOW))
    assert.are.equal(10 * MIN, Nudge.brainBehind({ { savedAt = atThreshold }, { savedAt = older } }, NOW))
  end)

  it("ignores a Scan with no savedAt, saved by a build from before the stamp", function()
    assert.is_nil(Nudge.brainBehind({ { id = 1 } }, NOW))
  end)
end)
