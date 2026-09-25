local Prune = require("Prune")

local function scan(id, realm, faction, requestedAt)
  return { id = id, realm = realm, faction = faction, requestedAt = requestedAt, listings = {} }
end

local function ids(scans)
  local out = {}
  for i, s in ipairs(scans) do
    out[i] = s.id
  end
  return out
end

describe("Prune.importedScans", function()
  it("deletes nothing when the Brain has never run", function()
    local scans = { scan(1, "Classic Beta PvP", "Alliance", 100) }

    assert.are.equal(0, Prune.importedScans(scans, nil))
    assert.are.equal(0, Prune.importedScans(scans, {}))
    assert.are.same({ 1 }, ids(scans))
  end)

  it("deletes Scans requested at or before the Market's last imported Scan, and keeps later ones", function()
    local scans = {
      scan(1, "Classic Beta PvP", "Alliance", 100),
      scan(2, "Classic Beta PvP", "Alliance", 200),
      scan(3, "Classic Beta PvP", "Alliance", 201),
    }
    local recommendations = { lastImported = { ["Classic Beta PvP"] = { Alliance = 200 } } }

    local removed = Prune.importedScans(scans, recommendations)

    assert.are.equal(2, removed)
    assert.are.same({ 3 }, ids(scans))
  end)

  it("uses each Market's own time", function()
    local scans = {
      scan(1, "Classic Beta PvP", "Alliance", 100),
      scan(2, "Classic Beta PvP", "Neutral", 100),
      scan(3, "Classic Beta PvP", "Horde", 100),
      scan(4, "Quel'Thalas", "Alliance", 100),
      scan(5, "Classic Beta PvP", "Alliance", 300),
    }
    local recommendations = {
      lastImported = {
        ["Classic Beta PvP"] = { Alliance = 150, Neutral = 50 },
        -- Horde on this realm never imported; Quel'Thalas only has a Horde Market imported.
        ["Quel'Thalas"] = { Horde = 500 },
      },
    }

    Prune.importedScans(scans, recommendations)

    assert.are.same({ 2, 3, 4, 5 }, ids(scans))
  end)

  it("keeps Scans it can't place in a Market or time", function()
    local scans = {
      scan(1, nil, "Alliance", 100),
      scan(2, "Classic Beta PvP", nil, 100),
      scan(3, "Classic Beta PvP", "Alliance", nil),
    }
    local recommendations = { lastImported = { ["Classic Beta PvP"] = { Alliance = 200 } } }

    assert.are.equal(0, Prune.importedScans(scans, recommendations))
    assert.are.same({ 1, 2, 3 }, ids(scans))
  end)

  it("keeps the remaining Scans in order with no gaps", function()
    local scans = {
      scan(1, "R", "Alliance", 10),
      scan(2, "R", "Horde", 10),
      scan(3, "R", "Alliance", 20),
      scan(4, "R", "Horde", 20),
    }

    Prune.importedScans(scans, { lastImported = { R = { Alliance = 20 } } })

    assert.are.same({ 2, 4 }, ids(scans))
    assert.is_nil(scans[3])
  end)
end)
