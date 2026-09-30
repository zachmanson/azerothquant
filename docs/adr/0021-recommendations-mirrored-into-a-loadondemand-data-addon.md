# Recommendations are mirrored into a LoadOnDemand data addon

A Scan used to take two reloads to reach the table: one to save it for the Brain, then a second to read the `Recommendations.lua` the Brain wrote in between, because the client reads an addon's files once, at load (#106). A LoadOnDemand addon's files are read from disk when it's loaded, not at client start (spike, 2026-09-29), so a Load button can pick up the Brain's output without a reload. It only works once per session, though.

The Brain writes the same `Recommendations.lua` twice: into `AzerothQuant/`, read at startup as before, and into `AzerothQuant_Data/`, loaded when the player clicks Load. Moving the file there outright would leave the table empty after every reload until Load, and a Load clicked too early would leave it stale for the whole session. It would also move pruning off `ADDON_LOADED`. With the mirror, the startup path is unchanged and Load can only make the data newer. Pruning again with the newer stamps is safe, since an older stamp just deletes less.

Whether a copy is fresh comes from the stamps the file already carries (`lastCharacterRead`, `lastImported`) compared with what was saved at the last logout. A Character Read is saved on every reload, so there is always something to check. A separate generation counter would be a second source of truth for the same fact.

The Brain creates `AzerothQuant_Data` in each install (TOC and file), and it isn't in the repo: it's Brain output, not source, like TSM's AppHelper.

## Consequences

- When the Data addon is missing (the first run before a client restart), the Addon falls back to Reload, which is the old two-reload cycle.
- Load is manual (a pulsing button), never on a timer: it's one-shot, and only the player can see whether `brain watch` has finished.
