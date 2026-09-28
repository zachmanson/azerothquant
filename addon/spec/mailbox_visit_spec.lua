local MailboxVisit = require("MailboxVisit")

local WON = { sender = "Alliance Auction House", subject = "Auction won: Rough Stone", daysLeft = 30 }
local SOLD = { sender = "Alliance Auction House", subject = "Auction successful: Linen Cloth (5)", daysLeft = 29.5 }

-- A fake mailbox: the inbox's Auction House mail, a clock, timers and the saved Reads,
-- driven through one MailboxVisit the way Mailbox.lua drives it from WoW events.
local function world()
  local w = { now = 1000, inbox = {}, timers = {}, saved = {} }
  w.visit = MailboxVisit.new({
    read = function()
      if w.loading then
        return nil
      end
      local mails = {}
      for i, m in ipairs(w.inbox) do
        mails[i] = { index = i, sender = m.sender, subject = m.subject, daysLeft = m.daysLeft }
      end
      return { readAt = w.now, shownCount = #w.inbox, totalCount = #w.inbox, mails = mails }
    end,
    save = function(read, firstOfVisit)
      table.insert(w.saved, { read = read, firstOfVisit = firstOfVisit })
    end,
    after = function(seconds, fn)
      local timer = { at = w.now + seconds, fn = fn }
      timer.Cancel = function()
        timer.cancelled = true
      end
      table.insert(w.timers, timer)
      return timer
    end,
  })
  -- Moves the clock to `to`, firing any timer due by then.
  function w.advance(to)
    for _, timer in ipairs(w.timers) do
      if not timer.cancelled and not timer.fired and timer.at <= to then
        timer.fired = true
        w.now = timer.at
        timer.fn()
      end
    end
    w.now = to
  end
  function w.subjects(i)
    local subjects = {}
    for _, m in ipairs(w.saved[i].read.mails) do
      subjects[#subjects + 1] = m.subject
    end
    return subjects
  end
  return w
end

describe("MailboxVisit", function()
  it("saves the won mail when it is taken within a second of opening the mailbox (#100)", function()
    -- Seen on the client: MAIL_SHOW with nothing loaded, the first MAIL_INBOX_UPDATE 0.3s
    -- later with headers ready, and the take 0.6s after that.
    local w = world()
    w.visit:show()
    w.inbox = { WON }
    w.visit:inboxUpdated()
    w.inbox = {}
    w.visit:inboxUpdated()
    w.visit:closed()
    w.advance(w.now + 60)

    assert.are.equal(2, #w.saved)
    assert.are.same({ "Auction won: Rough Stone" }, w.subjects(1))
    assert.are.same({}, w.subjects(2))
  end)

  it("saves the Read even when the mailbox closes right after it loads", function()
    local w = world()
    w.visit:show()
    w.inbox = { WON }
    w.visit:inboxUpdated()
    w.visit:closed()
    w.advance(w.now + 60)

    assert.are.equal(1, #w.saved)
    assert.are.same({ "Auction won: Rough Stone" }, w.subjects(1))
  end)

  it("saves no new Read when an update leaves the Auction House mail as it was", function()
    -- The inbox fires MAIL_INBOX_UPDATE several times as it loads, and daysLeft ticks down
    -- between them.
    local w = world()
    w.visit:show()
    w.inbox = { WON, SOLD }
    w.visit:inboxUpdated()
    w.inbox = { WON, { sender = SOLD.sender, subject = SOLD.subject, daysLeft = 29.4 } }
    w.visit:inboxUpdated()
    w.visit:inboxUpdated()

    assert.are.equal(1, #w.saved)
  end)

  it("saves a new Read when a mail arrives while the mailbox is open", function()
    local w = world()
    w.visit:show()
    w.inbox = { SOLD }
    w.visit:inboxUpdated()
    w.advance(w.now + 5)
    w.inbox = { SOLD, WON }
    w.visit:inboxUpdated()

    assert.are.equal(2, #w.saved)
    assert.are.same({ "Auction successful: Linen Cloth (5)", "Auction won: Rough Stone" }, w.subjects(2))
  end)

  it("gives each Read in a visit its own second, since the Brain keys Reads by readAt", function()
    local w = world()
    w.visit:show()
    w.inbox = { WON }
    w.visit:inboxUpdated()
    w.inbox = {}
    w.visit:inboxUpdated()
    w.inbox = { SOLD }
    w.visit:inboxUpdated()

    assert.are.equal(1000, w.saved[1].read.readAt)
    assert.are.equal(1001, w.saved[2].read.readAt)
    assert.are.equal(1002, w.saved[3].read.readAt)
  end)

  it("saves nothing while a header is still loading, then the Read once it has loaded", function()
    -- On the client the first update can show a mail as "Retrieving data" with no invoice.
    -- Saved like that, a mail already live in the Brain would look taken, then new again.
    local w = world()
    w.visit:show()
    w.loading = true
    w.inbox = { WON, SOLD }
    w.visit:inboxUpdated()
    w.loading = false
    w.visit:inboxUpdated()

    assert.are.equal(1, #w.saved)
    assert.is_true(w.saved[1].firstOfVisit)
    assert.are.same({ "Auction won: Rough Stone", "Auction successful: Linen Cloth (5)" }, w.subjects(1))
  end)

  it("never gives a new visit's Read a readAt at or before the last one saved", function()
    -- Bumped Reads can run a few seconds ahead of the clock, and the Brain drops a Read
    -- that isn't later than the last one it has.
    local w = world()
    w.visit:show()
    w.inbox = { WON, SOLD }
    w.visit:inboxUpdated()
    w.inbox = { SOLD }
    w.visit:inboxUpdated()
    w.inbox = {}
    w.visit:inboxUpdated()
    w.visit:closed()
    w.visit:show()
    w.visit:inboxUpdated()

    assert.are.equal(1003, w.saved[4].read.readAt)
  end)

  it("reads an inbox that fires no update once the mailbox has been open a while", function()
    -- An empty inbox fires no MAIL_INBOX_UPDATE at all (seen on the client).
    local w = world()
    w.visit:show()
    w.advance(w.now + MailboxVisit.NO_UPDATE_SECONDS)

    assert.are.equal(1, #w.saved)
    assert.are.same({}, w.subjects(1))
  end)

  it("doesn't read at the no-update fallback once an update has been read", function()
    local w = world()
    w.visit:show()
    w.inbox = { WON }
    w.visit:inboxUpdated()
    w.inbox = {}
    w.advance(w.now + MailboxVisit.NO_UPDATE_SECONDS)

    assert.are.equal(1, #w.saved)
  end)

  it("reads nothing before the mailbox opens", function()
    local w = world()
    w.inbox = { WON }
    w.visit:inboxUpdated()

    assert.are.equal(0, #w.saved)
  end)

  it("marks only the first Read of each visit as the first", function()
    local w = world()
    w.visit:show()
    w.inbox = { WON }
    w.visit:inboxUpdated()
    w.inbox = {}
    w.visit:inboxUpdated()
    w.visit:closed()
    w.advance(w.now + 5)
    w.visit:show()
    w.inbox = { SOLD }
    w.visit:inboxUpdated()

    assert.is_true(w.saved[1].firstOfVisit)
    assert.is_false(w.saved[2].firstOfVisit)
    assert.is_true(w.saved[3].firstOfVisit)
  end)

  it("saves the first Read of a new visit even when the mail is unchanged since the last", function()
    -- Each visit starts its own record of the inbox, so the Brain sees the mail was still there.
    local w = world()
    w.visit:show()
    w.inbox = { SOLD }
    w.visit:inboxUpdated()
    w.visit:closed()
    w.advance(w.now + 60)
    w.visit:show()
    w.visit:inboxUpdated()

    assert.are.equal(2, #w.saved)
  end)
end)
