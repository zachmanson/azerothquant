local LoadTries = require("LoadTries")

local SLOTS = { "AzerothQuant_Data1", "AzerothQuant_Data2", "AzerothQuant_Data3" }

-- A clock C_Timer.After runs on, and a Brain that's done at `doneAt` seconds after load:
-- a slot loaded from then on is fresh. Records which slot was tried when, and the outcome.
local function world(doneAt)
  local w = { now = 0, tries = {}, timers = {} }
  function w.after(seconds, fn)
    table.insert(w.timers, { at = w.now + seconds, fn = fn })
  end
  function w.try(slot)
    table.insert(w.tries, { slot = slot, at = w.now })
    return doneAt ~= nil and w.now >= doneAt
  end
  function w.done(fresh)
    assert.is_nil(w.outcome, "done twice")
    w.outcome = fresh
  end
  -- Runs the timers in order until none are left.
  function w.run()
    while #w.timers > 0 do
      table.sort(w.timers, function(a, b)
        return a.at < b.at
      end)
      local timer = table.remove(w.timers, 1)
      w.now = timer.at
      timer.fn()
    end
  end
  return w
end

describe("LoadTries.run", function()
  it("stops at the first try when the Brain was done by then", function()
    local w = world(15)
    LoadTries.run(SLOTS, w.after, w.try, w.done)
    w.run()
    assert.are.same({ { slot = "AzerothQuant_Data1", at = 20 } }, w.tries)
    assert.is_true(w.outcome)
  end)

  it("tries the next slot later while the copy is stale", function()
    local w = world(40)
    LoadTries.run(SLOTS, w.after, w.try, w.done)
    w.run()
    assert.are.same({
      { slot = "AzerothQuant_Data1", at = 20 },
      { slot = "AzerothQuant_Data2", at = 45 },
    }, w.tries)
    assert.is_true(w.outcome)
  end)

  it("gives up stale after the last slot", function()
    local w = world(nil)
    LoadTries.run(SLOTS, w.after, w.try, w.done)
    w.run()
    assert.are.same({
      { slot = "AzerothQuant_Data1", at = 20 },
      { slot = "AzerothQuant_Data2", at = 45 },
      { slot = "AzerothQuant_Data3", at = 90 },
    }, w.tries)
    assert.is_false(w.outcome)
  end)

  it("gives up after the last slot there is when fewer are installed", function()
    local w = world(nil)
    LoadTries.run({ "AzerothQuant_Data1", "AzerothQuant_Data2" }, w.after, w.try, w.done)
    w.run()
    assert.are.equal(2, #w.tries)
    assert.is_false(w.outcome)
  end)

  it("tries nothing with no slots", function()
    local w = world(0)
    LoadTries.run({}, w.after, w.try, w.done)
    w.run()
    assert.are.same({}, w.tries)
    assert.is_nil(w.outcome)
  end)
end)
