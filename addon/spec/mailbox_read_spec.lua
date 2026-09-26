local MailboxRead = require("MailboxRead")

-- What the glue layer captures per mail: every return of GetInboxHeaderInfo and
-- GetInboxInvoiceInfo, packed with their count so nils keep their positions.
local function pack(...)
  return { n = select("#", ...), ... }
end

-- Real mails from the #15 spike dump (Classic Beta PvP, Alliance).
local SOLD = {
  header = pack(nil, 134939, "Alliance Auction House", "Auction successful: Small Glimmering Shard (8)",
    2289, 0, 30, nil, false, false, true, false, false, nil, nil),
  invoice = pack("seller", "Small Glimmering Shard", nil, 2304, 8, 100, 115, 0, 0, 0, 8, false),
}

local FERMENTER = "|cnIQ2:|Hitem:273085::::::::20:1490::1::1:28:5256:::::|h[Blueprint: Fermenter]|h|r"
local CANCELLED = {
  header = pack(1001491, 134939, "Alliance Auction House", "Auction canceled: Blueprint: Fermenter",
    0, 0, 29.99739646911621, 1, false, false, true, false, false, 1, FERMENTER),
  invoice = pack(nil, nil, nil, 0, 0, 0, 0),
}

local VISIT = {
  readAt = 1790447060,
  realm = "Classic Beta PvP",
  character = "Kash-Patel",
  shownCount = 6,
  totalCount = 6,
}

describe("MailboxRead.build", function()
  it("records whose inbox was read, when, and how much of it the game showed", function()
    local read = MailboxRead.build(VISIT, {})

    assert.are.equal(1790447060, read.readAt)
    assert.are.equal("Classic Beta PvP", read.realm)
    assert.are.equal("Kash-Patel", read.character)
    assert.are.equal(6, read.shownCount)
    assert.are.equal(6, read.totalCount)
    assert.are.same({}, read.mails)
    assert.are.equal(0, read.skippedMails)
  end)

  it("keeps an Auction House mail's header and invoice fields raw, under their API names", function()
    local read = MailboxRead.build(VISIT, { SOLD })

    assert.are.same({
      index = 1,
      sender = "Alliance Auction House",
      subject = "Auction successful: Small Glimmering Shard (8)",
      money = 2289,
      daysLeft = 30,
      wasReturned = false,
      invoice = {
        invoiceType = "seller",
        itemName = "Small Glimmering Shard",
        bid = 2304,
        buyout = 8, -- equals the count in every spike mail; kept raw for the Brain to judge
        deposit = 100,
        consignment = 115,
        moneyDelay = 0,
        etaHour = 0,
        etaMin = 0,
        count = 8,
        commerceAuction = false,
      },
    }, read.mails[1])
  end)

  it("leaves out the invoice when the mail has none, and keeps the attached item", function()
    -- Cancellations come with no invoice; the returned stack is only in the attachment.
    local read = MailboxRead.build(VISIT, { CANCELLED })

    assert.are.same({
      index = 1,
      sender = "Alliance Auction House",
      subject = "Auction canceled: Blueprint: Fermenter",
      money = 0,
      daysLeft = 29.99739646911621,
      itemCount = 1,
      wasReturned = false,
      firstItemQuantity = 1,
      firstItemLink = FERMENTER,
    }, read.mails[1])
  end)

  it("skips player and COD mail, counts what it skipped, and keeps inbox positions", function()
    local letter = { header = pack(nil, 134939, "Someguy", "hi", 0, 0, 12.5), invoice = pack() }
    local cod = { header = pack(nil, 134939, "Someguy", "your mats", 0, 5000, 3, 1), invoice = pack() }
    -- Horde and neutral sender names aren't confirmed yet, so any "... Auction House" counts.
    -- (Player names can't contain spaces, so a player can't send as one.)
    local neutral = {
      header = pack(nil, 134939, "Blackwater Auction House", "Auction successful: Tigerseye", 205, 0, 30),
      invoice = pack("seller", "Tigerseye", nil, 110, 1, 100, 5, 0, 0, 0, 1, false),
    }

    local read = MailboxRead.build(VISIT, { letter, SOLD, cod, neutral })

    assert.are.equal(2, read.skippedMails)
    assert.are.equal(2, #read.mails)
    assert.are.equal(2, read.mails[1].index)
    assert.are.equal("Blackwater Auction House", read.mails[2].sender)
    assert.are.equal(4, read.mails[2].index)
  end)
end)
