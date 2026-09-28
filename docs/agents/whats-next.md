2026-09-28 (later 3): #67 BUILT on branch claude/zen-mccarthy-xaqoze (not on main yet, issue still open). Held units take the Sale Horizon before a Flip to Sell: `_flips` room = `_flip_room` minus the Item Key's unbound held units. `_Valuer.flips(under, unbound)` sizes the Flips; `recommend` sizes them twice, once with the raw Holdings (the Craft Actions value outputs after those) and again with `crafting.after`. `_exit_value` (Grades, held-at-writing) passes `{item_key: units}`, so Best Exit Value follows the same rule (ADR-0010: one definition). CONTEXT.md **Sale Horizon** says so. Tests that held and Flipped the same Item Key in one run now use a second `other_db` fixture; the #64 best-exit test holds 4 instead of 10. User to do: merge to main, close #67, restart `brain watch`.

Next, in order (none need the game):
1. #73, 2. #75, 3. #71, 4. #66 (low priority). /code-review + commit after each.
2. Then needs-info: #33, #19, #38, #44, #45, #15, #14, and triage #78.

2026-09-28 (later 2): #69 DONE (commit 71c5b47, on main, closed). Holdings rows and `bound` are now built from `_Crafting.left(shopping)`: the held units after the Craft Actions AND the Flips to Craft the Shopping List actually buys (read from each Shopping List Craft row's `uses`). The review caught that subtracting inside `_flips_to_craft` was wrong: `_shopping_list` can cut a Flip to Craft for gold, and its held reagents then vanished from both lists (test: 100 Ore to Vendor takes the 1 silver). `hold_buys` and `outlets` still use `crafting.after` (from before the Flips; Flips never touch Prediction keys or take held outputs). ADR-0009 amended, CONTEXT.md **Holdings** says used units show only on the craft's row. No Addon change. User to do: restart `brain watch` after pulling.

Next, in order (none need the game):
1. #67, 2. #73, 3. #75, 4. #71, 5. #66 (low priority). /code-review + commit after each.
2. Then needs-info: #33, #19, #38, #44, #45, #15, #14, and triage #78.

2026-09-28 (later): TRIAGED #66/#67/#69/#71/#73/#75/#76/#77. Specs are comments on each issue. ready-for-agent: #69 (Holdings from what's left after Flips to Craft), #75 (structured `blocked` reason, Addon renders the name), #67 (Flip to Sell room minus unbound held units: held units first), #73 (`non_stacking_effort_copper`, default 500, charged per unit bought + per unit posted on non-stacking Item Keys; Flips to Sell/Craft, Vendor buys only on the buy), #71 (`brain watch` logs import time; Addon pulses Reload + one chat line `RELOAD_READY_AFTER` = 10 s after a load with unimported Scans), #66 (freeze Grades + held-at-writing costs in a Brain-owned `grades.toml` next to predictions.toml, never overwritten; not SQLite, because ADR-0005 rebuilds the DB). needs-info: #76 (Disenchant, parked until #33, needs /research on DE tables) and #77 (chain panel, "Blocked by: #33, #76" line in the body). Filed #78 (AH deposits aren't in the Flip margin at all), needs-triage.

The in-game checks parked in the entry below still stand.

Next, in order (none need the game):
1. #69 build (tdd), 2. #67, 3. #73, 4. #75, 5. #71, 6. #66 (low priority: no Predictions yet). /code-review + commit after each.
2. Then needs-info: #33, #19, #38, #44, #45, #15, #14, and triage #78.

2026-09-28: #50 DONE (commits 3608c1e + review fixes, closed). Holdings Sell/Vendor rows carry `paid`, `paidUnits`, `roi`, `roiHint` (Recommendations.lua) when some held units came from open Purchase Lots not tied to a Prediction, newest Lots first. Held units = the Item Key's non-Craft Holdings rows (`recommend.held_units`; the Addon's `RecommendationTable.heldUnits` mirrors it), so crafted output counts in "of M". A row with no price gets no Paid at all. `roi_hint` (config.toml, default 0.20). CLI: ROI column like `+89.8% * on 2 of 3`. Addon: sortable ROI column (7th Holdings column, width 80), `roiLines` shared by row and item tooltips; "nets" is rebuilt as paid x (1 + roi), so it can be 1c off. The hint star is the raid-target star texture tinted green through the |T escape's vertex colour, not a ★ glyph (the game fonts may lack it): CHECK IN GAME that it shows and is green. CONTEXT.md has **Paid**, ADR-0007 amended. Not done: `_market_lots` now runs twice per Market (once for Hold costs with active Predictions, once for ROI with all of them); fine for now, fold together if `recommend` gets slow.

Cloud sessions: the SessionStart hook's `pip install -e brain[dev]` fails on the container's Python 3.11 (needs >= 3.12). Worked around with `uv venv -p 3.12 .venv` + `uv pip install -e ".[dev]"`, then `LUA=lua5.1 ../.venv/bin/python -m pytest -q` from `brain/` and `busted` from `addon/`. The hook should do that instead.

Parked until the user is back at the PC (they're away; don't ask for in-game checks before then):
- Restart `brain watch` (stop all 3 brain.exe/python processes), then /reload.
- #50: on an item bought on the AH, check the Holdings ROI cell (green/red), that the hint star shows and is green, and the row + item tooltip lines.
- #49 (still unchecked in game): Craft Note cells `on <Character>, N reagents` and the Use/Buy tooltip lines.

Next, in order (none of these need the game):
1. Triage #66/#67/#69/#71/#73/#75/#76/#77, then needs-info: #33, #19, #38, #44, #45, #15, #14.

2026-09-27 (late night 4): #50 GRILLED. Spec posted as a comment, labelled ready-for-agent. ROI on Holdings Sell/Vendor rows: Paid = held units costed by the NEWEST open non-Prediction Purchase Lots (loot/craft uncosted, partly costed rows OK "on 5 of 20"); ROI = (exit after cut - Paid)/Paid, per row, with split rows sharing Paid. Hint = Sell and ROI >= `roi_hint` (0.20). Brain writes paid/paidUnits/roi/roiHint, CLI gets an ROI column. Addon: sortable ROI column (green/red, star on hint) + tooltip lines. CONTEXT.md gets Paid, amend ADR-0007. Existing code to reuse: `_market_lots` / `_lot_costs` in recommend.py (Prediction-only today).

Next, in order:
1. #50 build (tdd), then triage #66/#67/#69/#71/#73/#75/#76/#77, then needs-info: #33, #19, #38, #44, #45, #15, #14.

2026-09-27 (late night 3): #49 DONE (commit a1534bb, closed). Every Craft row (blocked ones too) has `character`, and made ones have `uses` (held units only). Addon: Note cell `on <Character>, N reagents` (N = distinct across uses+buys), Use lines then Buy lines in the row tooltip and the item tooltip. `RecommendationTable.crafter` is gone (read `r.character`); `RecommendationTable.reagentLines(r, nameOf)` is shared by both tooltips, and `TooltipLines.forLink` now takes `nameOf` as a 5th arg (Tooltip.lua backs it with C_Item.GetItemInfo). A Craft row with no `uses` (blocked, quantity 0) keeps its note. ADR-0009 amended. Checked on the real Recommendations.lua: Thread shows as `Use 50` + `Buy 46` on one Flip to Craft.

User to do: restart `brain watch` (stop all 3 brain.exe/python processes) since the Brain changed, then /reload in game to see the new Note cells and tooltips.

Next, in order:
1. #50 grill, triage #66/#67/#69/#71/#73/#75/#76/#77, then needs-info: #33, #19, #38, #44, #45, #15, #14.

2026-09-27 (late night 2): #49 GRILLED. Spec posted as a comment, labelled ready-for-agent. Every Craft row gets structured `character` + `uses` (held units only, used - bought); the note stays for the CLI. Addon: Note cell `on <Character>, N reagents`, Use lines then Buy lines in row + item tooltips, crafter() reads r.character (no note-parsing fallback). Amend ADR-0009. Filed #75 (blocked Craft rows name reagent by ID), #76 (Disenchant as an exit/chain step), #77 (click a Craft row to see its chain as a visual panel; user wants more visuals, needs ui-ux-pro-max).

Next, in order:
1. #49 build (tdd), then #50 grill, triage #66/#67/#69/#71/#73/#75/#76/#77, then needs-info: #33, #19, #38, #44, #45, #15, #14.

2026-09-27 (late night): #74 DONE (commit ccfbdaf, closed, replay numbers on the issue). A Probable Sale now has to be <= 1.2x the LOWER of the Fair Values at its last-seen and gone-at Scans (last-seen only if the Item Key sold out). ADR-0004 + CONTEXT.md updated. Replay at now=1790537588: 250366 went 3 -> 2 Sale Events, held Sell 14s99c -> 1s00c. 264038 dropped off the Shopping List (3g Flip); nobody has checked why yet. brain watch was NOT restarted (the auto-mode classifier blocked stopping it): the user has to stop all 3 brain.exe/python processes and start `brain watch` again.

Gotcha from #74: a dict comprehension like `{at: f(at) for d in xs for at in (...)}` calls f once per item, not once per key. Build the set of keys first (the replay went from 20s to 5+ min before the fix). Test fixtures: cheap Listings in the Scan a sale went missing in now reject that sale, so to set up "cheap supply now", put it in a later Scan after a gap > 1h (not an Observation Window).

Next, in order:
1. #49 grill, #50 grill, triage #66/#67/#69/#71/#73, then needs-info: #33, #19, #38, #44, #45, #15, #14.

2026-09-27 (late): #72 DONE (commit 98e03ed, closed, numbers posted on the issue). A Sale Event is now one Item Key's Partial + Probable Sales in one Observation Window (size = total units, price = dearest). SaleEvent has no own/kind now. ADR-0012 + CONTEXT.md updated. Replay at now=1790537588: 250366 went 117 -> 3 Sale Events, Flip room 701 -> 274. Only the Sales column changed in `brain recommend`; the buy-90 row can't be replayed (Holdings/gold are today's). Flip room 274 is still > 90, so the remaining cause is the 699/day Sell Rate from the late-relist cancel: that's #74.

Replay recipe (worked well): `git worktree add -f <scratch>/before HEAD`, then from `brain/` run a scratch script with `PYTHONPATH=<scratch>/before/brain/src` (it beats the editable install). The script monkeypatches `scan_times` in brain.history, brain.fair_value, brain.observation, brain.recommend to drop Scans after NOW, then calls `cli.main()` with argv `["brain","recommend"]`. `load_config` needs `Path("config.toml")`.

2026-09-27 (night): #74 GRILLED. The spec is posted as a comment on the issue, which is labelled ready-for-agent. Decision: a Probable Sale must be <= 1.2x the LOWER of two Fair Values, the one at its last-seen Scan and the one at its gone-at Scan. With no supply at gone-at, use last-seen only. Repost lookahead was REJECTED: a placebo test showed matching stacks turn up in the Scan before a Disappearance as often as after (~40%), so it's mostly coincidence. Cost of the fix: 1.4% of Probable Sale units, 61 Sale Events.

Earlier (#48, commit 6955950): the Scan button pulses while it's enabled. Filed #71 (make it obvious when the second reload is ready; the Addon can only guess from a timer). #73: price the hassle of many non-stacking units. Way-later idea (user said don't file until the main code is done and working): exploit the AH Sell screen prefilling the cheapest-any-suffix price, e.g. a view of suffix items whose cheapest-any-suffix price sits far below that suffix's Sale Events, or a bait-listing experiment on expensive suffix items (not worth it on ~9s items). To look at later (not filed): a fresh Scan showed White Linen Shirt as both Craft 19 and Buy 1. Probably a Flip to Craft plus a Flip to Sell, but check it's not a double count like #69.

Market note: by Scan 1790550331, Recipe: Minor Cleric's Elixir had crashed to 5-15s (the flipper dumping), so today's recommendation won't show the bug. Replay at the old `now`.

Earlier (#70, ADR-0011): the Shopping List buys each Flip to Sell whole (`_FlipToSell`), or nothing.

Earlier (#68, ADR-0010): Post at is priced after only what the Shopping List buys. Item names: the Beta client saves links with empty names, so look them up with the Wowhead tooltip API (nether.wowhead.com/tooltip/item/<id>?dataEnv=4) or read the user's screenshot of the table. 250366 is Recipe: Minor Cleric's Elixir (the in-game table names it; Wowhead doesn't have it).

Open: #69 (a held reagent used by a Flip to Craft also shows as a Holdings row, a double count).

In-game checks: the user wants item NAMES, never raw IDs, with one concrete step at a time (what to type or search, and what number to expect). Reading their screenshots works better than long instructions.

Gotchas: the in-game AH Sell screen lumps every random suffix of an item together (Willow Belt showed "144 Available", all suffixes, prefilled 9s), while AQ keys by suffix. Not a bug (checked 2026-09-27); the player must type Post at by hand. `brain.exe watch` shows as 3 processes (brain.exe -> python -> python, the venv launcher), which is ONE watcher. Stop all three to restart. NEVER use `git stash -- <paths>` on this Z: drive: a stash push/pop left the whole index as "deleted + untracked" (fixed with `git reset`, working tree was fine). To compare before/after output, use `git worktree` or copy files instead. In Bash, never write `cat > file` without a heredoc (it waits on stdin until timeout). The Beta client runs the modern UI: CharacterFrameTabButtonTemplate, WhoFrameColumnHeaderTemplate and SetPortraitToTexture are missing. The chat box cuts /run input at 255 chars, so keep probes short. New Scans reach the table only after a reload (flushes SavedVariables), then `brain watch` or `brain import` (rewrites Recommendations.lua), then a second reload. Run the Brain from `brain/` with `../.venv/Scripts/brain.exe import`. Always restart `brain watch` after Brain commits (a stale watcher writes old-code output). PC-check screenshots land in `Z:\Battle.net\World of Warcraft\_classic_beta_\Screenshots` and I can read them directly. The Beta client has no global GetItemInfo, so /run probes need C_Item.GetItemInfo. GetMerchantItemInfo doesn't exist on this client either (C_MerchantFrame.GetItemInfo does). WoW's Lua sandbox has no `os`/`io`, and busted runs plain Lua, so it won't catch those. Spec pattern: nil out `_G.os` and set `_G.date`. The addon folder is symlinked into WoW, so `/reload` picks up edits to existing files, but new files and .toc changes need a client restart. When editing through a Bash heredoc (Python or otherwise), `\\` gets collapsed (including `\\n` in Python strings), so use the Edit tool for anything with backslashes. Merchant Costs are held in memory and written at logout/reload, so after a code change it takes reload -> open merchant -> reload to see new output. For quick real-data diagnostics, monkeypatch `brain.recommend` functions in a scratch script and call `brain.cli.main()` with argv `["brain","recommend"]`.

Local tooling: busted is at repo-root `.lua/`. From Bash in `addon/`: `../.lua/bin/busted.bat` (PowerShell: `& ..\.lua\bin\busted.bat`). Syntax-check with `../.lua/bin/luac.exe -p`. Pytest: from `brain/`, `$env:LUA = "..\.lua\bin\lua.exe"; ..\.venv\Scripts\python -m pytest` (Bash: `LUA=../.lua/bin/lua.exe ../.venv/Scripts/python -m pytest -q`), then `ruff check` + `ruff format`. Don't commit `addon/AzerothQuant/Recommendations.lua` (the Brain writes it). PowerShell mangles `gh ... --body` with quotes, so use `--body-file`.
