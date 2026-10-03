# Server clock for every Addon stamp

Only Scans are stamped with `GetServerTime()`. Every other Addon stamp (Character Reads, Mailbox Reads, Known Recipes, Purchase marks, Loot Alerts, the Recommendations table's "now") keeps `time()`, the PC clock.

## Why this is out of scope

There are three clocks, not two: the Addon's `time()` and the Brain's `time.time()` are the same PC clock, and `GetServerTime()` is the server's. Scans moved to the server clock (#120) because Pooled Scans come from other members' PCs and have to order on one clock. Reads never leave the player's PC.

Moving every stamp to the server clock wouldn't remove skew, only move it. Today the Scan vs Read comparisons (Purchases after the latest Scan, the newest `seen_at` for vendor prices and item info) cross clocks. After the move, the Read vs Brain comparisons would cross clocks instead: Profession cooldowns (`read_at + cooldown <= now`), Purchases that happened before now, and the Recommendations table against `generatedAt`. Those agree today.

Windows syncs the PC clock over NTP, so the skew is seconds, and every comparison that crosses clocks has minutes of slack. ADR-0026 records the split.

If a real skewed-clock bug turns up, the fix is to stamp Reads with both clocks (`readAt` plus `serverAt`) and let the Brain pick per comparison. Don't switch to one clock.

## Prior requests

- #126: "Reads and Purchase marks still stamp with time(), Scans now use GetServerTime()"
