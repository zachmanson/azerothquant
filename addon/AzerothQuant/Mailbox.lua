-- WoW glue for Mailbox Reads: records the Auction House mail in the inbox to
-- AzerothQuantDB.mailboxReads whenever it changes during a mailbox visit. Shaping is in
-- MailboxRead.lua and when to read in MailboxVisit.lua; this file only talks to the WoW
-- API. On load it also deletes the Reads the Brain has imported (Prune.lua).
--
-- Read-only (ADR-0003): only GetInboxNumItems, GetInboxHeaderInfo and
-- GetInboxInvoiceInfo. Never GetInboxText (it marks mail read), never CheckInbox, and
-- nothing that takes, returns, deletes or sends mail.
local _, ns = ...
local MailboxRead = ns.MailboxRead
local MailboxVisit = ns.MailboxVisit
local Prune = ns.Prune
local Chat = ns.Chat

local db

local function pack(...)
  return { n = select("#", ...), ... }
end

-- The subject a header shows until the client has loaded it (seen in #100).
local LOADING_SUBJECT = RETRIEVING_DATA or "Retrieving data"

-- The inbox's Auction House mail as it stands now, or nil while a header is loading.
local function readInbox()
  local shown, total = GetInboxNumItems()
  local mails = {}
  for i = 1, shown do
    mails[i] = { header = pack(GetInboxHeaderInfo(i)), invoice = pack(GetInboxInvoiceInfo(i)) }
  end
  if MailboxRead.loading(mails, LOADING_SUBJECT) then
    return nil
  end
  return MailboxRead.build({
    readAt = time(),
    realm = GetRealmName(),
    character = table.concat({ UnitFullName("player") }, "-"),
    shownCount = shown,
    totalCount = total,
  }, mails)
end

local function save(mailboxRead, firstOfVisit)
  table.insert(db.mailboxReads, mailboxRead)
  if #mailboxRead.mails > 0 then
    Chat.debug(string.format("Mailbox Read saved: %d Auction House mails.", #mailboxRead.mails))
  end
  if firstOfVisit and mailboxRead.totalCount > mailboxRead.shownCount then
    Chat.say(string.format(
      "Only %d of %d mails are visible; take some and reopen the mailbox to see the rest.",
      mailboxRead.shownCount,
      mailboxRead.totalCount
    ))
  end
end

local visit = MailboxVisit.new({ read = readInbox, save = save, after = C_Timer.NewTimer })

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
      db.mailDumpSpike = nil -- left by the removed #15 spike
      db.mailboxReads = db.mailboxReads or {}
      -- Recommendations.lua has loaded by now (it's in the TOC), as has SavedVariables.
      local pruned = Prune.importedMailboxReads(db.mailboxReads, AzerothQuantRecommendations)
      if pruned > 0 then
        Chat.debug(string.format("Deleted %d Mailbox Reads the Brain has imported.", pruned))
      end
    end
  elseif event == "MAIL_SHOW" then
    visit:show()
  elseif event == "MAIL_INBOX_UPDATE" then
    visit:inboxUpdated()
  elseif event == "MAIL_CLOSED" then
    visit:closed()
  end
end)
