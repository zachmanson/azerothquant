local NextStep = require("NextStep")

local MIN = 60
local NOW = 1000000

-- The loop as it stands after a Scan was imported long ago, the Brain fine and the AH
-- closed; each case changes what makes its state.
local function loop(changes)
  local state = {
    scanning = false,
    ahOpen = false,
    unsaved = 0,
    unimported = 0,
    behind = false,
    catchingUp = false,
    brainRan = true,
    trying = false,
    tookLonger = false,
    reloadReady = false,
    lastScanAt = NOW - 60 * MIN,
  }
  for k, v in pairs(changes or {}) do
    state[k] = v
  end
  return state
end

describe("NextStep.of", function()
  it("is Scan, pulsing, when a Scan can run with the AH open", function()
    local step = NextStep.of(loop({ ahOpen = true }), NOW)
    assert.are.equal("Scan", step.button)
    assert.is_true(step.enabled)
    assert.is_true(step.pulse)
    assert.is_nil(step.quiet)
  end)

  it("says to open the AH, with no button, when a Scan can run but the AH is closed", function()
    local step = NextStep.of(loop(), NOW)
    assert.are.equal("Open the Auction House to Scan.", step.line)
    assert.is_nil(step.button)
  end)

  it("is a disabled Scanning... while a Scan is in flight, even with an earlier one unsaved", function()
    local step = NextStep.of(loop({ ahOpen = true, scanning = true, unsaved = 1 }), NOW)
    assert.are.equal("Scanning...", step.button)
    assert.is_false(step.enabled)
    assert.is_false(step.pulse)
  end)

  it("is Reload, pulsing, once a Scan is saved, wherever the Brain is", function()
    local step = NextStep.of(loop({ unsaved = 1, unimported = 2, trying = true, behind = true }), NOW)
    assert.are.equal("Reload", step.button)
    assert.is_true(step.enabled)
    assert.is_true(step.pulse)
    assert.is_nil(step.warn)
  end)

  it("says the Brain is downloading guild Scans, with a quiet Reload, while it catches up", function()
    local step = NextStep.of(loop({ catchingUp = true, unimported = 1, behind = true }), NOW)
    assert.are.equal("Downloading guild Scans", step.title)
    assert.are.equal("Reload", step.button)
    assert.is_false(step.pulse)
    assert.is_nil(step.warn)
  end)

  it("warns the Brain isn't running when it's behind on a saved Scan", function()
    local step = NextStep.of(loop({ unimported = 1, behind = true, reloadReady = true, tookLonger = true }), NOW)
    assert.are.equal("Brain not running", step.title)
    assert.is_true(step.warn)
    assert.are.equal("Reload", step.button)
    assert.is_false(step.pulse)
  end)

  it("warns the Brain isn't running when it never has", function()
    local step = NextStep.of(loop({ brainRan = false, lastScanAt = nil, ahOpen = true }), NOW)
    assert.are.equal("Brain not running", step.title)
    assert.is_true(step.warn)
  end)

  it("says the Brain is working, with no button, while the Data slots are being tried", function()
    -- A stale try counts the Brain as due (reloadReady), but later slots may still catch it.
    local step = NextStep.of(loop({ unimported = 1, trying = true, reloadReady = true, ahOpen = true }), NOW)
    assert.are.equal("The Brain is working", step.title)
    assert.are.equal("New recommendations will show by themselves. About a minute.", step.line)
    assert.is_nil(step.button)
  end)

  it("warns the Brain took longer, with Reload pulsing, once every Data slot was stale", function()
    local step = NextStep.of(loop({ unimported = 1, tookLonger = true, reloadReady = true }), NOW)
    assert.are.equal("The Brain took longer than usual", step.title)
    assert.are.equal("Reload to try again.", step.line)
    assert.is_true(step.warn)
    assert.are.equal("Reload", step.button)
    assert.is_true(step.pulse)
  end)

  it("says the Brain is working, with no button, until it should be done, with no Data slots", function()
    local step = NextStep.of(loop({ unimported = 1, ahOpen = true }), NOW)
    assert.are.equal("The Brain is working", step.title)
    assert.are.equal("The Brain is reading your Scan. About a minute.", step.line)
    assert.is_nil(step.button)
  end)

  it("is Reload, pulsing, once the Brain should be done, with no Data slots", function()
    -- The first run before a client restart: the client hasn't found the slots yet.
    local step = NextStep.of(loop({ unimported = 1, reloadReady = true }), NOW)
    assert.are.equal("Reload", step.button)
    assert.are.equal("reload", step.action)
    assert.is_true(step.pulse)
    assert.is_nil(step.warn)
  end)

  it("shrinks to one line, with no button, when up to date and the Scan cooldown is running", function()
    local step = NextStep.of(loop({ ahOpen = true, lastScanAt = NOW - 3 * MIN - 30 }), NOW)
    assert.is_true(step.quiet)
    assert.are.equal("These are from your Scan 3 min ago. You can Scan again in 11:30.", step.line)
    assert.is_nil(step.button)
  end)

  it("stays one line with the AH closed while the cooldown runs", function()
    local step = NextStep.of(loop({ lastScanAt = NOW - 14 * MIN }), NOW)
    assert.is_true(step.quiet)
    assert.are.equal("These are from your Scan 14 min ago. You can Scan again in 1:00.", step.line)
  end)
end)
