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

## Amendment: Vendor Prices and JSON keys (#20)

Scans and Character Reads now carry `vendorPrices`, a map from itemID to copper. It is the first map in the Addon's data keyed by numbers, and JSON keys are always strings, so the archived copy reads back as `{"2589": 10}` where SavedVariables had `[2589] = 10`. Nothing is lost, and the Brain reads both shapes (and an empty map, which SavedVariables gives as a list), so an import and a rebuild give the same history. "Verbatim" means as close as JSON allows, not byte-for-byte.

## Amendment: Character Reads also carry Known Recipes (#18)

Known Recipes can only be read while that profession's window is open, so they work like the bank: a `professions` map on the Character Read, keyed by `professionID`, holding the latest read of each profession whose window was opened that session. Every Read also records which professions the Character has, since "the latest Read that has this profession" would otherwise keep a dropped profession's recipes forever. On Forever the window is backed by `C_TradeSkillUI` (the Classic `GetTradeSkill*`/`GetCraft*` calls don't exist), and the Addon keeps learned recipes only, raw: output, quantity range, every reagent slot with its type, and cooldown. The Brain doesn't parse them yet. Nothing uses them until the Craft Action, and because the Archive keeps every Read verbatim, `brain rebuild` can fill whatever table the Craft Action turns out to need, rather than guessing its shape now.

## Amendment: several Mailbox Reads per visit (#100)

One Read per visit, taken once the inbox had been quiet for 2 s, missed any mail taken in those first seconds. The Addon now saves a Read on every inbox update that changed the Auction House mail, and the Brain's matching of each Read against the one before joins them up. Two more things the Addon does to a Read, both because the Brain would otherwise misread it, not to interpret mail: it saves no Read while a header still shows the client's loading subject ("Retrieving data"), since the next update brings the loaded one; and it saves no Read equal to the last one of the visit (ignoring daysLeft), since the inbox fires several updates as it loads. The Brain keys a Read, and names its archive file, by `readAt` in whole seconds, so a Read that would share or precede the last saved one's second is given the next second instead. That is the one field the Addon doesn't record as read; it can run a few seconds ahead of the clock, well inside the 5-minute tolerance for matching arrival times.

## Amendment: Pooled Scans are stored stripped (#117)

Pooled Scans from the Scan Pool (ADR-0026) go into the Archive under `<era>/<realm>-<faction>/pool/<requestedAt>.json.gz`, exactly as downloaded. They were stripped before upload (`character`, `own`, item names, and the level and spec fields of each itemString), so for them "verbatim" means verbatim as pooled. The player's own Scans are uploaded stripped and archived locally unstripped, as before. Deleting `pool/` and running `brain rebuild` gives back a history of the player's own Scans only. A Scan's identity is still its Market and `requestedAt`: if a Pooled Scan shares a second with one already imported, the first one in wins.
