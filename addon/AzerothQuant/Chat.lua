-- The Addon's chat lines (#53). Quiet by default: say() is for what the player acts on,
-- errors, and replies to something they typed. Everything else goes through debug(),
-- which only prints while /aq debug has it on (AzerothQuantDB.debug, saved).
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for
-- the namespace fallback.
local _, ns = ...
ns = ns or {}

local Chat = {}

local PREFIX = "|cff33ff99AzerothQuant|r "

function Chat.say(msg)
  print(PREFIX .. msg)
end

function Chat.debug(msg)
  local db = AzerothQuantDB
  if db and db.debug then
    Chat.say(msg)
  end
end

-- /aq debug. AzerothQuantDB is set up at ADDON_LOADED, before a slash command can run.
function Chat.toggleDebug()
  AzerothQuantDB.debug = not AzerothQuantDB.debug
  Chat.say(AzerothQuantDB.debug and "Debug messages on." or "Debug messages off.")
end

ns.Chat = Chat
return Chat
