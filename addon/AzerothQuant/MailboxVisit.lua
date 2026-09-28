-- When to take a Mailbox Read during a mailbox visit. A Read is saved on every inbox
-- update that changed the Auction House mail, so a mail taken moments after the mailbox
-- opens is still in an earlier Read (#100). The Brain matches each Read against the one
-- before it, so a mail missing from the next Read counts as taken.
--
-- Plain Lua with no WoW API calls, so it runs under busted: Mailbox.lua passes in the
-- inbox reader, where Reads go, and the timer. See Money.lua for the namespace fallback.
local _, ns = ...
ns = ns or {}

local MailboxVisit = {}

-- An empty inbox fires no MAIL_INBOX_UPDATE (seen on the client), so read anyway this
-- long after the mailbox opened if nothing was read by then.
MailboxVisit.NO_UPDATE_SECONDS = 10

-- Equal apart from daysLeft, which ticks down between two reads of the same mail.
local function sameValue(a, b)
  if type(a) ~= "table" or type(b) ~= "table" then
    return a == b
  end
  for k, v in pairs(a) do
    if k ~= "daysLeft" and not sameValue(v, b[k]) then
      return false
    end
  end
  for k in pairs(b) do
    if k ~= "daysLeft" and a[k] == nil then
      return false
    end
  end
  return true
end

local function sameMail(a, b)
  return a.shownCount == b.shownCount and a.totalCount == b.totalCount and sameValue(a.mails, b.mails)
end

-- deps:
--   read()                  -> a Mailbox Read of the inbox as it stands (MailboxRead.build),
--                              or nil while a header is still loading
--   save(read, firstOfVisit)   stores a Read
--   after(seconds, fn)      -> a timer with :Cancel() (C_Timer.NewTimer)
function MailboxVisit.new(deps)
  local visit = {}
  local open = false
  local last -- the last Read saved this visit
  local lastReadAt -- of the last Read saved in any visit
  local timer

  local function cancel()
    if timer then
      timer:Cancel()
      timer = nil
    end
  end

  local function recordIfChanged()
    local mailboxRead = deps.read()
    -- Loading fires another MAIL_INBOX_UPDATE, which reads again.
    if mailboxRead == nil or (last and sameMail(last, mailboxRead)) then
      return
    end
    -- The Brain keeps one Read per second per Character and drops one no later than the
    -- last, and a take often lands in the same second the inbox loaded.
    if lastReadAt and mailboxRead.readAt <= lastReadAt then
      mailboxRead.readAt = lastReadAt + 1
    end
    deps.save(mailboxRead, last == nil)
    last, lastReadAt = mailboxRead, mailboxRead.readAt
  end

  function visit:show()
    open, last = true, nil
    cancel()
    timer = deps.after(MailboxVisit.NO_UPDATE_SECONDS, function()
      timer = nil
      if open and last == nil then
        recordIfChanged()
      end
    end)
  end

  -- Reading headers makes the client fire MAIL_INBOX_UPDATE again (#15 spike), which
  -- reads once more and finds nothing new, so it settles.
  function visit:inboxUpdated()
    if open then
      recordIfChanged()
    end
  end

  -- MAIL_CLOSED didn't fire in the #100 probe, so nothing may depend on it: show()
  -- starts every visit afresh.
  function visit:closed()
    open = false
    cancel()
  end

  return visit
end

ns.MailboxVisit = MailboxVisit
return MailboxVisit
