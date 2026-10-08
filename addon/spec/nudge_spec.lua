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

  -- Fakes for C_Timer.After, starting the button's pulse (which says which button it
  -- pulsed: "Load", "Reload", or nil when Load was already clicked) and a chat line.
  -- button: what the pulse returns; Reload unless given, and false for nil.
  local function world(button)
    local w = { timers = {}, pulses = 0, lines = {} }
    w.after = function(seconds, fn)
      table.insert(w.timers, { seconds = seconds, fn = fn })
    end
    w.pulse = function()
      w.pulses = w.pulses + 1
      if button == false then
        return nil
      end
      return button or "Reload"
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

  it("says to Load instead when the button pulsing is Load (#106)", function()
    local w = world("Load")

    Nudge.afterLoad({ { savedAt = NOW } }, NOW, w.after, w.pulse, w.say)
    w.timers[1].fn()

    assert.are.same({ "The Brain should be done: Load to see the new Scan." }, w.lines)
  end)

  it("says nothing when Load was clicked before the Brain should be done", function()
    local w = world(false)

    Nudge.afterLoad({ { savedAt = NOW } }, NOW, w.after, w.pulse, w.say)
    w.timers[1].fn()

    assert.are.same({}, w.lines)
  end)

  it("sets no timer when every saved Scan was imported", function()
    local w = world()

    assert.is_false(Nudge.afterLoad({}, NOW, w.after, w.pulse, w.say))

    assert.are.same({}, w.timers)
    assert.are.same({}, w.lines)
  end)

  it("when the Brain is behind, asks whether the Brain app is running instead of promising it's done", function()
    local w = world()

    local behind = Nudge.afterLoad({ { savedAt = NOW }, { savedAt = NOW - 7 * MIN - 59 } }, NOW, w.after, w.pulse, w.say)

    assert.is_true(behind)
    assert.are.same({}, w.timers)
    assert.are.same({ "Your Scan from 7 min ago hasn't reached the Brain. Is AzerothQuant Brain running?"
      .. " Start it from the Start menu." }, w.lines)
  end)

  it("while the Brain is catching up on the pool, neither asks after it nor promises it's done (#159)", function()
    local w = world()

    local behind = Nudge.afterLoad({ { savedAt = NOW - 7 * MIN } }, NOW, w.after, w.pulse, w.say, true)

    assert.is_false(behind)
    assert.are.same({}, w.timers)
    assert.are.same({}, w.lines)
  end)
end)

describe("Nudge.catchingUp", function()
  local NOW = 2000000

  it("is catching up while the Brain's long pull started under 15 minutes ago", function()
    assert.is_true(Nudge.catchingUp({ brain = { catchingUpSince = NOW - 15 * MIN + 1 } }, NOW))
  end)

  it("stops trusting a pull that started 15 minutes ago or more: the Brain was likely closed mid-pull", function()
    assert.is_false(Nudge.catchingUp({ brain = { catchingUpSince = NOW - 15 * MIN } }, NOW))
  end)

  it("isn't catching up with no pull running, or before the Brain has ever run", function()
    assert.is_false(Nudge.catchingUp({ brain = { version = "0.2.0" } }, NOW))
    assert.is_false(Nudge.catchingUp({}, NOW))
    assert.is_false(Nudge.catchingUp(nil, NOW))
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

describe("Nudge.atLogin", function()
  local NOW = 2000000

  local function said(recommendations)
    local lines = {}
    Nudge.atLogin(recommendations, function(line)
      lines[#lines + 1] = line
    end, NOW)
    return lines
  end

  it("says the Brain is downloading recent Scans while it catches up on the pool (#159)", function()
    local recommendations = { brain = { version = "0.2.0", catchingUpSince = NOW - 2 * MIN } }

    assert.are.same({ "AzerothQuant is downloading recent Scans. This takes a few minutes."
      .. " Type /reload after that to see recommendations." }, said(recommendations))
  end)

  it("says nothing of a pull that started too long ago to still be running", function()
    assert.are.same({}, said({ brain = { version = "0.2.0", catchingUpSince = NOW - 15 * MIN } }))
  end)

  it("says the Brain app is needed when it has never run: the shipped stub has no brain status", function()
    local never = { "AzerothQuant needs its Brain app to make recommendations. See the setup guide." }
    assert.are.same(never, said({ lastImported = {}, recommendations = {} }))
    assert.are.same(never, said(nil))
  end)

  it("passes on the Brain's problem, with where to send its log", function()
    local recommendations = { brain = { version = "0.1.0", problem = "Couldn't reach the guild scan server." } }

    assert.are.same({ "Couldn't reach the guild scan server. If this keeps happening, send the Brain log"
      .. " (Start menu > AzerothQuant Brain log) to whoever gave you the Brain." }, said(recommendations))
  end)

  it("says nothing when the Brain has run and has no problem", function()
    assert.are.same({}, said({ brain = { version = "0.1.0" } }))
  end)
end)
