local SearchQueue = require("SearchQueue")

-- A search request as the glue queues it: key names what's searched (no two alike wait
-- at once), match what its results event carries (the itemID).
local function request(key, match)
  return { key = key, match = match or key }
end

describe("SearchQueue", function()
  it("sends nothing until the Auction House's throttle is ready", function()
    local q = SearchQueue.new()
    SearchQueue.push(q, request("hide"))

    assert.is_nil(SearchQueue.next(q, false, 0))
    assert.are.equal("hide", SearchQueue.next(q, true, 0).key)
  end)

  it("keeps one search out at a time, sending the next once its results land", function()
    local q = SearchQueue.new()
    SearchQueue.push(q, request("hide"))
    SearchQueue.push(q, request("sword"))

    assert.are.equal("hide", SearchQueue.next(q, true, 0).key)
    assert.is_nil(SearchQueue.next(q, true, 1))
    assert.is_nil(SearchQueue.landed(q, "sword")) -- someone else's results
    assert.is_nil(SearchQueue.next(q, true, 1))
    assert.are.equal("hide", SearchQueue.landed(q, "hide").key)
    assert.are.equal("sword", SearchQueue.next(q, true, 2).key)
    assert.is_nil(SearchQueue.next(q, true, 2))
  end)

  it("sends a search the player is waiting on (Post's undercut line) ahead of the checks", function()
    local q = SearchQueue.new()
    SearchQueue.push(q, request("hide"))
    SearchQueue.push(q, request("sword"))
    SearchQueue.push(q, request("cloth"), true)

    assert.are.equal("cloth", SearchQueue.next(q, true, 0).key)
  end)

  it("doesn't queue a search that's already waiting or out", function()
    local q = SearchQueue.new()
    SearchQueue.push(q, request("hide"))
    SearchQueue.next(q, true, 0)
    SearchQueue.push(q, request("hide"))
    SearchQueue.push(q, request("sword"))
    SearchQueue.push(q, request("sword"), true)
    SearchQueue.landed(q, "hide")

    assert.are.equal("sword", SearchQueue.next(q, true, 1).key)
    SearchQueue.landed(q, "sword")
    assert.is_nil(SearchQueue.next(q, true, 2))
  end)

  it("gives up on results that never land, so one lost search can't stall the rest", function()
    local q = SearchQueue.new()
    SearchQueue.push(q, request("hide"))
    SearchQueue.push(q, request("sword"))
    SearchQueue.next(q, true, 100)

    assert.is_nil(SearchQueue.next(q, true, 100 + SearchQueue.STALE - 1))
    local sent, lost = SearchQueue.next(q, true, 100 + SearchQueue.STALE)
    assert.are.equal("sword", sent.key)
    assert.are.equal("hide", lost.key) -- so the glue stops waiting on it
  end)

  it("forgets everything when cleared (the Auction House closed)", function()
    local q = SearchQueue.new()
    SearchQueue.push(q, request("hide"))
    SearchQueue.push(q, request("sword"))
    SearchQueue.next(q, true, 0)

    SearchQueue.clear(q)

    assert.is_nil(SearchQueue.landed(q, "hide"))
    assert.is_nil(SearchQueue.next(q, true, 1))
  end)
end)
