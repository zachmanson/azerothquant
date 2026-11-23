-- WoW glue: ns.playerRealm(), the realm every Scan, Read and Recommendations lookup goes by.
-- Use it instead of GetRealmName(), which has been "" since the 2026-11-20 client patch
-- (Realm.lua, #238). Reads AzerothQuantRecommendations when called, since a Data slot can
-- replace it after load (DataAddon.lua).
local _, ns = ...
local Realm = ns.Realm

function ns.playerRealm()
  local character = table.concat({ UnitFullName("player") }, "-")
  return Realm.of(GetRealmName(), character, AzerothQuantRecommendations)
end
