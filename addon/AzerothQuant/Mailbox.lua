-- WoW glue for Mailbox Reads: once per mailbox visit, records the Auction House mail
-- in the inbox to AzerothQuantDB.mailboxReads. All shaping happens in MailboxRead.lua;
-- this file only talks to the WoW API. On load it also deletes the Reads the Brain has
-- imported (Prune.lua).
--
-- Read-only (ADR-0003): only GetInboxNumItems, GetInboxHeaderInfo and
-- GetInboxInvoiceInfo. Never GetInboxText (it marks mail read), never CheckInbox, and
-- nothing that takes, returns, deletes or sends mail.
local _, ns = ...
local MailboxRead = ns.MailboxRead
local Prune = ns.Prune

-- MAIL_INBOX_UPDATE fires a few times as the inbox loads (twice within 0.4s in the
-- spike). Read once it has been quiet this long.
local QUIET_SECONDS = 2
-- If no update comes at all, read anyway this long after the mailbox opened.
local NO_UPDATE_SECONDS = 10

local db
local visiting = false -- the mailbox is open
local readThisVisit = false
local timer

local function say(msg)
  print("|cff33ff99AzerothQuant|r " .. msg)
end

local function cancel()
  if timer then
    timer:Cancel()
    timer = nil
  end
end

local function pack(...)
  return { n = select("#", ...), ... }
end

local function read()
  timer = nil
  if not visiting or readThisVisit then
    return
  end
  -- Reading headers makes the client fire MAIL_INBOX_UPDATE again (spike): mark the
  -- visit done first so that doesn't start another read.
  readThisVisit = true
  local shown, total = GetInboxNumItems()
  local mails = {}
  for i = 1, shown do
    mails[i] = { header = pack(GetInboxHeaderInfo(i)), invoice = pack(GetInboxInvoiceInfo(i)) }
  end
  local mailboxRead = MailboxRead.build({
    readAt = time(),
    realm = GetRealmName(),
    character = table.concat({ UnitFullName("player") }, "-"),
    shownCount = shown,
    totalCount = total,
  }, mails)
  table.insert(db.mailboxReads, mailboxRead)
  if #mailboxRead.mails > 0 then
    say(string.format("Mailbox Read saved: %d Auction House mails.", #mailboxRead.mails))
  end
  if total > shown then
    say(string.format("Only %d of %d mails are visible; take some and reopen the mailbox to see the rest.", shown, total))
  end
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("MAIL_SHOW")
frame:RegisterEvent("MAIL_INBOX_UPDATE")
frame:RegisterEvent("MAIL_CLOSED")
frame:SetScript("OnEvent", function(_, event, arg1)
  if event == "ADDON_LOADED" then
    if arg1 == "AzerothQuant" then
      AzerothQuantDB = AzerothQuantDB or {}
      db = AzerothQuantDB
      db.mailboxReads = db.mailboxReads or {}
      -- Recommendations.lua has loaded by now (it's in the TOC), as has SavedVariables.
      local pruned = Prune.importedMailboxReads(db.mailboxReads, AzerothQuantRecommendations)
      if pruned > 0 then
        say(string.format("Deleted %d Mailbox Reads the Brain has imported.", pruned))
      end
    end
  elseif event == "MAIL_SHOW" then
    visiting, readThisVisit = true, false
    cancel()
    timer = C_Timer.NewTimer(NO_UPDATE_SECONDS, read)
  elseif event == "MAIL_INBOX_UPDATE" then
    if visiting and not readThisVisit then
      cancel()
      timer = C_Timer.NewTimer(QUIET_SECONDS, read)
    end
  elseif event == "MAIL_CLOSED" then
    visiting = false
    cancel()
  end
end)
