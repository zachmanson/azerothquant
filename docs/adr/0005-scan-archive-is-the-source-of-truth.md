# Keep every Scan verbatim in a Scan Archive; the history database is rebuildable

ADR-0002 kept raw Listing lifetimes so history could be recomputed under new formulas, but the lifetimes are already an interpretation: which Listing in one Scan is the same one in the next, and what counts as a Partial Sale or a Repost, are decided once at import. The Addon then prunes the Scan, so nothing could ever be re-matched. We now write every Scan, exactly as the Addon recorded it, to a Scan Archive (one gzipped JSON file per Scan under `<era>/<realm>-<faction>/<requestedAt>.json.gz`) before importing it, and a Scan whose archive write fails is not imported, so the Addon keeps it and the Brain retries. The history database becomes a working set that `brain rebuild` recreates from the archive, and the 60-day compaction from ADR-0002 is dropped: the database is estimated at about 1 GB a year, and we revisit only if it gets near that. The archive also keeps the door open to learned models that use the formulas as features, since every past Scan can be re-featurized.

## Considered Options

- Parquet instead of gzipped JSON: friendlier to data tools, but adds a large dependency to a Brain that has none, and converting later is a short one-off script.
- Archive only the normalized rows the Brain used: smaller, but bakes today's parsing into the archive, including throwing away rows the Brain can't read yet.
- Keep the 60-day compaction because the archive can restore anything compacted: saves disk nobody needs yet, for code nobody has written.

## Consequences

- The archive is the one thing that can't be recreated, so it lives in a configurable folder (`archive_dir`) that can point at a synced or backed-up drive. It is never committed.
- Archive files are never overwritten. A Scan's Market and `requestedAt` are its identity, so importing the same file again is a no-op.
- A Scan the Addon wrote without a readable Market or `requestedAt` can't be named, so it isn't archived or imported and stays in SavedVariables.
- A Scan rejected at import for being older than the latest one in its Market is still archived, so a rebuild includes it in time order.
- Scans imported before this ADR (two Beta smoke-test Scans) are not in the archive.

## Amendment: the Archive also holds Mailbox Reads (#15)

The Addon now also records Mailbox Reads: the headers and invoices of the Auction House mail in a Character's inbox, from which the Brain derives Outcomes and Purchases. They are archived under the same rules (verbatim, never overwritten, archive before import, prune only what was archived), so the Scan Archive is now just the Archive. They go in the same Archive, not a second one, so there is still exactly one thing to back up. Mail is recorded raw and interpreted in the Brain for the same reason Scans are: sender-to-Market mapping, subject parsing and de-duplicating the same mail seen on several visits can then be fixed and replayed with `brain rebuild`. The one filter the Addon applies (Auction House mail only) is made visible by counting what it skipped.

## Amendment: the Archive also holds Character Reads (#16)

The Addon now also records a Character Read on every logout and `/reload`: the Character's gold and faction, its bags, and its bank if it was opened that session. These go in the Archive under the same rules, at `<era>/character/<realm>/<character>/<readAt>.json.gz`, and every Read is kept rather than only the latest. "The latest Read per Character" (what Holdings and pooled gold use) is then just a query, and the history of what was in the bags is kept for later. That history is the only record of items that leave without mail (vendored, disenchanted, crafted away), which future Lot work will need. Items are stored as raw links, so the Brain derives Item Keys from them the same way it does for Scans and mail, and a rebuild can re-derive them.
