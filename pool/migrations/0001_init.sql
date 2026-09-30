-- Member keys. Only a hash of each key is stored.
CREATE TABLE keys (
  name TEXT PRIMARY KEY,
  key_hash TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL,
  revoked_at INTEGER
);

-- The Scan index. Bodies live in R2 under scans/<id>.json.gz.
CREATE TABLE scans (
  id TEXT PRIMARY KEY,
  era TEXT NOT NULL,
  realm TEXT NOT NULL,
  faction TEXT NOT NULL,
  requested_at INTEGER NOT NULL,
  uploader TEXT NOT NULL REFERENCES keys(name),
  uploaded_at INTEGER NOT NULL,
  rolled_back INTEGER NOT NULL DEFAULT 0
);

-- One live Scan per Market and requestedAt; a rolled-back one frees its slot.
CREATE UNIQUE INDEX scans_market_time ON scans (era, realm, faction, requested_at) WHERE rolled_back = 0;
CREATE INDEX scans_rate ON scans (uploader, era, realm, faction, uploaded_at);

-- Every change to the index, in order. A cursor is the seq of the last event a Brain has seen.
CREATE TABLE events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK (kind IN ('add', 'rollback')),
  scan_id TEXT NOT NULL REFERENCES scans(id)
);
