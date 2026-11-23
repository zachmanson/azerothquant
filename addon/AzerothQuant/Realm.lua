-- Which realm the player is on, as the Brain's Markets name it (#238).
--
-- Since the 2026-11-20 client patch the client gives addons no realm: GetRealmName() and
-- GetNormalizedRealmName() are "" and GetRealmID() is 0. Scans saved with realm "" made a
-- new Market with no history. So when the client gives none, the realm is the one the
-- Brain last read this character on (Recommendations.lua's lastCharacterRead and
-- lastMailboxRead), and "" only when the Brain has never read the character.
--
-- Plain Lua with no WoW API calls, so it runs under busted. In game, WoW passes
-- (addonName, namespace) as the file's varargs; under require() the namespace
-- is absent, so the module falls back to a fresh table and is returned instead.
local _, ns = ...
ns = ns or {}

local Realm = {}

local READS = { "lastCharacterRead", "lastMailboxRead" }

-- clientRealm: GetRealmName(). character: "Name-Suffix" as the Reads key it.
-- recommendations: AzerothQuantRecommendations, or nil.
function Realm.of(clientRealm, character, recommendations)
  if clientRealm and clientRealm ~= "" then
    return clientRealm
  end
  local found, foundAt = "", nil
  for _, section in ipairs(READS) do
    for realm, byCharacter in pairs(recommendations and recommendations[section] or {}) do
      local at = realm ~= "" and byCharacter[character]
      if at and (foundAt == nil or at > foundAt) then
        found, foundAt = realm, at
      end
    end
  end
  return found
end

ns.Realm = Realm
return Realm
