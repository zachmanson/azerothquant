# Auto-Load tries three Data slots after a reload

> Supersedes ADR-0021's Load button: the mirror stays, but the Addon loads it by itself, from one of three slots.

ADR-0021 mirrored `Recommendations.lua` into a LoadOnDemand `AzerothQuant_Data` so a Load button could pick up the Brain's import without a second reload. Load was manual and one-shot, since a LoadOnDemand addon's files are read from disk only the first time it loads in a session: clicked before the Brain was done, it locked in the stale copy until the next reload. The player had to watch a pulse and guess (#158).

The Brain now writes the same file into three LoadOnDemand slots, `AzerothQuant_Data1..3`, and the Addon tries them by itself after a reload whose startup copy is stale: slot 1 at about 20 s, slot 2 at about 45 s, slot 3 at about 90 s, stopping at the first fresh one. Three slots are three reads from disk, so three tries per reload, where one slot was one guess. The tries run on a timer whether the window is open or not, and there's no setting.

A try can't read a half-written file, since the Brain writes each slot atomically (temp file and swap), as it did the one. Freshness and keeping only a newer copy (`Freshness.isFresh`, `Freshness.covers`) are as in ADR-0021.

The try times are a guess until a warm `Import took` from `brain watch` is known. They're one constant (`LoadTries.AFTER`) to tune.

## Considered

- One slot on a later timer (say 90 s): every import waits the worst case, and a slow pass still misses.
- A slot per import (a counter in the folder name): the client only finds a new addon folder when it starts, so slots must exist before the session does.
- Polling a file: the client has no way to read a file outside of loading an addon.

## Consequences

- No Load button or `/aq load`. While tries remain the banner says the Brain is working; the first fresh try redraws the table, with a chat line if the window is closed. If all three are stale, the banner turns orange: "The Brain took longer than usual. Reload to try again." (Changed 2026-10-11, #176: see the last line.)
- The slots are Brain output, as before: setup creates all three, uninstall removes them, and both remove the old `AzerothQuant_Data`.
- When the slots are missing (the first run before a client restart), the Addon falls back to Reload once the Brain should be done, as before.
- While the Brain catches up on a long pull (#159) the Addon doesn't try: its Scans wait behind the pull.
- 2026-10-11 (#176): the Brain being off wasn't covered. A Scan counts as behind only 130 s after it was saved, so after the last try at 90 s the banner said "took longer" and never "Brain not running". Now, when all three are stale with Scans still waiting, the banner keeps saying the Brain is working until the oldest counts as behind, then says "Brain not running" (and the chat line). The Addon can't tell a slow Brain from an off one (neither has written a new copy), so "took longer" is gone: a Brain slower than the last try (90 s) also gets "not running", and Reload fixes it.
