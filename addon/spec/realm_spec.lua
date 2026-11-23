local Realm = require("Realm")

describe("Realm.of", function()
  local REALM = "CAMWOW US2 Realm 8 PvP"

  it("is the client's realm name when it has one", function()
    assert.are.equal("Other Realm", Realm.of("Other Realm", "Sab-Otage", {
      lastCharacterRead = { [REALM] = { ["Sab-Otage"] = 100 } },
    }))
  end)

  -- #238: since the 2026-11-20 client patch GetRealmName() is "" (and so are
  -- GetNormalizedRealmName() and GetRealmID()), so the Brain's record stands in.
  it("is the realm the Brain last read the character on when the client gives none", function()
    assert.are.equal(REALM, Realm.of("", "Sab-Otage", {
      lastCharacterRead = { [REALM] = { ["Sab-Otage"] = 100 } },
    }))
  end)

  it("also goes by Mailbox Reads", function()
    assert.are.equal(REALM, Realm.of(nil, "Sab-Otage", {
      lastMailboxRead = { [REALM] = { ["Sab-Otage"] = 100 } },
    }))
  end)

  it("never picks the empty realm those Reads were saved under", function()
    assert.are.equal(REALM, Realm.of("", "Sab-Otage", {
      lastCharacterRead = {
        [""] = { ["Sab-Otage"] = 900 },
        [REALM] = { ["Sab-Otage"] = 100 },
      },
    }))
  end)

  it("picks the latest Read when the character name is on two realms", function()
    local recs = {
      lastCharacterRead = { ["Old Realm"] = { ["Sab-Otage"] = 100 } },
      lastMailboxRead = { [REALM] = { ["Sab-Otage"] = 200 } },
    }
    assert.are.equal(REALM, Realm.of("", "Sab-Otage", recs))
  end)

  it("ignores other characters' realms", function()
    assert.are.equal("", Realm.of("", "Sab-Otage", {
      lastCharacterRead = { [REALM] = { ["Kash-Patel"] = 100 } },
    }))
  end)

  it("is empty with no Recommendations at all", function()
    assert.are.equal("", Realm.of("", "Sab-Otage", nil))
    assert.are.equal("", Realm.of("", "Sab-Otage", {}))
  end)
end)
