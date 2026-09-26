-- SPIKE (#15), throwaway: delete this file (and its TOC line) once the spike's answers
-- are on the issue. Not part of the Addon's design and not tested.
--
-- Questions for the live Forever client: AH sender names, subject strings per mail
-- kind, what GetInboxHeaderInfo / GetInboxInvoiceInfo return, daysLeft max and
-- precision, and how MAIL_SHOW / MAIL_INBOX_UPDATE are timed.
--
-- Usage: open a mailbox, wait a few seconds, type /aq maildump, then /reload (or log
-- out) and paste AzerothQuantDB.mailDumpSpike from the SavedVariables file.
--
-- Read-only (ADR-0003): only GetInboxNumItems, GetInboxHeaderInfo,
-- GetInboxInvoiceInfo and GetInboxItemLink. Never GetInboxText (it marks mail read),
-- never takes, returns, deletes or sends, and never calls CheckInbox.

-- Every return value by position, with nil spelled out so the gaps are visible
-- (a Lua table would silently drop them).
local function allReturns(...)
  local out = { n = select("#", ...) }
  for i = 1, out.n do
    local v = select(i, ...)
    out[i] = v == nil and "<nil>" or v
  end
  return out
end

-- Event log since the last MAIL_SHOW: event, seconds since MAIL_SHOW, inbox counts then.
local events = {}
local shownAt -- GetTime() at MAIL_SHOW

local function say(msg)
  print("|cff33ff99AzerothQuant spike|r " .. msg)
end

local function logEvent(event)
  local now = GetTime()
  if event == "MAIL_SHOW" then
    events = {}
    shownAt = now
  end
  local shown, total = GetInboxNumItems()
  events[#events + 1] = {
    event = event,
    t = shownAt and (now - shownAt) or "<no MAIL_SHOW yet>",
    shown = shown,
    total = total,
  }
end

local function dump()
  if not (MailFrame and MailFrame:IsShown()) then
    say("Open a mailbox first.")
    return
  end
  local shown, total = GetInboxNumItems()
  local mails = {}
  for i = 1, shown do
    local links = {}
    -- ATTACHMENTS_MAX_RECEIVE is the UI's own limit (12 in Classic); fall back to 16.
    for a = 1, (ATTACHMENTS_MAX_RECEIVE or 16) do
      local link = GetInboxItemLink(i, a)
      if link then
        links[#links + 1] = { slot = a, link = link }
      end
    end
    mails[i] = {
      index = i,
      header = allReturns(GetInboxHeaderInfo(i)),
      invoice = allReturns(GetInboxInvoiceInfo(i)),
      itemLinks = links,
    }
  end

  local db = AzerothQuantDB
  db.mailDumpSpike = db.mailDumpSpike or {}
  table.insert(db.mailDumpSpike, {
    dumpedAt = time(),
    dumpedAfterShow = shownAt and (GetTime() - shownAt) or nil,
    realm = GetRealmName(),
    character = table.concat({ UnitFullName("player") }, "-"),
    faction = UnitFactionGroup("player"),
    shownCount = shown,
    totalCount = total,
    events = events,
    mails = mails,
  })

  -- Chat labels assume the documented Classic return order; the saved dump is positional, so it holds either way.
  say(string.format("Inbox: %d shown / %d total. Events since MAIL_SHOW: %d.", shown, total, #events))
  for _, e in ipairs(events) do
    say(string.format("  %s at +%.2fs (%s/%s)", e.event, tonumber(e.t) or -1, tostring(e.shown), tostring(e.total)))
  end
  for _, m in ipairs(mails) do
    local h, inv = m.header, m.invoice
    say(string.format("#%d from=%s subject=%s money=%s COD=%s daysLeft=%s | invoice=%s item=%s buyer/seller=%s buyout=%s count=%s",
      m.index, tostring(h[3]), tostring(h[4]), tostring(h[5]), tostring(h[6]), tostring(h[7]),
      tostring(inv[1]), tostring(inv[2]), tostring(inv[3]), tostring(inv[5]), tostring(inv[11])))
  end
  say(string.format("Saved as dump #%d. /reload, then paste AzerothQuantDB.mailDumpSpike.", #db.mailDumpSpike))
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("MAIL_SHOW")
frame:RegisterEvent("MAIL_INBOX_UPDATE")
frame:RegisterEvent("MAIL_CLOSED")
frame:SetScript("OnEvent", function(_, event)
  logEvent(event)
end)

SLASH_AZEROTHQUANT1 = "/aq"
SlashCmdList.AZEROTHQUANT = function(msg)
  if msg:match("^%s*maildump%s*$") then
    dump()
  else
    say("Usage: /aq maildump (at an open mailbox)")
  end
end
