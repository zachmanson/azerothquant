local Freshness = require("Freshness")

local REALM = "Classic Beta PvP"
local ME = "Kash-Patel"

local function scan(faction, requestedAt, savedAt)
  return { realm = REALM, faction = faction, requestedAt = requestedAt, savedAt = savedAt }
end

-- A Recommendations.lua whose stamps say the Brain imported up to these times.
local function copy(alliance, horde, characterRead)
  return {
    lastImported = { [REALM] = { Alliance = alliance, Horde = horde } },
    lastCharacterRead = { [REALM] = { [ME] = characterRead } },
  }
end

describe("Freshness.isFresh", function()
  local lastSavedRead = { realm = REALM, character = ME, readAt = 500 }

  it("is fresh when the copy has imported the last logout's Character Read and every saved Scan", function()
    local scans = { scan("Alliance", 100, 400), scan("Horde", 200, 500) }

    assert.is_true(Freshness.isFresh(copy(100, 200, 500), scans, lastSavedRead))
    assert.is_true(Freshness.isFresh(copy(150, 250, 600), scans, lastSavedRead))
  end)

  it("is stale when the copy is from before the last logout's Character Read", function()
    assert.is_false(Freshness.isFresh(copy(100, 200, 499), {}, lastSavedRead))
  end)

  it("is stale when a saved Scan's Market isn't imported up to it", function()
    assert.is_false(Freshness.isFresh(copy(100, 199, 500), { scan("Horde", 200, 500) }, lastSavedRead))
    assert.is_false(Freshness.isFresh(copy(100, nil, 500), { scan("Horde", 200, 500) }, lastSavedRead))
  end)

  it("ignores Scans taken since the load, which aren't saved yet", function()
    assert.is_true(Freshness.isFresh(copy(100, 200, 500), { scan("Horde", 900, nil) }, lastSavedRead))
  end)

  it("with no Character Read saved yet, only the Scans count", function()
    assert.is_true(Freshness.isFresh(copy(100, 200, nil), {}, nil))
  end)

  it("is stale when there's no copy at all", function()
    assert.is_false(Freshness.isFresh(nil, {}, lastSavedRead))
    assert.is_false(Freshness.isFresh({}, {}, lastSavedRead))
  end)
end)

describe("Freshness.covers", function()
  local function stamps(scanAt, mailboxAt, characterAt)
    return {
      lastImported = { [REALM] = { Alliance = scanAt } },
      lastMailboxRead = { [REALM] = { [ME] = mailboxAt } },
      lastCharacterRead = { [REALM] = { [ME] = characterAt } },
    }
  end

  it("covers a copy when it has imported at least as far everywhere", function()
    assert.is_true(Freshness.covers(stamps(100, 200, 300), stamps(100, 200, 300)))
    assert.is_true(Freshness.covers(stamps(101, 200, 350), stamps(100, 200, 300)))
  end)

  it("doesn't when any stamp is older, so switching to it would undo an import", function()
    assert.is_false(Freshness.covers(stamps(99, 200, 300), stamps(100, 200, 300)))
    assert.is_false(Freshness.covers(stamps(100, 199, 300), stamps(100, 200, 300)))
    assert.is_false(Freshness.covers(stamps(100, 200, 299), stamps(100, 200, 300)))
  end)

  it("doesn't when a Market or Character is missing from it", function()
    local older = stamps(100, 200, 300)
    older.lastImported[REALM].Horde = 50

    assert.is_false(Freshness.covers(stamps(100, 200, 300), older))
  end)

  it("covers a startup copy the Brain never wrote, and a nil copy covers nothing", function()
    assert.is_true(Freshness.covers(stamps(100, 200, 300), nil))
    assert.is_true(Freshness.covers(stamps(100, 200, 300), {}))
    assert.is_false(Freshness.covers(nil, stamps(100, 200, 300)))
  end)
end)
