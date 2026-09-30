2026-09-30 (later 41): Built #110 slice 2 (1715615). `_row` writes `roomFromBeta = true` on a Prediction buy whose `BetaRoom.from_beta > 0` (not 0 or negative), and `RecommendationTable` `details()` adds "Room partly from Beta" to its tooltip. Both sides have tests: test_recommendations.py (real Lua read) and recommendation_table_spec.lua (the tooltip lines are built there, so the frame only shows them). The review found that a merged Prediction row can drop the flag when its tiers disagree on the sign of from_beta. Filed as #111 (needs-triage). #110 stays open until the Nov 18 look-back.

Next, in order (grill first where not ready-for-agent):
1. #76, #55, #81, then #89, #54, #44, #61, #14, #19, #10, #82. Triage #111 before ~Nov 6, when the weight may go on.
2. When at the PC: run the #85 checks (#97 slice 1, #39 throttle probe, #97 slice 2 buy-event probe). Optionally glance at a "Room partly from Beta" tooltip once w > 0. Then grill #39 using the probe results.
3. On dates: Nov 4, #91's list. ~Nov 6: run `brain recommend --beta-ratios` for #91's Item Keys, and set `beta_sell_rate_weight = 0.5` if they're close to 1. Nov 18: look back and close #110.

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. This PC has no `lua` binary, so the Brain's `lua` fixture tests skip silently. To run them, point `LUA` at a shim: a .bat that runs a Python script, which runs `-e <script>` on `lupa.lua51` and prints with tabs. `python scripts/busted.py` runs the addon specs.

2026-09-30 (later 40): Built #110 slice 1 (7c94159). New `brain/src/brain/beta_sell_rate.py`: `beta_ratios` (Beta/Live Fair Value per active Prediction Item Key, Live Markets only, within `beta_column_days` of the first Scan) and `beta_sell_rates` (all of Beta's history, only when `beta_sell_rate_weight` > 0). `_hold_buys` → `_demand_at`/`_room_at` take the `BetaSellRate` for a Prediction buy only. Beta's hours count even when none of its Sale Events are at the price, so a quiet Beta lowers the room. Prediction buy rows carry `beta_room` (`BetaRoom`: post_at, room, from_beta; from_beta can be negative). There's a CLI ratio line (when w > 0 or with `brain recommend --beta-ratios`), `--why-not ITEM_KEY` for a Prediction buy, and a replay ablation `Brain without Beta Sell Rate` that runs only while w > 0. Docs: ADR-0024, CONTEXT.md **Beta Sell Rate** and the Era exception, and an ADR-0015 note.

Next, in order (grill first where not ready-for-agent):
1. #110 slice 2 (Addon): write `beta_room` into Recommendations.lua (`recommendations.py` `_row`; flag it when `from_beta > 0`), and add a "room partly from Beta" line to the Prediction row tooltip in RecommendationFrame.lua. RecommendationFrame has no busted seam, so the tooltip needs an in-game check (#85, using a Beta Market test row). The Brain side is testable in test_recommendations.py.
2. #76, #55, #81, then #89, #54, #44, #61, #14, #19, #10, #82
3. When at the PC: run the #85 checks (#97 slice 1, #39 throttle probe, #97 slice 2 buy-event probe). Then grill #39 using the probe results.
4. On dates: Nov 4, #91's list. ~Nov 6: run `brain recommend --beta-ratios` for #91's Item Keys, and set `beta_sell_rate_weight = 0.5` if they're close to 1. Nov 18: look back and close #110.

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. `beta_ratios` runs in every Live `recommend_market` call during the first 14 days, even at w = 0 (it's cheap, just two cached Fair Value lookups). `beta_sell_rates` recomputes Beta's whole-history Sell Rate for each replayed Scan, which could be slow if a replay covers Live's first 14 days with w > 0. The review also noted, but I didn't fix: `beta_ratios` repeats `beta_prior`'s window/Beta Market gate, a possible shared helper.

2026-09-30 (later 39): Grilled #110. The spec is on the issue (comment 5912789542), and it's ready-for-agent. The Beta Sell Rate feeds only a Prediction buy's Max Loss room, behind `beta_sell_rate_weight` (default 0.0, off). It borrows all of Beta's Sale Events and window hours, each weighted w, and counts a Beta Sale Event when its price is at or above `post_at × Beta FV / Live FV`. It stops 14 days after Live's first Scan. There's a CLI ratio line, `--why-not`, an Addon tooltip marker, and a replay ablation row when w > 0. It needs ADR-0024 and CONTEXT.md edits (Era exception, new term **Beta Sell Rate**). Two slices, both before Nov 4.

Next, in order (grill first where not ready-for-agent):
1. #110 slice 1 (Brain): /tdd. Then slice 2 (Addon tooltip).
2. #76, #55, #81, then #89, #54, #44, #61, #14, #19, #10, #82
3. When at the PC: run the #85 checks (#97 slice 1, #39 throttle probe, #97 slice 2 buy-event probe). Then grill #39 using the probe results.
4. On dates: Nov 4 #91's list. ~Nov 6: read #110's ratio line for #91's Item Keys and set `beta_sell_rate_weight = 0.5` if they're close. Nov 18: look back and close #110.

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. The Max Loss room is `_room_at` inside `_hold_buys` (recommend.py). Only that path borrows; Flips must not. Sibling pooling (ADR-0022) is the pattern for weighted events counting toward `flip_min_sale_events`.

2026-09-30 (later 38): Tried to start #39, but it has no spec (only the two-line body, labelled ready-for-human + later). Posted the #97 slice 1 check and a #39 throttle probe on #85 (comment 5912630536). Both wait on the PC.

Next, in order (grill first where not ready-for-agent):
1. #110 Beta Prior as an engine nudge: grill before Nov 4
2. #76, #55, #81, then #89, #54, #44, #61, #14, #19, #10, #82
3. When at the PC: run the #85 checks (#97 slice 1, #39 throttle probe, #97 slice 2 buy-event probe). Then grill #39 using the probe results.

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. #39 isn't buildable until the throttle probe runs and it gets grilled. `python scripts/busted.py` runs the addon specs.

2026-09-30 (later 37): Built #97 slice 1 (8976314): right-click toggles a buy-side row's Bought mark. New `BoughtMarks.lua` (toggle, forMarket clearing by `entry.asOf`, spent, goldLeft) has busted specs, and `RecommendationTable.build` takes `marks, gold`. Bought rows grey out, sort last, can't be selected and never fold away. Once something is marked, the Shopping List and Flips to Craft fold on the gold left, and header line 2 shows ", Bought X". ADR-0016/0017 were amended and CONTEXT.md has **Bought mark**. It hasn't been tried in game yet. #97 stays open for slice 2 (gated on the #85 buy-event probe).

Next, in order (grill first where not ready-for-agent):
1. In game: right-click a Shopping List row, check it greys and sorts last, check the header and fold, `/reload` and check it persists. Add this to the #85 in-game check list.
2. #39 search the AH from a Shopping List row (needs in-game throttle probe)
3. #110 Beta Prior as an engine nudge: grill before Nov 4
4. #76, #55, #81, then #89, #54, #44, #61, #14, #19, #10, #82

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. `BoughtMarks.forMarket` requires RecommendationTable lazily (load-order cycle, noted in the file). `spent` counts every live mark, including ones whose row a newer Brain run dropped (that gold really left). `python scripts/busted.py` runs the addon specs.

2026-09-30 (later 36): Grilled #97. The spec is on the issue, and it's ready-for-agent. Bought buy-side rows (Shopping List, Flips to Craft, Prediction buys, not Buy Under) grey out and sort to the bottom, with no re-sizing. The Budget fold (#86) re-runs on gold left = min(Budget - spent, gold). Marks are per Market in `AzerothQuantDB` and cleared once an import's `entry.asOf` is later than the mark. Slice 1 is the manual right-click toggle (build now). Slice 2 is automatic detection by Item Key, gated on the new buy-event probe comment on #85.

Next, in order (grill first where not ready-for-agent):
1. #97 slice 1 (manual Bought mark): /tdd. Put the pure logic in a module with busted specs, and keep the WoW glue thin.
2. #39 search the AH from a Shopping List row (needs in-game throttle probe)
3. #110 Beta Prior as an engine nudge: grill before Nov 4
4. #76, #55, #81, then #89, #54, #44, #61, #14, #19, #10, #82

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. Right-click is free on rows (left-click = select for post/cancel, later #39). `python scripts/busted.py` runs the addon specs. #97 slice 2 waits on the #85 probe.

2026-09-30 (later 35): Fixed #108 (746a0d7), closed. `--why-not` now prices its Checks at the shortest run of the cheapest Listings that would clear the Flip margin if room were no limit and that has the minimum of Sale Events at its post price (`_Valuer.clearing_run`, which goes through the same `_flips` with an undercut pricer). `WhyNot` has new `post_at` and `needs` fields, and Room fails when room < held + needs. 5631 at forced Days to Sell now reads "Room fail: room for 112 at 4s 43c, needs 0 held + 177". Plain `recommend` is byte-identical, and made the list == Shopping List (22/22). #109 still only needs the user's OK to close.

Next, in order (grill first where not ready-for-agent):
1. #97 take a row off once bought (double-buy risk). It's needs-info, so /grilling first.
2. #39 search the AH from a Shopping List row (needs in-game throttle probe)
3. #110 Beta Prior as an engine nudge: grill before Nov 4
4. #76, #55, #81, then #89, #54, #44, #61, #14, #19, #10, #82

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. To force Days to Sell on real data, monkeypatch `brain.recommend.market_days_to_sell` in a scratch script (it's read per Market, not from config.toml). `ruff` isn't on PATH here: use `python -m ruff`.

2026-09-30 (later 34): QUEUE CHANGE. The user dropped the core/later split for ordering: work open tickets by need. Date-gated items are unchanged (#85's checks, the Oct 3 #83 replay, Nov 4 #91, #58's tooltip check, first `brain flips` grades).

Update, same day: #109 and #108 turned out to be built already (fa56555, c0c7021). #109 was checked Brain-side on Scan 46 by forcing Days to Sell. Flips to Sell drop out whole instead of shrinking, because on Beta they're wall buyouts (see the #109 comment). It works as designed and only needs the user's OK to close. #108 has a finding: `--why-not` says "Flip margin fail" with a passing margin when Days to Sell cuts a wall buyout. Room is priced as if only the cheapest Listing were bought (see the #108 comment).

Next, in order (grill first where not ready-for-agent):
1. #108 fix: make `--why-not` name room (at the wall-clearing post price) as the reason for a wall buyout cut short, then close #108. Close #109 if the user agrees.
2. #97 take a row off once bought (double-buy risk)
3. #39 search the AH from a Shopping List row (needs in-game throttle probe)
4. #110 Beta Prior as an engine nudge: grill before Nov 4, since without it #91's Predictions buy nothing at launch
5. #76 Disenchant as an exit
6. #55 loot and for-use buys
7. #81 Post / Cancel from a row (in-game probe first)
8. Then: #89, #54, #44, #61, #14, #19, #10, #82

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it.

2026-09-30 (later 33): Built #60 (189cf7f), closed. `brain/src/brain/flips.py` matches Purchases to the last Scan's Flip to Sell rows and grades them. It's shown in `brain flips` and in a `Graded Flips:` line in `brain recommend`, and it's not in the import path. Two changes to the spec, both agreed: the freeze is per Scan (`grades.toml` `[shown...]`, empty ones included, so an unmatched Purchase never costs another recompute), and the grade is a second append `[flips...."<item_key>@<scan>"]`. The grade is worked out once a Scan at or after the grading moment is in, and frozen once a Mailbox Read at or after it is in too. ADR-0023, CONTEXT.md **Flip Grade**. On the real Beta history it found 7 Flips (all pending). The first backfill took about 5 min (one recommend_market per Scan), and later runs are instant.

Next, in order:
1. At the PC or on a date: unchanged (#85's checks, the Oct 3 #83 replay, Nov 4 #91, Nov 18 #110), plus #58's in-game tooltip check. Close #58 after it. Also, once a Sale Horizon has passed, run `brain flips` and see the first real Flip Grades. Expect about 5 min the first time, because it writes `brain/grades.toml`.
2. Away from the game: #14, then #10, then the grills (the (later 29) list).

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. In this shell, heredoc'd Python patch scripts mangle `\n` escapes and quotes. Write the script to the scratchpad with the Write tool and run it from there, or use Edit.

2026-09-30 (later 32): Grilled #60. The spec is posted on the issue, and it's now ready-for-agent (still `later`). It grades Flips to Sell only, and reports without feeding back into decisions. A Purchase is matched automatically to a Flip to Sell row on the Shopping List as of the last Scan before it, at or under the row's dearest Listing, and one Flip is the matched Purchases of the same Scan's row. At first sight the Brain recomputes that row and freezes Post at, expected Profit, units and the Sale Horizon in `grades.toml` `[[flips]]`. Once a Sale Horizon has passed since the Purchase, the grade is: Sold Outcomes within it (oldest-first Lots) after the cut, plus open units at Best Exit Value, less cost. Deposits are left out. The output is a summary line plus a `brain flips` command. Beta is included (provisional), and existing history is backfilled.

Next, in order:
1. At the PC or on a date: unchanged (#85's checks, the Oct 3 #83 replay, Nov 4 #91, Nov 18 #110), plus #58's in-game tooltip check. Close #58 after it.
2. Away from the game: #14, then #10, then the grills (the (later 29) list). #60 can be built with /tdd whenever it fits.

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. For #60's freeze step, recomputing one past Scan's Shopping List reuses the replay machinery (`replay._brain`). It's slow per Scan, so run it only for new matched Flips.

2026-09-30 (later 31): Built #58 (473c4bc). `_Valuer.held_rate` pools Sibling Sale Events into held units only: rows, has_data, the Holdings queue, and so worth / Best Exit Value, Crafts and Disenchant choices. Flips, Buy Under, Max Loss and Flip to Craft outputs still read `rates`. There's a `suffix_pool_weight` config (0 to 1, default 0.5), `siblingSales` on Holdings rows, the tooltip `Sales N (+M other suffixes)`, a CONTEXT.md **Sibling** entry, and ADR-0022. The issue stays open until the in-game tooltip glance is done.

Next, in order:
1. At the PC or on a date: unchanged (#85's checks, the Oct 3 #83 replay, Nov 4 #91, Nov 18 #110), plus #58's in-game check: find a held suffixed item whose row now says Sell and check its tooltip. Close #58 after that.
2. Away from the game: /grilling #60, then #14, #10, then the grills (the (later 29) list).

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. The Lua round-trip tests in test_recommendations.py skip on this PC (no `lua`), so CI is what checks `siblingSales` reaches Lua (`python scripts/busted.py` covers the addon specs). A pooled `SellRate` has fractional `sale_events`/`sale_units`, now typed `float`.

2026-09-30 (later 30): Grilled #58. The spec is posted on the issue; it's ready-for-agent. Pool demand (not price, not Fair Value) across an itemID's suffixes, for held units only: sibling Sale Events at or above the post price count at `suffix_pool_weight` (0.5), the #41 cap uses own + sibling Sale Events, and the tooltip shows `(+M other suffixes)`. Flips and Buy Under are untouched.

Next, in order:
1. At the PC or on a date: unchanged (#85's checks, the Oct 3 #83 replay, Nov 4 #91, Nov 18 #110), plus #58's tooltip glance once it's built (on the issue, not blocking).
2. Away from the game: /tdd #58 (Brain plus a busted test for the tooltip line, then CONTEXT.md and ADR-0022). Then the (later 29) list from its item 2 on: /grilling #60, #14, #10, then the grills.

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. For #58, the held-unit post price and sibling evidence depend on each other: work out the price first (cap = dearest own + sibling Sale Event), then count siblings at or above it. Keep the pooled rate out of `rates`, which Flips read.

2026-09-29 (later 29): QUEUE CHANGE. The user wants `later` work done while `core` waits on the PC. Every open `core` item is blocked (in game, or a date), so work down this list when away from the game.

Next, in order:
1. At the PC or on a date: the (later 25) list still applies (#85's checks, the Oct 3 #83 replay, Nov 4 #91, Nov 18 #110). Those come first whenever they're possible.
2. Away from the game, `later` work:
   1. /grilling #58: pool Sell Rate and Fair Value across random suffixes, or not. It matters before Live on Nov 4, because suffixes split an already thin history.
   2. /grilling #60: grade Flips (was a Flip made, and did it sell at Post at within the Sale Horizon).
   3. #14: design how Outcomes match back to Listings (Cancelled and Expired mail has no price), then build.
   4. #10: compact Listing encoding and parser fast paths (the Lua side needs a #85-style in-game check afterwards).
   5. Grills, in any order: #97, #89, #61, #55, #54, #44, #19.
   - Needs the game, so skip for now: #81, #39, #76, #108, #109, #82 (browser).

- Gotchas: unchanged. `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it.

2026-09-29 (later 28): Closed #56 as answered, with a "revisit after Live" note. Nothing to act on until Blizzard adds a Forever API namespace or TSM adds Forever. If either ships, file a fresh issue (Blizzard: first check the 30-day retention rule against ADR-0005). Details are in `docs/research/ah-data-sources.md`.

Next, in order: unchanged from the (later 25) entry. Also, around #110's Nov 18 check, glance at whether Blizzard/TSM have shipped anything for Forever.

- Gotchas: unchanged. `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it.

2026-09-29 (later 27): #85's #50 check not done (away from the game for a while). The expected Holdings values are commented on #85: 5 paid rows now, with stars on 247754 (+190%) and 279962 (+451%), 279976 at +8% with no star, and 250933/20744 at -5% in red. Recheck against the latest import when you're back.

Next, in order: unchanged from the entry below.

- Gotchas: unchanged from the entry below. `addon/AzerothQuant/Recommendations.lua` shows as modified because an import wrote it. It's generated, so don't commit it as part of doc work.

2026-09-29 (later 26): Researched #56 with /research: `docs/research/ah-data-sources.md`, and the verdict is commented on #56. Nothing replaces or is worth importing alongside our Scans today. Only crowdsourced sites cover Forever, and they have listing snapshots only, no sales. Things to watch after Live: a Blizzard API Forever namespace (hourly, auction IDs, the only outside route to a Sell Rate, but its terms allow keeping data for 30 days at most, which clashes with ADR-0005) and TSM adding Forever (region-wide `saleRate`/`soldPerDay` as an ADR-0015 prior). #56 left open pending a decision to close it.

Next, in order: unchanged from the entry below.

- Gotchas: unchanged from the entry below.

2026-09-29 (later 25): Sorted #85's leftovers against the current data. Nothing was checked (not at the game).
- Checkable now: #50. The Holdings have 5 paid rows: 247754 (+190%, the only roiHint), 250933 (-5%), 20744 (-5%), plus 2 more. Check the ROI cell color, the green star on 247754, and `Paid ... each, nets ...` in the row and item tooltips.
- Not checkable: #33 (no `via` row), #75 (no `blocked` row), #83 replay (needs 7 days, ~Oct 3). Booty Bay Broker is optional browser work.

Next, in order:
1. In game: #85's #50 check (above). Then #33/#75 whenever a chained or blocked Craft row shows up.
2. ~Oct 3: `brain replay` for #83.
3. Nov 4 at the PC: #91's list.
4. ~Nov 18: answer #110's triage question.

- Gotchas: unchanged from the entry below.

2026-09-29 (later 24): Triaged #110 (Beta Prior as an engine nudge): `enhancement`, `later`, `needs-info`. The triage comment asks for a check around Nov 18: how close the Beta column was to Live prices, and which Item Keys were blocked by thin Live history. Close means spec + ADR; far off means wontfix + `.out-of-scope/`.

Next, in order:
1. At the PC: #85's parked in-game checks (core).
2. Nov 4 at the PC: #91's list (see gotcha below).
3. ~Nov 18: answer #110's triage question from two weeks of Live.

- Gotchas: unchanged from the entry below. Recommendations.lua in the working tree is Brain output; don't commit it with other work.

2026-09-29 (later 23): AT THE PC. Built #106 (77a2994) with /tdd, then /code-review. The Brain mirrors Recommendations.lua into a Brain-created `AzerothQuant_Data` (LoadOnDemand). The Addon's new `Freshness.lua` (busted) decides stale or fresh, and `covers` decides newer. `DataAddon.lua` (glue) runs Load, and the Reload button relabels to Load. RELOAD_READY_AFTER is now 70 s. #106 stays open for the in-game check, which is a comment on the issue.
- Review fixes applied: the Brain writes the Addon's copy before the Data copy; `db.lastSavedRead` is cleared on a logout with no Character Read; Scanner recounts saved Scans after Load instead of subtracting the pruned ones.

- Checked in game and closed: Load works, one reload per Scan. Not run: the early-Load case and `/aq load` with nothing new.
- `brain watch` restarted. A stale watcher from 7:56 PM had a window title that play.bat's taskkill filter doesn't match, so check `Get-CimInstance Win32_Process -Filter "Name='brain.exe'"` for duplicates.

Next, in order:
1. Nov 4 at the PC: #91's list (see gotcha below).
2. Anything `core` in needs-triage / ready-for-agent.

- Gotchas:
  - The Bash tool mangles `\n` inside Python heredocs (they became real newlines). Use Edit for string literals with escapes.
  - The rest are unchanged from the entries below.

2026-09-29 (later 22): AT THE PC. Grilled #106: the spec comment is on the issue, it's relabelled `ready-for-agent` (still `later`), and ADR-0021 records the mirror decision.

Next, in order:
1. Build #106 per its spec comment. It's `later`, so it goes after anything `core`.
2. Nov 4 at the PC: #91's list (see gotcha below).

- Gotchas: unchanged from the entry below. For #106, new addon folders are only found at client start, so the first in-game check needs Brain run -> client restart.

2026-09-29 (later 21): AT THE PC. Built #91's code change (faeaf84): `_hold_buys` in recommend.py stops at the first Listing at or above the Merchant Cost after the Market's cut. Review was clean on both axes. #91 stays open for the Nov 4 at-the-PC steps (read Mister Graphed's Item Keys, write the four Predictions).
- Restart `brain watch` so it picks up the change.

Next, in order:
1. Grill #106's open questions.
2. Nov 4 at the PC: #91's list (see gotcha below).

- Gotchas: unchanged from the entry below.

2026-09-29 (later 20): AT THE PC. Built #90 (d1dd9d4), checked in game on Beta data, closed.
- `brain/src/brain/beta_prior.py` runs from `cli._write_recommendations` after `recommend`, never inside it (ADR-0015). It reuses the pass's FairValueCache, so a pass takes ~50 s, up from ~40 s. The remaining ~9 s is `sell_rates` on the Beta Market. Beta freezes on Oct 21, so that result could be saved and reused if speed ever matters.
- Beta Markets get their own Beta Prior too (the user chose this so it could be checked in game), so the column shows on Beta until about Oct 10.
- Cell widths: the Shopping List with Beta has 12 columns. Beta, Post at and Cost are 85 px, and Item is narrowed to 120 px (`BETA_COLUMN_WIDTHS` in RecommendationFrame.lua).

Next, in order:
1. Build #91's Merchant Cost cap (before Dec 9).
2. Grill #106's open questions.

- Gotchas:
  - After Brain code changes, restart `brain watch`: a running one keeps the old code and rewrites Recommendations.lua without the new fields. That happened this session. The venv is an editable install, so a restart is enough.
  - On Nov 4 at the PC, in this order: open Mister Graphed's window with a Live Character, read the Item Keys of #91's list in game, then write the four Predictions in `predictions.toml` before buying anything.
  - There's no Lua on this PC, so the brain real-Lua tests skip locally. To run them, point `LUA` at a lupa shim (`python -c` wrapper around lupa.lua51 running `-e script`); CI runs them on real Lua.
  - `git stash list` has an old "pre-pull local changes 2026-09-28" stash. Leave it alone unless the user asks.
  - addon/AzerothQuant/Recommendations.lua is still modified locally (Brain output). Don't commit it.

2026-09-29 (later 19): NOT AT THE PC. Grilled #90 and #91; both are now ready-for-agent. Filed #110.
- #90 Beta Prior: display only (the Brain never reads it), shown as a grey "Beta" column plus a tooltip on every tab. Raw median Sale Event price (Beta's last 14 days, at least 3 Sale Events), or else the median daily Fair Value (last 7 days), marked "listed, not sold". It comes from the same-faction Beta Market, or else Alliance. `beta_column_days` = 14 from the Live Market's first Scan. The Brain writes it into Recommendations.lua. Full spec in the comment on #90. CONTEXT.md and ADR-0015 are updated (d3e6dd6).
- #110 (needs-triage): Beta as an engine prior. Split out of #90.
- #91: four Predictions (one per group), Catalyst = raids unlock Dec 9, lapse Dec 23. The Max Loss rule stays. The one code change: no Prediction buy at or above the Merchant Cost after the 5% cut (ADR-0006 amendment). Mister Graphed (the Black Market) is already a Merchant Cost since #65.

Next, in order:
1. Not at the PC: build #90 (deadline Nov 4).
2. Not at the PC: build #91's Merchant Cost cap (before Dec 9).
3. Grill #106's open questions.

- Gotchas:
  - On Nov 4 at the PC, in this order: open Mister Graphed's window with a Live Character, read the Item Keys of #91's list in game, then write the four Predictions in `predictions.toml` before buying anything.
  - #90's column needs an in-game check (RecommendationFrame.lua has no busted seam). The only Beta Market is Classic Beta PvP Alliance, so it can be tested on Beta data before Oct 21.
  - addon/AzerothQuant/Recommendations.lua is still modified locally (Brain output). Don't commit it.

2026-09-29 (later 18): AT THE PC. #85's Buy Under checks done; #88 closed. One fix (6fec61b).
- The AH green wash never fired: the ScrollBox init callback gets an index as elementData, and row.rowData is still nil then. The Listing now comes from `list.getEntry(index)`. Checked on all three lists (browse, item, commodity), scrolling included.
- The Disenchant group Buy Unders are correct but empty on real data: Beta mats are too cheap for any group to pay (numbers on #85). The Addon half was checked with a test group row.
- Cosmetic, not filed: long item names and a group row's Way out get cut off with `...` in the Buy Under tab.

Next, in order:
1. Not at the PC: grill #90 (Beta Prior column) before Live on Nov 4; #91 has the same deadline. Then grill #106's open questions.
2. At the PC: nothing is queued on #85.

- Gotchas:
  - The Brain only knows the Enchanting skill level from a Read taken with the Enchanting window open.
  - To test an Addon path with no live data, add a tagged entry to the local Recommendations.lua and /reload at once: `brain watch` overwrites it on the next import.
  - RecommendationFrame.lua and BuyUnderHighlight.lua have no busted seam. Changes need an in-game check on #85.
  - addon/AzerothQuant/Recommendations.lua is still modified locally (Brain output). Don't commit it.

2026-09-29 (later 17): AT THE PC. #93 verified and closed; the #106 spike passes.
- #93: the Brain drops options over its own Budget, so a row only folds when the box is set below the Budget the Brain sized at. The check: size the Brain at 0.1g, then set the box to 0.01g without a reload. No Craft fits 0.1g right now, so it was checked on the Shopping List, which uses the same `section()` path.
- #106: the client reads a LoadOnDemand addon's file from disk when it loads. The global `LoadAddOn` is nil here; use `C_AddOns.LoadAddOn`. Now `needs-info` + `later`: grill its open questions before building. The TestLOD folder is removed.

Next, in order:
1. At the PC: the rest of #85 (Buy Under tab, AH wash, Disenchant groups).
2. Not at the PC: grill #90 (Beta Prior column) before Live on Nov 4; #91 has the same deadline. Then grill #106's open questions.

- Gotchas:
  - RecommendationFrame.lua has no busted seam. Any change to it needs an in-game check on #85.
  - addon/AzerothQuant/Recommendations.lua is still modified locally (Brain output). Don't commit it.

2026-09-29 (later 16): AT THE PC. Fixed a #109 bug (98b4da2): after /reload the Budget and Days to Sell boxes showed blank over saved values, and an Enter in a blank box wiped the setting. The frame's OnShow now fills both boxes and clears focus. Checked in game. Results are on #85 and #109.
- #108: `--why-not` ran; the near misses are all Flip margin and none are on the Shopping List. 17 of 20 show `?` for the name (the Brain lacks their names). Not filed yet.
- #93: not exercised. At Budget 0.1g the only Craft (4s 74c) fit. Set the Budget to 0.01 to force the all-over-Budget case.

Next, in order:
1. At the PC: #93 at Budget 0.01g (open Flips to Craft), then #106's LoadOnDemand spike (steps on #85), then the older #85 items (Buy Under tab, AH wash, Disenchant groups).
2. Not at the PC: grill #90 (Beta Prior column) before Live on Nov 4; #91 has the same deadline.

- Gotchas:
  - RecommendationFrame.lua has no busted seam. Any change to it needs an in-game check on #85.
  - addon/AzerothQuant/Recommendations.lua is still modified locally (Brain output). Don't commit it.

2026-09-29 (later 15): TRIAGE DONE, nothing built. needs-triage is empty.
- #92 closed: fixed by #105. The latest `Import took` lines (on #71) are 11-23 s warm and 31 s cold, down from 33-56 s.
- #106: its LoadOnDemand spike is added to #85's checklist. Relabelled `needs-pc` + `later`.
- #56 is `ready-for-agent` (a `/research` task, `later`).
- #97, #91, #90, #89, #61, #60, #58, #55 and #54 are `needs-info`: each needs a grill with the user. #55's body had a stray pasted `gh issue create` command, now removed.

Next, in order:
1. At the PC: #85's list: #93's check (Budget 0.1g, open Flips to Craft), #108's check (`brain recommend --why-not` vs the Shopping List), #109's Days to Sell = 2 check, and #106's LoadOnDemand spike.
2. Not at the PC: grill #90 (Beta Prior column). It's `later`, but it only helps if built before Live on Nov 4, so the user may want it made `core`. #91 (Launch Predictions) has the same deadline.

- Gotchas:
  - Before building an issue from this queue, check `git log --grep '#N'` and the issue's last comment.
  - addon/AzerothQuant/Recommendations.lua is still modified locally (Brain output). Don't commit it.

2026-09-29 (later 14): #93 BUILT (f147226), with /tdd then /code-review, and relabelled needs-triage -> needs-pc. In `section()` (RecommendationTable.lua), a tab with no rows only gets its `empty` text when nothing was folded over the Budget, so an all-over-Budget tab shows just "N over the Budget (Reload to re-size)". A tab of only low-value rows still says it's empty, since those aren't options. The mixed case can only happen on the Shopping List, because a Craft is never low-value.

Next, in order:
1. Not at the PC: triage the rest of needs-triage. #92 looks fixed by #105 (recommend 45 s to 10 s), so check the latest `Import took` lines and close it if so. #106 is blocked on its in-game LoadOnDemand spike, so add that spike to #85.
2. At the PC: #85's list, including #93's check (Budget 0.1g, open Flips to Craft), #108's check (`brain recommend --why-not` vs the Shopping List) and #109's Days to Sell = 2 check.

- Gotchas:
  - Before building an issue from this queue, check `git log --grep '#N'` and the issue's last comment.
  - addon/AzerothQuant/Recommendations.lua is still modified locally (Brain output). Don't commit it.

2026-09-29 (later 13): QUEUE CLEANUP, nothing built. The "#88, then #76" item was stale: #88 (bd7f467, 9886c89, 8fda1f3, 3b9fc6d) and #76 (e8da1ea, ac81a0b) were already built and are open only for their #85 checks. #88, #76, #108 and #109 moved from `ready-for-agent` to `needs-pc`, so `ready-for-agent` now lists only unbuilt work (currently none).

Next, in order:
1. Not at the PC: triage + fix #93 (an all-folded tab shows "No <tab> right now" above "N over the Budget"; RecommendationTable.lua, busted). Then triage the rest of needs-triage. #92 looks fixed by #105 (recommend 45 s to 10 s); check the latest `Import took` lines and close it if so. #106 is blocked on its in-game LoadOnDemand spike, so add that spike to #85.
2. At the PC: #85's list, including #108's check (`brain recommend --why-not` vs the Shopping List) and #109's Days to Sell = 2 check.

- Gotchas:
  - Before building an issue from this queue, check `git log --grep '#N'` and the issue's last comment: a stale queue line cost this session.
  - addon/AzerothQuant/Recommendations.lua is still modified locally (Brain output). Don't commit it.

2026-09-29 (later 12): #108 BUILT (c0c7021), with /tdd then /code-review. It stays open for the human check at the PC. `recommend(..., why_not=True)` fills `MarketRecommendations.why_not` (`WhyNot`, `Check` in recommend.py) from `_why_not`, which reuses `_room_at` (Days to Sell), `_way_out` and `_under_margin`. `_options` is now `_flip_options` + `_best_ranks`, which the Row cap check shares. Two changes from the brief, agreed in session:
- Names come only from own Listings, Purchases and linked Outcomes (`lots.item_names`). Scans don't carry other players' item names, so most rows show "?".
- The Flip margin, Sale Events and Room are all priced as if the cheapest Listing were bought, so posting under the NEXT ask, as `_flips`' first run does. The plain Buy Under value made a lone cheap Listing under a wall look 41% short when it was really 1c short.
On the real history, plain `brain recommend` is byte-identical to HEAD, and "made the list" = the Shopping List's Sell/Vendor Item Keys (24/24). Of the 4740 candidates: 3851 fail Sale Events, 862 Flip margin, 3 Budget.

Next, in order:
1. Not at the PC: #88, then #76.
2. At the PC: #85's list (Days to Sell = 2 check and the Budget box, from #109). Also #108's human check: run `brain recommend --why-not` and eyeball the near misses against the Shopping List.

- Gotchas:
  - `--why-not`'s top 20 are all Flip margin on the real data (margin misses come first by design, as the brief asks), so Budget/Row cap misses never show there. Use `--why-not ITEM` for those.
  - Review leftovers, not done: CONTEXT.md has no entry for "Check"/"near miss". `why_not=""` means the near-miss list (argparse `const`). `market_days_to_sell` repeats `market_budget`'s SQL. `parseDays`/`daysText` repeat the shape of `Money.parseGold`/`goldText`.
  - Git Bash heredocs here turn `\n` inside Python source strings into real newlines. Use Edit for anything containing `\n`.
  - addon/AzerothQuant/Recommendations.lua is still modified locally (Brain output). Don't commit it.

2026-09-29 (later 11): #109 BUILT (fa56555), with /tdd then /code-review. It stays open for the in-game check, which is now on #85 (see the comment there). The Days to Sell box is saved per Market in `AzerothQuantDB.daysToSell` and sent as `daysToSell` in the Character Read. The Brain side is `character_read.days_to_sell` and `market_days_to_sell`. `recommend_market` puts it on `Config.days_to_sell_seconds`, and `Config.days_to_sell_or_horizon_seconds` clamps it to the Sale Horizon. `_flip_room`/`_room_at` now take the horizon explicitly. With the setting unset, `brain recommend` output is byte-identical to HEAD on the real history. The full summary is on #109.

Next, in order:
1. Not at the PC: #108 (`brain recommend --why-not`), per its agent brief. Then #88 and #76.
2. At the PC: #85's list, now with the #109 check: set Days to Sell to 2, /reload, and after the import the big rows shrink. Also check that the Budget box still works (it moved onto the shared `createSettingBox`).

- Gotchas:
  - #108: use `_room_at(..., config.days_to_sell_or_horizon_seconds)` for the Flip room, as `_flips` does. Prediction buys pass `sale_horizon_seconds`, so a "why not" that ignores Days to Sell will disagree with the Shopping List.
  - CONTEXT.md avoids "buy horizon": say Days to Sell.
  - Review leftovers, not done: `market_days_to_sell` repeats `market_budget`'s SQL. `parseDays`/`daysText` repeat the shape of `Money.parseGold`/`goldText`.
  - `budgetKey` is now `RecommendationTable.marketKey`.
  - addon/AzerothQuant/Recommendations.lua is still modified locally (Brain output). Don't commit it.

2026-09-29 (later 10): TRIAGE. #109 and #108 are both ready-for-agent + later, with agent briefs on the issues. #109 became **Days to Sell** (CONTEXT.md, ADR-0020, amends ADR-0017): a per-Market Addon box next to Budget, carried in the Character Read, that caps only buys exiting through Sell (Flip to Sell run, Flip to Craft output Sell room, Buy Under Sell units), clamped to the Sale Horizon. The Sale Horizon is left alone: Holdings, Best Exit Value, Predictions and the replay's grading stay on it. #108 became `brain recommend --why-not [ITEM]`: CLI only, the first check each candidate fails (Sale Events, Room, Flip margin, Budget, row cap) plus its gap, with the Flip-margin gap measured against the Buy Under way value. No Flips to Craft.

Next, in order:
1. Not at the PC: #109 (the user cares most about it), per its agent brief. It's Brain + Addon, so the in-game check goes on #85's list. Then #108, then #88 and #76.
2. At the PC, still open on #85: a blocked/empty Craft Chain (#77/#75, needs a blocked Craft row to exist), #33 chained rows, #50, the `brain rebuild` for #78, the #80 replay (Oct 3+ for 7 days of history), and the Booty Bay Broker follow-up. Once #109 is built, also set Days to Sell = 2 and confirm the big rows shrink.

- Gotchas:
  - #109: with Days to Sell unset, every recommend and replay output must come out byte-identical. That's the regression net.
  - #108 should use the same check helpers as the real Shopping List (`_room_at`, `_resells`, the Buy Under way value) rather than copying them, or the diagnostic will drift from what the Brain actually does.
  - The gotchas in the entry below still apply (screenshots, `brain watch`, Recommendations.lua stays uncommitted).

2026-09-29 (later 9): PC SITTING. #77 CLOSED: the in-game check passed, and the Craft Chain panel now docks LEFT of the table, over the AH (c1a2b4b), because on the right it ran off a 1920px screen. #71 tuned: `RELOAD_READY_AFTER` 50 -> 30 s (bbc4282), from 11-23 s imports, and checked in game. #104 CLOSED: the in-game check passed (warning line + header note with watch stopped, both gone after restart). Filed #108 (Shopping List "why not" diagnostic) and #109 (player-set stock horizon for Buy Qty: the user dislikes 100-200 unit buys but doesn't want to force it on everyone). Both are needs-triage.

Next, in order:
1. Triage #109, then #108 (the user raised both; #109 is the one they care about). Use the triage skill and grill the design: a separate Buy horizon vs. reusing `sale_horizon_days` (which also grades the replay).
2. Not at the PC: ready-for-agent #88, #76.
3. At the PC, still open on #85: a blocked/empty Craft Chain (#77/#75, needs a blocked Craft row to exist), #33 chained rows, #50, the `brain rebuild` for #78, the #80 replay (Oct 3+ for 7 days of history), and the Booty Bay Broker follow-up.

- Gotchas:
  - Pasted screenshots don't reach the session. The user presses PrtScn in game, and the newest file is in `Z:\Battle.net\World of Warcraft\_classic_beta_\Screenshots`: read it with the Read tool.
  - Claude can run `brain watch` itself as a background Bash task (`cd brain && PYTHONIOENCODING=utf-8 ../.venv/Scripts/brain.exe watch`) and read "Import took" lines from its output file.
  - watch's first import after starting ran 31.4 s (cold), just over the 30 s nudge. Running imports were 16-22 s. Bump it only if the line shows before the table is current.
  - addon/AzerothQuant/Recommendations.lua is still modified locally (Brain output). Don't commit it.

2026-09-29 (later 8): #77 ADDON SLICE BUILT (e2216da), with /tdd then /code-review. It stays open for the in-game check, which is now on #85. `CraftChain.build(row, nameOf)` turns `chain` into lines: guides, text, tag, gold, color, blocked and tooltip, plus `profit` or `empty`. Table rows carry `id` (Item Key, action, Character) and `record`, and `RecommendationTable.find(section, id)` finds the selection again. In RecommendationFrame.lua, a click selects a row and a shift-click links it. A selected Craft row opens the docked panel. The selection is kept while any tab has its row, and the close button clears it. The ADR-0016 note is in. The full summary is on #77.

Next, in order:
1. At the PC: #85's checklist, which now starts with a FULL client restart (CraftChain.lua is new in the .toc), plus the #77 panel check. Also #71's tune and #104's in-game check (as in the entries below).
2. Not at the PC: nothing is queued from this thread. Pick from ready-for-agent issues (`gh issue list --label ready-for-agent`).

- Gotchas:
  - The glue can't run under busted. A throwaway WoW-stub smoke script (catch-all metatable stubs for CreateFrame and friends) caught nothing but was cheap. Worth keeping in mind for glue-heavy changes.
  - Review leftovers, not done: a cooldown row's panel doesn't show the row note. `CraftChain`'s `REASONS` repeats `RecommendationTable.note`'s reason text. The "only Craft opens the panel" check is in the glue.
  - addon/AzerothQuant/Recommendations.lua is modified locally (real Brain output). Don't commit it.

2026-09-29 (later 7): #77 BRAIN SLICE BUILT (1b34337), with /tdd then /code-review. #77 stays open for the Addon slice. Every Craft row has `chain` (a `ChainNode` tree). It's recorded while sourcing: `_Chain.parts` holds `_Part`s keyed by `at`, the craft the part feeds as Item Keys from the top output down. `_Sources.parts` values the held units and leftovers, `_held_exits`/`_exits` add the exits, `_Plan.add(chain, parts)` sums them, and `_Plan.chain()` builds the tree. The roots are the exits, and the LAST one has the top craft as its only child. A craft's gold is the sum of its children, and every other node sums to `profit`. Blocked rows: `_blocked_chain`. Written to Lua as `chain` (the node keys are in the Recommendations.lua header). `brain recommend --chain ITEM_KEY` prints an ASCII tree. The full summary is on #77.

Next, in order:
1. Not at the PC: the #77 Addon slice, per the spec comment's "### Addon" section and the Brain-slice comment:
   - CraftChain.lua (busted), which turns the tree into lines.
   - The frame glue in RecommendationFrame.lua.
   - Plain click selects a row, shift-click links it.
   - The ADR-0016 note.
   - The .toc change goes on the #85 checklist (full client restart).
2. At the PC: #71's tune and #104's in-game check (as in the entries below).

- Gotchas:
  - The Brain's Lua tests (`test_recommendations.py`) SKIP unless `LUA` is set: `LUA=Z:/vibing/azerothquant/.lua/bin/lua.exe python -m pytest`. Lua 5.1 prints whole floats without `.0`.
  - Ruff isn't on PATH: use `../.venv/Scripts/ruff.exe` from `brain/`. `brain recommend` needs `brain/` as the working directory (for config.toml).
  - Bash heredocs with `\\n` inside Python replace scripts didn't match here. Write the script to the scratchpad with the Write tool, or use Edit.
  - Piped stdout on Windows is cp1252: box glyphs in CLI output crash. The Addon has no such limit.
  - A blocked row whose other reagents can't be sourced has an empty `chain`. The panel needs a "no chain" state.

2026-09-29 (later 6): #84 DONE and closed (9dbff93), with /tdd then /code-review. `recommend_market(pricer=)` takes an optional `Pricer` (Item Key, cheapest other ask left) -> post price. `_Valuer` switches on it in `sale_queue`, `priced`, `has_data`, `_post_at_or_under` and `rows`, and `_flips`/`_outlet` take the per-Item-Key `priced` callable. Only `replay._tsm_pricer` builds one. New Policy row "Brain without own-Market Sell Rate". ADR-0015 describes it. Replay on beta (24 h, 23 Scans, ~40 min): the other rows are unchanged from #103, and the new row is -240g 19s 52c against Brain 5g 64s 29c and TSM -249g 73s 87c (table on #84).

Next, in order:
1. At the PC: #71's tune and #104's in-game check (both as in the entry below).
2. Not at the PC: #77.

- Gotchas:
  - Replay is slow (~40 min on beta at 24 h) mostly because it passes no `fair_value_cache`, so `sell_rates` recomputes every past Scan's Fair Value per Brain run and per `exit_values`. Worth an issue: one `FairValueCache` per Market through the replay.
  - Review leftovers, not done: the "pricer or Sell Rate" switch is repeated in ~7 places in recommend.py and could be one small pricing object in `_Valuer`. In replay.py, a policy's variant is split across `_BRAINS` (identity lambda for the new one) and a per-Scan `pricers` dict.
  - With a pricer, `_sell_way` (Buy Under) and the Shopping List's Per day/Per click still use the Sell Rate. The replay doesn't grade either.

2026-09-29 (later 5): #103 DONE and closed (1d39004), with /tdd then /code-review. `known_recipes`, `enchanting_skills`, `_professions` and `_market_characters` take an optional `as_of` (only Character Reads up to it count). `recommend_market(as_of)` passes it to `known_recipes` and to `_valuer(..., skills_as_of=)`. `exit_values(at)` passes `at`. The replay reads Known Recipes per replayed Scan. `_LATEST_CHARACTER_READS` is gone (inlined into `_market_characters`). CONTEXT (Known Recipe) says so. Replay on beta (24 h, 23 Scans): Brain 5g 67s 00c before, 5g 64s 29c after. TSM went from -286g 31s to -249g 73s, since it no longer crafts at a loss with recipes learned later (tables on #103).

Next, in order:
1. At the PC: #71's tune and #104's in-game check (both as in the entry below).
2. Not at the PC: #77, #84.

- Gotchas:
  - `_valuer`'s `at` is the Scan time (live, the latest Scan). Don't bound Character-Read facts by it: live Reads after the latest Scan must still count. That's why `skills_as_of` is its own argument.
  - Still no as-of: `merchant_costs` and `vendor_prices` (latest seen). Fine for now: they barely move.
  - Review leftovers, not done: the "latest Read per Character up to a moment" SQL is now copied in `pooled_gold`, `_market_characters` and `_professions`, and could share a helper. The as-of argument is named `at`, `as_of` or `skills_as_of` depending on the function.
  - Don't `git stash push -- <path>` here. It broke the index (everything showed as staged-deleted plus untracked). `git reset` fixed it without touching files.

2026-09-29 (later 4): #104 BUILT (f6d2021), with /tdd then /code-review. It stays open for the in-game check. `Nudge.stampSaved` runs at PLAYER_LOGOUT. `Nudge.brainBehind` gives the oldest behind Scan's age. `Nudge.whenReloadReady` is now `Nudge.afterLoad(scans, now, after, ready, say)`, which either says `BRAIN_BEHIND_LINE` or starts the timer, and returns whether the Brain is behind. `waitingNote(unsaved, unimported, behind)` still puts unsaved Scans first. The review notes are on #104.

Next, in order:
1. At the PC: #71's tune (below) and #104's in-game check. For #104: stop brain watch, Scan, `/reload`, wait more than 2 min, then `/reload` again. The chat line and the "start brain watch" note should show. Start watch, then `/reload` after the import: both should be gone. Close #104 if that works. Note: Scans saved by the old build have no `savedAt`, so they never count as behind. The first Scan to test with has to be saved by this build.
2. Not at the PC: #103, #77, #84.

- Gotchas:
  - `RELOAD_READY_AFTER` tuning (#71) also moves `BRAIN_BEHIND_AFTER` (it's +60 s).
  - Busted runs locally: `.lua\bin\busted.bat --directory=.` from `addon\` (196 specs).
  - Python `'''...'''` string replaces in Lua source mangle `\\` escapes. Use the Edit tool for lines with backslashes.

2026-09-29 (later 3): CLOSED #105 (slices 1+2 took `recommend` from ~45 s to ~10 s; slice 3 isn't worth it now). TRIAGED #103 (ready-for-agent, later) and #104 (ready-for-agent, **core**, the user's call). The specs are the issue comments.
- #104 in short: stamp `savedAt` on each Scan at PLAYER_LOGOUT (only if it has none). At load, after pruning, the Brain is behind if any Scan has `savedAt <= now - (RELOAD_READY_AFTER + 60)`. Then print a `Chat.say` line, have `waitingNote` say to start brain watch, and skip the reload-ready timer. It's all Addon (busted), and the Brain ignores the extra field.
- #103 in short: an optional `as_of` on `known_recipes`, `enchanting_skills`, `_professions` and `_market_characters`, passed from `recommend_market(as_of)`, `exit_values(at)` and the replay (move its `known_recipes` into the tick loop). Then a before/after replay on beta.
- #71's `RELOAD_READY_AFTER` (50 s now) is still waiting on real `Import took` lines. The user runs `brain watch` in their own terminal, Scans and `/reload`s a few times, and pastes the lines. Set it to the slowest import + 3 s settle + a few seconds.

Next, in order:
1. Build #104 (core; no PC needed for the build, the in-game check waits for the next PC sitting).
2. At the PC: #71's tune (above) and #104's in-game check.
3. Not at the PC: #103, #77, #84.

2026-09-29 (later 2): #107 DONE and closed (c8d9002), with /tdd then /code-review. `SellRate` now carries `sale_prices` (each Sale Event's price and units). `max_sale_price` is now a property, and `at_or_above(P)` gives the rate at a price. When the Brain decides whether to buy something to Sell, it counts only the Sale Events at or above the post price. The helpers are `_demand_at`, `_room_at`, `_flip_queue` and `_sell_take`, used by `_flips` (each run at its own post price; it stops after a partial take), `_outlet`, `_hold_buys` and `_sell_way` (via `_Valuer.flip_post_at`). Held units keep the whole rate and the max cap (`_Valuer.post_at`). CONTEXT (Sell, Sell Rate, Flip, Buy Under) and ADR-0019 say so. Replay on beta at a 24 h horizon over 23 Scans: the Brain went from -14g 94s 22c to +5g 67s 00c (table on #107).
- Review notes left as they are (also on #107):
  - A Flip to Sell's `stack`/`posts` still uses the whole rate's Sale Event size.
  - `_flip_queue` repeats the Flip-prior branch of `_Valuer.queue`.
- Gotchas:
  - `brain replay` at the default 7-day horizon grades 0 Scans until the beta history is longer than 7 days (#83). For a check now, copy history.sqlite into the scratchpad with a config.toml there that sets `sale_horizon_days = 1` above `[[installs]]` (the history path resolves next to the config). Each run takes ~32 min. Before and after can run in parallel, since each process imports its code at start.
  - On this machine `git stash push` / `git stash pop` left the index EMPTY: every file showed as staged-deleted and untracked. `git reset -q` fixes it (index only, the working tree is intact). To check that a test is red on old code, use `git archive HEAD brain/src | tar -x -C <scratch>/old` and `PYTHONPATH=<scratch>/old/brain/src` instead of stash.
  - `addon/AzerothQuant/Recommendations.lua` shows as modified because the Brain's import writes it. Don't commit it.

Next, in order:
1. #105 slice 3, only if the user wants more (see below), or close #105 and take #71's reload-ready guess once the user has run a real watch pass with the new build.
2. Not at the PC: #77, #84, then triage #103 and #104.

2026-09-29 (later): #107 TRIAGED, now ready-for-agent + core. The spec is the issue comment. In short, when the Brain decides whether to buy something to Sell, the Sell Rate only counts Sale Events priced at or above the post price P. That covers Flip to Sell, Flip to Craft output, the Hold buy Max Loss resale and Buy Under's Sell way. It also replaces the `max_sale_price` cap on those paths. Held units don't change. NEXT: build #107.
- Gotchas:
  - The item is 14747 on Classic Beta PvP Alliance (item names aren't in history.sqlite; the addon's Recommendations.lua has itemKeys). Of its 8 Sale Events, only 2 (the 2g 99s pair on 09-27) are at or above the 2g 48s 99c post price.
  - In `_flips`, room is computed once before the run loop today. It now depends on each run's post price. Post price never falls as a run grows, so once a run is over its room the loop can stop.
  - The deposit `_Queue` is built from the whole Sell Rate. The Flip's own units should wait at the price-aware rate.
  - Replay grades the Shopping List options it assumes are taken (`replay._brain`), so a before/after `brain replay` on beta is the check the spec asks for.

2026-09-29: FILED #107 (needs-triage) from in-game Shopping List feedback. A Flip to Sell said to buy all 14 Hulking Gauntlets and repost at 2g 48s. The user thinks the item isn't worth that: the Sell Rate was measured at the old low prices, the resale cap is the single highest Sale Event, and the Listing left after the run is likely an unsold outlier. The open questions are on the issue (price-aware Sell Rate, a median/percentile cap, a Fair Value sanity ratio, capping run size, checking it with replay). The screenshot wasn't on disk, so the user attaches it to the issue. The item isn't findable by name in history.sqlite (listing.item_name is mostly NULL), so ask for the item ID or look it up when triaging.

2026-09-28 (later 46): #105 SLICE 2 DONE (8d8810c), with /diagnosing-bugs (perf branch) then /code-review. `FairValueCache` (fair_value.py) is created in `_watch` and passed as `fair_value_cache=` through `watch_step` → `run_import` → `_write_recommendations` → `recommend` → `recommend_market` → `_valuer` → `sell_rates` → `sell_rate_evidence`. The key is (Market, requested_at, fair_value_slice_share, fair_value_outlier_share). `recommend` calls `start_pass()`, and a pass keeps only the Scans the previous pass used. Pass 2 went from 19.5 s to 10.2 s, and the output is byte-identical. The re-profile is in a comment on #105.
- Review notes left as they are:
  - `brain rebuild` while watching could leave the cache stale until the watcher restarts. Rebuild already says to stop watch first.
  - `seen, fair_value_cache` now travel together through `_valuer`/`sell_rates`/`sell_rate_evidence` (a data clump, like `seen` in slice 1). If a third per-pass input shows up, bundle them.
  - The replay and one-shot `brain recommend` don't use the cache (without one, each `sell_rate_evidence` builds its own).
  - `fair_values()` hands back the cached dict itself. Callers only read it.
- Gotchas:
  - Bench harness (scratchpad `bench.py`, write it again): copy history.sqlite, `dataclasses.replace(load_config(...), history_path=copy, grades_path=None, archive_dir=None)`, run `recommend` twice in one process with one `FairValueCache`. Modes `time`, `out <file>` (repr of both passes + `run_recommend` text, compare with `cmp`), `prof N` (pass 2). Check that it really passes the cache: the first run here silently didn't (the parameter name was wrong).

Next, in order:
1. #105 slice 3, only if the user wants more: `cheapest_seen` (3.5 s) could read per-Scan data, or look at the parse time (8.2 MB, 5.8 s). Or close #105 and take #71's reload-ready guess once the user has run a real watch pass with the new build (`Import took` in the log).
2. Not at the PC: #77, #84, then triage #103 and #104.

2026-09-28 (later 45): #105 SLICE 1 DONE (28c2d69), with /diagnosing-bugs (perf branch) then /code-review. On the real history, `recommend` went from 49.7 s to 18.3 s, and the output is byte-identical. `recommend_market` loads `listings` once and passes an optional `seen` down to `_valuer`, `_market_lots`, `_lot_costs`, `sell_rates`, `non_stacking`, `sell_rate_evidence` and `disappearances`. `_flips` prices each run in one pass (`_undercut`, `_cheapest`, `_cheapest_from`). The re-profile and the next design question are in a comment on #105.
- Review notes left as they are:
  - `seen` isn't shared yet with `grades` → `_market_lots`/`exit_values`, with `deposit_of`, or with the replay.
  - No direct test for `_cheapest_from`, because the tests only go through public seams. The Flip tests and the real-data diff cover it.
  - `(conn, market, seen)` is a data clump across 7 signatures.
  - `_cheapest_from` differs from `without` only on negative quantities, which the DB never holds.
- Gotchas:
  - Perf harness: scratchpad `bench.py` (modes `out <file>`, `prof N`, `parse`) runs `recommend` on a copy of history.sqlite with `grades_path=None, archive_dir=None`. It's session scratch, so write it again from this description. Check "identical" with `cmp` on `repr(recommend(...))` plus the `run_recommend` text.
  - The SQL for `supply_at` is floored at ~0.2 s per Scan (a full walk over the 440k Listings). A batched query over every Scan was slower (11.7 s). Don't retry the SQL route.
  - A Python `read_text`/`write_text` edit turns files into CRLF on Windows. That's fine here: autocrlf=true, and every edited file stayed consistent.

Next, in order:
1. #105 slice 2: per-Scan Fair Values, computed once rather than every pass (~9 s of the 18 s). Ask the user first: (a) a cache in the watcher process, or (b) a table written at import (schema change, ADR). Then the parse time (8.2 MB, 5.8 s) and #71's reload-ready guess.
2. Not at the PC: #77, #84, then triage #103 and #104.

2026-09-28 (later 44): #102 DONE (3ef8724), with /tdd then /code-review. A bound unit is Disenchanted only by the Character who holds it, and only if that Character can (`_disenchants(..., bound)`, `_bound_by`, `_holders`, `_NextUnit`). Otherwise it's Vendored. Unbound units stay pooled. `exit_values` runs the Disenchant marginal rule once over all of `held` (`_Valuer.best_exit` is gone), and so do Grades' open units. The replay passes `market_bound` for its untouched Holdings. ADR-0018 and CONTEXT (Disenchant, Best Exit Value) say so.
- Review fixes made: Grades are valued jointly too (the Spec review caught them), a `_bound(h)` helper, `_NextUnit` instead of a bare tuple, and "Sale Horizon" instead of "sale slots" in the docs.
- Review notes left as they are:
  - The replay queries `_by_character` twice per tick (`market_holdings` + `market_bound`).
  - `exit_values` with `bound` left out Disenchants no bound unit. That's safe today, since only the replay passes bound units.
  - A crafted bound-on-craft output has no holder in `bound`, so it isn't Disenchanted (#77 territory).
  - One Item Key can now get two Disenchant rows, one per Character.
- Gotchas:
  - Grade freeze tests now monkeypatch `brain.recommend.exit_values` (`valued_at_nothing`), not `_exit_value`. `held_at_writing` still uses `_exit_value`.

- Same session, after #102: the Brain looked stuck on old data because `brain watch` wasn't running (nothing imported since 19:42). A manual `brain import` fixed it. Filed #104 (the Addon warns when the Brain is behind) and #105 (a watcher pass takes 55.8 s: 10.6 s parsing SavedVariables and about 45 s in `recommend`; the profile is on the issue).
  - A `brain watch` started by Claude dies with the session. The user runs it in their own terminal.
  - To check whether the Brain is behind, compare the newest `requestedAt` in SavedVariables (`parse_savedvariables`) with `MAX(requested_at)` in `scan`.
  - To profile without side effects, copy `history.sqlite` to the scratchpad and run `recommend` on it with `grades_path=None`. That doesn't write `Recommendations.lua`.

Next, in order:
1. #105 first (the user asked for it): triage it, then speed up with a profile after each change, and keep the `brain recommend` output identical.
2. Not at the PC: #77, #84, then triage #103 and #104.
2. Next PC sitting: unchanged from "later 38", plus the #88 slice 2 and slice 3 checks on #85 (restart the client first).

2026-09-28 (later 43): #101 DONE (9565f97), with /tdd then /code-review. Per day = profit / max(days, 1) in `per_day` (recommend.py) and `measures` (RecommendationTable.lua), and CONTEXT **Per day** says so. Tests: `per_day` unit tests, a Shopping List ranking test (a fast one-off Tin no longer takes a Per day top row from a bigger Linen Flip), and an Addon spec (days 0.125 shows the Profit). Both reviews came back clean apart from wording, which was fixed.
- Gotchas:
  - Never use `git stash push <path>` to check a test goes red. Here it failed on a pathspec, and the `git stash pop` after it popped the user's older `stash@{0}` ("pre-pull local changes 2026-09-28"). That conflicted, and the recovery (`git reset`) cleared the `skip-worktree` flag on `addon/AzerothQuant/Recommendations.lua`, which then had to be set again (README.md, line 84). `stash@{0}` is still there, untouched. To check red, edit the code by hand instead.

Next, in order:
1. Not at the PC: #102, #77, #84, then triage #103.
2. Next PC sitting: unchanged from "later 38", plus the #88 slice 2 and slice 3 checks on #85 (restart the client first).

2026-09-28 (later 42): #88 SLICE 3 DONE (8fda1f3), with /tdd then /code-review. Disenchant Buy Unders: the Disenchant way on an Item Key (`_disenchant_way`: expected mats at their own `_way_out`, a mat's Craft way included), Buy Under per Disenchant source group (`_cheapest_by_group`, `_Disenchanting.group`/`disenchanter`, gated on the group's highest item level, effort = `non_stacking_effort_copper`), `BuyUnder.group` (item_key None on a group row), `buyUnder` group entries + `disenchantExcluded` in Recommendations.lua, group rows in `brain recommend` (`_group_name` shared with `brain disenchants`). Addon: `DisenchantGroup.lua` (name, contains), tab group rows (`Disenchant (Bob) -> <mats>`), tooltip line and AH flag take the higher of item and group. The .toc changed, so restart the client. The PC check is on #85. #88 stays open only for its PC checks (slices 2 and 3).
- Decided with the user: `disenchantBands` dropped (group entries carry their bounds). The Addon arrow is "->" (font safety, like "no limit").
- Review notes left as they are: the `add` closure in `_buy_unders` with an item_key/group pair (only one set, not enforced), Tooltip.lua calling `forLink` twice for the #96 fallback, and one full mat drops the whole Disenchant way (slice 1's rule).
- Gotchas:
  - The lupa `lua -e` shim works: a `lua.bat` calling a Python script that runs `lupa.lua51.LuaRuntime().execute(argv[2])` with `print` overridden to write tab-joined `tostring`s to stdout. Point `LUA` at the .bat (Windows path) and the Recommendations.lua tests stop skipping. It's still scratchpad-only; worth adding to `scripts/` (ask first).
  - Never start a Bash command with a bare `cat > file` with no input: it waits on stdin until the 2-min timeout.
  - `Scan.fromGetItemInfo(getItemInfo(x))` is the one helper for item info in glue. Don't hand-roll the 12-return unpack again.
  - Found on the client after the commit: the AH item lists have no view at ADDON_LOADED of Blizzard_AuctionHouseUI, so `ScrollBox:ForEachFrame` threw. Fixed in 3b9fc6d (`refreshShown` checks `GetView()`). The user confirmed that the AH opens cleanly after a /reload. The rest of the #85 checks (highlights, group rows, tooltips) are still open.
  - The Beta client HAS a global `require` (a module loader for other addons) that throws "Invalid import". The `ns.X or require("X")` fallback, meant only for busted, throws in game whenever a new file is added and the client is only /reloaded, not restarted. The fix is a client restart. Not filed.

Next, in order:
1. Not at the PC: #101 (small, ready-for-agent), #102, #77, #84, then triage #103.
2. Next PC sitting: unchanged from "later 38", plus the #88 slice 2 and slice 3 checks on #85 (restart the client first).

2026-09-28 (later 41): #88 SLICE 2 DONE (9886c89), with /tdd then /code-review. Addon half of Buy Under: a 5th Recommendation Table tab `Buy Under (N)` (Item, Buy Under, Way out, Units, Seen, Note), the tooltip line `AQ: Buy Under 21s: Craft <output> (<crafter>), seen 14 Scans / 7d` (forLink and forItemName), `BuyUnderMatch.lua` (plain Lua + busted: by link, or itemID + row name for suffixed browse rows), and `BuyUnderHighlight.lua` (glue: a green wash via `ScrollUtil.AddInitializedFrameCallback` on the browse, item and commodity lists, plus a re-flag on ITEM_KEY_ITEM_INFO_RECEIVED). The .toc gained both files, so the client needs a restart. The PC check is a comment on #85.
- Decided with the user: Units shows "no limit", not ∞ (the font may lack the glyph). The tab is the 5th. The tooltip line has the "AQ: " prefix.
- Review fixes made: "auction" renamed to "listing" (CONTEXT bans "auction"), the CONTEXT Recommendation Table entry now lists Buy Unders, the default sort is written as `{}` with a comment (Brain order via the tie-break), and rows already on show get flagged at hook time.
- Review notes left as they are: the itemID + name match exists in both `BuyUnderMatch.matches` and `TooltipLines.forItemName`, and `TooltipLines.itemKey` is exported for the matcher (it could move next to `RecommendationTable.itemString`).
- Gotchas:
  - `lowValue` treats a row with `way` as not low, and `heldUnits` skips rows with no `quantity`. Slice 3's group rows must carry `way` too.
  - `RecommendationTable.wayOut` needs `output` and `crafter` on a Craft row. Slice 3 adds a "Disenchant" way: give it a branch there.
  - The glue relies on untested client facts: `row.rowData` being set at init, `buyoutAmount` being the total for the Listing, and the browse `minPrice` being per unit. They are listed on #85.
  - Blizzard's CallbackRegistry keeps one callback per owner, so hook with an owner table of your own, never the Blizzard frame.

Next, in order:
1. Not at the PC: #88 slice 3, Disenchant (/tdd; the second comment on #88, plus the gotchas above). Then #101, #102, #77, #84, and triage #103.
2. Next PC sitting: unchanged from "later 38", plus the #88 slice 2 check on #85 (restart the client first).

2026-09-28 (later 40): #88 SLICE 1 DONE (bd7f467), with /tdd then /code-review. #88 is split in 3 slices (agreed with the user): 1 the Brain, 2 the Addon, 3 Disenchant.
- Slice 1: `BuyUnder` / `MarketRecommendations.buy_under` in recommend.py (`_buy_unders`, `_way_out`, `_sell_way`, `_craft_way`, `_under_margin`), `history.cheapest_seen` (one query, distinct Scans), `_Sources.chain_without` for a Craft way's other reagents (Holdings ignored). The config keys `buy_under_min_sightings`/`buy_under_window_days`, a Buy Under section in `brain recommend`, and `buyUnder` in Recommendations.lua (`{ itemKey, price, way, units?, seen, windowDays, listedNow?, recipe?, output?, crafter? }`; `output` is the Craft output Item Key, for the tab's `Craft <output> (<crafter>)`). CONTEXT **Buy Under**, and ADR-0019.
- Decisions made in the build: a way with 0 units isn't a way (falls back to the next); Craft units are whole crafts (`room // quantity_min * qty`); a Craft output that binds on craft, or whose bind type is unknown, counts only its Vendor Price; the replay passes `buy_under=False` (it adds ~4.5 s per recommend on the real history, mostly the query).
- On the real history, `brain recommend` shows ~dozens of Sell-way Buy Unders. The whole recommend takes ~50 s, and Buy Under isn't the slow part (`without` in `_post_at`, `listings`, `supply_at` are).
- Review notes left as they are: `BuyUnder`'s recipe_id/output/crafter could be one optional type; `_under_margin` restates the Flip margin rule that `_resells` and `_flip_step` also spell out.
- Gotchas:
  - A 1-unit Listing reads as non-stacking, so it pays the 5s effort. Use `quantity=20` in Buy Under test fixtures unless effort is the point.
  - No Lua on this PC, so the Recommendations.lua tests skip. A `lua -e` shim on lupa is easy: a .bat calling a Python script that runs `lupa.lua51.LuaRuntime().execute(argv[2])` with a `print` override. Set `LUA` to the .bat. It lived only in the session scratchpad; worth adding to `scripts/` (ask first).

Next, in order:
1. Not at the PC: #88 slice 2, the Addon (/tdd): the Buy Under tab (4th section), the tooltip line, and the AH highlight matcher (plain Lua + busted specs, thin frame glue on the ScrollBox row init; .toc change). Then slice 3, Disenchant (the second comment on #88). Then #101, #102, #77, #84, and triage #103.
2. Next PC sitting: unchanged from "later 38", plus the #88 PC check once slice 2 is in.

2026-09-28 (later 39): TRIAGED #101 and #102. No code. Both are now bug + ready-for-agent + later, with agent briefs as comments on the issues.
- #101 Per day: floor at 1 day, not the Sale Horizon (a Sale Horizon floor would make Per day = Profit/7 for nearly every Flip). The Addon computes Per day on its own in RecommendationTable.lua `measures`, so fix it there too, plus CONTEXT **Per day**.
- #102: item 1 (bound units only Disenchanted by the Character holding them) and item 2 (Best Exit Value values Disenchant mats jointly across all held Item Keys; the user chose to fix it, not accept it). Item 3 is split out as #103 (needs-triage): `known_recipes` and `enchanting_skills` have no as-of, so the replay and Grades use today's recipes and skills. Item Info as-of doesn't matter.
- #88 wasn't started: triage filled the session budget.

Next, in order:
1. Not at the PC: #88 Buy Under (/tdd; spec comment and hooks comment on #88), then #101 (small), #102, #77, #84, then triage #103.
2. Next PC sitting: unchanged from "later 38".

2026-09-28 (later 38): #76 SLICE 2 DONE (ac81a0b), with /tdd then /code-review. Disenchant Results: `DisenchantCapture.lua` (plain Lua, busted specs) is fed by Character.lua on UNIT_SPELLCAST_START/SUCCEEDED 13262 and LOOT_READY. The item is the bag diff from cast start; a Result waits up to 5 s of bag reads for the item to leave, then falls back to mats only. Results ride on Character Reads as `disenchantResults` into the Brain tables `disenchant_result` + `disenchant_result_mat`. `brain disenchants` (`disenchant_check.py`) runs Wilson + exact t-intervals (A&S 26.7.3/4, no new deps), with `disenchant_check_min_results` = 20. CONTEXT "Disenchant Result" and the ADR-0018 amendment are done. The event-order probe is a comment on #85. #76 stays open only for its PC check. Its Buy Under parts are #88, Flip to Disenchant is #89, and the chain node is #77.
- New tool: `scripts/busted.py` runs addon/spec on lupa's Lua 5.1 (`pip install lupa`, then `python ../scripts/busted.py` from addon/). It only knows the busted API the specs use; add to it when a spec needs more. CI still runs real busted.
- Gotchas:
  - Heredocs in the Bash tool here turn `\\n` inside Python source into a real newline. Write edit scripts with the Write tool into the scratchpad and run them, rather than `python - <<'EOF'` with escapes.
  - `ruff` isn't on PATH: use `python -m ruff`.
  - A background `brain watch` from an earlier session was killed for low memory on 2026-09-28. It is NOT running. Restart it at the next PC sitting.
- Review notes left as they are: `CharacterRead.build` now takes 7 positional args (a candidate for an options table if an 8th comes). Mats show as item IDs in `brain disenchants`, with no names.

Next, in order:
1. Not at the PC: #101 (triage: 1 day vs Sale Horizon), #102 (triage), #88 (with the Disenchant Buy Under; see the #88 comment for hooks), #77, #84.
2. Next PC sitting: restart `brain watch`, then the #85 checks from "later 35" and "later 37", plus the new Disenchant probe comment on #85 (does UNIT_SPELLCAST_START fire for Disenchant? is the green gone at LOOT_READY?).

2026-09-28 (later 37): #76 SLICE 1 DONE (e8da1ea), with /tdd then /code-review. It adds the Disenchant data file (`brain/src/brain/data/disenchant.toml`, `disenchant.py`), Item Info from Scans AND Character Reads (a bound green is never scanned), the Enchanting skill on `known_profession`, the Holdings Disenchant Action (Craft's marginal rule, with fractional mats interpolated), and Best Exit Value with the Disenchant way (`_Valuer.best_exit`; `worth` stays Sell/Vendor for Crafts). The replay treats Disenchant rows as kept. ADR-0018 is new, and CONTEXT.md gained Disenchant and Disenchant source group.
- Scope decided with the user: the Buy Under parts of #76 moved to #88 (comment on #88 lists the hooks to build on). #76 stays open for slice 2.
- Review follow-ups filed as #102 (needs-triage): bound units on a non-enchanter Character, Best Exit Value ignoring held mats, as-of look-ahead of skills and Item Info.
- PC check added to #85 (the Scan `itemInfo`, `skill_level`, a bound green's Disenchant row and tooltip).
- Gotchas:
  - No Lua on this PC. `pip install lupa` works, and a busted stand-in lives only in the session scratchpad (describe/it/assert.are.same etc. on lupa's Lua 5.1). It's worth making a real `scripts/` tool if Lua work keeps coming; ask first.
  - Python `open()` defaults to cp1252 here: always pass `encoding="utf-8"` when scripting edits (a `×` got double-encoded once).
  - The review found real bugs twice: the marginal valuation for mats of 1 or more units, and `Money.format(nil)` on a priceless tooltip row. A Holdings row without `price` needs its own `holdingLine` branch.

Next, in order:
1. Not at the PC: #76 slice 2. Disenchant Results capture: Addon, plain Lua + specs, on UNIT_SPELLCAST_SUCCEEDED 13262 → LOOT_READY with a bag diff, into a `disenchantResults` list on Character Reads. Then a Brain table, `brain disenchants` (Wilson / t-interval, `disenchant_check_min_results` = 20), the CONTEXT "Disenchant Result" update and the ADR-0018 amendment. Add the event-order probe to #85. Then #101 (triage: 1 day vs Sale Horizon), #102 (triage), #88 (now with the Disenchant Buy Under), #77, #84.
2. Next PC sitting: the #85 checks in "later 35" plus the new #76 ones.

2026-09-28 (later 36): Discussion only, no code. The user asked why Kingsblood's Per day was 9g 50s on a Qty 1, 3s 71c flip. Its Sell Rate is ~250 units/day after the priors (448 units in 13 Sale Events over 7.7 h, with chunks of 124/63/54/47), so one unit clears in ~6 min, and Profit/days blows up. Filed #101 (needs-triage): floor Per day's days at 1 (or the Sale Horizon) so Per day never beats Profit, and update CONTEXT.md. Not filed: mass cancels look the same as mass buys in Sell Rate (no seller data). The user may want that filed later.

Next, in order:
1. Not at the PC: #76 Disenchant (ready-for-agent, spec on the issue), then #101 (triage it first: 1 day vs Sale Horizon), #88, #77, #84.
2. Next PC sitting: the #85 checks in "later 35".

2026-09-28 (later 35): #100 FIXED and closed (97ce455), found with /diagnosing-bugs. Root cause confirmed with an in-game probe: taking a mail restarted the 2 s quiet timer, so the mail was gone before the Read. Now `MailboxVisit.lua` saves a Read on every update that changed the AH mail. Verified in game: a Magefist Gloves won mail taken right away became a Purchase. `brain rebuild` done, and `brain watch` restarted on current main.
- Found on the client and fixed in the same commit: headers can show `Retrieving data` (no Read is saved then), and a taken mail lingers for a moment with nothing attached, which double-counted a Willow Belt sale (`parse_mail` now returns None for it). Also, a Read with any unreadable mail no longer marks mail taken, and `readAt` is bumped to stay increasing across visits (ADR-0005 amendment, CONTEXT.md "Mailbox Read").
- Client facts (probe): MAIL_SHOW comes with 0 mails, and the first MAIL_INBOX_UPDATE ~0.3 s later has headers ready. Reading headers causes no update loop. MAIL_CLOSED did NOT show up in the probe log. An empty inbox fires no update. For probes, log to `AzerothQuantDB.<key>` and read SavedVariables after /reload, since chat only shows a few lines.
- Parked on #85: `/reload` plus a mailbox visit with no Lua errors (the post-review glue change isn't run in game yet), and the #50 Paid tooltip. The data is verified (Magefist Gloves paid=12000, roi=-5%), but the gloves were sold before the tooltip was checked. It needs any held AH buy with a Holdings Sell/Vendor row.
- Still parked: "show Paid on any held item with a Purchase Lot, whatever its row" (the user's "bought for" idea). File it only if the #50 line isn't enough once seen. Paid stays a hint (ADR-0003, sunk cost).
- The Hunter's Muzzle Loader `Auction canceled` warning is NOT the mid-take case: it has money 1600 and no item. It's still unexplained, and still unfiled.

Next, in order:
1. Not at the PC: #76 Disenchant (ready-for-agent, spec on the issue), then #88, #77, #84.
2. Next PC sitting: the two new #85 checks above, plus the rest of #85.

2026-09-28 (later 34): PC CHECKS DONE for #95, #96 and #98, all closed. `brain watch` restarted (it wasn't running), then stopped for `brain rebuild` (26 Scans, 0 rejected, 2.5 min) and started again on current main.
- #95: the client prints `Between 2 hrs and 12 hrs` / `Greater than 12 hrs`, so the defaults are now <30m, 30m-2h, 2-12h, 12-24h (740b0fe; bucket 4 capped at 24 h, the longest Forever post).
- #96: PASS on the Willow Belt of the Sorcerer browse row.
- #98: PASS, including a clicked sort surviving /reload. Fixed on the spot: Profit/Per click/Per day truncated gold (widened, 772fae8). Truncated cells show their full text as a bare tooltip line (RecommendationFrame.lua), which looked like stray lines.
- #85 stays open: #50 is blocked by the new bug #100 (a won-mail taken within ~2 s of opening the mailbox is never read; hypothesis on the issue), #33/#75 have no data, #83 replay waits until ~Oct 3, Booty Bay Broker optional.
- Noted on #92: one import took 50.7 s, just over RELOAD_READY_AFTER = 50.
- Unchecked: `brain rebuild` logs `skipped a mail: missing or bad 'firstItemQuantity'` for an `Auction canceled` mail (Hunter's Muzzle Loader). Probably old; nobody has looked.

Next, in order:
1. #100 (core bug, needs-triage): diagnose at the PC (the confirm steps are on the issue), then fix. It unblocks the #50 check.
   After #100, recheck the Paid tooltip line from #50 in game. The user wants a "bought for" reminder on held flips (e.g. undercut, relist lower). The line already exists but only shows on a Holdings Sell/Vendor row. If that's not enough, file: "Tooltip: show Paid for any held item with an open Purchase Lot, whatever its row" (refs #50, #100). Paid stays a hint only (ADR-0003, sunk cost).
2. Not at the PC: #76 Disenchant (ready-for-agent, spec on the issue), then #88, #77, #84.

2026-09-28 (later 33): #98 is MERGED to main (the cloud branch landed), and the review questions are settled in 12189b8: (a) replay `_taken` grades only the profit top `shopping_list_rows` Flips (`_brain`/`_taken` take `flip_rows`); (b) a clicked sort is saved per tab in `AzerothQuantDB.recommendationSorts`, by column NAME (`RecommendationTable.savedSort`/`restoredSort`), so it survives column changes; (c) the Per day cut ranks Flips to Sell only. ADR-0017 amendment + CONTEXT.md updated. #98 stays open for its PC check (below).

`core` is now ALL PC work (plus #83, which can't grade anything before ~Oct 3). The user has a free week of usage until ~Oct 5, so do `later` issues too.

Next, in order:
1. At the PC (one sitting, one session): the (later 30) #95/#96 checks, the #98 check from (later 32) plus "sort by ROI, /reload, still sorted by ROI", and the #85 checklist. Restart `brain watch` first (Brain commits since the last restart).
2. Not at the PC: #76 Disenchant (ready-for-agent, spec on the issue). It's the base for #88 Buy Under, #89 Flip to Disenchant and a node kind in #77, so it goes first. Then #88, #77, #84 (#84 matters for the #83 Oct 21 read).

2026-09-28 (later 31): #98 GRILLED (3 rounds), spec on the issue, ready-for-agent + core. The Shopping List tab only (Flips to Sell and Flips to Vendor; the Flips to Craft tab is unchanged). New per-row measures:
- Per click = Profit / (Listings bought + stacks posted). Listings are counted exactly, so don't merge same-price Listings before counting. Posts = ceil(units / usual Sale Event size); a Flip to Vendor posts nothing.
- Per day = Profit / days until the run's last unit sells, with held units queued ahead (the Deposit queue). A Flip to Vendor shows "now".
- ROI = Profit / Cost.

The cut keeps a row in the top `shopping_list_rows` on ANY of Profit / Per click / Per day / ROI. The buying order, the Sale Horizon and the replay are unchanged. Recommendations.lua gets `listings`, `posts` and `days`; the Addon gets sortable Per click / Per day / ROI columns (it opens on Profit and remembers the clicked sort) and the tooltip line `12 Listings + 3 posts, sells in ~2.5 days`. The CLI gets the columns too.

Also this session: #90/#91 were NOT decided. A spec was posted there by mistake, then withdrawn (the comments say so), and the labels are back to needs-triage + later. #99 (black market NPC) was filed and then closed as not planned. It can be refiled when #91 is grilled.

Next, in order:
1. #98 build (/tdd), then /code-review + commit. It needs no PC.
2. At the PC: the (later 30) and (later 27) checks.
3. Once `core` is empty: ask whether #90 or #97 move to `core`.

2026-09-28 (later 32): #98 BUILT on branch `claude/zen-mccarthy-xaqoze` (a cloud session, so not on `main` yet). Commits 582b28d + the review-fix commit after it. The issue is still open and labelled needs-pc.
- Brain:
  - Each Flip to Sell and Flip to Vendor row gets `listings`, `posts` and `days`. `_listings_left` keeps same-price Listings apart for the Flip to Vendor count; the old `without` merged them. `_SellRun.listings` is `len(units)`.
  - Posts use `_Valuer.stack`: the usual Sale Event size under the Flip prior (`_sale_size`), or 1 for an Item Key that doesn't stack.
  - `days` = (held + bought) / units per day under the Flip priors.
  - `_options` keeps a row that's in the top `shopping_list_rows` by any of `_profit`, `per_click`, `per_day` or `return_on_cost`, ties going to profit.
  - The new Row fields are `compare=False`, so tests assert them on their own.
- CLI: Per click, Per day and ROI columns after Profit.
- Addon: the Shopping List tab has 11 columns (`flipCells`/`flipKeys`). Flips to Craft keeps the old 8. Tooltip lines: `N Listings + M posts, sells in ~2.5 days`, `~N h` for a wait under a day, and `N Listings, vendor now` for a Flip to Vendor. The frame's MAX_COLUMNS is 11, with new Shopping List widths.
- CONTEXT.md (**Per click**, **Per day**) and the ADR-0017 amendment are done.

Review leftovers. Open questions for the user:
- (a) Replay `_taken` walks the longer list (up to 200 Flips), so replay numbers can change. The spec says the replay is "not changed". Accept this, or make replay walk only the profit top 50?
- (b) "The sort you click is remembered". Today a clicked sort resets on each open, as before. Should it persist in `AzerothQuantDB`?
- (c) Every Flip to Vendor ties at "now" on Per day. With 50+ of them, no Flip to Sell gets in on Per day.
Judgement calls, not done:
- `posts`/`stack` vs the Listing entry's _Avoid_ ("post", "stack"). The names come from the spec.
- The Lua `flipCells` inserts cells by index.
- No zero guard on `days` (a run needs a Sell Rate, so it's safe today).

User to do at the PC (add to #85): /reload (no new files). Open the Shopping List tab and check:
- The 11 columns fit, and Note isn't clipped badly.
- Sorting by Per click, Per day and ROI works, and Flips to Vendor show `now`.
- The tooltip line reads right.
Then close #98.

Next, in order:
1. Merge `claude/zen-mccarthy-xaqoze` into `main`, and answer the (a)-(c) questions above.
2. At the PC: the (later 30) list, the #98 check above, the (later 27) client restart and the #85 checklist, plus #86, #18 and #51.
3. Once `core` is empty: ask whether #90 or #97 move to `core`.

2026-09-28 (later 31): #98 GRILLED (the spec is on the issue), ready-for-agent, `core`. The Shopping List tab only (Flips to Sell and Flips to Vendor; the Flips to Craft tab is unchanged). Each row gets `listings`, `posts` and `days`. Per click = Profit ÷ (Listings bought + stacks posted at the usual Sale Event size); Per day = Profit ÷ days until the run's last unit sells, held units queued ahead (a Flip to Vendor shows "now"); ROI = Profit ÷ Cost. The cut keeps a row in the top 50 on ANY of Profit/Per click/Per day/ROI. The buying order, Budgets, Sale Horizon and replay are unchanged. Addon: sortable columns, opens on Profit, tooltip `12 Listings + 3 posts, sells in ~2.5 days`. Gotcha: `_without` merges same-price Listings, so count Listings before merging.
Mix-up this session (now undone): I took the user's #98 answers as answers about #90/#91, and posted and then withdrew specs there. #90 and #91 are still needs-triage/`later`, and #99 was closed as not planned. #90 still has its Nov 4 deadline: ask the user.

Next, in order:
1. #98 build (/tdd), then /code-review + commit. This is the last core item that needs no PC.
2. At the PC: the (later 30) list, the (later 27) client restart and the #85 checklist, plus #86, #18 and #51.
3. Once `core` is empty: ask whether #90 or #97 move to `core`.

2026-09-28 (later 30): #95 and #96 BUILT here (no PC), both labelled needs-pc for the in-game checks.
- #95 (d832a11): time-left buckets now default to Classic's <30m, 30m-2h, 2-8h, 8-24h. Matching and expiry read these at import, so a `brain rebuild` is needed. Also check that brain/config.toml doesn't set `time_left_max_minutes`.
- #96: when a tooltip's link finds no lines, `TooltipLines.forItemName` matches the Market's Item Keys of that itemID by the row's name. The name comes from `owner.rowData.itemKey` via `C_AuctionHouse.GetItemKeyInfo`, else the tooltip's title line. That owner shape is a guess from retail's AH UI. The fallback covers it if the title shows the suffixed name.

Next, in order:
1. At the PC: `/reload`, then:
   - #95: `/run print(AUCTION_TIME_LEFT3_DETAIL, AUCTION_TIME_LEFT4_DETAIL)` should print 2-8 h / 8-24 h (otherwise, set the default to what it says). Then `brain rebuild`. Close #95.
   - #96: hover the "Willow Belt of the Sorcerer" browse row. AQ lines should show. If not, `/run local o=GameTooltip:GetOwner() print(o and o.rowData and o.rowData.itemKey and o.rowData.itemKey.itemID, GameTooltipTextLeft1:GetText())` while hovering, and fix from that. Close #96.
2. Once `core` is empty: ask whether #90, #97 or #98 move to `core`.

2026-09-28 (later 29): FILED two user ideas as `later` + needs-triage. #97: take a Shopping List row off (or mark it, or cut its Qty) once the player buys it. The Addon never buys (ADR-0016), so it needs a PC probe of which AH buy events Forever fires and what they carry. #98: rank the Shopping List by profit for the effort and risk (Listings to click, time to sell, market depth), not by raw profit. The open questions are on each issue. No code changed.

Next, in order: unchanged from (later 28): #96, then #95 (both `core`, both need the PC). Then ask whether #90, #97 or #98 move to `core`, and grill whichever does.

2026-09-28 (later 28): PC CHECKS DONE. Client restarted, `brain rebuild` (23 Scans, clean), `brain watch` restarted. Closed: #53, #86, #87, #18, #51, and #94 (a bug found and fixed on the spot: row tooltips repeated the hook's `On <Character>`/`Use` lines; now `showTooltip` skips lines already on the tooltip). Commits: c29e23d/c10d14f (Nudge.RELOAD_READY_AFTER 10 -> 50: real imports take 33-42 s even with 0 new Scans, filed #92 `later`), ec76ab6 (#94), d0f2e1c (#78: Forever posts for 2/8/24 h only, deposit = floor(Vendor Price x 5%) x 1/4/12, so `post_duration_hours` defaults to 24; 0.60 share confirmed; no 1s minimum).
- #83: `brain replay` graded 0 Scans. Beta history is only 51.6 h, and the horizon is 7 days. Re-run from about Oct 3, and again before Oct 21. Noted on #83.
- #85 stays open. Not checkable on today's data: #50 (no AH-bought Holdings), #33 (no chained Craft row), #75 (no blocked Craft row). Booty Bay Broker follow-up is optional.
- Filed: #93 `later` (an all-folded tab says "No X right now" above its fold line), #95 `core` needs-triage (time-left buckets assume 12-48 h, but Forever's max post is 24 h), #96 `core` bug (AH browse rows for suffixed items have no AQ lines: the tooltip link lacks the suffix).
- The AH event-name chat spam came from the old AQProbe spike addon, not AQ; the user disabled it.
- Flips to Craft is empty on real data because no craft clears the Flip margin (best: 41c on 14s 94c), so it isn't a bug. To test the tab, temporarily set `flip_min_margin_share = 0` / `flip_min_margin_copper = 0` at the top of brain/config.toml.
- Changing only the Budget never fires the "Brain should be done" nudge (that needs a new Scan), so it's easy to reload before the import is done.
- The user's local pre-pull changes (1072 lines, looked like an older copy of the #86 work) are in `git stash` ("pre-pull local changes 2026-09-28"). Ask before dropping them.

Next, in order:
1. #96: probe the AH browse row's itemKey in game (a short /run), then fix the tooltip Item Key for suffixed items. It needs the PC.
2. #95: grill or probe which time-left bucket an 8 h and a 24 h post show on the Beta, then fix the default.
3. Once `core` is empty: ask whether #90 (Beta Prior, Nov 4 deadline) moves to `core`. Then the `later` queue.

2026-09-28 (later 27): #53 GRILLED and BUILT, on `main`. The spec is the grill comment on the issue. New plain-Lua `Chat.lua` (first logic module in the .toc): `Chat.say` always prints; `Chat.debug` prints only while `AzerothQuantDB.debug`, which `/aq debug` flips (saved, off by default). The five local `say` helpers are gone. Debug-only now: the `Deleted N …` prune lines, `Mailbox Read saved`, `Read N recipes`, `Scan requested`, `N saved Scans not imported`, `Scan ready` (the pulsing buttons cover the last two). busted: `spec/chat_spec.lua`. `claude/zen-mccarthy-xaqoze` was already equal to `main` (the #87 merge is done). #86, #87, #18 and #53 are relabelled `needs-pc`: every open `core` issue now waits only on the PC (or on live data for #83). The #53 checks were added to #85 as a comment. Review notes left as they are (judgement calls): Chat reads the `AzerothQuantDB` and `print` globals instead of having them injected like Nudge does; `debug` guards against a nil db but `toggleDebug` doesn't (a slash command can't run before ADDON_LOADED).

Next, in order:
1. At the PC: a full CLIENT RESTART first (Chat.lua is a new file). Then the #85 checklist (including `brain replay` for #83, the #87 tab check and the new #53 chat check), the PC checks on #86 and #18, and #51. File a `core` bug for anything that fails, and close each issue once its checks pass.
2. Once `core` is empty: ask the user whether #90 (Beta Prior, Nov 4 deadline) moves to `core`. Then the `later` queue.

2026-09-28 (later 26): #87 BUILT on branch `claude/zen-mccarthy-xaqoze` (a cloud session, so it's not on `main` yet: merge it before the PC checks). `_options` cuts the Flips to Sell and Flips to Vendor to `shopping_list_rows` (50), and the Flips to Craft apart to the new `craft_list_rows` (25). `shopping` is still one list sorted by profit. The Addon splits `shoppingList` into a **Flips to Craft** tab after the Shopping List. It splits on `action == "Craft"`, not `r.buys`, because the writer leaves out an empty `buys`. Each tab folds its own options over the Budget. ADR-0017 amendment and CONTEXT.md updated. The PC check was added to #85 as a comment. The #85/#86/#18/#51 PC checks were NOT done: the user was away from the PC. Review notes left as they are (judgement calls): `load_config` has four copies of the whole-number check, where a `_parse_whole` helper would fit; the Addon still tests `r.buys` for "is a Flip to Craft" in its cells and tooltips.

Next, in order:
1. Merge `claude/zen-mccarthy-xaqoze` into `main`. Then, at the PC: the #85 checklist (including `brain replay` for #83 and the new #87 tab check), the PC checks on #86 and #18, and #51. File a `core` bug for anything that fails. Close #87 once its tab check passes.
2. #53 grill, then build.

2026-09-28 (later 25): SCOPED. Every open issue now has a `core` or `later` label (see docs/agents/triage-labels.md). Work only on `core` until that queue is empty; new issues default to `later`. The Next lists in the older entries below are superseded by this one.
- core: #85, #86 and #18 (PC checks of built features), #51 (PC check), #83 (the Beta replay read, by Oct 21), #87 (Flips to Craft section), #53 (quieter chat).
- later: everything else, including #84, #88, #76, #77, #89, #90 and #91. #90 (Beta Prior) has a Nov 4 deadline, so as `later` it most likely won't make launch. Ask the user whether to move it to `core` or accept thin recommendations for the first days of Live.

Next, in order:
1. At the PC: the #85 checklist (including `brain replay` for #83), the PC checks on #86 and #18, and #51. File a `core` bug for anything that fails.
2. #87 build (/tdd), then /code-review + commit. It needs no PC.
3. #53 grill, then build.

2026-09-28 (later 24): FILED #91 (needs-triage) from the user's list of launch predictions: endgame potion mats, T1 reagents, Enchanting mats, and Uncommon Waylaid Supply Crates ("invest early"). Some are sold by a "black market" NPC. The issue lists the open questions. (1) Buy-and-hold Prediction vs "Hold what you farm". (2) With no Best Exit Value there's no Max Loss, so no Prediction buys at launch; the Beta Prior (#90) might fill that gap. (3) The itemIDs are unchecked, and several names look like Forever additions. (4) Limited-stock NPC items are never read as Merchant Cost. (5) The Catalyst. The user then clarified that all of these are buy-and-Hold calls with a raid release as the Catalyst, so (1) is settled; see the comment on #91. Grill it together with #90, since both touch launch pricing with no Live history.

Next, in order (none need the PC):
1. /grilling #90 together with #91 (Nov 4 deadline).
2. #84 build (/tdd), then /code-review + commit.
3. #87 build (/tdd), small, then /code-review + commit.
4. #88 build (/tdd), then /code-review + commit.
5. #77 build (/tdd), then #76.
6. The needs-triage queue: #89, #53, #54, #55, #56, #58, #60, #61.

2026-09-28 (later 23): FILED #90 (needs-triage) from user feedback. Beta Prior: for about the first 2 weeks of Live, show a Beta price column next to the live numbers. It's a reference only, "not gospel", and gets dropped once Live history builds up. Beta Prior exists only as a CONTEXT.md term, and no code reads Beta data in Live. The open questions are on the issue: which number, absolute vs Live/Beta-scaled, display-only vs engine nudge, the cutoff rule, and Beta->Live Market mapping. It must land before Live (Nov 4). The user's message was cut off, so ask whether they had more to add.

Next, in order (none need the PC):
1. /grilling #90 (it has a Nov 4 deadline; the grill is short).
2. #84 build (/tdd), then /code-review + commit.
3. #87 build (/tdd), small, then /code-review + commit.
4. #88 build (/tdd), then /code-review + commit.
5. #77 build (/tdd), then #76.
6. The needs-triage queue: #89, #53, #54, #55, #56, #58, #60, #61.

2026-09-28 (later 22): GRILLED #88, #76 and #87. The specs are comments on the issues, and all three are labelled ready-for-agent. Filed #89 (Flip to Disenchant on the Shopping List, needs-triage, split out of #76).
- #88 Buy Under:
  - One per Item Key, from its best way out: Vendor, Sell, or a Craft it's a reagent of (any Character's Known Recipes, pooled).
  - The value before the margin is `way_out_value`. CONTEXT.md bans "worth", so don't use it as a term. A Craft way costs the other reagents at their cheapest current source and ignores Holdings. The Flip margin and effort are charged once, at the top.
  - Shown only if >= `buy_under_min_sightings` (1) distinct Scans in `buy_under_window_days` (7) saw a Listing under it. Units are ∞ for a Vendor outlet, else the Sell Rate room.
  - Not graded by the replay.
  - Addon: a Buy Under tab, a tooltip line, and a highlight on the modern AuctionHouseFrame ScrollBox rows (needs a PC check).
  - The wand loop is only an example; don't special-case it.
- #76 Disenchant (build after #88):
  - A static `data/disenchant.toml`, re-derived from the wiki tables. TSM's file is All Rights Reserved, so don't copy it.
  - Gated by the Enchanting skill level (new columns on known_profession).
  - Scans record `itemInfo` (ilvl, quality, classID, equipLoc) into an `item_info` table.
  - Disenchant Results are captured in the Addon. `brain disenchants` compares them to the tables with 95% intervals and "too few Results" under 20. The user stressed that a lucky or unlucky run must never read as a table change, and nothing auto-updates.
  - Adds Disenchant as a Holdings Action (bound units too), in Best Exit Value, as group Buy Unders, and as the Craft Chain `disenchant` node.
- #87: `craft_list_rows` (25) as a separate cap for Flips to Craft, in their own `Flips to Craft` tab. Budget folding is per tab. Replay `_taken` is unchanged: it grades the longer shown list, so replay numbers from before this change aren't comparable.
- Research facts (not saved as a file): Forever's Greater Magic Wand likely takes 2 Lesser Magic Essence (from snippets). Forever adds an "Arcane Salvager" said to improve disenchanting, with no numbers published.

Next, in order (none need the PC):
1. #84 build (/tdd), then /code-review + commit.
2. #87 build (/tdd), small, then /code-review + commit.
3. #88 build (/tdd), then /code-review + commit.
4. #77 build (/tdd), then #76.
5. The needs-triage queue: #89, #53, #54, #55, #56, #58, #60, #61.

2026-09-28 (later 21): FILED #87 and #88 from the user's feedback on #86 (both needs-triage).
- #87: Flips to Craft get their own Shopping List section and cap. In the one top-50 list sorted by profit, small craft options lose to big Flips to Sell.
- #88 Buy Under: the Brain computes the most a reagent (per Known Recipe) or a Disenchant source (quality, item-level band, armor or weapon) is worth. A target shows only if past Scans saw Listings under it. The Addon flags Auction House results at or under a target live, since Scans every 15 minutes miss short-lived Listings. The user's example is the Beta Greater Magic Wand loop (DE item level 16-20 green weapons at about 21s or less, craft wands, vendor them). The reagent half doesn't need #76; the Disenchant half does. A comment on #76 links them. "Buy Under" is a proposed CONTEXT.md term (snipe is banned).

Next, in order (none need the PC):
1. /grilling #88 together with #76's open questions. Grill #87 too (small; it could land before #86 closes).
2. #84 build (/tdd), then /code-review + commit.
3. #77 build (/tdd), then /code-review + commit.
4. The needs-triage queue: #53, #54, #55, #56, #58, #60, #61.

2026-09-28 (later 20): #86 BUILT on branch claude/zen-mccarthy-xaqoze (issue still open). This came from the user's in-game feedback: the Shopping List spent all their gold as one greedy basket, where one big Flip crowded out other good options and a tail of copper Flips filled the rest. ADR-0017, and CONTEXT.md gets **Budget** plus updates to **Shopping List**, **Sell**, **Flip**, **Holdings**, **Sub-craft**, **Deposit** and **Best Exit Value**. ADR-0010 is superseded, and ADR-0011 and ADR-0009 (#69) are superseded in part.
- Brain:
  - The Shopping List is **options**: one per Item Key's Flip to Sell or Flip to Vendor, and one per recipe's Flips to Craft (`_flips_to_craft(..., plan)`, fresh sources and outlet).
  - Each option is sized alone within `spend = min(gold, Budget)` by `_option`, priced after only its own buys, sorted by profit and cut to `shopping_list_rows` (50, a config.toml key).
  - Holdings, Craft Actions and Best Exit Value are valued with nothing bought (`_Valuer.flips` now returns a Valuer with nothing taken). `_buy_what_fits`, `with_shopping` and `Row.leftovers` are gone.
  - Prediction buys get `spend`, under the same caps. `MarketRecommendations.budget` and `.spend` are new, and `shopping_cost` is gone.
  - Budget: new column `character_read.budget`, read by `history.market_budget` (the Market's latest Read).
  - Replay `_taken`: options in profit order while the gold lasts, with no shared Item Key. Held reagents a taken Flip to Craft uses come off the Holdings moves. Prediction buys get what's left.
  - Recommendations.lua: adds `budget` (only when set) and drops `shoppingCost`.
- Addon:
  - A Budget box left of Reload. Enter saves `AzerothQuantDB.budgets["<realm>-<faction>"]` (`RecommendationTable.budgetKey`), and blank clears it. `Money.parseGold` and `Money.goldText` are new.
  - Character.lua puts it in each Character Read.
  - `RecommendationTable.build(..., budget)` folds options costing more into `N over the Budget (Reload to re-size)`. The header reads `Gold X, Budget Y|all[ (Reload to re-size)], Prediction buys Z`.
- /code-review is done, and its fixes are in.

Review leftovers (judgement calls, not done):
- `_Valuer.flipped`/`after(bought)` and `_post_at`'s bought argument are now always empty. The whole bought-units path in `_Valuer` could go.
- The first `_valuer()` in `recommend_market` computes Flips it throws away.
- `_options` groups by `(item_key, is Flip to Sell)`.
- `section()` in RecommendationTable.lua now has 10 positional parameters.
- Replay: a taken Flip to Craft's Sub-craft leftovers aren't counted (it under-counts). Also, replay Prediction buys get only the gold the options leave, while live gives them the full spend.
- A held unit's Sell price can sit under a Flip to Sell's Post at for the same Item Key (ADR-0017 Consequences).

NOT checked on real data: `brain recommend` speed. Each recipe now runs its own greedy Flip to Craft loop.

User to do at the PC (add to #85): /reload is enough (no new Addon files), and restart `brain watch`. Type a Budget (say `50`) and press Enter: options over it should fold, and the header should say `Budget 50g (Reload to re-size)`. Then /reload, wait for the Brain, and /reload again: the options should be re-sized within 50g and the note gone. Check the Shopping List shows up to 50 independent options, most profit first. Then close #86.

Next, in order (none need the PC):
1. #84 build (/tdd), then /code-review + commit.
2. #77 build (/tdd), then /code-review + commit.
3. The needs-triage queue: #53, #54, #55, #56, #58, #60, #61.

2026-09-28 (later 19): #82 RESEARCHED: docs/research/booty-bay-broker.md (commit dd41df1). The verdict is unclear, probably not usable today. It lists only (Min Buyout, Market Value, Listed Quantity) and has no sales data, so at best it's a Fair Value prior and never a Sell Rate. There's no API, the Terms ban scrapers, and the cloud proxy blocks the site, so every claim about the site is from search snippets. The likely import path is the file the desktop Companion writes on the PC (format unknown). The PC follow-up is on #85 under "Booty Bay Broker". #82 waits on it: don't decide #82 until the user has done it.

Next, in order (none need the PC):
1. #84 build (/tdd), then /code-review + commit. It's small and the Beta replay before Oct 21 wants it.
2. #77 build (/tdd), then /code-review + commit.
3. The needs-triage queue: #53, #54, #55, #56, #58, #60, #61.

2026-09-28 (later 18): GRILLED #77 and #84. Both specs are comments on the issues, and both are labelled ready-for-agent.
- #77 (Craft Chain panel): it no longer waits on #76, which gets a reserved `disenchant` node kind (noted on #76).
  - Brain: every Craft row (blocked ones too) gets a nested `chain` tree. Node kinds: sell/vendor/craft/use/buy/merchant/leftover. Quantities are row totals, and gold follows `_Sources.cost`. A test asserts the nodes add up to the row's `profit`. `via`/`uses`/`buys` stay.
  - CLI: `brain recommend --chain <item>`.
  - Addon: a plain click selects a row, and a shift-click links it in chat (this changes today's click). Selecting a Craft row opens a panel about 300px wide, docked right of the frame: a top-down tree with elbow connectors and a Profit footer. The layout goes in a new plain-Lua `CraftChain.lua` (a .toc change, so the client needs a restart).
  - Docs: CONTEXT.md gets **Craft Chain**, and ADR-0014 and ADR-0016 get amendments.
- #84 (own-Market Sell Rate ablation): `recommend_market` takes an optional injected pricer, built only in `replay.py` (DBMarket + the TSM post rule). When given, it replaces the Sell Rate everywhere: unlimited room, has_data = has a DBMarket, no `max_sale_price` cap (the Merchant cap stays), and no expected lost Deposits. It runs on every replay, and the grader is unchanged.
- #82: /research running in the background, writing docs/research/booty-bay-broker.md.

Next, in order (none need the PC):
1. #84 build (/tdd), then /code-review + commit. It's small and the Beta replay before Oct 21 wants it.
2. #77 build (/tdd), then /code-review + commit.
3. Act on the #82 research verdict.
4. The needs-triage queue: #53, #54, #55, #56, #58, #60, #61.

2026-09-28 (later 17): #79 BUILT on branch claude/zen-mccarthy-xaqoze. MailDumpSpike.lua is deleted, along with its .toc line and the two spike comments. `/aq` in RecommendationFrame.lua no longer chains to a previous handler, and an unknown command prints the usage line. Mailbox.lua's ADDON_LOADED sets `AzerothQuantDB.mailDumpSpike = nil`. No busted test: the slash handler is WoW glue (it calls the file-local toggle/reload/say, and the file runs CreateFrame when it loads). /code-review found nothing blocking. The branch is now 6 commits ahead of main, and main hasn't moved. The user merges it when they say to.

User to do at the PC (add to #85): after merging, fully restart the client (a .toc change isn't picked up by /reload). Then check that `/aq foo` prints the usage line and that `/aq recs` still toggles the table.

Next, in order (none need the PC):
1. The #77 grill, the #84 grill, #82 /research.
2. The needs-triage queue: #53, #54, #55, #56, #58, #60, #61.

2026-09-28 (later 16): CLOSED #32, #33, #38, #78 and #80 (built, with comments). Every parked in-game and real-data check is now one checklist issue, #85 (needs-pc): restart `brain watch`, `brain rebuild` (#78 deposits), `brain replay` on Beta before Oct 21 (the table goes on #83), and the hover checks for #38/#33/#75/#50/#49/#71 plus the #78 Copper Bar deposit. It replaces the "parked" lists in the entries below. The user can't do PC checks now: don't ask until they say they're back. The branch `claude/zen-mccarthy-xaqoze` is 4 commits ahead of main (#80, #38), and main hasn't moved, so it fast-forwards. Merge it when the user says to.

Next, in order (none need the PC):
1. #79 (small): /tdd, then /code-review and commit.
2. The #77 grill, the #84 grill, #82 /research.
3. The needs-triage queue: #53, #54, #55, #56, #58, #60, #61.

2026-09-28 (later 15): #38 BUILT on branch claude/zen-mccarthy-xaqoze (issue still open). `MarketRecommendations.held`: Item Key -> `CharacterHolding(character, bags, bank, bound)` per Character, by name, from the same Reads as Holdings (`recommend._by_character`; `market_holdings` = `_pooled` of it). `bags`/`bank` are totals and `bound` is the part of them that's bound. Written to Recommendations.lua as `held`. Addon (RecommendationTable.lua): `holderLines(whose)` gives `On X: 12 bags, 30 bank (5 bound)` at the end of row and item tooltips. `reagentLines(r, nameOf, whose)` adds `Mail n <Reagent> from Y to <crafter>` lines: the Characters with the most unbound units go first, and the crafter's own bound units count toward what it has. `build(..., character)` puts `RecommendationTable.BAG` (the backpack icon) in front of the Holdings Item cell when the logged-in Character (UnitFullName joined with "-") has the Item Key in its bags. ADR-0009 amendment, CONTEXT.md **Holdings**. /code-review is done and its fixes are in: a Craft with a Sub-craft on another Character gets no mail lines, since `uses` can't say whose reagents are whose.

Known limit (ADR-0009): each Craft row's mail lines are checked on its own, so two rows on one crafter that share a reagent can each look covered.

Review leftovers (judgement calls, not done):
- `CharacterHolding.bags`/`bank` include bound units, but `Holding.bags`/`bank` don't. Same field names, different meanings.
- `section()` now takes 9 positional parameters, and `nameOf, held, holdersOf` travel together.
- `table.concat({ UnitFullName("player") }, "-")` is now in 5 files, so a shared helper is due. A new file needs a .toc change and a client restart.
- `market_holdings` is a thin wrapper, kept for replay.py.

User to do at the PC: /reload (no new files). Hover a Holdings row and a Craft row, and check the `On X` and `Mail` lines and the bag icon. Then close #38.

Next, in order:
1. Run the replay on the Beta data (user, before Oct 21), and fix anything it shows.
2. #79 (small). Then the #77 grill, the #84 grill and #82 /research. The #81 probe waits until the user is at the PC.

2026-09-28 (later 14): #80 BUILT on branch claude/zen-mccarthy-xaqoze (issue still open). New `brain/replay.py` and the `brain replay [--since DAY] [--until DAY]` command. Per Market, it grades every Scan that has a whole Sale Horizon of Scans after it. Each policy's grade is the **value added over holding on**: Vendor gold, plus posts filled by later Sale Events (a Sale Event's dearest price at or above the post, up to its units, cheapest posts first), less Deposits lost, plus what's still held at the end of the horizon at Best Exit Value (`recommend.exit_values`), less gold spent, less the same Holdings untouched. The policies:
- Brain: `recommend.recommend_market(..., now=t, as_of=t)`, now split out of `recommend`, with the Holdings and gold of then.
- Auctionator: flips an ask under the next one by more than the cut plus the Deposit, and posts 1c under the cheapest other Listing, or Vendors.
- Emulated TSM: `db_market` / `db_min_buyout`, with the method in ADR-0015. Posts between 0.8x DBMarket and DBMarket, and crafts one level deep with no Sell Rate.
- Ablations: `craft_chain_depth=1`, and the new Config fields `flips_to_craft` / `deposits` (not config.toml keys).

The grader always charges Deposits. Realized profit is the range's Sold Outcomes after the cut, less the Lot cost they closed. The Beta Market is labelled provisional. Row got `merchant_gold` (a Craft Action's merchant spend) and `made` (`CraftOutput`: a Flip to Craft's output units, selling, post_at). Both are `compare=False` and not written to Lua. The `_Outlet` now keeps `post_at`. The helpers replay needs went public: `auction_cut`, `item_id_of`, `cheapest`, `without`, `BOUND_ON_CRAFT`, `market_holdings`, `deposit_of`, and `lots.happened_at`. The own-Market Sell Rate ablation was split to #84 (needs-triage, needs a grill).

Review leftovers (judgement calls, not done):
- The Known Recipes, Merchant Costs, deposits and Lots (Hold costs/ROI) the Brain uses at a past Scan are the latest, not as of it.
- A Flip to Craft posts all its outputs at the one `post_at`.
- Data Clumps in the baseline signatures (held/others/vendor/gold; market_value/min_buyout), and `_tsm_craft` returns a 4-tuple.
- Prediction buys are graded as held units (no test: none of the replay tests has Predictions).

NOT checked on real data: speed. Each replayed Scan runs 4 `recommend_market`s and 7 `exit_values`, and each rebuilds Sell Rates. If it's too slow, cache `sell_rates` per (Market, Scan) in `_valuer`, or add a `--every N`. Also not checked: whether the numbers look sane on the Beta Archive.

User to do: run `brain replay` on the Beta history before Oct 21 (from brain/, no restart needed). Post the table on #80, then close #80 if it runs.

Next, in order:
1. Run the replay on Beta data (user), and fix anything it shows.
2. #38 build (tdd), then /code-review + commit.
3. #79 (small). Then #77 grill, #84 grill, #82 /research. #81 probe when the user is at the PC.

2026-09-28 (later 13): GRILLED "keep going vs. TSM". Two new ADRs, and CONTEXT.md **Addon** and **Recommendation Table** updated. ADR-0003 is superseded in part.
- ADR-0015: keep going, judged by a replay over the Archive.
  - What TSM offers on Forever: nothing. There is no official support and no Forever AuctionDB data, and Blizzard's auction API reportedly has no Forever data either. Auctionator and Auctioneer forks already run there. Beta ends Oct 21, and Live launches Nov 4.
  - The test: the Brain against an Auctionator baseline and an emulated TSM baseline (DBMarket and DBMinBuyout computed from our Scans), graded by Best Exit Value, with ablations (Sub-crafts, Flip to Craft, Deposits, own-Market Sell Rate).
  - Checkpoints: the Beta read is provisional. The binding Live read comes at ~Dec 2. Continue if the Brain beats Auctionator by at least 10% and is no worse than TSM. Stop if it's within ±5% of Auctionator. Anything in between gets a 2-week live split.
  - Outside data (TSM, Booty Bay Broker) only supplements ours, as a prior. It replaces one of our metrics only if the replay proves it predicts better.
- ADR-0016: the Addon posts or cancels the selected row, one protected call per click, only in `OnClick`. It never buys, bids or takes mail. An addon/spec test enforces the API-name rule.
- Issues:
  - #80 replay harness (ready-for-agent)
  - #81 Post/Cancel button (ready-for-human: in-game probe first, for `ADDON_ACTION_BLOCKED` and whether posting takes a Confirm step)
  - #82 Booty Bay Broker research (needs-info)
  - #83 checkpoints (ready-for-human)

Next, in order:
1. #80 build (tdd), then /code-review + commit. Run it on Beta data before Oct 21.
2. #38 build (tdd), then /code-review + commit.
3. #79 (small). Then #77 grill. #82 /research. #81 probe when the user is at the PC.

2026-09-28 (later 12): #33 BUILT and pushed to main (issue still open for the user to close). Sub-crafts (ADR-0014, CONTEXT.md **Sub-craft**): a greedy step is still one more craft of recipe R, but its reagents come from `_Sources` (recommend.py): held (no-data held units aren't used), then merchant, then one source per short reagent, a Sub-craft (recursive) or the AH asks (Flip to Craft only), whichever costs less by `_Sources.cost` (gold + effort + held worth lost - leftovers' worth). `_Sources.may_use` holds the guards: path rule, `craft_chain_depth` (config, default 3, counts the top craft), Predictions, cooldown limits via a shared `spent` Counter (`_Crafting.spent` carries it into Flips to Craft). `_Chain` is one craft's sourcing; `_Plan.add(chain)` aggregates `used`/`bought`/`via`. Rows get `via = (SubCraft(item_key, crafts, character), ...)`, deepest first, written to Recommendations.lua; the CLI note is `on X: uses 2 of 2770, via 2 of 2840 on Y, 1 of 2996 on Z`. Leftovers: a Craft Action's go straight into `crafting.crafted`; a Flip to Craft's ride on `Row.leftovers` (not written to Lua) into `_Crafting.with_shopping` (was `left`, now returns a `_Crafting`). A no-data reagent blocks a recipe only when no maker passes `may_use` for it. `_Valuer.worth` is memoized (the search values many Holdings). Addon: `reagentLines` puts `Craft N <Name> on <Character>` lines first (both tooltips).

Review leftovers (judgement calls, not done): `Row.leftovers` is internal plumbing on the public Row; `_subcrafted` counts an unknown-bind leftover as bound while `_crafted` counts an unknown-bind top output as unbound (top recipes with unknown bind are blocked anyway); `_on_hand` (blocked-row display) and `_step`'s "some held unit taken" say the same rule two ways; config.py now has four hand-written "whole number >= 1" checks (a `_parse_whole` helper is due). Not checked on real data: `brain recommend` speed with chains (each step tries every maker per short reagent).

User to do now: close #33.

Parked until the user is back at the PC (they can't do in-game checks now; don't ask before then): restart `brain watch` (stop all 3 processes), /reload (no new Addon files), then hover a chained Craft row and check the `Craft N <Bar> on <Character>` lines come before Use/Buy. Also note how long `brain recommend` takes with chains. The earlier parked lists (later 10, later 7, #19 spike) still stand.

Next, in order:
1. #38 build (tdd), then /code-review + commit.
2. #79 (small). Then #77 needs a grill now that #33 has landed (#76 still needs /research on DE tables).

2026-09-28 (later 11): TRIAGED the needs-info queue. #33 GRILLED, spec posted as a comment, ready-for-agent: Chained Craft through **Sub-crafts** (backward, not forward valuation). A greedy step is still one more craft of recipe R, but a short reagent can be covered by crafting it with another Known Recipe, recursively. This covers both `_step` and `_flip_step`. Reagent sources in order: held, then merchant (never sub-crafted), then one source per reagent for the rest (sub-craft or AH asks, whichever costs less). Path cycle guard, config `craft_chain_depth` = 3, cooldown limits shared. Held no-data reagents aren't used but can be sub-crafted. Leftovers join the crafted Holdings, and crafted units are still never reagents. Rows get `via = ({itemKey, crafts, character})`, and the Addon shows via lines before Use/Buy. New ADR-0014, CONTEXT.md **Sub-craft**. Disenchant stays out (#76).
#38 GRILLED, spec posted, ready-for-agent: per-Item-Key, per-Character breakdown `held` in Recommendations.lua. Addon: tooltip lines `On X: 12 bags, 30 bank (5 bound)`, a bag marker on rows the logged-in Character holds, and `Mail n <Reagent> from Y to <crafter>` lines on Craft rows. CLI unchanged.
#19: decisions posted (what-if valuation, payback in days, own professions only, skill gating). Relabelled ready-for-human: an in-game spike with 4 `/run` probes on the issue (GetRecipeSourceText, recipe-info fields, C_Item.GetItemSpell on a Recipe item, trainer fees). Write the build spec from the results.
#44: parked, still needs-info. Findings and the approach (the Addon records crafts via UNIT_SPELLCAST_SUCCEEDED) are on the issue. It un-parks when Flips to Craft get graded or blank ROI on crafted outputs is missed.
#45 closed as a duplicate of #69. #15 closed (done). Its spike gaps are passive: watch `brain import` for unknown-sender / `mails_unreadable` warnings (Horde/neutral AH sender, expired and outbid mail). Filed #79 (remove MailDumpSpike.lua + .toc line, ready-for-agent; needs a client restart).
#14 stays ready-for-human, parked until 30 own Sold Outcomes link to own Listings (count `link_sales` output with an item_key in a scratch script).
#76/#77 stay needs-info (#77 is blocked by #33 and #76).

The user is still away from the PC: the parked in-game steps in (later 10) and (later 7) still stand, plus the #19 spike probes.

Next, in order:
1. #33 build (tdd), then /code-review + commit. It's the biggest; `recommend.py` `_step` / `_flip_step` / `_Plan.row`.
2. #38 build (tdd), then /code-review + commit.
3. #79 (small). Then #77 needs a grill once #33 lands (#76 still needs /research on DE tables).

2026-09-28 (later 10): #78 BUILT on branch claude/zen-mccarthy-xaqoze (not on main yet, issue still open). Each unit valued as posted pays the deposits it's expected to lose (ADR-0013, CONTEXT.md **Deposit**). `_Queue` (recommend.py) is an Item Key's sale queue: `units_per_hour` from `_units_per_day` (factored out of `sellable_units`) under the Flip or Holdings priors, `lost(i)` = floor(i / units_per_hour / post_duration_hours) x deposit. `_Valuer.deposit`: latest Sold invoice `deposit / count` (`lots.deposits`, on `link_sales` output), else `ah_deposit_share` x Vendor Price. `_Valuer.held` carries the unbound held units ahead of the Flips (set by `flips()`), and `flip_lost` prices a Flip to Sell row in `_buy_what_fits`. Charged in `_flips`/`_resells` (last unit of the run), `_Outlet.value` (`take()` advances room and queue), `_holding_rows` (Sell is a prefix; margin = average net per unit - Vendor Price) and `_hold_buys`. `parse_mail` keeps `deposit` (not part of mail equality, so a stale history still matches its live mail; new `auction_mail.deposit` column, old mails get it on `brain rebuild`). Existing tests use a 3 h horizon, so they're deposit-free; deposit tests set `post_duration_hours=1`. The CLI Flip went 4s98c -> 4s92c (one 6c deposit).

Review leftovers (judgement calls, not done): `_outlet` queues craft outputs behind `valuer.flipped`, which includes Flip to Vendor units (same as the old room rule; over-charges only when one Item Key is both Flipped to Vendor and crafted). `_valuer` learns deposits from every Sold invoice, even ones after a past Scan being valued (Best Exit Value/Grades); the comment says a rate doesn't move. `_Queue.lost_by` is a Python loop, O(units): check `brain recommend` speed on real data. `queue(item_key, flips: bool)` flag, `flip_lost` tuple return, `_Valuer` constructor with 11 params. ROI still uses the gross post price (deposits aren't in it). `lots.deposits` has no direct unit test (covered through recommend).

User to do: merge to main, close #78, run `brain rebuild` (so old Sold mail gets its deposit), restart `brain watch`. Parked in-game check: post one Copper Bar at 48h and read the deposit (checks `ah_deposit_share` and the rumoured 1s minimum).

Next, in order:
1. Needs-info: #33, #19, #38, #44, #45, #15, #14.

2026-09-28 (later 9): #78 GRILLED. Spec posted as a comment, labelled ready-for-agent. Charge the expected AH deposits lost wherever a unit is valued as posted: Flip to Sell (`_flips`, `_resells`, `_buy_what_fits` reprice), `_Outlet.value`, Holdings Sell vs Vendor (`_holding_rows`, Selling becomes a prefix of the queue) and `_hold_buys` Max Loss. Deposit per unit = latest Sold invoice `deposit / count` for the Item Key (`parse_mail` keeps `deposit`, the Item Key is resolved by name as in lots.py), else config `ah_deposit_share` (0.60, unverified) x Vendor Price (0 if unknown/0). Expected expiries come from a queue model: unit i (held first, then Flips to Sell, then Flip to Craft outputs, the same order as the room rule) waits i / units_per_hour and loses floor(wait / `post_duration_hours`, 48) deposits. No UI change. New ADR-0013 + CONTEXT.md **Deposit**. Research: Forever runs the retail C_AuctionHouse UI, and no published deposit rates exist for it.

Parked in-game check (when the user is back at the PC): post one Copper Bar at 48h and read the deposit the AH shows (checks `ah_deposit_share`, and the rumoured 1s minimum).

Next, in order:
1. #78 build (tdd), then /code-review + commit.
2. Then needs-info: #33, #19, #38, #44, #45, #15, #14.

2026-09-28 (later 8): TRIAGED #78 as needs-info. The triage comment on the issue lists what's open: the deposit formula vs Sold invoices (the Addon already stores the invoice `deposit`; `mailbox.parse_mail` drops it), expected expiries, which margins, and no-Vendor-Price items. It needs a grill. #66 BUILT and LANDED on main (a07e102), closed. New `brain/grades_file.py` owns `Grade` (re-exported through recommend) and a Brain-owned, append-only `grades.toml` next to predictions.toml (gitignored; `Config.grades_path`, None in tests like `archive_dir`). Entries are `[held|grades.<era>.<realm>.<faction>.<Prediction>]`, keyed by Market because `recommend` grades per Market. `held_at_writing` freezes once the Market has a Scan at or after the start of the day after the written day. `grades()` freezes once there's a Scan at or after the grading moment. Both read the frozen entry from then on. `_append` re-reads the file first, so a second Brain process can't write a duplicate table (that would make the file unreadable). A malformed file raises `GradesError`, logged by the CLI like PredictionsError. ADR-0006 and ADR-0007 amended, and CONTEXT.md, README and .gitignore updated. Review leftovers (judgement calls, not done): `grades()` and `held_at_writing` now write the file as a side effect (the spec asks for it), `load_frozen` re-reads the file on every call, and an edited Prediction that keeps its name keeps its old entry (the ADR says to delete it by hand). User to do: merge to main, close #66, restart `brain watch`.

Next, in order:
1. Grill #78 (AH deposits), then needs-info: #33, #19, #38, #44, #45, #15, #14.

The user is away from the PC (no game, no `brain watch`): don't ask for PC steps. When they're back, the parked list in the (later 7) entry still stands, and its `brain watch` restart also picks up #66 and #69.

2026-09-28 (later 7): #67, #73, #75 and #71 LANDED on main (fast-forward to e5f3745) and closed. The user couldn't get in game, so these are parked for when they're back at the PC:
- Restart `brain watch` (stop all 3 brain.exe/python processes), then /reload. No new Addon files, so no client restart.
- #75: a blocked Craft row's Note and tooltips say `no market data for <Name>` (not an item ID).
- #71: after a Scan + reload, about 10 s later the chat line `The Brain should be done: Reload to see the new Scan.` prints and the Reload button pulses (with the table open). Read a few `Import took Xs` lines in the `brain watch` window and tune `Nudge.RELOAD_READY_AFTER` (Xs + 3 s settle + up to 1 s poll).
- Optionally set `non_stacking_effort_copper` in config.toml (#73, default 500).

Next, in order (none need the game):
1. Triage #78, then #66 (low priority). /code-review + commit after each.
2. Then needs-info: #33, #19, #38, #44, #45, #15, #14.

2026-09-28 (later 6): #71 BUILT on branch claude/zen-mccarthy-xaqoze (not on main yet, issue still open), on top of #67 + #73 + #75. `brain watch` logs `Import took Xs` after each import (from noticing the file settled to Recommendations.lua written; not logged when every file failed; `cli.watch_step` takes an injected clock). Addon: `Nudge.whenReloadReady(unimported, after, ready, say)` waits `Nudge.RELOAD_READY_AFTER` (10 s) after a load with unimported Scans, then sets `Scanner.reloadReady()` and prints `The Brain should be done: Reload to see the new Scan.` once. The Reload button pulses (the Scan button's glow, now `Scanner.addPulse`/`setPulsing`) while reloadReady and no Scan is in flight; it only pulses while the Recommendation frame is shown. The spec's `(wrote Recommendations.lua)` suffix was dropped: installs without the Addon get no file (they get their own warning). Review leftovers (judgement calls, not done): the glow helpers live in Scanner.lua rather than a shared UI module (a new file needs a .toc change + client restart); the pytest feeds the clock exactly 3 values, so an extra `clock()` call breaks it. User to do: merge to main, close #67, #73, #75 and #71, restart `brain watch`, /reload (no new files, so no client restart). Then read a few real `Import took Xs` lines and tune RELOAD_READY_AFTER (add the 3 s settle + up to 1 s poll).

Next, in order (none need the game):
1. #66 (low priority). /code-review + commit.
2. Then needs-info: #33, #19, #38, #44, #45, #15, #14, and triage #78.

2026-09-28 (later 5): #75 BUILT on branch claude/zen-mccarthy-xaqoze (not on main yet, issue still open), on top of #67 + #73. A blocked Craft row carries `blocked` (`Blocked(BlockReason, item_key)` in recommend.py), written to Recommendations.lua as `{ reason = "noData", itemKey }` or `{ reason = "unknownBindType" }`. The CLI note is unchanged (`no data for <key>`; the CLI names items by key everywhere). Addon: `RecommendationTable.note(r, nameOf)` is the one place a row's note is read for the Holdings Note cell, row tooltip and item tooltip (`TooltipLines.holdingLine`): `on <Character>: no market data for <Name>` (falls back to `item:<key>` while uncached, like reagent lines), `on <Character>: unknown bind type`, else the Brain's note (cooldown rows, and any reason the Addon doesn't know yet). ADR-0009 amended. Review leftover (judgement call, not done): `section` passes `nameOf` to every cells function, only Holdings uses it. User to do: merge to main, close #67, #73 and #75, restart `brain watch`, /reload.

Next, in order (none need the game):
1. #71, 2. #66 (low priority). /code-review + commit after each.
2. Then needs-info: #33, #19, #38, #44, #45, #15, #14, and triage #78.

2026-09-28 (later 4): #73 BUILT on branch claude/zen-mccarthy-xaqoze (not on main yet, issue still open), on top of #67. New config `non_stacking_effort_copper` (default 500 = 5s, config.example.toml). An Item Key doesn't stack when no Listing of it was EVER seen with more than one unit (`sell_rate.non_stacking`; Sell Rate's usual Sale Event size uses the same `_stacking` test over its range only). `_Valuer.effort(item_key)` is the per-unit charge (0 for stacking keys). Flip to Sell pays 2x effort a unit in `_flips` run profit, `_resells` (margin on what's left; Sell beats Vendor when resale - effort > Vendor Price) and the `_buy_what_fits` reprice. Buy to Vendor: vendor - effort - unit > 0. Flip to Craft: effort per AH reagent unit (`_flip_step`, not merchant/held) and per output unit that Sells (`_Outlet.effort`). Holdings are never charged, but their Sell prices / Best Exit Value can shift because fewer non-stacking Flips are bought (ADR-0010). CONTEXT.md **Flip** says so. Review leftovers (judgement calls, not done): `2 * effort` appears at 3 sites; the spec's 90-unit example is tested with 3 units (same mechanism). User to do: merge to main, close #67 and #73, restart `brain watch`; optionally set non_stacking_effort_copper in config.toml.

Next, in order (none need the game):
1. #75, 2. #71, 3. #66 (low priority). /code-review + commit after each.
2. Then needs-info: #33, #19, #38, #44, #45, #15, #14, and triage #78.

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
