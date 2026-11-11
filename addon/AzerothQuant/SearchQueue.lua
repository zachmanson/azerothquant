-- The Addon's Auction House searches, one at a time and only when the AH's throttle takes
-- another (#177, ADR-0044). A search sent while throttled is dropped, and with one out at
-- a time its results can't be mistaken for another's. The glue in RecommendationFrame.lua
-- sends what next() hands it and reports results with landed().
--
-- Plain Lua with no WoW API calls, so it runs under busted. See Money.lua for the
-- namespace fallback.
local _, ns = ...
ns = ns or {}

local SearchQueue = {}

-- Seconds after which results that haven't landed are given up on.
SearchQueue.STALE = 10

function SearchQueue.new()
  return { waiting = {}, out = nil }
end

-- Queues a request { key, match, ... }: key names what's searched, match what its
-- results event carries. One the player waits on (urgent) goes first. A key already out
-- isn't queued again, since its results are on the way; one already waiting stays where
-- it is unless urgent moves it up.
function SearchQueue.push(q, request, urgent)
  if q.out and q.out.key == request.key then
    return
  end
  for i, waiting in ipairs(q.waiting) do
    if waiting.key == request.key then
      if not urgent then
        return
      end
      table.remove(q.waiting, i)
      break
    end
  end
  table.insert(q.waiting, urgent and 1 or #q.waiting + 1, request)
end

-- Drops everything, out or waiting (the AH closed).
function SearchQueue.clear(q)
  q.waiting, q.out = {}, nil
end

-- The request to send now, or nil: none while one is out or the throttle isn't ready
-- (ready is C_AuctionHouse.IsThrottledMessageSystemReady()). now is in seconds. The
-- second value is the request given up on this call (STALE seconds out), or nil.
function SearchQueue.next(q, ready, now)
  local lost
  if q.out and now - q.sentAt >= SearchQueue.STALE then
    lost, q.out = q.out, nil
  end
  if q.out or not ready or #q.waiting == 0 then
    return nil, lost
  end
  q.out = table.remove(q.waiting, 1)
  q.sentAt = now
  return q.out, lost
end

-- Results carrying match landed: the request out, if they're its, which frees the queue.
function SearchQueue.landed(q, match)
  local out = q.out
  if out and out.match == match then
    q.out = nil
    return out
  end
  return nil
end

ns.SearchQueue = SearchQueue
return SearchQueue
