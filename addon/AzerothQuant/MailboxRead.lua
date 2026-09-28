-- Shapes one Mailbox Read (the Auction House mail in a Character's inbox, taken whenever
-- it changes during a mailbox visit; see MailboxVisit.lua) into the table stored in
-- SavedVariables. Mail is kept raw; the
-- Brain turns it into Outcomes and Purchases (ADR-0005 amendment).
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for
-- the namespace fallback.
local _, ns = ...
ns = ns or {}

local MailboxRead = {}

-- Positions of the returns worth keeping, as confirmed on the client (#15 spike).
-- Left out: icons, CODAmount (COD mail is skipped), wasRead, textCreated, canReply, isGM.
local HEADER = {
  [3] = "sender",
  [4] = "subject",
  [5] = "money",
  [7] = "daysLeft",
  [8] = "itemCount",
  [10] = "wasReturned",
  [14] = "firstItemQuantity",
  [15] = "firstItemLink",
}
local INVOICE = {
  "invoiceType",
  "itemName",
  "playerName",
  "bid",
  "buyout",
  "deposit",
  "consignment",
  "moneyDelay",
  "etaHour",
  "etaMin",
  "count",
  "commerceAuction",
}

-- Auction House mail only. Horde and neutral sender names aren't confirmed, so match the
-- suffix; player names can't contain spaces, so no player (and so no COD mail) matches.
local function fromAuctionHouse(sender)
  return type(sender) == "string" and sender:sub(-#" Auction House") == " Auction House"
end

local function named(values, names, into)
  for i, name in pairs(names) do
    into[name] = values[i]
  end
  return into
end

-- One kept mail: its inbox index plus the named header and invoice fields.
local function shape(index, m)
  local mail = named(m.header, HEADER, { index = index })
  -- Cancellations have no invoice: invoiceType is nil and the rest is zeros.
  if m.invoice[1] ~= nil then
    mail.invoice = named(m.invoice, INVOICE, {})
  end
  return mail
end

-- visit: { readAt, realm, character, shownCount, totalCount }, with the counts from
-- GetInboxNumItems. shownCount < totalCount means the read is incomplete (over 50 mails).
-- mails: one per shown inbox index, { header, invoice }: every return of
-- GetInboxHeaderInfo / GetInboxInvoiceInfo, packed with n so nils keep their place.
function MailboxRead.build(visit, mails)
  local kept = {}
  local skipped = 0
  for index, m in ipairs(mails) do
    if not fromAuctionHouse(m.header[3]) then
      skipped = skipped + 1
    else
      kept[#kept + 1] = shape(index, m)
    end
  end
  return {
    readAt = visit.readAt,
    realm = visit.realm,
    character = visit.character,
    shownCount = visit.shownCount,
    totalCount = visit.totalCount,
    skippedMails = skipped,
    mails = kept,
  }
end

-- Whether any header still shows loadingSubject (RETRIEVING_DATA), the subject the
-- client shows until it has loaded a header (#100). mails as for build.
function MailboxRead.loading(mails, loadingSubject)
  for _, m in ipairs(mails) do
    if m.header[4] == loadingSubject then
      return true
    end
  end
  return false
end

ns.MailboxRead = MailboxRead
return MailboxRead
