2026-11-10 (later 208): Grilled the Live dropped-row blowup, filed #226 (ready-for-agent) + follow-up #227 (needs-triage), commented #150 (superseded by #226). Facts: drops 0 -> 14.2% of rows since Scan 111 (Nov 6 20:30), dropped items pile up across sessions (54 -> 3,019), ~2/3 of each Scan's dropped items were also dropped the Scan before; 2,581 of Scan 137's 3,019 dropped items had other rows read in the same Scan, so #156's re-read (waits only on GetItemInfo == nil) re-reads them at once and they stay nil. The per-item guard leaves 88-96% of Listings out of Observation Windows since Scan 131. Decided: probe the cause in game first (throwaway addon `docs/research/issue-226-probe/`, junctioned like AQProbe97), Addon fix from the result, pack still-dropped rows `itemID,qty,buyout,timeLeft`+own (pool too), Brain per-row keep-alive (one-to-one, most time left wins), old Scans 111-137 keep per-item exclusion + per-item hours, warn when dropped share > 2%. Done = <5% of Listings left out on new Live Scans + before/after Sell Rates on one snapshot.{nl}{nl}Next: finish #212 (below), then #226 step 1, the probe (needs the game at the AH; Claude builds it, user runs the slash command).
2026-11-08 (later 207): #225 Live check PASSED (Scan 00:26 Nov 8): all 10 Risky Shopping List rows right, 7 at exactly 3x avg cost, 3 (264066, 2951, 3844) under a next Listing already below the cap; nextListing still the sticker. #212 built TDD (2c57c79, pushed, both reviews done, fix + rerun NOT done): `Buy.took` = (Item Key, units) taken from other players; `simulate` maps them to Listing ids via `Terms.listings` (`history.listings_at`) by `_listings_taken` (cheapest, then id, whole Listings) and passes the bought set to every policy (5th BuyPolicy arg); `supply_at(exclude=)`, `recommend_market(taken=)` -> `_valuer_at` (cache keys include it). Only the buying side: Sale Records, Fair Value history, market mark unchanged. 5 new tests at backtest(), each verified to fail with the exclusion off.{nl}{nl}Next: finish #212. 1) Fix the standards review's finding: `_listings_taken` re-derives which Listings a buy took and can be wrong: Auctionator breaks ties at its ask smallest-quantity first (`_AuctionatorOption.units`), and `take_under` can take part of a Listing. Better: each policy reports the Listing ids it took (Buy carries ids, not (key, units)); drop the `Terms.listings` default lambda (a real Terms forgetting it silently turns #212 off). Spec review (finished late) adds: the Brain's Flip to Vendor row buys `_listings_left(offers, to_sell)` (what's left after the Item Key's best Flip to Sell run), not the cheapest, so with mixed prices the cheapest-first guess drops the wrong Listings; carry the run's/`_VendorBuy`'s exact Listings on the Row. Partial takes over-remove a little (probably fine). No tests for Craft reagents/Flip to Sell yet. Optional tidy: NamedTuple for listings_at rows. 2) /code-review again on the fix. 3) Rerun before/after on one history snapshot: old code via `git worktree add <scratch>/wt-before d7ab321`, then in a dir holding a sqlite-backup copy of history.sqlite + config.toml/grades.toml/predictions.toml run `python -c "import sys; sys.argv=['brain','backtest','--policy','brain,auctionator','--until','2026-10-31']; from brain.cli import main; main()"` (PYTHONPATH=<wt>/brain/src for before). ~90 min each, run both in background at once. Post numbers on #212, re-judge ADR-0034..0041 (sanity only, ADR-0042), push, close. Then check #220, #222.{nl}{nl}2026-11-07 (later 206): #225 built, TDD + /code-review (aeb1684, pushed). User picked: post at the cap (never drop), `risky_no_sales_markup` = 3 x the run's average unit cost, Holdings Risky rows capped on Paid when known (looted units uncapped). /code-review caught that counting Sale Events at the capped price could drop a row (3+ sales under the sticker): "too few" is now judged in `_flips` under the next Listing, and `sales_seen` counts at the capped price (Holdings likewise, in `_risky_holding`). Holdings Paid uses `held` (after crafts, before Disenchants), the same count `_with_roi` shows. ADR-0043 amendment, CONTEXT.md, config.example.toml. Stopgap removed from local config.toml. `brain recommend` on Live: 10 Risky rows, all at the 3x cap now (6g 55s to 19g 95s each, ROI ~170-180%, 69% for 2276), vs 15g-372g claimed before. `brain watch` restarted (pid 34676, current code); it writes on the next import.

Next: on the next AH visit, glance at the Shopping List's Risky rows (price = 3x cost, "Next one's listed at" still names the sticker); the user only does the game steps. Then #212, check #220, #222. Gotchas: every no-sales row now sits at exactly 3x, so the cap is effectively the price on Live; if they don't sell, the knob is the lever (file, don't tune before Flip Grades exist, ADR-0042). tests/test_recommend.py and test_config.py are LF in git, the rest CRLF; heredoc'd Python with `\r\n` literals fails silently on them, use Edit.

2026-11-07 (later 205): #224 checked on Live, and it's bad. All 10 Shopping List Risky rows posted at 5x-437x their buy price under a never-sold sticker (6413: buy 2g 38s, post 80g, +372g). User: a markup cap is the line (filed #225, needs a spec: drop vs post-at-cap, and whether Holdings no-sales rows get it too). Stopgap: `risky_no_sales_rows = 0` in the local brain/config.toml. It also hides the Holdings no-sales rows, since both go through that knob. Remove it when #225 ships. `brain import` with the watch stopped forces a Recommendations.lua rewrite (the watch only writes after an import). A cold import is now 90 s of Fair Values + up to 230 s of Decision Engine.

Next: #225 (spec, then /tdd), then #212, check #220, #222.

2026-11-07 (later 204): #224 built, TDD + /code-review (dd5afc8, ADR-0043). Flips to Sell under `flip_min_sale_events` that pass everything else are now Risky rows (`Row.sales_seen`, Lua `salesSeen` + `nextListing`, no `days`; Addon "Risky: nobody's been seen buying this yet. Next one's listed at X. If it never sells you lose Y.", wait and Per day "?"). They only exist with risk caps on, only for an Item Key with no other Flip to Sell run, and must make the Minimum Profit. Own cap `risky_no_sales_rows` = 10 (config.example.toml documents it). grades.toml `risky = "noSales"`. `--why-not` says "shown as Risky (no sales)". Holdings: deviation agreed with the user, NOT `_sell_way` (Holdings never goes through it; changing it would move Buy Unders/Loot Alert/Flips to Disenchant). Instead `_Valuer.shown_rows` turns no-data/Vendor units into a Risky Sell row, only on displayed rows: `worth` (Stake, Disenchant, Craft) is unchanged, because putting it in `rows` inflated the Stake with own sticker prices. On the real history: Live went from 0 rows to 10 Risky rows (4827 at 16s -> 69g 99s 99c, +66g 24s), 17 Risky Holdings rows; `recommend` cold 400 s vs 398 s before (no measurable cost). The running `brain watch` predates dd5afc8.

Next: restart `brain watch` so it writes the new rows, then on the next AH visit glance at the Shopping List's Risky rows and their details line (the user only does the game steps). After that, the post-launch queue: #212, check #220, #222. Gotchas: a held no-sales unit can still get a Disenchant row, since Disenchant compares against its unchanged worth (ADR-0043 consequence; file it if it shows up). The code uses "sales" in names (`sales_seen`, `risky_no_sales_rows`) because the spec fixed the Lua/config names, though CONTEXT.md says to avoid "sale". `sed -i` in this Bash tool strips CRLF from the Lua files: restore with `sed -i 's/\r$//; s/$/\r/'` (write it via the Edit tool or chr(92): heredoc'd Python turns the backslash into a real CR).

2026-11-07 (later 203): #224 grilled and specced (issue comment), relabeled ready-for-agent. No code. Short version: Flips to Sell under `flip_min_sale_events` that pass everything else become Risky rows (`risky = "noSales"` in grades.toml, `salesSeen` in Lua). Post price has no cap. Same sizing as ADR-0037 (room still applies, <= 5 units). Own cap `risky_no_sales_rows` = 10, ranked by profit. Held units get a Holdings Sell row instead of Vendor. Out of the Backtest. Write ADR-0043.

Next: build #224 per the spec comment (`/tdd`). Gotcha: the Holdings part touches `_sell_way` (`recommend.py:1632`), which every way-valuation uses; limit the change to no-sales Item Keys so normal Sell values don't move.

2026-11-07 (later 202): Empty Live Shopping List diagnosed, no code. 7,294 of 7,508 Item Keys stop at Sale Events (<3, only ~52 h of Live windows); the 214 that reach the margin all sit ~13.6% short (= priced at market: post x 0.95 / 1.1). `--why-not` sorts margin failures first, so it hid the Sale Events wall. `flip_min_sale_events = 1` gives just one +15s Flip. But 557 Item Keys (mostly random-enchant BoE gear, 0 Sale Events) have a post_at that beats the ask by >10%: `_sell_way` gives no Sell value without room (`recommend.py:1641`). User wants those as Risky rows: filed #224 (needs-triage, grill first: price sanity vs sticker-price next Listings, row count, spend cap).

Next: grill #224 (`/grilling`), then spec it.

2026-11-03 (later 201): Pre-launch check, no code. Step 1 of the Nov 4 checklist verified: one `brain watch` (pid 32692, started 11-03 10:38, after the last code commit), config 0.5 weight, only `_forever_` watched, no lock errors since Oct 30, both junctions point at C:ibing, no AzerothQuant SavedVariables in `_forever_` yet (nothing to clear). Client build 1.60.1.70755 matches the `.toc`'s 16001, so step 2 should need no patch unless launch bumps it. TSM refresh committed (babfc01).

Next: Nov 4 the user is LEVELING and doesn't want to spend time on the Addon. Launch day is the minimum only: (a) launch, note whether AzerothQuant shows out of date; (b) next time they pass an AH, open it (glance at #164's spot), Scan, `/reload`, back to leveling; Claude watches the import and the pool counts (step 4) and checks the two launch Predictions' Item Keys in the Scan (step 11 part). Step 13 (XP food) only if it happens naturally. Steps 5-10 and 12 move to a calm evening later that week, in one sitting. Don't ask the user for more than (a) and (b) on Nov 4.

2026-11-02 (later 200): #221 diagnosed and closed as not a bug, no code (comment 6587215243). The 47 min wasn't Predictions: it was a copy with no grades.toml. `split_purchases` reworks every past Scan with a Purchase whose named set isn't frozen (35 Scans x ~60 s on the 97-Scan Beta copy, CLI has no cache), then freezes them. Timings: cold active 2501 s (under py-spy), cold inactive 2035 s, warm active 303 s, warm inactive 172 s. `_hold_buys` was 0 s. Filed #222 (needs-triage, after launch): `brain recommend` passes no `FairValueCache`, which also explains the ~130 s active-Prediction overhead (`held_at_writing` not memoized without a cache). Not a Nov 4 blocker: the watcher passes a cache and Live's history starts small.

Next: Nov 4 at the PC, the checklist under later 174 (step 1's remaining part as in later 199). After launch: #212 first, check #220 cleared itself, #222 when there's room. Gotchas: any timing on a history copy must bring grades.toml along (or expect the ~35-min cold rework the first time). py-spy is now in `.venv` (`.venv/Scripts/py-spy.exe record --subprocesses --format raw`, needs `--subprocesses` because the venv python.exe is a launcher). Profiling copies are in scratchpad session 89da592c (`run/` warm with active Predictions, `cold/` warm with inactive; `prof.py` times `_hold_buys` and prints Prediction lines).

2026-11-01 (later 199): #210 done (fc854f2), TDD. A Prediction unit that could only be Vendored because its Item Key has fewer Sale Events than `flip_min_sale_events` (Live's + Beta's x weight while the Beta Sell Rate is on, `_too_few_sale_events` in recommend.py) now gets `NoBuyKind.NO_SALES`, "no Live sales seen yet", in place of "would lose N%". /code-review caught that checking for zero Sale Events missed 1-2 (default minimum 3). Nov 4 step 1 config part done early: `brain/config.toml` has `beta_sell_rate_weight = 0.5` and the `_classic_beta_` install is removed (checked: the Beta column reads Beta from the history via `beta_market`, pool sync doesn't use installs, a missing install was only a skipped write). Also checked: one `brain watch` runs (Startup, pid 33392, from 11:07 today, so it predates #209/#211/#210 and the new config); the Oct 30 "database is locked" errors were the old Z: path, none since; both `_forever_` junctions point at C:ibing. `addon/AzerothQuant/Recommendations.lua` shows modified in git: Brain output written through the junction Oct 30, never commit it.

Next: Nov 4 at the PC, the checklist under later 174 from step 1's remaining part (restart `brain watch` so it runs current main and the new config, confirm ONE runs, first sync clean in brain.log, clear `recommendationFrame`/`recommendationFrameSize` in the Live SavedVariables before the first open). After launch: #212 first, then #220 is gone by itself on Nov 4 (check). Gotchas: a `git stash`/`stash pop` this session left `.git/index` empty (every file staged-deleted + untracked); `git reset` (mixed) rebuilt it. Don't stash here. Tests: `../.venv/Scripts/python -m pytest` from `brain/`, instance-lock test still fails under the venv (known).

2026-11-01 (later 198): #209 and #211 done, TDD. #209 (1dbae29): `Prediction.active_on` now needs `written <= day`. Its only caller is `market_recommendations` (recommend.py:819), which the live Brain, both Backtest policies and the Predictions tab all go through. Test: "not yet written" case in `test_a_prediction_stands_from_its_written_day_until_its_catalyst_or_lapse`. /code-review found a second path, filed as #220: `lots_with_crafts`/`held_at_writing` fold a Prediction's held units at its written day with no check against now, so until Nov 4 Paid/ROI and tied_up for its Item Keys are off on the live Brain (not the Backtest; fixes itself on Nov 4). #211 (0d7ddbb): `DEFAULT_RISKY_MAX_LOSS_SHARE` 0.5 -> 0.25, config.example.toml, ADR-0041 amendment (revisit at 10 graded Risky Flips; the user's config.toml doesn't set it). Backtest on 97 Beta Scans with predictions.toml after #209: brain +90g 69s vendor mark (175g 59s market, 103 buys), matching the audit's no-Predictions +90.7g, so the bug was the whole -10.5g swing (87 min run). It still carries the 11288 re-buy artifact (#212).

Next: /tdd #210 ("no Live sales seen yet" reason) before Nov 4 if budget allows, then the Nov 4 checklist under later 174. After launch: #212 first. Gotchas: the venv is at the repo root (`.venv`), not `brain/.venv`; run tests as `../.venv/Scripts/python -m pytest` from `brain/`. The instance-lock test still fails under the venv (launcher PIDs), known.

2026-11-01 (later 197): Independent audit Pass 2 done (`docs/research/independent-audit-2026-11-01/pass2-audit.md`; a fresh Opus agent read the code and data before any docs) and grilled, no code. The two headline claims were confirmed in the code: `Prediction.active_on` ignores `written` (predictions.py:32), and the Backtest re-buys the same Listings at every Scan. A Flip to Vendor closes at once and never counts as posted (backtest.py:236), so 11288 wands at 100c were 136% of the Brain's +90.7g. Grill decisions: ADR-0042 (no tuning on Beta; Live fits on week 1, judges on week 2, bars from measured noise; Flip Grades + calibration report are the primary judge, the Backtest is a sanity check). Filed in work order: #209 written-date bug (before Nov 4), #210 "no Live sales seen yet" reason (before Nov 4 if it fits), #211 Risky limit back to 25%, #212 Backtest re-buy then rerun and re-judge ADR-0034 to 0041, #213 calibration report, #214 per-gap exposure (needs grill), #215 Live cancel discount + holdout plan (later). Also filed, open since the 10-06 review: #216 dearest-unit pricing, #217 holdings room, #218 Buy Under highlights, #219 Partial Sales tests. Security: `pool_admin_secret` (brain/config.toml) was printed into the audit agent's tool output; user agreed to rotate it.

Next: /tdd #209 (one line + test), then #210 and #211 before Nov 4 if budget allows, then the Nov 4 checklist under later 174. After launch: #212 first, because it unblocks re-judging everything. Gotchas: Nov 4 checklist step 1 already sets `beta_sell_rate_weight` to 0.5, so #210's wording matters mostly for Item Keys with no Beta Sale Events either. Expect the fixed Backtest to show the Brain losing on Beta: that's the expected result, not a regression.

2026-11-01 (later 196): #207 Addon half done, TDD + /code-review (e92ca05). The tab "Prediction buys" is now "Predictions", built from `entry.predictions`. It has a header row per Prediction (wording as the CLI: "<name>: N held, X of Y tied up, lapses <date>" or "Catalyst on <date>") and a line per Item Key with a Held column. Lines with no buy show the reason starting at Qty, spanning the buy cells (`row.span`, drawn in the frame's drawLine). Under any sort, each header stays above its own lines and buys come before reason lines. Headers can't be selected, marked or searched; reason lines can't be marked or searched. The tab counts buys only (user's call). A saved "Prediction buys" tab reopens as Predictions (`RENAMED` in openingTab). The Prediction column is gone. A contract check found a real bug the specs missed: Lua's table.sort can compare a header with itself, which crashed on nil `order`. It's fixed and has a spec. The check rendered a PredictionSummary through the Brain's `render` and then ran `RecommendationTable.build` (scripts in scratchpad session 9957101a, `e2e.py`/`e2e.lua`). 378 busted specs. The Beta 97-Scan run was not repeated: the Brain is unchanged since 56d8d7c's acceptance. Review left as is: the header line still says "Prediction buys <cost>" (that's the total of the Prediction buys, the CONTEXT.md term); a sort saved under the old tab title is dropped once and falls back to the default; `r.reason` is checked in several places. Pushed; #207 open until the in-game look on Nov 4.

Next: Nov 4 at the PC, the checklist under later 174. Add an in-game look at the Predictions tab: headers, reasons spanning the buy cells, right-click does nothing on a reason line, Search hidden there. After launch: move TooltipLines off `predictionBuys` onto `predictions`, then drop `predictionBuys` from the export. Gotchas: run specs with `cmd //c ".lua\bin\busted.bat --directory=addon"`. Python that rewrites Lua files opens them in text mode and writes LF, so restore CRLF (`sed -i 's/$/
/'`) or the working copies end up with mixed line endings. Apostrophes inside a bash heredoc broke the Bash tool once; write the script to the scratchpad instead.

2026-11-01 (later 195): #207 Brain + CLI half done (56d8d7c, not pushed): `MarketRecommendations.predictions` = a `PredictionSummary` per active Prediction (held, tied_up, cap, lapse/happened) with a `PredictionLine` per Item Key (held, buy Row or reason text from `no_buy_reason`). `brain recommend` shows a Predictions section; `--why-not <id>` covers Prediction Item Keys with no buy; SavedVariables gets `predictions` (name, held, tiedUp, cap, lapse, happened?, lines[{itemKey, held, buy?, reason?}]) next to the old `predictionBuys`. Acceptance on Beta history passed (Launch week mats 5 buys unchanged, Briarthorn/Bruiseweed/Swiftthistle/Medium Leather and all 11 Weeks 2-3 lines show "would lose N%", --why-not 4306 = would lose 37%; recommend 304s). User picked: only active Predictions get a header; a future `happened` reads "Catalyst on <date>". "would lose N%" rounds up. Review left as is: `predictionBuys` duplicates the buy Rows until the Addon moves over (then drop it from the export, but SearchButton/Tooltip read it: check); "out of gold" also shows when the Budget is what ran out.

Next: the Addon half of #207, review by end of Nov 3, else skip it (fallback = what's committed). Tab "Prediction buys" -> "Predictions" in RecommendationTable.lua/RecommendationFrame.lua/SearchButton.lua/Tips.lua (and openingTab saved titles), built from `entry.predictions`: a header row per Prediction ("Launch week mats: 13 held, 14g 54s of 14g 55s, lapses 2026-11-11"), a row per Item Key with a Held column, the reason in place of the buy cells. Header rows must stay above their own lines under any sort, aren't markable/searchable. Then the Nov 4 checklist under later 174. Gotchas: Lua toolchain is repo `.lua/` (gitignored); its .bat/luarocks paths were repointed Z: -> C: this session. Run specs with `cmd //c ".luainusted.bat --directory=addon"`, and real-Lua Brain tests with `LUA=../.lua/bin/lua.exe`. In this Bash tool, backslashes in heredoc'd Python get mangled: use the Edit tool or chr(92).

2026-11-01 (later 194): #207 grilled, no code (decisions comment 6561251266, now ready-for-agent). Before Nov 4, one TDD slice, display only (no change to what's bought, no Backtest rerun): tab "Prediction buys" -> "Predictions"; a header per Prediction (units held, gold tied up of its cap, lapse date or "Catalyst happened"); one line per Item Key with a Held column, buys first, else the first reason that stopped its next unit: none listed / at Merchant Cost / would lose N% (cheapest unit's Loss %) / cap full or all Predictions' cap full (+ "halved: Predictions losing" under the brake) / out of gold. One reason function read by `recommend`, `--why-not` (now covers Prediction Item Keys with no buy) and the Addon. Fallback: not reviewed by end of Nov 3 -> ship Brain + CLI only. Standing max price per Prediction Item Key filed as #208 (after launch, needs-triage). CONTEXT.md Prediction updated.

Next: /tdd #207 per decisions comment 6561251266, then /code-review and commit; then the Nov 4 checklist under later 174. Gotchas: the no-buy reasons come out of `_hold_buys` (stops at Merchant Cost or first unit over Max Loss) and `_spend_on_predictions` (`_Caps.room` = min of per-Prediction and total; brake halves both), both in recommend.py; the acceptance run is the Beta 97-Scan history through the fake install as in later 181 (expect Launch week mats' 5 buys unchanged), ~10 min, one run at a time.

2026-11-01 (later 193): No code. Showed `brain recommend` on Beta (Scan 97) with item names (names from item links in saved SavedVariables; script in scratchpad session 553abe94, `names.py`/`named.py`). User asked why the Prediction tab is so thin; filed #207 (needs-info): show every Item Key of each Prediction with a reason, and the open question of a per-Scan buy list vs. a standing plan per Item Key. Launch week mats hit its 15% cap (14g 45s of 97g); Weeks 2-3 mats got no rows, reason unconfirmed: `--why-not` can't explain a Prediction Item Key with no buy (noted on #207). `brain recommend` took 9m23s on this PC, not chased.

Next: /grill-with-docs #207 (what ships before Nov 4, what waits), then the Nov 4 checklist under later 174. The Backtest reruns and the "missed" glossary pass from later 192 are still optional.

2026-11-01 (later 192): #152 and #150 (c) pulled back before Nov 4 and built TDD + /code-review (bcd5b5d, pushed). Own Purchases leave Sell Rate's Sale Events and the Backtest's Sale Records: exact stack at the Purchase's unit price first, else cheapest-first units within what it paid; before the price check, never own Listings, only mail read before `until`. `brain backtest` prints "Own Purchases left out of Sell Rate". A Disappearance an identical Listing new in the next Scan explains (as it stood in that Scan, `listings_first_seen_in`) was only missed; next Scan only before `until`; cached per window keyed by the next Scan's time. Beta 97 Scans: Sale Events 60,492 -> 55,143, Sale Records 188,011 -> 169,709 (resurrections are most of it; own Purchases 104 units). `brain bench` pass 2 3.7s -> 4.0s. CONTEXT.md Probable Sale / Sale Event / Sale Record updated. #152 closed; #150 open for per-item hours (measure first).

Next: optional, rerun the 87/97-Scan Backtests (brain, auctionator, gap line) to see what the smaller Sale Records did to P&L, one at a time; then Nov 4 at the PC, the checklist under later 174 (step 1 restarts `brain watch`, which picks this up). Gotchas: "missed" (a Listing back in the next Scan) has no glossary entry yet, worth a /domain-modeling pass; a Listing that comes back can still pair as a Repost in the window after (errs toward fewer sales, noted on #150). A backslash-n escape written through a bash heredoc into a Python script came out as a real newline three times this session: use Edit for string literals.

2026-11-01 (later 191): #204's two rerun findings grilled, no code. (a) No-data units vendored at first expiry: kept as the Backtest's stand-in for the player's call where the Brain shows "no data"; ADR-0032 amendment, not filed. (b) Lots that keep reposting (brain's 22 still-posted lots, 41.85g over 194 postings on 97 Scans): the Holdings test never reads the lot's own Expired Outcomes. Same as #189 (#171 slice C): evidence added there (#206 filed then closed as a dup), decision 8's blocked rebuys folded in, after launch. Nov 4 checklist refreshed for the drive clone: step 1 (weight 0.5, drop the `_classic_beta_` install if the Beta column doesn't need it, kill the Startup watch before restarting, one watch only, no lock errors), step 11 (launch Predictions already written). User: rest of the drive migration (global CLAUDE.md steps 7-8, game-configs) waits until after Nov 4.

Next: Nov 4 at the PC, the checklist under later 174. Nothing Brain-only is queued before it; if there's budget, after-launch work from later 174's list. Gotchas: `brain watch` pid 30448 (started Oct 31 12:28) predates #204 and has no 0.5 weight; step 1 restarts it. Run at most one Backtest at a time on this PC.

2026-10-31 (later 190): #204 built TDD + /code-review. The Backtest exits held units like the Brain's Holdings advice for every policy: at the first Scan at or after a 24 h posting runs out, each unit loses a Deposit, then reposts at the Holdings `post_at` (its own without one) while price after the cut less `queue.lost(i)` beats Vendor, up to the Holdings room; the rest is vendored. Sale Records in the gap between postings don't fill. New `holdings_advice` + `HoldingsAdvice` + `units_selling` (shared with `_holding_rows`) + `_Valuer.holdings_room` in recommend.py; the queue uses `deposit_of`'s Deposit (what the Backtest charges). Split is sold out / part vendored / still posted with postings and Deposits lost. ADR-0032 step 2 + amendment, CONTEXT.md. Reruns at 5s (comment 6551852795): 87 Scans brain +136.04g -> +148.25g, auctionator -69.69g -> -51.68g; 97 Scans brain +57.34g -> **+107.90g**, auctionator -69.89g -> -54.27g, gap +182.1% -> +298.8%. Line on #83, #203 closed.

Next: the user's call on two findings from the reruns: (a) units with no Sale Events are vendored at their first expiry (room 0), where the Brain's Holdings say "no data": auctionator now buys ~3x as often because of it; (b) brain's 22 still-posted lots on 97 Scans lost 41.85g over 194 postings (Beta Sell Rate keeps saying they sell; also blocks rebuys ~9 days a lot, decision 8). File either only if the user wants. Then Nov 4 at the PC (checklist under later 174). Gotchas: two Backtests at once pushed the PC into Claude Code's low-memory reaper twice (it kills background waiters, not detached runs); run dirs `r87/r97` (before) and `a87/a97` (after) are in scratchpad session b887a8b1, the worktree there (`wt`) can be removed with `git worktree remove`.

2026-10-31 (later 189): #204 grilled, no code (decisions comment 6550533641, now ready-for-agent). The Backtest exits held units like the Brain's Holdings advice, for every policy: at the first Scan after a 24 h posting runs out, unit i reposts at the Holdings `post_at` (current price when none) while price after the cut less `queue.lost(i)` (Holdings `_Queue`, exported helper like `deposit_of`) beats Vendor, capped by the Sale Horizon room; the rest is vendored. No 7+7 calendar, no 14-day stop; units aren't on the AH between a posting's end and the next Scan; Deposits per actual expired posting. Split becomes sold out / part vendored / still posted with postings and Deposits lost.

Next: build #204 TDD, then rerun the 87- and 97-Scan copies before/after (`brain`, `auctionator`, gap line), post on #204, one line on #83, close #203. Gotchas: `auctionator` will now build Sell Rates per Scan (as slow as a Brain run); the 87-Scan copy is `F:/Z-backup/aq-check-195/history.sqlite`, run the CLI as `python -c "import sys,brain.cli;sys.exit(brain.cli.main())" --config config.toml backtest --policy brain,auctionator`; get the "before" numbers from #203's comments (87: +94.41g at 2s, 97: -4.44g) only if the config matches, else rerun on a worktree of f52b5b1.

2026-10-31 (later 188): #205 grilled (decisions comment 6549911761) and built TDD (50724c5). Max Loss of a Prediction buy now steps down: a unit with no room at its post price exits at the dearest Sale Event price at or under it with room (Beta's scaled ones too while the Beta Sell Rate is on), less queue deposits, never under Vendor (`_stepped_exits` in recommend.py; ADR-0006 amendment, CONTEXT.md Max Loss). Prediction buys only, not Flips. User: keep 10%, Option A at 0.5 from Nov 4 (step 1 of the checklist), B (same-Scan dump test) dropped. Probe: on Beta the 4 risers had almost no trades near their last price (Swiftthistle 0 even at half), so the last Beta Scan is byte-identical (5 Prediction buys, 14g 45s, bounded by the 15% cap); `brain bench` pass 2 3.5 s before and after.

Next, before Nov 4: grill #204 (Backtest exits like the Brain's Holdings advice). Gotchas: `git checkout -p` is interactive and hangs the shell: to undo a mutant, copy the file aside first. The 9-item Beta Sale Event probe is `scratchpad/p205/probe.py` in session 9927425c.

2026-10-31 (later 187): User set 5s (`non_stacking_effort_copper` line removed from their gitignored `brain/config.toml`; restart `brain watch` on Nov 4 to pick it up). Rendered the last Beta Scan as the Addon would show it (artifact https://claude.ai/artifact/YQVfEeiKZA7FPVAbqAMJar): Shopping List is 1 row at 2s and 5s alike (Black Velvet Robes, 2800), no Risky rows (nothing for the loss cap to drop); Prediction buys are the 5 "Launch week mats" rows from later 181. User: buying as early as possible in a fresh market is where the gold is, and they have no idea what Live prices will be. Filed #205 (Prediction buys can't fire early in Live; options: beta_sell_rate_weight from day 1, a same-Scan dump test, or as is).

Next, before Nov 4: grill #205 (/grilling), then #204. Gotchas: a fresh `recommend` process on the 97-Scan history is cold for ~70 min the first time on a new copy (then 25 s on that copy); scratchpad `rec/` in session ebe7e852 is a warm copy with `rec_full.py` (dumps every row as JSON) and `whynot.py`.

2026-10-31 (later 186): #203 fully split, no code (comments 6547784957, 6547993793). Beta Backtest 136.0g (later 178) -> -4.4g (#203) = ~42g from the user's 2s `non_stacking_effort_copper` (5s gives +136.04g on the 87-Scan copy, 2s +94.41g: 10 more gear buys, mostly relisted) + ~99g from the 10 late Scans + 0 from code. The late-Scan part is ~81g from 24 new buys 10-07..10-13 (5 won) and ~18g from earlier buys' unsold units running their full two weeks. Over half the relisted loss (~84g of 163g) is Deposits: the Backtest reposts unsold units daily for 14 days, which the Brain's Holdings advice wouldn't. Filed #204. Deposits: Beta Sold invoices follow max(1s, 0.60 x Vendor Price x units) through 10-16; the user remembers a flat 1s late in Beta, which isn't in the data (the web reports describe the 1s minimum). Research refresh appended to `docs/research/ah-data-sources.md`: TSM still has no Forever data; a player reports a `dynamic-forever-us` API namespace since Oct 30 (realms only, auctions 404, unconfirmed); Booty Bay Broker's price file still unknown.

Next: the user's call on 2s vs 5s (the Backtest can't see Flips to Disenchant, the reason for 2s; recommended 5s now, split the knob later only if Live shows Flips to Disenchant hidden by 5s). Then grill #204 (Backtest exits like the Brain's Holdings advice) before the Dec 2 read; #203 can close once #204 is filed and the user agrees. Add to Nov 4: (a) rerun the deposit check on the first Live Sold mails (does a big post pay exactly 1s?), (b) ~10 min with a free Battle.net API client: does `connected-realm/{id}/auctions` (and `/auctions/index`) answer under `dynamic-forever-us`? Gotchas: the 97-Scan trade dump is `scratchpad/b97/trades.json` in session ebe7e852 (`dump_trades.py` next to it writes one for any config).

2026-10-31 (later 185): #203 triaged, no code (comment 6547288171). It's the 10 late Scans, not code: on the 87-Scan copy with the 97-Scan run's config, fae7e3c (#200) and current main give byte-identical output, +94.41g vendor (99 buys, relisted 43 made -61.89g). On 97 Scans it's -4.44g: 24 more buys, ~101g more relisted loss, week-1 sellouts about the same. Side finding, untested: later 178's +136.0g used the default 5s `non_stacking_effort_copper`. At the user's 2s (#172) the same copy gives +94.4g, so the 2s may cost ~42g.

Next: the user's call on what #203 needs now: (a) one 40-min run at 5s on the 87-Scan copy to confirm the effort-knob cost (matters: the user's config is at 2s), (b) list the late relisted lots (bt196 `trades.py` with policy `brain` on the 97-Scan copy), or (c) leave #203 as a Beta-market fall and close it. Also still open: the Dec 2 "Brain P&L > 0" rule (#202). Gotchas: the 87-Scan copy is now at `F:/Z-backup/aq-check-195/history.sqlite`; run dirs with a secret-free config are in scratchpad session ebe7e852 (`main/`). Run the CLI as `python -c "import sys,brain.cli;sys.exit(brain.cli.main())" --config config.toml backtest` (no `brain.__main__`). Old code runs from a `git worktree` with `PYTHONPATH=<wt>/brain/src`. `git worktree list` still shows a dead `Z:/aq-check-168b/head`; `git worktree prune` clears it.

2026-10-30 (later 184): #196 done and closed (f523356, 70334d3), TDD + /code-review. `auctionator` Backtest policy: Flip to Sell only, the Listings at the cheapest ask when posting 1c under the next-lowest ask beats them after the cut and one Deposit; at most 1/5 of the Stake (user's pick) AND a stack of 20 units per Item Key (added after the first Beta run bought 528 Copper Rods and ended -191g); most profit first, the last Item Key gets the whole Listings the gold left buys. `brain backtest` prints the Dec 2 gap line when brain and auctionator both run; `--policy` can now be repeated. ADR-0039 has the cap note. Beta read posted on #83 (comment 6532277791): brain **-4.44g** vendor (x0.65 -14.15g, x1.2 +10.78g), auctionator -69.89g, gap +93.6% / +78.0% / +114.3%. Finding: the Dec 2 rule passes when both lose money (proposal on #202: also require Brain P&L > 0; user to decide, ADR unchanged). Filed: #201 stronger Auctionator (post at price history), #202 Backtest beside `brain profit`, #203 Brain loses on the full 97-Scan Beta Backtest (week-1 sellouts +161g, relisted -163g; the +136g in later 178 was an 87-Scan copy).

Next: triage #203 (is the loss the 10 late-Beta Scans or code since #200? rerun current main on `Z:/aq-check-195/history.sqlite`, the 87-Scan copy, ~40 min), and the user's call on the Dec 2 "Brain P&L > 0" rule. Nov 4 at the PC (checklist under later 174) is a date, not next. Gotchas: the run copy is in scratchpad session aa493372 (`bt196/`: config.toml without predictions, history to 10-22, trades.py lists a policy's trades by profit). The Brain Backtest on 97 Scans took ~75 min alone (Auctionator alone ~5 min). `brain watch` (pid 26488) is still on old code: restart before playing.

2026-10-30 (later 183): #174 and #172 triaged and closed, no code. #174: not a bug, `pending` means the 7-day Sale Horizon hadn't passed when the review took its 10-08 copy; on today's history both 13114 buys grade as sold. #172: the effort charge was already `non_stacking_effort_copper`. User's calls: one knob (no Disenchant-only knob), config.toml only (not in game), 2s for them, set in their gitignored `brain/config.toml`; the 5s default stays for guildies. Probe on the latest Beta Scan (10-20 19:52): Flips to Disenchant rows at 5s/2s/0, Minimum Profit on and off, were 0 in all six, so the click cost isn't what empties that tab now (the review's cheap greens aren't listed). Not chased. The probe script is `scratchpad/de_probe.py` from session 9c1c2d4e (calls `run_recommend` with `dataclasses.replace` on the config; 6 passes took ~15 min).

Next: the QoL list is empty, and Nov 4 at the PC (checklist under later 174) is a date, not next. Until then, Brain-only work from the after-launch list: #196 Auctionator baseline as a Backtest policy (ready-for-agent, /tdd). Gotchas: `brain watch` (pid 26488) is on old code and old config (it reads config.toml once at start): restart it before playing so the 2s effort and the #116 speedup apply. Never `git stash` (it wipes `.git/index` here; the fix is in later 182). Run at most 2 Backtests at once on this PC.

2026-10-30 (later 182): #116 done and closed (f4b75e1). Re-bench found a regression: with today's predictions.toml, `brain bench` pass 2 was 217 s (3.5 s without it). `held_at_writing` costed each held Item Key with an uncached Valuer, twice a pass, and Predictions written after every Scan never freeze. Fix: `fair_value_cache` threaded through held_at_writing/grades/exit_values/Lots helpers, held-at-writing memoized per Prediction per pass, `exit_values`/`deposit_of` use `_valuer_at` (Valuer before Flips), `non_stacking` in scan_only. Three-pass: new Scan 288 -> 11.4 s, no Scan 269 -> 4.0 s, byte-identical (numbers on #116, comment 6528353028).

Next: triage #172 and #174 (QoL before Nov 4), then Nov 4 at the PC (checklist under later 174). Gotchas: the running `brain watch` (pid 26488) is on the old code and takes ~4 min a pass with predictions.toml: restart it before playing. I used `git stash` again despite the later-163 gotcha and it wiped `.git/index` again; `git reset -q` + `git update-index --skip-worktree addon/AzerothQuant/Recommendations.lua` fixed it. Check red by editing code by hand, never stash. `test_instance_lock.py::test_another_running_brain_holds_the_lock_until_it_is_killed` fails on main too (not filed; likely the running watch). Bench any Decision Engine change with a predictions.toml in place; the three-pass script is `scratchpad/bench/three.py` from session f48801ea (rewind latest Scan, pass 1, import it back from brain/archive, passes 2 and 3).

2026-10-30 (later 181): Predictions rows done (ee59a94), release step 5. Check run on Beta history: Recommendations.lua gets 5 Prediction buys, all under "Launch week mats" (10940 x651, 10938 x498, 2592 x365, 2771 x62, 2841 x12; 14g 45s total, Loss % 5-6%), and "Weeks 2-3 mats" has only a Hold (4306 x2). Grilled, user took every recommendation: the Prediction buys tab adds Loss % (Max Loss / Cost, downside only, ADR-0006) and Cost; no Profit column. Fold: user does NOT want Prediction buys hidden, so they never fold (a spec pins it) and unaffordable rows look normal, no tag. CONTEXT.md (Bought mark, Max Loss) updated. Addon only, no Brain change. Clicking (Search, #39) and grouping (sort by Prediction) were already there.

Next: QoL before Nov 4 (later 174's list): #116 fast loop (ready-for-agent, /tdd), then triage #172 and #174. Nov 4 at the PC (the checklist under later 174) is a date, not next. Gotchas: the top Prediction buys are hundreds of units; the big-runs rule was for Flips, and the user didn't raise it for Predictions, so it's not filed. `Z:/aq-check-preds` is safe to delete.

2026-10-30 (later 180, stopped early, PC off): Predictions rows step started. `brain/predictions.toml` is written (gitignored) with the two launch Predictions from #91 comment 6427046797. The check run (`Z:/aq-check-preds/predrows.py`: calls `recommend` once, writes Recommendations.lua into a fake install under the folder given as argv[1] (it needs `<dir>/fake/Interface/AddOns/AzerothQuant`), and prints the Prediction buys and Holds under a Prediction) was stopped before it finished. Rerun it: `.venv/Scripts/python.exe Z:/aq-check-preds/predrows.py Z:/aq-check-preds`, ~30 min. Addon read so far: the Prediction buys tab already has Search (#39), can be marked Bought, and sorts by Prediction. Next to the Shopping List it has no Cost column, no Profit-ish number, and doesn't fold on gold left (`fold` is nil for it in RecommendationTable.build). Those go into the grill. Nothing built or committed.

Next, in order: rerun the check, /grill-with-docs the gaps, /tdd, /code-review, commit. Then Nov 4.

2026-10-29 (later 179): #173 done and closed (fd986ca), grilled (spec comment 6511624125) then built with TDD. ADR-0019 amended: a Buy Under has no Sell way, so it falls back to Vendor, Craft or Disenchant (latest Beta Scan: 154 -> 19 Buy Unders: 13 Disenchant, 3 Vendor, 3 Craft). Backtest (87-Scan copy, 40g), Sell-way lots: unchecked -50.4g, with the price-moved test (`take_under`: buy only while nothing else is listed under the post price) -50.0g, plus a Recent Price check -53.4g (that patch was not kept). The test halves the buying but not the loss: the crash comes after the buy. The Sell way stays behind `buy_under_sell_way` (off, not in config.toml); the `buyunder` / `buyunder_unchecked` Backtest policies turn it on and print P&L by way, to regrade on Live. No Addon issue filed (the live test was only for a pass). Must-pass Troll's Bane wasn't bought in any run.

Next, in order: Predictions rows (later 174's step 5: write `brain/predictions.toml` with the two launch Predictions from #91 comment 6427046797, run `brain recommend` on Beta history, check Hold and Prediction buy rows reach Recommendations.lua, compare with the Shopping List's click/price/grouping), then Nov 4. Gotchas: running 2 Backtests at once got their wrapper shell killed for low memory, but the Python processes kept running and wrote their files: check `tasklist` before rerunning. `Z:/aq-check-173`, `Z:/aq-check-200` and `Z:/aq-check-195` are safe to delete (173's run.py dumps every trade as JSON, a useful template).

2026-10-29 (later 178): #200 done and closed (fae7e3c), built with TDD. ADR-0041 has the results. Skipping the cheap-stock cutoff for every Flip to Sell under its Recent Price LOST the Backtest (-7.1g vendor vs main 131.4g), so the spec's fallback is built: only a long Risky row (> risky_max_units) skips it. `_Valuer._flips_of` runs `_flips` a second time with the skip for an Item Key with a Recent Price and cheap stock, and hangs those runs on `_FlipToSell.long_runs` (a `_FlipToSell` may have empty `runs` then: only a Risky row comes from it). The all-rows skip is `recent_price_skips_cutoff` (off, not in config.toml). The user raised the long Risky loss limit 25% -> 50% (`risky_max_loss_share`; Steel Bar's real buy was 43% of the 41.2g Stake). A too-big long run shrinks to the best long run within the limit (review catch). Minimum Profit adds 5s a click (`row_min_profit_per_click`); `--why-not` says which term bit. Built: 136.0g vendor / 161.0g market from 40g (the per-click floor alone; Risky rows aren't backtested). Must-pass met: Steel Bar is a 216 Risky row at 1791734591; no Cured Medium Hide at 1791844181. Rows per Scan: normal 1.96 -> 1.85, Risky 1.18 -> 2.60 (so many long Risky rows now show on Beta, 18-29 units; their Flip Grades will say if they pay).

Next, in order: #173 (Buy Unders lose money as standing orders: grill, then build), then Predictions rows, Nov 4. Gotchas: the final #200 Backtest was stopped by the OS for low memory after 50 of ~107 calls (its rows and gold matched the cutoff-kept run call for call); run at most 2 Backtests at once on this PC. Tests that turn the Minimum Profit off need `row_min_profit_per_click=0` too. `Z:/aq-check-200` and `Z:/aq-check-195` are safe to delete.

2026-10-29 (later 177): #200 grilled, no code. Spec comment 6506552213, ADR-0041, CONTEXT.md (new **Recent Price**; Minimum Profit and Risky row updated). Summary: Minimum Profit adds clicks × 5s; a Flip to Sell posted at or under its Recent Price (7-day median sale price, ≥3 Sale Events) skips the cheap-stock cutoff; Risky rows come back at any size, and above 5 units must post under the Recent Price, stay within #198's clipped demand, and lose ≤25% of the Stake. Finding: Steel Bar and the hide are both blocked by the cheap-stock cutoff today, not the cap (Steel Bar by stock 3% under its post a day earlier). The user's "only a few suggestions late in Beta" is what #200 is for; rows per Scan get reported before/after.

#152 + #150 deferred past Nov 4 (user, 2026-10-29), per their 10-24 triage comments (both under the ~5% bar). Re-check on Live with #153's backtest line.

Next, in order: build #200 (/tdd, spec comment), then #173, Predictions rows, Nov 4. Gotchas: a cold history copy takes ~27 min and ~1.5 GB per Scan in `recommend_market`; probes must use `paid=False` like the Backtest, since `paid=True` also builds a latest-Scan valuer (a probe that spied on the last valuer got future data that way). Probe scripts in `Z:/aq-check-200/`. ADR-0036/0040 both lost by loosening Flip to Sell; the cutoff skip may too, so the fallback (big Risky rows only) is in the spec. `Z:/aq-check-195` is safe to delete.

2026-10-29 (later 176): #195 grilled (spec comment 6484894211), built with TDD, swept, and LOST; code not kept (diff in `Z:/aq-check-195/issue-195.patch`). ADR-0040: the Unsold Loss cap stays a flat 3%. Backtest (87-Scan copy, current main): `brain` 131.4g vendor / 156.6g market from 40g; ceilings 6/10/15% at 65.9/90.0/86.9g, every grader bound lower. From 15g: `brain` 104.8g vs 97.3/53.8/64.5g. Finding from the grill: on the latest Beta Scan the cap shrinks nothing (caps off gives the same 4 rows); #197's minimum is what drops 3. Must-pass: no hide row at Scan 85 at any ceiling; Steel Bar, Staff of the Friar, The 1 Ring, Redbeard 09-28 and Troll's Bane 10-06 aren't named even at flat 3% (something besides the cap; not chased, not filed).

Next, in order: #152 + #150 (release step 3, /tdd), then grill #200 (user, 2026-10-29: no hundreds-of-units flips for small gain; big profitable runs show, Risky if over the cap; watch the hide-buyout evidence), then #173, Predictions rows, Nov 4. Gotchas: same as later 175. `run_backtest`'s start_gold is copper (40g = 400_000): a sweep script that passes gold starts at 40c and buys nothing (cost a 2 h rerun). `Z:/aq-check-195` (run.py, sweep.sh, the 87-Scan history) is safe to delete.

2026-10-28 (later 175): #197 done and closed (99fbb95), grilled then built. **Minimum Profit** (CONTEXT.md): a Shopping List row under max(`row_min_profit_copper` 10s, `row_min_profit_share` 0.5% x Stake) is dropped in `_options` before the row cap, so it frees its place; every kind of Flip and Risky rows, not Prediction buys or Buy Unders; Profit only. Backtest `relaxed` zeroes it, `uncapped` keeps it. `brain recommend` header: "each making at least X"; `--why-not` has a Minimum Profit Check between Budget and Row cap. The Stake now counts own Listings up even with `risk_caps` off (review catch). Real Beta: 97g Stake, 48s 50c minimum, Shopping List 4 rows -> 1 (76s). Most rows are small because the 3% Unsold Loss cap sizes them small, which is #195's job. Review note, not filed: `_why_not` sizes rows without the risk caps (pre-existing, Row cap had it too), so a row the caps shrink under the minimum shows "made the list" in why-not.

Next, in order: #195, then the rest of later 174's list from step 3 (#152 + #150, #173, Predictions rows, Nov 4). Gotchas: same as later 173. Test configs that turn the minimum off need both `row_min_profit_share=0.0` and `row_min_profit_copper=0`.

2026-10-28 (later 174): Release planning, no code. User: launch is next week and this reset is the budget for it (aim to use 60-70%). Goal for Nov 4: the Brain working as intended with good recommendations, then must-dos, then QoL. #196 is the Dec 2 checkpoint, not release work, so it moves after launch.

Next, in order (user's call):
1. #197 min Profit per row that grows with the Stake (user's "50s trades" complaint). /grill-with-docs then /tdd.
2. #195 Unsold Loss cap grows with strong sale evidence (user's call from #194; a flat 3% of a small launch Stake blocks every Flip worth doing). /grill-with-docs then /tdd.
3. #152 + #150 pulled back before Nov 4 (later 169 had moved them past it on Beta's tiny numbers; at launch, with zero history, a few fake sales from own buys or dropped unloaded links are a big share). Both ready-for-agent: /tdd.
4. #173 Buy Unders lose money as standing orders (45 of 78 fully sold Lots lost). Grill, then build.
5. Predictions in game: rows are enough (user). Write `brain/predictions.toml` now with the two launch Predictions from #91 comment 6427046797 (Classic IDs), run `brain recommend` on Beta history, check Hold and Prediction buy rows reach Recommendations.lua. User wants them like the Shopping List: clickable, a price, grouped by Prediction. The Prediction buys tab already has Prediction/Qty/Price/Max Loss columns (sortable by Prediction) and the Search button (#39); check what's missing against that (maybe a Profit-ish column or grouping by Prediction) and build only that. Launch-day buys won't fire (Max Loss needs Live sales), so day 1 is mostly Holds.
6. Nov 4 at the PC: the checklist below.
QoL if budget is left: #172 effort setting, #116 fast loop, #174. After launch: #196, #183, #188, #185, #186, #187, #165, #198. Guildie work stays parked.

2026-10-27 (later 173): #184 done and closed (9e0cb75, 5e1a76e), grilled then built. Replay is retired (ADR-0039, which supersedes ADR-0015). The Dec 2 Live checkpoint is `brain backtest`, Brain vs. an Auctionator policy: P&L at the vendor mark, 1x grade, continue at +10% or more, stop within ±5%, live split in between, 0.65x/1.2x shown beside it. No TSM port, no ablation table. #83's body is restated for this. #196 is rewritten as "Auctionator baseline as a Backtest policy" and labelled ready-for-agent (post cap to pick and justify). Realized profit is the new `brain profit [--since] [--until]` (`realized.py`). Also deleted: recommend's `pricer`, `Config.flips_to_craft`/`deposits` and `Row.merchant_gold`. `_flips`' old pricer argument is now `post_by`, used only by `clearing_run` (ADR-0038). `brain recommend` on the real history is identical before and after. `brain/replay-83/` is deleted. Review note, not filed: test_replay's end-to-end "options most profit first" test wasn't ported; the `options_taken` unit tests in test_backtest cover the rules.

Next, in order: #196 (/tdd, before Dec 2), then #195, #197; #188 stays parked. Then Nov 4 at the PC, the checklist below. Gotchas: `test_instance_lock` still fails on this PC (as in later 170). In this Git Bash, Python heredocs mangle `\n` and `\\` in string literals, so use Edit for escapes.

2026-10-26 (later 172): #91 more Predictions, no code. The user's launch-window calls (3 waves) checked against Beta history and posted as comment 6427046797 with defaults: two new Predictions, "Launch week mats" (lapse Nov 11) and "Weeks 2-3 mats" (lapse Nov 25); wave 3's new Item Keys join potion mats / Enchanting / T1 reagents. Beta (09-27..10-20, mid-Beta, not a launch) backs wave 2's herbs (Kingsblood, Liferoot, Goldthorn, Fadeleaf up 5-10x) and Swiftthistle; Strange Dust, Lesser Magic Essence, Silk and Wool fell; raid mats too thin to read. Launch-day buys won't fire (no Live Sale Events yet, Max Loss rule), so wave 1 is mostly Holding what's gathered. Nov 4 step 11 updated. Queue unchanged.

2026-10-26 (later 171): #151 done (e87ec24), grilled then built. ADR-0038 amends ADR-0017: when `_Valuer.clearing_run` exists for a held Item Key (a Flip to Sell would buy its cheapest others' Listings), the units that would Sell at `post_at(bought=run.units)` become `Action.WAIT` rows at that price and profit; the tail and bound units still Vendor. `wait_at` is None under a pricer, when the Valuer already bought the Item Key (`flipped`, the #108 Checks), or with no others' Listings. Wait counts as a post in `_held_exits` and ROI (`PRICED_AS_A_POST`), never the ROI hint; replay keeps Wait units like Hold. Addon: "Wait" row ("Keep them for now: someone's selling these cheap. Check again after the next Scan."), tooltip `AQ: Wait N, then post @ X`, not folded, no Post button. CONTEXT.md has **Wait**. Real Beta history: 0 Waits at the latest Scan (46 Sell, 49 Vendor); `brain bench` pass 2 3.0 -> 3.4 s. Review notes, not filed: units under a Prediction left over after the Hold caps can Wait though no Flip is offered for them (follows the rule); the `flipped` guard has no test (no simple scenario shows it).

Next, in order: the tuning batch: settle #184 (retire replay?) before #196's 3.5 h rerun; #195, #197; #188 stays parked. Then Nov 4 at the PC, the one checklist below (replaces later 161-168's scattered steps).

**Nov 4 at the PC** (Claude runs the Brain side and reads logs/screenshots; user does only game steps):
1. (Config part done 2026-11-01, later 199.) Claude: set `beta_sell_rate_weight = 0.5` in `brain/config.toml` (#205, gitignored). Check the Beta column reads from history, not the `_classic_beta_` install (that folder is gone since the drive clone); if so, remove that `[[installs]]` entry. Then restart `brain watch` so it runs current main (239f44f or later) and the new config: the Startup `brain-watch.bat` starts one at login (system Python, `python -m brain.cli watch`), so kill it first and confirm only ONE is running, then check the first sync in `brain.log` has no "database is locked" (seen Oct 30 during the migration). Quick look that `_forever_/Interface/AddOns/AzerothQuant` and `AQProbe97` are still the `C:ibing` junctions and the Data slots are current (#147 step 2). Before the user's first open, clear `recommendationFrame`/`recommendationFrameSize` in the Live SavedVariables (for the #164 check).
2. User: launch Live. If AzerothQuant shows out of date, say so (tick "Load out of date AddOns" for now). Claude: if Live's Interface isn't 16001, bump the `.toc` and ship a patch release (#147).
3. User: open the AH. #164: the table's first open sits right of the AH, or below it on this ~1365-wide screen; resize, close, reopen, it keeps the spot.
4. User: Scan, `/reload`. Claude: watch the import in `brain.log`, then the pool counts per Era (Live push/pull working, Beta not re-imported as Live) (#147).
5. User: open the table, screenshot. Expect the young-Market line, the Beta column, no problem line (#147).
6. #161 banner, steps 1-6 on the issue: tabs on top, banner Scan -> Scanning -> Reload -> "The Brain is working" -> Load -> the one-line up-to-date with the cooldown.
7. #160 side pane and #136 resize, on every tab with Beta on and off, narrowest and widest: per the lists on those issues (no Note column, pane follows hover/click, hidden columns in the pane, Post/Search from the pane, Bought right-click; grip, refit, size survives /reload, Craft Chain on screen).
8. #180: Scan, walk off, `/reload`; the sound + "You can Scan again" line come ~15 min after the request; with the AH open, sound only.
9. #151: if any Holdings row says Wait, check its text, that it isn't folded, has no Post button, and the tooltip reads `AQ: Wait N, then post @ X`. Don't force one.
10. AQProbe97 (`docs/research/issue-97-probe/README.md`): `/aqp clear`; `/aqp note commodity` + part of a commodity stack; `/aqp note item` + one gear Listing (suffix if possible); `/aqp note failed` + a try at a failed buy; wait ~10 s, close the AH, `/reload`. Claude reads `SavedVariables/AQProbe97.lua`, posts on #85, removes the junction, then grill/build #97 slice 2.
11. #91: Claude searches the first Live Scans for Demon/Undead/Slaying/Protection names and gives a shortlist; user confirms and reads any Item Keys the Scans lack; eight Predictions go in `predictions.toml` (the six + "Launch week mats" and "Weeks 2-3 mats", draft TOML and the Dec 9 additions in #91 comment 6427046797). The two launch ones are already in `brain/predictions.toml` (Classic IDs, `written = 2026-11-04`): right after step 4, check their Item Keys show up in the first Live Scans; the other six follow as planned.
12. Check the setup guide against what a guildie sees; fix wording the same day (#147 step 6).
13. XP food (#91 comment 6429464226): user eats a low-level food (e.g. Herb Baked Egg) and a higher one, kills the same mob type under each, and screenshots the XP per kill and both buff tooltips. If every food gives the same +5%, no Food Prediction. If a higher food gives more, Claude proposes a Prediction for it (and maybe its reagents).
~Nov 6: recheck #110's `beta_sell_rate_weight` (0.5 from Nov 4, #205) against `brain recommend --beta-ratios`. Guildie work still parked (#146/#179/v0.3.0) until the user says ready.

- Gotchas: same as later 170. `test_instance_lock.py::test_another_running_brain_holds_the_lock_until_it_is_killed` fails on HEAD too on this PC (lock file holds a different PID than the spawned child, likely the venv launcher); not this work, not filed. Run Addon specs from `addon/` (`python ../scripts/busted.py`). `brain/replay-83/` is someone's untracked replay logs; left alone.

2026-10-25 (later 170): #153 done (18ca488). `observation.own_outcomes` is the one Outcome-matching rule (grader_calibration, the new drop, sell_rate_calibration). An own Probable Sale matched to a Cancelled/Expired Outcome read before Sell Rate's `until` is dropped in `_window_evidence`, after the cached `_EndsOfWindow` and after Repost pairing; an own Cancelled Listing the pairing calls a Repost stays a Repost (review call: the brief drops Probable Sales only). The `until` cutoff was a review catch: without it a Backtest as of a past Scan saw later mail. `GraderCalibration` -> `Calibration`; `MarketBacktest.calibration` -> `grader_calibration`, plus `sell_rate_calibration`. Beta history: "Sell Rate checked on own Listings: of 29 ... 79% really sold; it caught 47% of the 49 Sold mails" (grader 43/65%/57%, unchanged). The triage read was 26/22/45; the gap is in how the throwaway triage script matched mail (Sold mails 45 vs the shared rule's 49), not 10-22 (the history has no Scans or mail after 10-20). Not chased.

Next, in order: grill #151 (lowball -> Vendor; clashes with ADR-0017). Then the tuning batch: settle #184 (retire replay?) before #196's 3.5 h rerun; #195, #197; #188 stays parked. Nov 4 at the PC as in later 168.

- Gotchas: same as later 169. Git Bash heredocs that hold a Python script with apostrophes or `\n` fail or mangle; write the script to the scratchpad and run it. The Backtest now rebuilds `own_outcomes` every simulated Scan (cheap on Beta's ~280 mails; watch it if Live mail grows a lot).

2026-10-24 (later 169): Triage, no code. Found the Oct 6 plan's gap work (#153, #151, #150 (c), #152; later 102) had dropped off the queue; it goes before the model-tuning batch because that batch is judged on the demand model #153 checks. #153 re-briefed (comment 6393180136, + enhancement): #167 already did it for the Backtest grader, so what's left is Sell Rate: own Probable Sales with a Cancelled/Expired Outcome stop being sales, and a "Sell Rate checked on own Listings" line in `brain backtest`. Triage read (Beta, 10-22 out): 22 of 26 matched own Probable Sales really sold (~85%), recall 22/45 (~49%, mostly >12 h gaps). Own Purchases 0.0% of others' Probable Sale units, own dropped-row Listings 6 (none Sold): #152 and #150 (c) move past Nov 4 (commented). CONTEXT.md Probable Sale entry updated. Script: scratchpad `own153.py` (not kept).

Next, in order: #153 (/implement), then grill #151 (lowball -> Vendor; clashes with ADR-0017). Then the tuning batch: settle #184 (retire replay?) before #196's 3.5 h rerun; #195, #197; #188 stays parked. Nov 4 at the PC as in later 168.

- Gotchas: same as later 168. Sell Rate's per-window evidence is cached (`_EndsOfWindow`); a filter on mail must run after the cache or late mail won't count. Scripts importing `brain` need `PYTHONPATH=src ../.venv/Scripts/python.exe` from `brain/` (`-I` breaks it). `observation_window_max_minutes` default is 720, not the 60 the 10-08 review describes.

2026-10-24 (later 168): #193 done (5309bd1). `pull()` has `first_pull = cursor is None and since is None`; a first pull saves its cursor only when `page.more` is false, others after every page as before. FakePool now leaves rolled-back Scans out of `entries` like the Worker (`pool/src/index.ts:252`), and `fail_fetching` fails fetches of chosen IDs. The spec's double-roll-back test is pinned on `roll_back_pooled` directly: with the real contract a retry can only re-roll-back a Scan rolled back mid-attempt, which the fake can't stage. Review note, not filed: an empty pool's first pull saves cursor 0, so a later pull isn't a first pull and has no backfill bound (pre-existing).

Next, in order: nothing before Nov 4 in the Brain-only queue. Rest same as later 161. On Nov 4 at the PC: the AQProbe97 steps (later 167), the #164 and #180 checks (later 165/166), #147 checklist, #91 Item Keys.

- Gotchas: same as later 167. DON'T use `git stash` on this Z: checkout: a `stash push -- <path>` + `pop` deleted `.git/index` (every file showed staged-deleted + untracked). `git reset -q` rebuilt it; then re-run `git update-index --skip-worktree addon/AzerothQuant/Recommendations.lua`. To see a test go red without a fix, edit the code by hand instead.

2026-10-24 (later 167): #97 slice 1 was already done (8976314, passed in game 2026-09-30); the queue's "#97" meant slice 2, which waits on the #85 buy-event probe that never ran. Wrote the probe instead (e3b5435): `docs/research/issue-97-probe/AQProbe97/`, a read-only addon (events + `hooksecurefunc` post-hooks on the AH buy calls, own `AQProbe97DB`). Named apart from the old #39 `AQProbe`, whose save file is still in both WTF folders. `_forever_/Interface/AddOns/AQProbe97` is a junction to it. Smoke-run under lupa with stubbed WoW calls only; not loaded in game yet.

Next, in order: #193 before Nov 4. Rest same as later 161. On Nov 4 at the PC: run the AQProbe97 steps (README in that folder), read `SavedVariables/AQProbe97.lua`, post results on #85, then grill/build #97 slice 2 from them. Also the #164 and #180 checks (later 165/166).

- Gotchas: same as later 166. If AQProbe97 errors at load in game, check `/aqp` works and the first log entry's `missing` list. Remove the junction once the probe is done.

2026-10-24 (later 166): #180 done (720e104). New pure `Nudge.pingIn(lastScanAt, now)` (seconds until the cooldown ends, nil if none running) and `Nudge.togglePing`/`pingOn` (`/aq ping`, saved as `AzerothQuantDB.pingOff`, on by default). Scanner.lua sets a one-shot timer at the Scan request and at load; it plays `SOUNDKIT.AUCTION_WINDOW_OPEN`, plus "You can Scan again at the Auction House." in chat unless the AH is open. Chat.lua's header names the exception. Not checked in game yet.

Next, in order: #97 (offline QoL, checked Nov 4). Then #193 before Nov 4. Rest same as later 161. On Nov 4: check #164 (as later 165 says) and #180: Scan, walk off, /reload, and the sound + line should come ~15 min after the request; with the AH open, sound only.

- Gotchas: same as later 163. The cooldown math `lastScanAt + COOLDOWN_SECONDS - now` now lives in four places (Nudge.due, Nudge.pingIn, NextStep.lua, Scanner.lua cooldownRemaining); review flagged it, not filed.

2026-10-24 (later 165): #164 done (c320087). New pure `Placement.firstOpen(room, width, minWidth)`: with the AH up and no saved spot, the Recommendation Table narrows to the room right of the AH (down to MIN_WIDTH 1000), else keeps its size and opens below the AH. The pane can't collapse: it holds Post/Search, and the pane plus the columns that never hide need ~976. `savePosition` now saves the frame's TOPLEFT against UIParent (GetLeft/GetTop), not GetPoint. Not checked in game yet. The Beta Config.wtf has no uiScale, so the screen is ~1365 wide and there's only ~550 beside the AH: expect "below", clamped up over the AH's lower part.

Next, in order: #180, #97 (offline QoL, checked Nov 4). Then #193 before Nov 4. Rest same as later 161. On Nov 4, when at the AH, check #164: first open with no saved spot (clear `recommendationFrame`/`recommendationFrameSize` in SavedVariables), then resize, close, reopen.

- Gotchas: same as later 163.

2026-10-24 (later 164): #91's new groups GRILLED, decisions in comment 6392535503, no code. Two new Predictions: "Protection potions" (Greater Fire/Shadow Protection only, plus reagents not already in another Prediction; Dreamfoil stays in potion mats) and "Slaying" (only items that trade on the AH; the Demonslaying enchant and its mats are out). Catalyst is raids unlock (Dec 9), lapse Dec 23, same as the other four. Nov 4 step added: Claude searches the first Live Scans for names with Demon/Undead/Slaying/Protection and gives the user a shortlist; the user confirms and reads any Item Keys the Scans don't have; then six Predictions go in `predictions.toml`.

Next, in order: #164, #180, #97 (offline QoL, checked Nov 4). Then #193 before Nov 4. Rest same as later 161.

- Gotchas: same as later 163.

2026-10-24 (later 163): #157 closed as not planned, no code. Its premise was wrong: nothing writes the old `AzerothQuant_Data` folder; the write into `AddOns/AzerothQuant/Recommendations.lua` is ADR-0030's startup copy (TOC loads it, `DataAddon.atLoad` judges freshness and the Addon prunes by it). User's call: keep the write. On the dev checkout `git update-index --skip-worktree addon/AzerothQuant/Recommendations.lua` is now set, as development.md says, so the junction's writes no longer show in git.

Next, in order: grill #91's new groups, then #164, #180, #97 (offline QoL, checked Nov 4). Then #193 before Nov 4. Rest same as later 161.

- Gotchas: same as later 162. The stub is skip-worktree on this PC: if a commit ever needs to change the shipped stub, run `git update-index --no-skip-worktree` on it first, and a pull that changes it will refuse until you do.

2026-10-24 (later 162): #199 done. `GAME_FOLDERS` maps `_forever_` to Live; `_classic_` (MoP) maps to nothing. Setup guide, development.md and CONTEXT.md (Era) say `_forever_`; Live test fixtures moved off `_classic_`. Dev PC: `_forever_/Interface/AddOns/AzerothQuant` is now a junction to the repo, `brain/config.toml` has the `_forever_` Live install, and `brain watch` was restarted and watches both. The Oct 21 `_forever_` save had no Scans and no Mailbox Reads, only 3 Character Reads from test realm "CAMWOW US2 Realm 4 PvP". User's call: backed up (with the old Addon copy) to `brain/archive/forever-2026-10-21/` and cleared. Era comes only from the folder (`_era_of`); user's call: no realm guard, noted on the issue.

Next, in order: #157 (stop writing the old Addon path), grill #91's new groups, then #164, #180, #97 (offline QoL, checked Nov 4). Then #193 before Nov 4. Rest same as later 161.

- Gotchas: same as later 160. `test_instance_lock.py::test_another_running_brain_holds_the_lock_until_it_is_killed` fails under the venv's python.exe (it's a launcher, so Popen.pid is the launcher's PID) and passes under the base interpreter; pre-existing, not filed. `update()` still falls back to the old config's installs when it finds no game folder: harmless while no guildie has a `_classic_` Live config.

2026-10-24 (later 161): Release planning, no code. FOUND A NOV 4 BLOCKER, filed #199: Live is the `wowf` product in `_forever_` (1.60.1, same build as Beta); `_classic_` is MoP Classic 5.5.4. `GAME_FOLDERS` maps `_classic_` to Live, so on Nov 4 the Brain would read no Live Scans and guildies' `update` would install into MoP. `_forever_` already has a plain-copy Addon (Oct 21) and a save file with "Classic Beta PvP" + "CAMWOW US2 Realm 4 PvP" the Brain never read. User's prediction ideas (fire/shadow protection potions, demon/undead slaying items for Hyjal/Barrow Deeps) are on #91 (comment 6392226664), to grill.

Next, in order (user wants full release fully working + QoL): #199 (blocker), #157 (stop writing the old Addon path; pairs with the dev junction), grill #91's new groups, then QoL that can be built offline and checked Nov 4: #164, #180, #97. Then #193 before Nov 4 pulls pass one page. Model tuning (#195, #196, #188, #197) after launch. Nov 4 at the PC: #147 checklist, #136/#160/#161 in-game checks, #91 Item Keys + predictions.toml. ~Nov 6: decide #110's `beta_sell_rate_weight`. Guildie work still parked (#146/#179/v0.3.0) until the user says ready, but #199 must land before any v0.3.0.

- Gotchas: same as later 160.

2026-10-22 (later 160): #194 DONE (Risky rows, ADR-0037 amends ADR-0034). `_capped_option` sizes each option once more with the Unsold Loss cap off (room still on); a Flip to Sell the caps dropped whose run is <= `risky_max_units` (5, 0 turns it off) comes back as `risky`, with `unsold_loss` on the row. `_options` ranks normal rows among themselves so Risky rows take no place in the `shopping_list_rows` cut. `options_taken` (replay + Backtest) drops Risky rows. Lua row carries `risky`/`unsoldLoss`; Addon tags "Risky" and puts "Over your risk cap: if none of it sells you lose X." ahead of any "Capped at" line (review fix: a Risky row the room trims shows both). grades.toml shown rows keep `risky = true`. Live checks pass (10-14: 10603 risky, 13926 absent; 10-17: 10040 risky; Scan 85: no Cured Medium Hide). Backtest on a history copy byte-identical before/after.

Next: #195, #196, #188, then #193. Guildie work stays parked.

- Gotchas: same as later 157. 2026-10-22, the last Beta day, Blizzard made every mob drop epics: that day's market, gold and items are junk, so leave 10-22 out of live checks and don't read absolute Backtest/P&L numbers that include it. Running two Backtests at once on this PC got one killed for low memory (~1.1 GB each, next to `brain watch`); run them one after the other. `--why-not` still ranks uncapped, so for a capped row its ranking can disagree with the list (pre-existing, not filed). Git Bash heredocs mangle `\\n` in Python/Lua text; use the Edit tool for anything with backslashes.

2026-10-22 (later 159): #194 GRILLED -> ready-for-agent, retitled "Risky rows"; agent brief is comment 6346324624 (supersedes the 10-20 spec). Claim confirmed: at the ~17g Stake the 51s Unsold Loss cap cuts every Flip to Sell over ~1g on every Scan since 10-14, and the mail record's winners are few-unit dear flips. Decision: caps unchanged, Backtest unchanged; a Flip to Sell the loss cap drops entirely comes back inline as a "Risky" row if its run is <= risky_max_units (5). It's named, gets Lots, and is flagged in grades. Split out: #197 (min Profit growing with the Stake, needs-triage) and #198 (part 2 clip+cap, parked; caps scale away at a big Stake).

Next: #194, #195, #196, #188, then #193. Guildie work stays parked.

- Gotchas: same as later 157. `recommend_market` over 14 Scans with caps on/off takes >10 min on a fresh copy (no Fair Value cache); run it in the background.

2026-10-22 (later 158): #193 TRIAGED -> bug + ready-for-agent; agent brief is comment 6345305541. Cause confirmed, but it can't fire until the pool index passes one page (1000 entries, the Worker's MAX_PAGE; the pool has ~100), so not before Nov 4. User's call: a first pull saves its cursor only after the last page; no schema change. Queued after the others.

Next: #194, #195, #196, #188, then #193. Guildie work stays parked (user: skipping guildie stuff for now).

- Gotchas: same as later 157.

2026-10-22 (later 157): #191 DONE (commit 1299bb3, closes on push). A Flip to Vendor unit must clear max(flip_min_margin_share x unit, flip_min_margin_copper) after its buy effort, plus still > 0 so a zero margin (Backtest) keeps break-even units out as before. `_flip_margin` in recommend.py is now the one copy of the margin rule (Sell, Vendor, Craft, Disenchant). The brief's guess that --why-not needed no change was wrong: the chain checks Sale Events/Room first, so a dropped Vendor-only Item Key said "Sale Events". New branch: when the best way out is Vendor and the cheapest ask was under Vendor Price less effort (`_vendors_at_a_profit`), it's Check.MARGIN. A first, wider version (any Vendor way out) misreported unsold items with tiny Vendor Prices as margin failures with a negative clear-at; the review caught it and a test pins it. Old penny-Vendor tests pinned to NO_MARGIN (test_recommend, test_replay); the two Flip-to-Craft tests and test_cli's `_near_misses` raised Vendor Prices instead, since margin 0 would change their other rows (Linen turns into a Flip to Sell; the CLI's Linen row is a margin miss).

Next: #193 (interrupted first pull loses the window). #194, #195, #196 and #188 after Beta. Guildie work stays parked.

- Gotchas: same as later 156. The replay's penny Vendor flips are gone with this change, so replay numbers move again.

2026-10-22 (later 156): #191 TRIAGED -> bug + ready-for-agent; agent brief is comment 6344822337. User's call: a Flip to Vendor unit must clear the same Flip margin as a Flip to Sell, max(flip_min_margin_share x unit, flip_min_margin_copper) after its buy effort. No new settings, no Addon change. Why: the Buy Under's Vendor way already charges that margin (ADR-0019), so the row (Star Ruby at 49s 99c) and its Buy Under (45s 45c) disagreed. Docs amended in place (CONTEXT.md Flip, ADR-0011), no new ADR.

Next: /implement #191 (Brain-only, no game). Then #193. #194, #195, #196 and #188 after Beta. Guildie work stays parked.

- Gotchas: same as later 155. Backtest pins both margins to 0, so it won't move; the replay will lose its penny Vendor flips.

2026-10-22 (later 155): #192 DONE (commit 2edbf74, closes on push). A post's Deposit is max(ah_deposit_min_copper (new, default 100), rate x stack), split over `_Valuer.stack` units, held units included; invoices at or under the minimum teach no rate. `deposit_of` now builds its Valuer at the Market's latest Scan (with at=None it had no Sell Rates, so every stack was 1 and the Backtest would pay 1s a unit). ADR-0013 and CONTEXT.md corrected. Several old tests are pinned to ah_deposit_min_copper=0 to keep their worked examples.

Next: #191 (grill: Flip to Vendor rows worth pennies; still needs-triage), then #193. #194, #195, #196 and #188 after Beta. Guildie work stays parked.

- Gotchas: same as later 154. NEW: on this Z: drive, `git stash` + `git stash pop` left a 32-byte .git/index (every file showed staged-deleted plus untracked). `git reset` (mixed) fixed it with nothing lost. Don't stash here; compare against HEAD another way (e.g. `git worktree` or `git show HEAD:path`). Replay and Backtest numbers move with this change (more Deposits on cheap items), so #83's figures are from before #192.

2026-10-22 (later 154): #192 TRIAGED -> bug + ready-for-agent; agent brief is comment 6344465756. Verified on all 135 Beta Sold invoices with a Vendor Price: max(1s, floor(0.60 x VP x units)) per auction fits 123 (current per-unit 0.60 x VP fits 76). ADR-0013's "no 1s minimum" note is wrong (Copper Bar paid 1s on 09-28); the brief says to correct it. Cured Medium Hide settled: VP is 200c (tooltip 40s per stack of 20), stored 200c since the Oct 20 Character Read. User's call: held units assume the same post size as Flips (`_Valuer.stack`, #98). Steel Bar check skipped (user has none).

Next: /implement #192 (last full Beta day is 2026-10-22; #192 needs no game). Then #191 (grill), #193. #194, #195, #196 and #188 after Beta. Guildie work stays parked.

- Gotchas: same as later 153. Five invoices don't fit the floor (Steel Bar x2 72c twice, Hunting Cloak 63c, Large Glimmering Shard x2 40c, a Writ 0c): the brief says leave them, don't fit them. Sold mail's item_key column is NULL in the DB; resolve names with `lots.link_sales(outcomes, listings, purchases)`.

2026-10-21 (later 153): #83's Beta read POSTED (comment 6311523547), issue left open. The overnight script from later 152 never ran; reran as one `brain replay --since D --until D` per day, 6 at once (`brain/replay-83/run.sh`, ~3.4 h, not committed). 86 of 97 Scans graded (to Oct 13). Summed: Brain +51.82g, Auctionator -4273.97g, TSM -5463.67g; ablations: Sub-crafts +3.50g, Flips to Craft +139.65g, Deposits +109.58g, own-Market Sell Rate +2580.31g. Brain up through Oct 7 (+206.55g), down every day Oct 8-13 (-154.73g). Realized profit 114.13g; 111 sessions (30-min gap), 31.4-40 h: 2.85-3.63g/h (lower bound), 1.03g/session.

Correction posted on #83: the summed baseline values are mostly 7 reposting Deposits on everything they post (one Scan broken down: TSM -11.38g, 7.71g Deposits), so "Brain beats both" is unproven vs realistic setups. Filed #196 (post caps + fair Deposits for the baselines, rerun).

Next: #191/#192 (triage first), #193. #194, #195, #196 and #188 after Beta. Guildie work stays parked.

- Gotchas: same as later 152. One day's replay takes 15 min to 3 h (Sep 27, 20 Scans, was slowest); run days in parallel. `brain/replay-83/` is safe to delete.

2026-10-20 (later 152): #188 grill turned into #194, both PARKED until after Beta (user's call: low on credits, only pre-Beta-end work now). The user wants back the few-unit, high-margin flips (gear, BoEs) that vanished after the #170 caps. Cause: Stake 17.47g, so the 3% Unsold Loss cap is 52s. Named 2g+ rows went from 20-29 a Scan (up to 30g) through 10-11 to 4-7 (max 3.36g) from 10-16. #194 has the evidence, a spec (bags in Stake, Flip to Sell buys no more than it's seen sell, 1g floor variant) and a park comment: part 1 was built and backed out, because live it made the Stake 47.68g but the room 0 (the hides are 24.88g at Best Exit Value, 63% of the Stake), and the user doubts counting held stock at all. #188 has its grill notes (held units still post at the cheapest-undercut; the Hide check as worded can't pass). Nothing committed but this note.

Next: #83's Beta read (due Oct 21, the one pre-Beta-end item), then #191/#192 (triage first), #193. #194, #195 (cap grows with strong sale evidence) and #188 after Beta. Guildie work stays parked.

- Gotchas: same as later 151. The Backtest grader catches only 57% of real Sold mails, so it likely underrates single-unit gear (Lil Timmy's Peashooter: -22g in the Backtest, +3.8g real); worth an issue when #194 resumes. ADR-0034's Backtest is the evidence any cap change must beat (uncapped -49.6g vs 3% +44.7g at the vendor mark).

2026-10-19 (later 151): #155 DONE and closed (commit 187a101). Item 1: `SellRate.at_or_above` memoizes each cut by a bisect into the sorted Sale Event prices (cached_property `_cuts`). Item 3: when only Scans newer than every one seen arrive, `FairValueCache.before_new_scans` hands the pass what `scan_only` dropped; `listings` reloads only Listings last seen in the new Scans (`listings_last_seen_in`, merged by ID), and `_others_lows_as_of` extends the kept stretches (Item Keys in `item_keys_turned_own_in` redone). Three-pass bench on a frozen snapshot (numbers on #116, comment 6281292227): new Scan 23.9 -> 10.6 s, no new Scan 3.9 -> 3.1 s, `brain bench` pass 2 4.0 -> 3.1 s, byte-identical. Both #116 budgets met; item 2 (Flips memo) dropped. brain watch was NOT restarted: it picks the speedup up on its next restart.

Next: #191/#192 (triage first), #83's Beta read, #188, #193. Guildie work (#146, #179, v0.3.0) stays parked until the user says.

- Gotchas: same as later 150. Three-pass bench script lives only in session scratch: rebuild from #142's description (rewind the latest Scan with `history._rewind` on a copy of a `backup()` snapshot, pass 1, `import_archived_scans` the Scans at that requestedAt with archive_dir=None, passes 2 and 3, copy Recommendations.lua after each). Take ONE frozen snapshot and run old (git worktree at HEAD, `PYTHONPATH=<worktree>/brain/src`) and new against copies of it, since the user Scans and the live history moves. Don't edit source while a background bench is starting: it imports whatever is on disk.

2026-10-19 (later 150): #147 slice 5 DONE (commit f9111d7). Setup guide names only `_classic_`. New test in test_installer.py: `update` installs the Addon into a `_classic_` that only has `WTF` (characterization: already worked, mutation-checked). Review gap fixed in the guide: a never-launched `_classic_` (no WTF/Interface) is skipped and setup says "Couldn't find the game", so the guide now says to start a never-played WoW version once before installing or updating. Nov 4 guildie step = launch Live once, then run the new exe. Posted on #147. All #147 code slices are done; #147 stays open for its Nov 4 checklist.

Next (user's call 2026-10-19: no guildie handoff on Beta; guildie work is in the back pocket until they say it's ready, so #146, #179 and the v0.3.0 guildie release are parked): #155, then #191/#192 (triage first), #83's Beta read, #188, #193.

- Gotchas: same as later 149. Edit tool beats Python heredoc patches on this repo's CRLF files (two anchors missed this session).

2026-10-19 (later 149): #147 slice 4 DONE (commit a40b13f). `scripts/yardstick.py` (run from brain/, ~3.5 min) replays the first N archived Beta Scans plus every Character Read into a fresh history. Results are on #147 (comment 6278822258): Holdings settle by 10 Scans, and Buy Under fills slowly (34 at 10, 89 at 20). User's calls: YOUNG_MARKET_SCANS = 10 (own+Pooled), and only Live Markets are flagged. The Addon header line 1 shows "Live just started: the table fills in over the first few Scans." (plus "Beta prices are shown for reference." when `entry.beta` is set) in place of the Observation Window hours. The Qty-0 blocked Craft rows stay; slice 1's test kept its assertion and got a new comment. CONTEXT.md has a new Young Market entry. `MarketRecommendations.scan_count` is filled only by `recommend()`; replay/Backtest leave it at 0.

Next: #147 slice 5 (setup guide says only `_classic_`; test that `update` after `_classic_` first gets `WTF` installs the Addon there, extending test_installer.py:262-284 if needed). Then #179 and v0.3.0, #155, #191/#192, #83's Beta read, #188, #193.

- Gotchas: same as later 148. Run the Addon specs from `addon/` (`python ../scripts/busted.py`): protected_calls_spec opens paths relative to it and fails from the repo root. Python heredocs in bash: write `\n` inside string literals carefully (a literal newline broke recommendations.py once).

2026-10-19 (later 148): #147 slice 3 DONE (commit 45c5ac0): `history.vendor_prices()` / `item_info()` for Era.LIVE read Beta rows first, then Live's on top (helper `_eras_to_read`); no copying, Beta never reads Live. CONTEXT.md Era + Vendor Price entries updated (a second, item-fact exception to the Era rule). The day-1 rehearsal test (slice 1) has no Beta in its data folder, so it's unchanged. Posted on #147 (comment 6276981314).

Next: #147 slice 4 (Yardstick script: replay first N Beta Scans of one Market into a fresh history, row counts after 1/3/5/10/20, post on #147; then the young-Market flag in Recommendations.lua + one plain Addon line; decide explain/fold for the Qty-0 blocked-craft rows and update slice 1's pinned test). Then slice 5, #179 and v0.3.0, #155, #191/#192, #83's Beta read, #188, #193.

- Gotchas: same as later 147. Appending to a test file with a bash heredoc can leave mixed line endings; `ruff format` on the file fixes it. `addon/AzerothQuant/Recommendations.lua` shows modified (generated by `brain watch`): never commit it.

2026-10-19 (later 147): #147 slice 2 DONE (commit f01694a): a fresh Brain's first pull reaches back pool_backfill_days from the newest Scan of each Era in the pool (not from now; Live's newest is ~now so Live is unchanged). `pull()` lost its `now` parameter; the first pull reads the index twice (test_cli call lists updated). Real pool 2026-10-19: 93 Beta Scans, newest Oct 18 18:55; a fresh pull downloads 34 (old rule 32, and 0 on Nov 4). Posted on #147 (comment 6276829276). Filed #193 (an interrupted first pull loses the window; pre-existing, low priority, after the Nov 4 work).

Next: #147 slice 3 (Beta fallback for vendor prices and item info at read time when Live has none for an Item Key; spec comment 6251948315). Then slices 4-5, #179 and v0.3.0, #155, #191/#192, #83's Beta read, #188, #193.

- Gotchas: same as later 144. `test_instance_lock.py::test_another_running_brain_holds_the_lock_until_it_is_killed` fails on a clean tree on this PC (seen while `brain watch` is running); not caused by slice 2. Don't `git stash` on this Z: drive: a stash pop here wrote an empty .git/index (every file showed staged-deleted + untracked); `git reset` (mixed) rebuilt it with no work lost.

2026-10-19 (later 146): #147 slice 1 DONE (commit 7c64e72): day-1 rehearsal tests in `brain/tests/test_cli.py` ("Day 1 on Live" section) and `test_pool_sync.py` (both Eras into separate Markets). The fixture cut to its first Scan under a `_classic_` Era.LIVE install runs clean: no problem line, Live entry present, nothing in recommend.py tripped, so no source change. The Qty-0 Craft rows are blocked crafts (#75): with one Scan there are no Sale Events, so every held reagent has "no data". Their test PINS today's behavior (user's call); slice 4 decides explain/fold and updates that test (exact list match: Bolt of Linen Cloth 2996, blocked on 2589). Slices 2/3 (Beta backfill, Beta fallback) may change it too.

Next: same order as below, starting at #147 slice 2 (after Oct 21; before then #146 or keep Scanning).

2026-10-19 (later 145): #147's pre-Oct-21 fallback check PASSED (results on #147 comment 6276274849, #146 comment 6276275264). Fresh data folder Z:/aq-check-147 (pool off, 1 real Scan + 1 Character Read, rebuild then watch; safe to delete): no problem line, sane table, the Beta column shows on Holdings (on the Shopping List it's hidden by width, by design, and the side pane has the Beta line). First pass took 2.3 s. Finding for slice 1: a young Market shows Holdings Craft rows with Qty 0 and no price ("on Sab-Pumps: no data for <reagent>"); the full history has none. Also for slice 4: the header's "Observation Window 0.0 h" is jargon on day 1. The `_classic_` update part waits for slice 5 and Nov 4.

Next: #146 if the guildie is free before Oct 21; otherwise keep Scanning. After Oct 21: #147 slices 1-5 in order (slice 1 asserts on the Qty-0 Craft rows), then #179 and the v0.3.0 release, #155, #191/#192, #83's Beta read, #188.

- Gotchas: same as later 144. To run a second Brain against the game, stop the normal `brain watch` first (it rewrites Recommendations.lua on every import), then restart it with `Start-Process cmd -ArgumentList '/k','Z:\vibing\azerothquant\scripts\brain-watch.bat'`.

2026-10-18 (later 144): #147 grilled, spec on the issue (comment 6251948315), relabelled ready-for-agent. Key facts: a fresh Brain backfills only 14 days, so a guildie installing ~Nov 4 gets no Beta Prior (fix: anchor Beta backfill on the newest Beta Scan); vendor prices/item info are per Era (fix: Beta fallback at read time); no "not enough data" text exists (fix: young-Market line, threshold from a yardstick replay). Era never mixes (Market key includes Era). v0.3.0 ships #147 + #179 before ~Nov 2; guildies download it on Nov 4. The spec has a Nov 4 checklist.

Next: before Oct 21, #146 when the guildie is free. If #146 isn't booked by Oct 20, do #147's fallback check instead (Claude: fresh Brain data folder + one real Scan; user: `/reload`, read the table). After Oct 21: #147 slices 1-5 in order (one session each is fine), then #179 and the v0.3.0 release, #155, #191/#192, #83's Beta read, #188.

- Gotchas: same as later 143. Recommendations.lua is still the usual generated diff, don't commit it. The only real SavedVariables fixture is brain/tests/fixtures/AzerothQuant.lua (Era isn't in the file: drop it under a `_forever_` install with Era.LIVE; `_classic_` is MoP since #199).

2026-10-18 (later 143): #171 slice A FAILED the Backtest and is CLOSED (not planned). All four variants lost at the vendor mark (best 68.6g vs `brain` 84.6g) and broke drawdown (17-60% vs 9%); each overbought and the relisted stock lost 95-135g. Code reverted (never committed; the diff is saved at Z:/aq-check-171/slice-a.patch). ADR-0036 has the table; results on #171 (comment 6251649963); #188 told it runs on today's gate. No CONTEXT.md change (Sell Chance / Expected Profit were only for a pass). The 4 runs at once took 85-220 min and ~1.2 GB each; Claude Code killed the wait loop once for low memory (the runs survived).

Next: #146 when the guildie is free; otherwise keep Scanning. After Oct 21: #147, #179, #155, #191/#192, #83's Beta read, then #188.

- Gotchas: same as later 141. Recommendations.lua is still the usual generated diff, don't commit it.

2026-10-16 (later 142): In-game checks done (results on #85): #38, #49, #120, #78, #170's capped line and the Brain-off banner (#146 rehearsal) PASS; #50 ticked. #33/#75 still open (no chained or blocked Craft row showed; screenshot one if it does). Filed #191 (penny Flips to Vendor on the Shopping List, e.g. 20 Star Ruby for 20c) and #192 (1s deposit minimum per auction not modelled); both brain-only, after Oct 21, next to #147/#179. Near misses explained to the user: no Flip to Sell because every ask is within the 5% cut + 10% Flip margin (that's #171's rule). brain watch was restarted by Claude (Start-Process cmd /k scripts\brain-watch.bat); its first Decision Engine took 66.7 s (for #155). The user wants Claude to run Brain-side steps in the background and give only in-game steps, one part at a time.

Next: #146 when the guildie is free (later 141, 1a). Otherwise just keep Scanning.
After Oct 21 the user moved #171 first: #171 (rerun the four backtests per later 140), then #147, #179, #155, #191/#192, #83's Beta read, then #188. The user asked why margins are so small: mostly the 17g Stake (caps: 3% Unsold Loss = ~51s, 60% room), a tight AH, and the strict Flip margin #171 replaces.

2026-10-16 (later 141): Plan to Beta's end (Oct 21, last day with a game). The user's remaining Claude usage is all there is for this project: spend it on the game-only work and Live day-1 problems first, one short session per issue, and no long experiment loops. v0.2.1 prep for #146: version bumped (Brain `__version__` + Addon .toc), committed with only those files (the #171 work from later 140 stays uncommitted and isn't in the release), tagged v0.2.1 and pushed; CI builds the exe.

Next, in order:
1. Before Oct 21, needs the game:
   a. #146 when the guildie is free (pick a day). Check the v0.2.1 Release exe downloads and starts, `brain pool key add <guildie>`, user sends the exe + `docs/setup-guide.md` on Drive with the key, then #146's Checks.
   b. User at the PC, no Claude needed: restart `brain watch` (12 h windows, capped lines); see a capped row's line in the side pane (#170); #85's open boxes #38, #33, #75, #49, #120, #78 (one Copper Bar at 48h, read the deposit). #50 already passed (comment on #85): just tick it.
   c. Keep Scanning until Beta closes: it's the Beta history the Live Brain leans on.
2. After Oct 21 (no game), Live day-1 problems first:
   a. #147: zero history on Nov 4 (grill first: what's testable offline).
   b. #179: tell guildies when a newer Brain is out.
   c. #155: Scan time budget, fed by #146's `Import stages:` numbers.
   d. #83's Beta read on the saved history (after the last Scans).
   e. Only with usage left: #171 (rerun the four backtests per later 140), then #188.
3. Everything else waits until after Nov 4.

- Gotchas: same as later 140. If a fix lands before the guildie installs, bump to 0.2.2 and tag again (the release job fails if the tag and `__version__` differ).

2026-10-16 (later 140, IN PROGRESS, not committed): #171 slice A built TDD, uncommitted in the working tree (brain/src/brain/config.py, recommend.py, tests/test_recommend.py; Recommendations.lua is the usual generated diff, don't commit it). Behind `Config.flip_expected_profit` (off, not read from config.toml) plus `flip_sell_horizon_seconds` (3 d), `flip_buyers_scale` (κ), `flip_min_expected_profit_share` (0.10; the 1s reuses `flip_min_margin_copper`). `_flips_by_expected_profit` + `_SellChance` (Poisson tails cached per mean). Stops buying through once the next unit's Sell Chance < 1% (`_LEAST_SELL_CHANCE`, not in the spec: say so in the ADR). No partial Listings: part of one posts under the rest of it, below cost. 18 new tests, mutation-checked; full suite green but the known test_instance_lock.

Backtest in Z:/aq-check-171 (fresh 87-Scan copy, code snapshot in src/, `run.py config.toml <variant>`): brain.txt done = 84.6g / x0.65 56.8g / x1.2 88.1g, market 115.7g (x0.65 89.4g), worst -16.2g, dd 9% (matches). ep3k1, ep7k1, ep3k05, ep7k05 were started 00:11 Oct 16 but killed by a PC shutdown ~01:15 (no results). Rerun all four from Z:/aq-check-171, 4 at once, in the background: `PYTHONPATH=/z/aq-check-171/src /z/vibing/azerothquant/.venv/Scripts/python run.py config.toml <variant> > <variant>.txt 2> <variant>.err` (src/ is the current code; recopy it first if the code changed). They took over an hour each with 4 at once; brain alone took 32 min. Wait with Monitor or a background until-loop, not sleep.

Next: read the four results against the spec's pass bar; if worst trade got worse, add a Sale Events minimum 2 variant. Then: pass -> flip the default on, migrate the old Flip to Sell tests, ADR + CONTEXT.md (Sell Chance, Expected Profit); fail -> revert the code, short tried-and-lost ADR. Then /code-review and commit. Note: _why_not still explains the old checks when the switch is on.

2026-10-15 (later 139): #171 grilled. Spec comment on #171 (6206697350), retitled to slice A (Expected Profit gates Flip to Sell), ready-for-agent, **build from Oct 21** (parked past the PoC: brain-only, Backtest-judged, fits the no-game window). Split: #188 several post prices (needs-triage, runs on whichever gate wins A; Cured Medium Hide check), #189 stop reposting non-sellers (later, judge on Live Outcomes: the Backtest's exit is fixed), #190 recency/falling market (later, with the Live re-fit). Pass bar: vendor central beats `brain` by >5g, vendor bounds not lower, worst trade and drawdown no worse, market x0.65 not >5g under 89.4g. No CONTEXT.md/ADR yet: written when A is judged (terms Sell Chance, Expected Profit).

Next, in order (PoC by Oct 20):
1. #146 when the guildie is free (see later 126).
2. In game when on the PC: see a capped row's line in the side pane (from later 136); restart `brain watch` so it picks up the 12 h windows.
3. Anything the PoC turns up before Oct 20.
4. From Oct 21: #171 (slice A) per its spec comment, then #188.

- Gotchas: same as later 138.

2026-10-15 (later 138): #169 built TDD, reviewed, committed (bc30af2), pushed; CLOSED by the commit. `DEFAULT_OBSERVATION_WINDOW_MAX_MINUTES = 720`; config.example.toml and the observation.py/sell_rate.py/ObservationWindow docstrings cite ADR-0035. New tests in test_observation.py (6 h gap: bucket-4 gone is a Probable Sale, bucket-3 isn't, hours count; Partial Sale in 6 h; 12 h counts, 12 h + 1 s adds nothing). Backtest on a fresh 87-Scan copy matched the prototype exactly: brain vendor 44.7 -> 84.6g, x0.65 47.7 -> 56.8g, x1.2 65.6 -> 88.1g, worst -17.7 -> -16.2g, drawdown 9% both; market-mark x0.65 106.4 -> 89.4g. Posted on #169 (comment 6185337458).

Next, in order (PoC by Oct 20):
1. #171 (needs-triage): grill per #166's order. It must beat the capped, 12 h `brain` on #168's bar (vendor mark central + both bounds, worst trade, drawdown); watch the market-mark x0.65 bound (89.4g now).
2. #146 when the guildie is free (see later 126).
3. In game when on the PC: see a capped row's line in the side pane (from later 136); restart `brain watch` so it picks up the 12 h windows.

- Gotchas: same as later 137, plus:
  - Tests now pin the old 1 h cap as `HOUR_CAP` (test_observation, test_beta_prior), and test_recommend's shared `CONFIG` pins `observation_window_max_seconds=HOUR`. A new recommend test that wants 12 h windows must use `DEFAULTS` or override it.
  - test_instance_lock's `test_another_running_brain_holds_the_lock_until_it_is_killed` fails locally on old and new code alike (the venv launcher's child pid differs). CI is the authority.
  - `git stash push <path>` emptied the index again this session (fixed by `git reset`). Don't use it.
  - Check copy in Z:/aq-check-169b (safe to delete, with Z:/aq-check-169): history.sqlite (87 Scans), before-src/ and after-src/ snapshots, `run.py <config> <policy>` with `PYTHONPATH=<snapshot>`. Four backtests at once ran fine (~30 min).

2026-10-15 (later 137): #169 grilled. Spec comment on #169 (6184660098), retitled "Sell Rate: Observation Windows up to 12 hours", ready-for-agent. ADR-0035 (amends 0004, "Amended by" line added), CONTEXT.md Observation Window updated. The change is one default: `observation_window_max_minutes` 60 -> 720. Hours stay Market-wide; gaps over 12 h still add nothing (no Partial Sales from them either). Backtest on a fresh 87-Scan copy: brain 44.7g/118.3g -> 84.6g/115.7g (vendor/market), vendor bounds up, worst trade -17.7 -> -16.2g, drawdown 9% both; the market-mark x0.65 bound fell 106.4 -> 89.4g. The pass bar is the vendor mark (capped); the market mark is reported only. Per-Item-Key hours (the review's idea) and a 2 h cap were tried and lost (ADR-0035).

Next, in order (PoC by Oct 20):
1. #169 (ready-for-agent): build per the spec comment (TDD), check `brain backtest --policy brain,uncapped` before/after on one fresh copy, /code-review, commit.
2. #171 per #166's order (must beat the capped, 12 h `brain` on #168's bar; watch the market-mark x0.65 bound).
3. #146 when the guildie is free (see later 126).
4. In game when on the PC: see a capped row's line in the side pane (from later 136).

- Gotchas: same as later 136, plus:
  - Tests that build Scans 12 h apart to get a non-window gap (`walls`, #168) become windows at exactly 12 h. Move the gap past 12 h or pin `observation_window_max_seconds=3600`; don't change what they assert.
  - Check copy in Z:/aq-check-169 (safe to delete): history.sqlite (87 Scans), run.py + variants.py (`w12`, `w2`, `pb` per-Item-Key hours, each with a `u` uncapped twin), facts.py (gap/bucket counts). Results in *.txt.
  - 8 backtests in parallel ran the machine critically low on memory (Claude Code killed the background wait shells; the backtests survived). Run at most 4 at once, and don't leave a background wait loop going.

2026-10-14 (later 136): #170 slice 2 built TDD, reviewed, committed (3a95231), pushed, CI green; #170 CLOSED by the commit. The Brain now writes Market `lossCap` (Unsold Loss cap, copper) and row `cappedBy` ("room" if sizing within the room alone gives as few units, else "loss"; the Disenchant loop records the first cap it hits). The Addon puts a plain-words line first in a capped row's details (`cappedLine` in RecommendationTable.lua): "Capped at N of M: if none sell, you'd lose at most Xg (3% of what you're trading with)" or "...: more would put over 60% of what you're trading with into auctions" (share worked back from room/stake/gold). `BoughtMarks.goldLeft(budget, gold, spent, room)` also folds on room less what's marked. ADR-0034 and CONTEXT.md (Bought mark) updated. Review left: marks on Prediction buys also come off the room (spec says "marked costs"), not changed.

Next, in order (PoC by Oct 20):
1. #169, then #171 per #166's order (#171 must beat capped `brain` on #168's bar).
2. #146 when the guildie is free (see later 126).
3. In game when on the PC: see a capped row's line in the side pane after a Brain run (restart `brain watch` so it writes lossCap/cappedBy).

- Gotchas: same as later 135, plus:
  - This PC has no lua/busted. lupa (pip) is installed, so a busted stand-in on lupa's Lua 5.1 works: describe/it/before_each/after_each, assert.are.equal/same, is_nil/is_true/is_false/matches. This session's copy was in its scratchpad (gone); CI's busted is the authority.
  - Python heredocs that write Lua/Python string literals with `
` or `\"` mangle them: edit those lines with the Edit tool.

2026-10-14 (later 135): #170 slice 1 built TDD, reviewed, committed (9b35e4c), pushed. `_RiskCaps` (loss, room) inside sizing: `_FlipToSell.fitting`, `_option` (Vendor room-only, Craft steps), `_flip_to_disenchant`; `_SellRun`/`_CraftBuy.unsold_loss`; `Row.capped` (by sizing again with gold alone; the Disenchant loop counts it). `MarketRecommendations.stake/room`, written to Recommendations.lua (`stake`, `room`, row `capped`). `recommend_market(tied_up=)` (Stake = gold + tied_up; no separate stake override). Live Stake: own units in the Scan costed by newest open Lots, else Best Exit Value; with `paid=False` (past Scans) no Lots (recursion through `held_at_writing`), noted in ADR-0034. `options_taken` tracks the room. `BuyPolicy` takes a 4th arg (tied-up at cost); `uncapped` policy; `Config.risk_caps` (not in toml), `flip_unsold_loss_share` (now 0.03) and `flip_tied_up_share` (0.6) in config.toml. Check posted on #170 (6183475938): brain passes every line vs uncapped; 3%/60% beat 5%/60% by 12g/17g so default switched, ADR-0034 has the table; hide row gone as of Scan 85. Filed #187 (Why Not ignores the caps).

Next, in order (PoC by Oct 20):
1. #170 slice 2 (Addon): tooltip line on a capped row in plain words (uses row `capped`, Market `stake`/`room`; loss share is 3% now, not 5%), and the Bought-mark fold (#97) takes marked costs off `room` as well as the gold left. Then close #170.
2. Then #169, #171 per #166's order (#171 must beat capped `brain` on #168's bar).
3. #146 when the guildie is free (see later 126).

- Gotchas: same as later 134, plus:
  - Test configs (test_recommend/flips/replay/backtest/craft_flips/disenchant/cli) set `risk_caps=False`; cap tests use `CAPPED` with shares pinned to 0.05/0.6.
  - Check copy in Z:/aq-check-170 (safe to delete): history.sqlite (87 Scans), run.py adds `c3_60`/`c5_100`, hide.py. Four policies in parallel took ~30 min.
  - Never `git stash push <path>` from brain/ for a mutation check: it emptied the index here (fixed with `git reset`). Revert by sed instead.

2026-10-14 (later 134): #170 grilled. Spec comment on #170 (6182758039), ADR-0034, ADR-0017 "Amended by" line, CONTEXT.md gains Stake and Unsold Loss (and Shopping List mentions the caps). Labelled ready-for-agent. Two caps inside sizing, as shares of the Stake (pooled gold + own Listings up at cost): Unsold Loss <= 5%, cost <= room (60% of Stake − own Listings at cost). No brake (#185), no Backtest tail change (#186).

Next, in order (PoC by Oct 20):
1. #170 slice 1 (Brain): TDD per the spec comment. Pass bar is `brain` vs new `uncapped` on a fresh live copy, plus the hide check at Scan 85. Slice 2 (Addon tooltip + Bought-mark fold on the room) only if slice 1 passes.
2. Then #169, #171 per #166's order (#171: must beat `brain` on #168's bar, and now `brain` is capped).
3. #146 when the guildie is free (see later 126).

- Gotchas: same as later 133, plus:
  - Backtest Stake must be passed in (simulated gold + unsold at cost), not read from Scans: Scans show the real player's posts. Add overrides beside `recommend_market(gold=)`.
  - A capped Flip to Sell is a shorter run inside ADR-0011's run choice, so it posts lower. Don't just cut units off the full run's plan.
  - The full 3-share Backtest on the 86-Scan copy takes 10+ minutes. Run it in the background.
  - `addon/AzerothQuant/Recommendations.lua` was left modified from a local Brain run. It's generated, so it isn't committed.

2026-10-13 (later 133): #168 built TDD, reviewed, committed (44ad4ba), closed by the commit. ADR-0029's 24 h unwatched rule is gone: `SellRate.since_cheap(cutoff)` (no `now`) returns self with no window hours after the cutoff; `UNWATCHED_STRETCH_SECONDS`, `_Cheap.latest`, `WhyNot.watched_since` and "(not watched since)" removed. CONTEXT.md Sell Rate/Flip and an ADR-0029 "Amended by" line updated. Tests using `walls` (Scans 12 h apart) now pass `watched_cheap=` to get an hour watched after the cutoff. Check on a fresh 86-Scan live copy (posted on #168, comment 6160137763): brain -34.84g/+76.45g -> -24.30g/+78.55g, all bounds up, worst trade/drawdown unchanged, relaxed identical. Matches the spec's patched run.

Next, in order (PoC by Oct 20):
1. #170 (needs-triage): grill (risk caps; the Cured Medium Hide case is the headline, gold-at-risk per buy may matter more than units).
2. Then #169, #171 per #166's order (#171: any cutoff loosening must beat `brain` on #168's bar).
3. #146 when the guildie is free (see later 126).

- Gotchas: same as later 132, plus:
  - Check copies now in Z:/aq-check-168b (safe to delete, along with Z:/aq-check-168): `history.sqlite` (86 Scans), `config.toml`, `run.py <config> <policy>`, `head/` is a git worktree at 181a009 (remove with `git worktree remove Z:/aq-check-168b/head`), `after-src/` a source snapshot. Run old code via `PYTHONPATH=<worktree>/brain/src`.

2026-10-13 (later 132): #168 grilled into a spec (comment 6159665234), retitled, ready-for-agent. ADR-0033 committed (amends 0029). It drops only the 24 h unwatched rule: an unwatched stretch keeps its demand. Backtest on a live-history copy (86 Scans): brain -34.8g/+76.5g, this rule -24.3g/+78.5g (better on every line), cutoff off -49.7g/-18.9g (drawdown 53%), power test -45.2g/-22.3g. So the cutoff stays. The user's Cured Medium Hide loss (Brain said 241 at 14s49c on 4 Sale Events over a 6s68c floor; the floor came back a day later) isn't a cutoff case: noted on #170 as its headline, and #170 moves ahead of #169. Note on #171: loosening the cutoff must beat `brain` on #168's bar.

Next, in order (PoC by Oct 20):
1. #168 (ready-for-agent): build per the spec comment (TDD), check with `brain backtest --policy brain,relaxed` before/after on one fresh live-history copy, then /code-review and commit.
2. #170 (needs-triage): grill (risk caps; the hide case is the headline, gold-at-risk per buy may matter more than units).
3. Then #169, #171 per #166's order.
4. #146 when the guildie is free (see later 126).

- Gotchas: same as later 131, plus:
  - Check copies live in Z:/aq-check-168 (safe to delete): `live/` (brain), `nocut/`, `vb/`, `vc/`, each its own history copy and config.toml with an empty fake-wow dir. `run.py`/`run_variant.py` add policies by patching (`POLICIES`, `SellRate.since_cheap`). `dump.py` pickles the central run's trades.
  - The live copy has 86 Scans: one `brain` policy takes ~25 min (3 runs). Run policies as separate processes in parallel (12 cores).
  - Copy the live history with sqlite `backup`, not cp: `brain watch` may be writing it.

2026-10-13 (later 131): #167 slice 2 built TDD, reviewed, committed (5af13a9); #167 CLOSED. `simulate(grade_share=)`, `Simulation.curve`/`max_drawdown`/`gold_low`, `MarketBacktest.bounds` (low, high runs per policy) and `.calibration`, `observation.grader_calibration` (own Listings vs mail, as p6; shares `_gone_like_a_sale` with `sale_records`), `Config.backtest_grade_low/high` (0.65/1.2, not read from config.toml). Check on the review's history copy matched §6.2 exactly (posted on #167): bounds -12.45/-8.23g vendor, -8.55/-4.85g market, drawdown 26%, calibration 27 of 39 / 27 of 47.

Next, in order (PoC by Oct 20):
1. #168 (needs-triage): grill it into a spec (review step 2: cheap-stock cutoff). Judge it with `brain backtest --policy brain,relaxed`.
2. Then #169-#171 per #166's order (#170 can start any time).
3. #146 when the guildie is free (see later 126).

- Gotchas: same as later 130, plus:
  - `brain backtest` now runs every policy 3 times (central, 0.65x, 1.2x): ~20 min for `brain` on the 69-Scan history.
  - The calibration line reads the Market's whole history, ignoring `--since/--until` (on purpose: own-Listing evidence is thin).
  - Bound runs fill fractional units (as p4); `Trade.sold` is a float.

2026-10-13 (later 130): #167 slice 1 built TDD and committed (7cfbea0). `brain backtest` (backtest.py): `observation.sale_records`, the walk-forward sim (`simulate`, pure, tested with scripted policies), the `brain`/`relaxed` policies (`POLICIES`, config overrides), the vendor/market-mark report, ADR-0032 (amends ADR-0015), CONTEXT.md Sale Record and Backtest. Check passed and posted on #167: brain -10.49g/+1.14g, relaxed -37.65g/-27.51g, equal to p4 to the copper once p4's Flips to Vendor net is counted (the port counts them as trades). Filed #184 (needs-triage): retire `brain replay`.

Next, in order (PoC by Oct 20):
1. #167 slice 2 (TDD): the 0.65x/1.2x bound runs (`backtest_grade_low`/`backtest_grade_high` in config), the own-Listing calibration line (as p6), max drawdown and gold low. Spec comment 6112184474.
2. Then #168-#171 per #166's order (#170 can start now).
3. #146 when the guildie is free (see later 126).

- Gotchas: same as later 127, plus:
  - `brain backtest` takes ~8-9 min a policy on the 69-Scan history. Checks run on copies under Z:/aq-check-167 (safe to delete).
  - `recommend_market(..., gold=)` replaces the Characters' gold and the Budget.
  - `Config.cheap_stock_cutoff` is not read from config.toml.
  - `replay._taken` is now `options_taken`, so the review's p4 needs `from brain.replay import options_taken as _taken` to run on new code.
  - Locally on Windows, `test_instance_lock.py::test_another_running_brain_holds_the_lock_until_it_is_killed` fails at HEAD too (the venv launcher's child PID). CI is Linux.
  - Close every `open_history(":memory:")` in tests (use a fixture): an unclosed one fails a random later test via ResourceWarning.
  - Review smells left as judgement calls: `_backtest` duplicates `_replay`'s error handling, and `_render_backtest` computes won/lost/worst itself (could move onto `Simulation`).

2026-10-13 (later 129): #175 closed as not planned (not a bug: the cheap-stock cutoff takes nearly every candidate on thin Scans; tuning belongs to #167, then #170/#171). Next: #167 slice 1 (TDD), then the rest of later 127's queue.

2026-10-12 (later 128): no code. Discussion + filing. Filed (all needs-triage): #179 Brain update notice (core), #180 Scan-ready ping (core, small, Addon only), #181 profit so far (later), #182 minimap button (later), #183 undercut wars: cancel-and-repost Deposits + post a few at a time (core, under #166, lands with #171). #178 closed as a duplicate of #147 (its additions commented on #147: day-1 replay yardstick, setup guide's `_classic_beta_` and "out of date AddOns" lines to check on Nov 4). Future update path discussed (not filed): Addon on CurseForge, Brain self-updates from GitHub releases (#179), Brain stops installing the Addon if CurseForge owns it, version stamp in Recommendations.lua.

Next, in order (PoC by Oct 20): unchanged from later 127. #180 fits before Oct 20 if there's slack.

- Gotchas: same as later 127.

2026-10-11 (later 127): #167 grilled, spec on #167 (comment 6112184474), now ready-for-agent. New `brain backtest` command + `backtest.py` (replay untouched; file a follow-up to retire it). Policies `brain` and `relaxed` (config overrides). Grader uses new `observation.sale_records` (Partial Sales any gap + can't-have-expired Disappearances in gaps <= 12 h, 1.2x cap). Bounds fixed 0.65/1.2 in config, calibration line printed. ADR-0032 amends ADR-0015; CONTEXT.md gets Sale Record and Backtest. Two slices; #170 can start after slice 1.

Next, in order (PoC by Oct 20):
1. User: close #175 (not a bug) or say otherwise.
2. #167 slice 1 (TDD), then slice 2, then #168-#171 per #166's order.
3. #146 when the guildie is free (see later 126).

- Gotchas: same as later 126. Reproduction check: run p4 and `brain backtest` on the SAME commit and history copy (recipe in later 121 gotchas), within 5g at both marks.

2026-10-11 (later 126): In-game checks PASSED, #156 and #176 closed (results on each). #156: "re-read 4920 of 7854 dropped rows in 0.2 s" (cap fine); the AH-closed-partway check can't be done by hand at 0.2 s (busted covers it); the latest Scan's 830 dropped items are all off the Shopping List. #176: 'Brain is working' then 'Brain not running' + the chat line, no 'took longer'; table caught up after the Brain restarted. **v0.2.0 tagged and released** (CI built the exe). brain watch restarted 14:11 in its own window.

#146 is parked until the user says the guildie is free. When they do: anything merged after v0.2.0 means bumping the version (Brain `__version__` + Addon .toc; the CI release job fails if the tag and `__version__` differ), tagging v0.2.x and giving the guildie THAT exe. Then: download the exe and check it starts, `brain pool key add <guildie>`, user uploads exe + `docs/setup-guide.md` to Drive and DMs the link + key, then #146's Checks.

Next, in order (PoC by Oct 20):
1. User: close #175 (not a bug) or say otherwise.
2. #167: backtest yardstick in replay (needs-triage: grill first), then #168-#171 per #166's order.
3. #146 when the guildie is free (above).

- Gotchas: same as later 124. Recommendations.lua in the working tree is still Brain-written dev data: never commit it.

2026-10-11 (later 125): #176 built (c9b7ab2), option (b), not closed: in-game check left (on #176's last comment). After every Data slot try is stale with Scans waiting, Scanner keeps tryState "trying" (banner: Brain is working) until new pure `Nudge.behindIn(scans, now)` says the oldest saved Scan counts as behind, then rechecks `brainBehind` (skipped while catching up): behind -> behindAtLoad + `Nudge.behindLine` in chat, else reloadReady. 'Took longer' state, line and `Scanner.tookLonger` deleted (a slow Brain and an off one look the same). ADR-0030 got a dated line, the setup guide's 'took longer' entry removed. 346 busted specs.

Next, in order (target #146 by ~Oct 13; PoC by Oct 20):
1. User: close #175 (not a bug) or say otherwise; in game: #176's check.
2. Then #156/#146 release steps; #167 before any of #169-#171 (and #168 after #170/#171).

- Gotchas: same as later 124.

2026-10-11 (later 124): no code. Filed #177 (needs-triage, later): Addon shows which of my live Listings have been undercut, display only. It's the first half of #134 (commented there). Queue below unchanged.

2026-10-11 (later 123): #175 diagnosed, no code change. Not about the day away, and not a code bug: on thin Scans the cheap-stock cutoff (ADR-0028/0029) takes nearly every candidate. With it off, the low Scans return to 23-30 passing. It also takes ~20 on good Scans. One-offs: 10-07 21:33 was Dropped rows (the last Scan before 6983547), and 10-05 18:17 is a replay artifact (gold pinned before the session's first Character Read). The market's raw cheap outliers don't dip after gaps. Full numbers on #175's comment. Probes in `docs/research/issue-175-probes/`. ADR-0031 got a correction line ("isn't mainly the cutoff" was wrong). #175 left open for the user to close as not-a-bug.

Next, in order (target #146 by ~Oct 13; PoC by Oct 20):
1. User: close #175 (not a bug) or say otherwise. Whether the cutoff leaves too few rows belongs to #167's backtest yardstick, then #170/#171.
2. #176: pick a/b/c (small, Addon only, busted).
3. Then #156/#146 release steps; #167 before any of #169-#171 (and #168 after #170/#171).

- Gotchas: same as later 122. Replays with `recommend_market(..., as_of=now)` pin gold and Holdings to before the Scan, so a session's first Scan can show a Budget collapse the live import never saw. Use a fresh history copy for each cutoff/observation variant (the Fair Value cache persists in it).

2026-10-10 (later 122): no code. In-game checks done. #162 closed: items 1-3, 5 and 6 passed, item 4 FAILED. Brain off, Scan, Reload showed 'took longer' (banner + chat), not 'Brain not running'. Filed #176 (needs-triage, options a/b/c on it): `Nudge.brainBehind` needs savedAt 130 s old, the last try is at 90 s, and nothing checks again. Import took with a new Scan: 29-36 s, slowest 53 s (#155), so {20, 45, 90} stays. #163 closed: tooltips good per user, guide sections 2-4 match the screen. Also seen: the first Scan after ~18 h away (10-10 17:00) gave a 2-row Shopping List (16:44 gave 9). That's #175's pattern, a fresh example.
Later the same evening: #140 closed (crates stack, no bug). #85: #38 and #50 PASS (logged there). Shopping List rows that evening: 16:44 9, 17:00 2, 17:20 5, 17:38 18 (on #175). #155 has a 58.5 s Decision Engine pass. #164: user picked (a), now ready-for-agent.

Next, in order (target #146 by ~Oct 13; PoC by Oct 20):
1. #175: diagnose what empties the list after a day away (diagnosing-bugs). Start from the Item Keys passing at 10-06 21:45 and failing at 10-07 21:33; the 10-10 17:00 Scan is another case.
2. #176: pick a/b/c (small, Addon only, busted).
3. Then #156/#146 release steps; #167 before any of #169-#171 (and #168 after #170/#171).

- Gotchas: same as later 121. brain watch was restarted 2026-10-10 17:03 (window titled 'brain watch').

2026-10-08 (later 121): #168 grilled, built TDD and checked, then NOT committed: ADR-0031 committed as rejected (numbers in it and on #168, patch in #168's comment). Rule tried: old Sale Events/units/window hours count at w = exp(-max(0, E - n)) x 0.5^(age/24 h), with the 3-Sale-Event minimum on the raw count. p4 `brain` (last_buy=1790818960) went from -13.1g/-1.4g to -29.5g/-26.2g, worst trade -6.6 to -11.1g. p5: rows after gaps barely moved (5/2/4/2 to 5/2/7/6) while mid-week rows grew (10-03: 11 to 41). So the after-gap collapse isn't mainly the cutoff (the review's §2.1 was wrong there): filed #175 to diagnose it. #168 is parked behind #170/#171.

Next, in order (target #146 by ~Oct 13; PoC by Oct 20):
1. In game (user): the rest of #162's list and #163's check.
2. #175: diagnose what empties the list after a day away (diagnosing-bugs). Start from the Item Keys passing at 10-06 21:45 and failing at 10-07 21:33.
3. Then #156/#146 release steps; #167 before any of #169-#171 (and #168 after #170/#171).

- Gotchas: same as later 120. Running the review's probes against a code version: make a dir with code/brain/src (git archive HEAD brain/src, or a copy of the tree) and probes/ (repo copy of the probes) and probes/_work/ (copy history.sqlite, sales.pkl, grades.toml from Z:/aq-decision-review/probes/_work), then run `.venv/Scripts/python.exe probes/p4_backtest.py brain wide last_buy=1790818960 tag=lb` from it. p4 takes about 15 min, and p5 about as long. Never `git stash` here: revert with `git checkout -- <paths>`.

2026-10-08 (later 120): outside review of the recommend design done and committed (`docs/research/decision-review-2026-10-08/`: REVIEW.md, BRIEF.md, probes + text outputs; JSON outputs and the history work copy stay in Z:/aq-decision-review). Finding: the checks are pass/fail 'can't lose' on 'sales seen at this price', but only 14 of 294 h are watched (60-min windows), and the cheap-stock cutoff zeroes demand after a day away, so the Shopping List drops to 2-5 rows after every gap (20-32 otherwise). Its backtest: no policy made money on this history; loosening without sizing was worst; EV + caps matched the Brain with a third the worst trade. Spot-checked `since_cheap` (sell_rate.py:66-75). Filed parent #166 and, in its order: #167 backtest yardstick in replay, #168 cheap-stock cutoff (quick win, needs an ADR amending 0029), #169 wider sale evidence (ADR amending 0004), #170 risk caps, #171 EV replaces Sale Events min + margin, #172 effort setting (empties Flips to Disenchant), #173 Buy Unders lose as standing orders, #174 13114 buys show pending though sold. All needs-triage.

Next, in order (target #146 by ~Oct 13; PoC by Oct 20):
1. In game (user): the rest of #162's list and #163's check (#145 closed, auto-load seen working).
2. #168: grill (power test size, discount shape, unwatched = shrink not zero), ADR amending 0029, TDD. Check with the review's `p5` rows per Scan and `p4_backtest.py brain` (copy the probes; they run against a history copy).
3. Then #156/#146 release steps; #167 before any of #169-#171.

- Gotchas: never `git commit -a` here: it picks up the Brain-written Recommendations.lua (done once by mistake, reverted in 4878d33). User's config.toml has flip_min_margin_share = 0.1.

2026-10-08 (later 119): no code. User asked why so few recs, why 2 reloads, why the Brain is slow, and the window overlapping the AH. Few recs: `--why-not` shows nearly everything fails Flip margin (listed at about its clear price), so working as designed. 2 reloads: the running `brain watch` (started 12:05) predates #162 (16:40), so only the old AzerothQuant_Data existed and the Addon fell back to Reload; user told to do #162's dev setup (restart watch, delete old folder, restart client). Slow: restart Fair Values ~25-33 s is #145 (watcher predates it), new-Scan Decision Engine ~21 s is #155. Filed #164 (window opens over the AH; options a/b, user hasn't picked). Then: did #162's dev setup for the user (old folder deleted, watch restarted, slots written; user restarted the client and auto-load WORKED, table refreshed by itself). #145 restart check PASSED (Fair Values 0.2 s on the second restart, 18:28). User's config.toml now has flip_min_margin_share = 0.1 (adds 0 Sell rows on the 18:23 Scan). Probed Copper Tube (4361): the Shopping List was right not to list it (the 1s 20c wall has room 0 above it under #132, and 3s 19c rests on week-old sales), but why-not mislabels it: filed #165. User thinks the whole recommend design is too cautious (hard pass/fail gates aimed at 'can't lose' vs expected value across many bets), and wants an outside review: snapshot at `Z:\aq-decision-review` (BRIEF.md, code/, design-docs-read-last/, data/history.sqlite copy + config with no secrets, out.txt). Next session runs it, outside the repo.

Next, in order: unchanged from later 118.

2026-10-08 (later 118): #145 built (0c13931), not closed: restart check left (#145's last comment: restart watch twice, paste the second `Import stages` line). `FairValueCache(keep_in_history=True)`, made by cli's `watch_fair_value_cache()` (watch only; recommend/bench/replay stay in memory), keeps each Scan's Fair Values in new history table `scan_fair_values` (scan_id PK, `worked_out_with` = `FAIR_VALUE_VERSION` + the 2 Fair Value config fields, JSON). `_rewind` deletes them with their Scans (needed: foreign keys are on). test_scan_only_reuse's re-match tests now run kept-in-memory / kept-in-history / restarted. 1152 pytest.

Next, in order (target #146 by ~Oct 13):
1. In game (user, by ~Oct 11): as later 116's item 1, plus the #163 check, plus the #145 restart check.
2. #156 passes: tag v0.2.0 and run #146's release steps.
3. Meanwhile: #134, then the gap.

- Gotchas: same as later 117, plus: bump `FAIR_VALUE_VERSION` (fair_value.py) whenever `fair_value` or `supply_at` changes what a Scan's Fair Values come to, or a restarted Brain loads stale ones. `test_instance_lock.py::test_another_running_brain_holds_the_lock_until_it_is_killed` fails here on a clean tree too (not from #145; unlooked-at). Never `git stash -- <paths>` in this repo on this machine: a stash/pop of brain/ emptied .git/index (every file showed staged-deleted + untracked); `git reset` (mixed) fixed it with no loss.

2026-10-08 (later 117): #163 built (da9639f), not closed: in-game check left (list on #163's last comment). New pure `Tips.lua` (loads after NextStep in the .toc): TABS, COLUMNS (by column name), STEPS (by NextStep action), BUDGET, DAYS_TO_SELL, POST, SEARCH, SORT, RESIZE. RecommendationFrame's local `showTip(owner, title, text, footnote)` draws them; tabs and headers use HookScript so the templates keep their own scripts. The AH Scan button in Scanner.lua shows Tips.STEPS.scan (motion scripts on while disabled). `spec/tips_spec.lua` (3 cases) checks every tab and column `RecommendationTable.build` makes (Beta included) and every banner action has a tip. The frame's `TAB_TITLES` must keep matching build's section titles (the test reads build's). Setup guide: the strip and its Scan/Reload button, Days to Sell, hover line, Load line removed. No per-field side-pane hover (agreed). 344 busted specs. That closes #158's slices once the in-game checks pass.

Next, in order (target #146 by ~Oct 13):
1. In game (user, by ~Oct 11): as later 116's item 1, plus the #163 check.
2. #156 passes: tag v0.2.0 and run #146's release steps.
3. Meanwhile: #145, then #134, then the gap.

- Gotchas: same as later 116. Recommendations.lua in the working tree has uncommitted Brain-written data from dev runs: never commit it with a feature.

2026-10-08 (later 116): #162 built (20c14ce), not closed: in-game check left (list on #162's last comment, incl. dev setup: restart brain watch, let it import, restart the client, delete the old AzerothQuant_Data by hand). ADR-0030 supersedes ADR-0021 in part. Brain writes Recommendations.lua into `DATA_SLOTS` AzerothQuant_Data1..3 (titles 'AzerothQuant Data N'); setup/uninstall cover all 3 and remove the old folder (`old_data_addon_folder`). Addon: pure `LoadTries.run(slots, after, try, done)` with `LoadTries.AFTER = {20, 45, 90}` (5 busted cases); Scanner.lua's `tryDataSlots()` runs it at load when `DataAddon.slotsToTry()` is non-empty and the Brain isn't catching up; `DataAddon.lua` is now just atLoad/slotsToTry/load(slot). Manual Load button and `/aq load` removed. NextStep.of: Brain working (trying) > orange took longer (Reload pulsing) > the no-slots fallback (working, then 'should be ready' Reload). Chat: 'are ready' only with the window closed and Scans waiting; 'took longer' always (problem line) unless the Brain is behind. 341 busted specs.

Next, in order (target #146 by ~Oct 13):
1. In game (user, by ~Oct 11): #156 both parts (later 111's item 1), the guide read-through (#138, the guide's loop text changed for #162), the #136, #160, #161 and #162 checks (each on its last comment), and paste the last few `Import took` lines from the Brain log to tune `LoadTries.AFTER` (warm pass ~60 s: file a Decision Engine profiling issue).
2. #156 passes: tag v0.2.0 and run #146's release steps (later 111's item 2).
3. Meanwhile: #163 (hover text, last slice of #158). Then #145, #134, gap.

- Gotchas: same as later 115, minus its #162 line, plus: the bash tool here turns a backslash-n escape inside heredocs into a real newline, so edit Python/Lua strings with the Edit tool. ADDON_LOADED for AzerothQuant no longer runs in DataAddon.lua: Scanner calls `DataAddon.atLoad(db)`.

2026-10-08 (later 115): #161 built (8ea6766), not closed: in-game check left (list on #161's last comment). Tabs on top (`PanelTopTabButtonTemplate` if the client has it, checked with `C_XMLUtil.GetTemplateInfo`; else the bottom template). A banner under them replaces the Reload/Load button and `waitingNote` (deleted): pure `NextStep.of(loop, now)` (new NextStep.lua, 12 busted cases) returns { title, line, button, action, enabled, pulse, warn, quiet }; the glue's `loopState()` in RecommendationFrame.lua gathers the loop each frame. Precedence: scanning > unsaved (Reload) > catching up > Brain not running (never ran or behind) > Brain working > Load/Reload > cooldown one-liner > open the AH > Scan. Scanner exposes `requestScan` and `ahOpen()`; 'Scan saved' and 'should be done' chat lines go out only while the frame is closed (`windowShown()` in Scanner.lua). When catching up ends mid-session, a timer sets `reloadReady`. 336 busted specs.

Next, in order (target #146 by ~Oct 13):
1. In game (user, by ~Oct 11): #156 both parts (later 111's item 1), the guide read-through (#138), the #136, #160 and #161 checks (each on its last comment), and paste the last few `Import took` lines from the Brain log for #162.
2. #156 passes: tag v0.2.0 and run #146's release steps (later 111's item 2).
3. Meanwhile: #162 (auto-Load with 3 slots; needs a new ADR changing ADR-0021 first; timings wait on the `Import took` lines). Then #163, #145, #134, gap.

- Gotchas: same as later 114, plus: the banner's layout constants (`TABS_TOP`, `BANNER_TOP`, `BANNER_HEIGHT`, `HEADER_ROW`) are guesses until the #161 check. #162 should add its orange 'took longer' state to `NextStep.of` and swap the Load state's 'should be ready' for 'are ready'.

2026-10-08 (later 114): #160 built (d2fe1cc), not closed: in-game check left (list on #160's last comment). The Note column is gone from every tab. A side pane on the right of the frame (260 wide) shows the hovered row, else the selected one: Action, Note, a plain "what to do" line (`WHAT_TO_DO` per tab in RecommendationTable.lua), hidden/clipped values, then details. The row tooltip and #136's stopgap are gone. Post/Search sit in `pane.actions` and hide while the pane shows a row other than the selected one. Item now takes the slack (least 150). Hide order: Beta, Cost, ROI, Per click, Per day. Built rows carry `name`, `action`, `note`, `todo`, `details` (was `tooltip`). `RecommendationTable.paneText(row, values)` builds the pane text. 331 busted specs.

Next, in order (target #146 by ~Oct 13):
1. In game (user, by ~Oct 11): #156 both parts (later 111's item 1), the guide read-through (#138), the #136 check and the #160 check (each on its last comment), and paste the last few `Import took` lines from the Brain log for #162.
2. #156 passes: tag v0.2.0 and run #146's release steps (later 111's item 2).
3. Meanwhile: #161 (tabs on top + banner, slice 3 of #158), TDD. Then #162, #163, #145, #134, gap.

- Gotchas: same as later 113, plus: the pane body is one FontString with no scroll; a long Craft row may overflow (on the #160 check list). Heredocs through the Bash tool can mangle `
` inside Python strings: write the script to the scratchpad and run it from there.

2026-10-08 (later 113): #136 built (761de4a), not closed: in-game check left (list on #136's last comment). New plain-Lua `ColumnLayout.fit(section, width)` (4 busted specs) replaces the per-tab width tables: widths by column name (gold 95, Item 190, Qty 50), `TAB_WIDTHS` for per-tab overrides, last column takes the rest, hides Beta, Cost, ROI until the Note gets 150. Frame opens 1100x540, min 1000x400, corner grip, size in `AzerothQuantDB.recommendationFrameSize`, max width keeps the Craft Chain panel on screen. Hidden columns' values go in the row tooltip (stopgap: #160 replaces it). At 1100 the Shopping List already hides Cost (and Beta): #158 item 4 accepted that.

Next, in order (target #146 by ~Oct 13):
1. In game (user, by ~Oct 11): #156 both parts (later 111's item 1), the guide read-through (#138), the #136 check (its last comment), and paste the last few `Import took` lines from the Brain log for #162.
2. #156 passes: tag v0.2.0 and run #146's release steps (later 111's item 2).
3. Meanwhile: #160 (side pane, slice 2 of #158), TDD. It removes the tooltip stopgap for hidden columns. Then #161, #162, #163, #145, #134, gap.

- Gotchas: same as later 112, plus: in-game units may not be screen pixels (UIParent is ~1365 wide at 1920x1080 at default scale), so 1100 may overlap the AH: retune WIDTH/MIN_WIDTH from the in-game check. `lupa` can compile-check glue files busted doesn't load: `loadstring(src)` on a `lupa.lua51` runtime.

2026-10-08 (later 112): #158 designed, no code. ui-ux-pro-max, /prototype (branch `prototype/158-table-layouts`, layout D won), grilled the loop; decisions on #158's comment. Tabs on top, a next-step banner with one Scan/Reload/Load button, every number column in the table, Note and Post/Search in a hover/pin side pane, resizable frame opening ~1100 px. Auto-Load, always on: the Brain writes 3 LoadOnDemand slots, the Addon tries at ~20/45/90 s after a reload (each LoadAddOn is one disk read). Slices filed: #136 → #160 → #161 → #162 (needs an ADR updating ADR-0021) → #163. #156 in-game results still pending.

Next, in order (target #146 by ~Oct 13):
1. In game (user, by ~Oct 11): #156 both parts as in later 111's item 1, plus the guide read-through (#138), plus **paste the last few `Import took` lines from the Brain log** (Start menu > AzerothQuant Brain log): they set #162's try times.
2. #156 passes: tag v0.2.0 and run #146's release steps (later 111's item 2).
3. Meanwhile, or after: #136 (slice 1 of #158), TDD. Then #160. Both may ride along with v0.2.0 if done before the tag; else they ship as an update.
4. #161, #162, #163, then #145, #134, gap: as in later 109.

- Gotchas: same as later 111, plus: the prototype isn't on main; `git switch prototype/158-table-layouts` to open it. `git stash list` has an old "pre-pull local changes 2026-09-28" stash: leave it, don't pop it by accident. `git stash push -- <path>` skips untracked files.

2026-10-08 (later 111): #159 built and closed (e357536). Grilled: own-Scan-first, chunked and widening backfills all hit the late-Scan rule (an older Pooled Scan re-matches the tail within 48 h, else waits for `brain rebuild`), so the fix is "backfill first, and say so". A pull with >= 10 Pooled Scans to import on a page writes `brain.catchingUpSince` to Recommendations.lua first and rewrites without it when the pull ends, however it ends (logged: "Told the Addon a long pull ... ended, in X s"). The Addon (`Nudge.catchingUp`, trusted for 15 min) says "AzerothQuant is downloading recent Scans. This takes a few minutes. Type /reload after that to see recommendations." It shows no "Is the Brain running?" line and no Reload pulse. `pool_backfill_days` now defaults to 14. The setup guide has the line. The first pull is still 281 s on the 67 Beta Scans (all inside 14 days): the wait is honest now, not shorter. The cold Decision Engine pass is still unmeasured (the sim's 0 s isn't real: no installs or Holdings). Read it off the guildie's log in #146.

Next, in order (target #146 by ~Oct 13):
1. In game (user, by ~Oct 11): #156 both parts, steps as in later 108's item 1, plus a guide read-through (#138). Optional #159 check: in config.toml set `pool_backfill_days` high on a fresh history copy, or just watch for the line on the guildie's first run.
2. #156 passes: `git tag v0.2.0 && git push --tags`, download the Release exe, `brain pool key add <guildie>`, upload exe + guide to Drive, then run #146's Checks with the guildie.
3. #158 UI rework, #145, #134, gap: as in later 109.

- Gotchas: same as later 110, plus: `addon/AzerothQuant/Recommendations.lua` shows as modified because a Brain run wrote it. Never commit it. `FakePool(page_size=...)` exists for tests that need one big page. `cli.pool_syncer` takes `pool`, `clock`, `now` and `fair_value_cache` for tests and the watcher.

2026-10-08 (later 110): #146 grilled (decisions on its comments) and release prep done, no tag. v0.2.0 tagged only after #156 passes in game AND #159 is fixed. One guildie, same realm and faction, own key from `brain pool key add <name>` sent by DM. Exe + `docs/setup-guide.md` via a Google Drive link (exe 13.4 MB, over Discord's 10 MB). Repo stays private. Version bumped (0535d51). Old unpacked Pooled Scans parse fine, and a v0.1.0-built history upgrades fine (only `scan_dropped_item` is new). **Filed #159 (core):** a fresh install's first pool pull (30-day backfill) took 252 s on my 67 Scans, and the watcher is busy for all of it. A guildie's first Scan then gets the wrong "Is AzerothQuant Brain running?" line.

Next, in order (target #146 by ~Oct 13):
1. #159: grill the fix (own Scans before the backfill, chunked backfill, or a shorter first backfill), then TDD. Also measure the first Decision Engine pass on a cold 63-Scan history (the rest of the guildie's first wait).
2. In game (user, by ~Oct 11): #156 both parts, steps as in later 108's item 1, plus a guide read-through (#138).
3. Both pass: `git tag v0.2.0 && git push --tags`, download the Release exe, `brain pool key add <guildie>`, upload exe + guide to Drive, then run #146's Checks with the guildie.
4. #158 UI rework, #145, #134, gap: as in later 109.

- Gotchas: same as later 109, plus: archive files wrap the Scan as `{"era", "scan"}`. The first-pull simulation is: strip each archived Scan with `pool.strip_scan`, `FakePool.upload` it (from `brain/tests/fake_pool.py`), then `pool_sync.pull` into `open_history(":memory:")` with `now` = the latest requestedAt. Run it from `brain/` with `tests` on sys.path.

2026-10-08 (later 109): #138 guide drafted at `docs/setup-guide.md` (README points to it), from app.py's popups and the Addon's strings. Covers install via the exe (SmartScreen, WoW folder, pool code), Scan / Reload / wait / Load, each tab in one line, Post/Search/right-click Bought/Budget, the two "Brain" chat lines, the `AzerothQuant Brain log` Start menu shortcut for feedback, update and uninstall. #138 stays open: its Acceptance is a guildie following it alone.

Next, in order (target #146 by ~Oct 13):
1. In game (user, by ~Oct 11): #156 both parts, same steps as later 108's item 1. Read the guide while there and fix anything that doesn't match the screen (Scan button spot, the "Load out of date AddOns" line, whether the window opens next to the AH).
2. #146 PoC (the rest of #85 rides along). The guildie in it follows `docs/setup-guide.md`; that run is #138's Acceptance.
3. #158 UI rework (filed 2026-10-08, core): ui-ux-pro-max, `/prototype` layouts, grill the Scan/Reload/Load loop, then slices. #136 (wider table, now core) is its first slice.
4. #145 (keep Fair Values across a restart, now core): a guildie's first Scan after booting the PC waits ~30 s extra.
5. #134 Cancel button: wanted before Nov 4, after the PoC.
6. Gap, Oct 21 to Nov 4: same as later 103.

- Gotchas: same as later 108, plus: the repo is private, so guildies can't open the guide or the Release on GitHub. Send them the exe and the guide (paste or file). The guide says Post only: Cancel from ADR-0016 isn't built. Keep it in step with any change to app.py popups, Nudge.lua lines or tab names.

2026-10-08 (later 108): #156 part (2), the Addon re-read, built (6983547). Issue stays open for the in-game check of both parts. After the main read, `Scanner.lua` calls GetItemInfo on each dropped row's itemID (`Scan.missingItemIDs`), waits for `GET_ITEM_INFO_RECEIVED` on all of them or 15 s (`REREAD_CAP_SECONDS`), then `Scan.reread` reads the dropped rows' links again in one pass. A link whose itemID isn't the row's is refused (the list can change under the wait). AH closed mid-wait: re-reads what it can (`GetReplicateItemLink` is pcall'd, unknown whether the list survives the close) and saves. Chat line: "Scan #N saved: X Listings (re-read N of M dropped rows in X s), ...".

Next, in order (target #146 by ~Oct 13):
1. In game (user, by ~Oct 11): #156 both parts. Scan once, AH open the whole time. Check the chat line's "re-read N of M" (how many come back, and the seconds: tune the cap if it always hits 15). Then a second Scan, closing the AH during the "Waiting up to 15 s" debug line: it must still save. After `brain watch` imports, the Shopping List should have more rows than Scan 67's 10, and any still-dropped items stay off it. If it's close: comment results on #156 and close it.
2. #138 guide, then #146 PoC (the rest of #85 rides along).
3. Gap, Oct 21 to Nov 4: same as later 103.

- Gotchas: same as later 107, plus: run the busted stand-in from `addon/` (`cd addon && python ../scripts/busted.py`); from the repo root protected_calls_spec fails on a relative path. If the in-game re-read gets 0 of M, the item loading isn't what makes `GetReplicateItemLink` return a link; part (1)'s backstop still covers it.

2026-10-07 (later 107): #156 part (1), the Brain backstop, built (stays open for part (2)). `recommend_market` reads the Scan's drop list (`history.dropped_at`, only the Scan the table is built from). Flips to Sell/Vendor of a dropped item, Flips to Craft whose output is dropped, and Flips to Disenchant candidates that are dropped are left off. Crafts that only buy a dropped reagent stay. Holdings rows of a dropped item get "Price may be off. Check the AH." (`PRICE_MAY_BE_OFF`). Why not has a new Check, `Dropped rows`, between Flip margin and Budget. On Scan 67 the table is 4 rows, none dropped, and 27 of 65 Holdings rows have the note. Part (2) is what brings rows back.

Next, in order (target #146 by ~Oct 13):
1. #156 part (2): Addon re-read, TDD on a pure `Scan.lua` function (busted), per Decisions 4 to 6 on the issue. Then the in-game check for both by ~Oct 11.
2. #138 guide, then #146 PoC (the rest of #85 rides along).
3. Gap, Oct 21 to Nov 4: same as later 103.

- Gotchas: same as later 106, plus: replay and `rework` apply the backstop to past Scans too, so grades and replay numbers for Scans with drop lists move. Tests that need a drop to matter must use `sale_events>=3`: with fewer, #150 (a) already strips the item's evidence and the test goes green by accident. `dropping(scans, *ids)` in test_recommend.py marks the latest Scan.

2026-10-07 (later 106): #156 diagnosed and grilled (decisions on the issue's last comment). Root cause: `recommend.py` never reads `scan_dropped_item`, so the latest Scan's partial ladder is taken as the whole market. Thin table: NOT #150 (a). With Scan 67's drop list deleted, the 10 rows are identical. As of Scan 66 it's 23 rows. Partial Scans make fake price gaps, and the Shopping List picks those first: 6 of Scan 67's 10 rows are dropped items, and 3 more Crafts buy a dropped reagent. So #150 (b) is back: the Addon re-reads dropped rows (15 s cap), with a Brain backstop. Filed #157 (Brain still writes the old `addon/AzerothQuant/Recommendations.lua`, the 4k-line diff in git status).

Next, in order (target #146 by ~Oct 13):
1. #156 part (1): Brain backstop, TDD. Leave off the Shopping List the Flips to Sell/Vendor, Craft outputs and Disenchant sources the latest Scan dropped. Crafts that only buy a dropped reagent stay. Holdings note "Price may be off. Check the AH." First test: `selling_two_linen_an_hour(row(quantity=3, unit=10000), unit=19500, sale_events=3)` with the last Scan's `droppedRows=5, droppedItemIDs=[2589]` (sale_events=1 goes green by accident).
2. #156 part (2): Addon re-read, TDD on a pure `Scan.lua` function (busted). Then the in-game check for both by ~Oct 11.
3. #138 guide, then #146 PoC (the rest of #85 rides along).
4. Gap, Oct 21 to Nov 4: same as later 103.

- Gotchas: same as later 105, plus: an as-of-Scan recommend (`recommend_market(..., now=at, as_of=at, paid=False, loot_alert=False, buy_under=False)`) on a copy of `history.sqlite` takes ~50 s. That's the quick way to compare tables across Scans.

2026-10-07 (later 105): #144/#150 (a) in-game check passed. Scan 68 in game (67 in the history): 70,893 Listings, 7,925 dropped (2,804 items), and `scan_dropped_item` has the 2,804. Parse 5.6-11 s -> 0.4 s. File 4.4 -> 3.3 MB (packed string ~36 bytes/row, not the 1.2 MB estimated). Load fills normally. #144 closed, #150 commented ((a) done; (c) + per-item hours still for the gap). **New: #156.** The current-market picture trusts a Scan with dropped rows. Fishing Rack (279965): the Scan kept 3 of 7 price levels, so the Brain said post at 39s 44c under 65 units at ~30s, and buy only 9. The user also thinks the table is too thin for 41g (6 Shopping List rows); check in the same diagnosis.

Next, in order (target #146 by ~Oct 13):
1. #156: diagnose, grill the fix (drop latest-Scan-dropped items from the Shopping List vs. re-query dropped itemIDs in the Addon), build. Before #146: guildies would see wrong rows.
2. #138 guide, then #146 PoC (the rest of #85 rides along).
3. Gap, Oct 21 to Nov 4: same as later 103.

- Gotchas: same as later 103, plus: `brain recommend` takes >3 min now. Read the Shopping List from `Interface/AddOns/AzerothQuant_Data/Recommendations.lua` instead. `brain watch` was restarted 21:06 on ef446a1.

2026-10-07 (later 104): #149 built and closed. `pool_sync.pull` now leaves out a Pooled Scan whose body's realm, faction or requestedAt differs from its index entry (`_matches`). It's neither archived nor imported, so `brain rebuild` can't bring it back. It counts under `rejected`. There's no era check: the body has no era and is imported under the entry's. "Not later than the upload time" holds because the Worker rejects a header more than 10 min past the upload by its own clock, and the body must now equal the header. A pull-time check against the PC clock was built, then dropped in review: a PC clock running slow would have dropped real Scans for good, since the cursor moves past them. Accepted gap: a bad body archived before this change still freezes its Market on every rebuild. Before the PoC there was a single uploader, so this is unlikely. If it ever happens, delete that file from `pool/`. ADR-0026 and CONTEXT.md (**Pooled Scan**) now say this. `FakePool.upload(header_overrides=...)` makes the index disagree with the body.

Next, in order (target #146 by ~Oct 13):
1. In game (user, by ~Oct 11): the #150/#144 check (unchanged from later 103).
2. #138 guide, then #146 PoC (the rest of #85 rides along).
3. Gap, Oct 21 to Nov 4: same as later 103.

- Gotchas: same as later 103.

2026-10-07 (later 103): Addon batch built and pushed (088ee4b): #150 part (a) + #144 packed rows. Both stay open until the in-game check (steps on #150's comment; #144's comment adds the file-size check). The Addon saves `droppedItemIDs` (from `GetReplicateItemInfo` return 17) and `packedListings` ("itemString,quantity,buyout,timeLeft;..."). Own rows stay tables in `listings`. The Brain leaves dropped items out of both Observation Windows touching that Scan (`scan_dropped_item`, `_ends_of_windows`). `pool.strip_scan` folds own rows into the sorted packed string (ADR-0026). The parser's plain-run regex took one real 73k-row Scan from 4.4 s to 0.11 s. `item_id_of` moved to `scan.py`. Review leftover, deferred to the gap and noted on #150: a left-out item still gets the window's hours (`window_hours` is per Market), which pushes its Sell Rate toward 0. That's the safe side. Fix it with per-item hours if #153's data shows the same items dropping often.

Next, in order (target #146 by ~Oct 13):
1. In game (user, by ~Oct 11): the #150/#144 check. The chat line "N dropped (M items)" must show M > 0 when N > 0. Import works, and the SavedVariables file is smaller. With what fits of #85. If M = 0, return 17 is nil and #150 (a) needs another itemID source.
2. #149 Brain-side Pooled body checks (build while waiting on the PC).
3. #138 guide, then #146 PoC (the rest of #85 rides along).
4. Gap, Oct 21 to Nov 4: same as later 102, plus #150's per-item hours.

- Gotchas: same as later 101, plus:
  - Packed format lives in three places that must agree: `Scan.lua` (build), `scan._packed_row` (read), `pool._strip_packed` (strip). Item strings never contain `,` or `;`.
  - Python edit scripts: open files with `encoding="utf-8"` (cp1252 default fails on some test files). Bash heredocs still mangle backslashes, so write the script with the Write tool.

2026-10-06 (later 102): Grilled #149-#153 and #155 against the Oct 20 PoC. **Rule: before Oct 20 only what needs the game or would spoil the #146 PoC; Brain-only work goes in the Oct 21 to Nov 4 gap** (no game, but the Brain and the archive work; guildies reinstall for Live anyway). Decisions are commented on each issue. Facts found: all 66 own Scans have `dropped_rows > 0` (avg ~2.5k of ~74k), so #150's "skip windows next to dropped-row Scans" was impossible; it became (a) the Addon records dropped rows' itemIDs (`Scanner.lua:159` discards `GetReplicateItemInfo` return 17) + (c) a Brain resurrection check in the gap. Own Listings with mail (122 sold, 38 cancelled, 48 expired) are enough for #153 now. #146's speed check is now "record, don't block" (with the pool on, most passes are new-Scan passes at ~19 s), and #147's zero-history in-game check was added to it.

Next, in order (target #146 by ~Oct 13):
1. Addon batch: #150 part (a) (record dropped itemIDs, Brain skips those items' windows) + #144 packed rows. One in-game check, with what fits of #85. Cut #144 if not checked in game by ~Oct 11.
2. #149 Brain-side Pooled body checks (build while waiting on the PC).
3. #138 guide, then #146 PoC (rest of #85 rides along).
4. Gap, Oct 21 to Nov 4: #147 offline part (grill first), #153, #151 (grill the design first), #155, #150 (c), #152. #150 (c) and #152 move past Nov 4 if #153 shows they're small (~5%).

- Gotchas: same as later 101.

2026-10-06 (later 101): #143 built and closed (d8213a1, slice C of #116). `FairValueCache.scan_only(conn, market, what, work)` keeps Scan-only results across passes, dropped when any of the Market's `scan_stamps` changes (`_check_scans`): `listings`, `supply_at` (all and others only), `sell_rates` (keyed on the whole Config and `now`), `_others_lows`, and the Buy Unders' `cheapest_seen`. Bench (three-pass script, numbers on #116): no new Scan 19.4 s -> 5.9 s (`brain bench` pass 2: 5.9 s), new Scan 22.1 s -> 19.3 s, byte-identical. **Neither budget is met.** Buy Unders and Flips are NOT reused: they read the Holdings (the post-Flips Valuer's `held`, in `_sell_way`) and Deposits, so the issue's "key on Known Recipes and skill" was not enough. The rest is filed as #155 (needs-triage): `SellRate.at_or_above` bisect (3.6 s of the profiled no-Scan pass, likely enough on its own), a per-Item Key Flips memo, and the new-Scan `listings`/`_others_lows` loads.

Next, in order: 1. Grill #149-#153 together (see later 100), then decide where #155 goes against the Oct 20 deadline (a no-Scan pass at ~6 s may be fine for the PoC). Then #138, #146, #85 day-1 checks, #147.

- Gotchas: same as later 100, plus:
  - With a cache, `sell_rates` and `_valuer` ignore the `seen` passed in and use `cache.listings`, because the kept results aren't keyed on `seen`.
  - Three-pass bench script (rewind the latest Scan, cold pass, import it back, new-Scan pass, no-Scan pass, copy the Lua after each): rebuild it from #142's description; it takes ~3 min per code version.

2026-10-06 (later 100): Independent quant review done in a fresh session outside the project (snapshot at `Z:\aq-fresh-review`, code first, ADRs read last). Report and probes committed in `docs/research/independent-review-2026-10-06/` (a6ba1d7). Spot-checked: own Purchases are never read by observation/sell_rate (finding 1), and own Scans skip `_complete_enough` while `dropped_rows` is never read (finding 2). Both true. Filed, all needs-triage: #149 bad Pooled Scan freezes a Market (core), #150 dropped rows make phantom sales (core), #151 lowball listing makes Holdings say Vendor (core), #152 own Purchases count as demand (core), #153 measure Probable Sale precision on own Listings (core), #154 umbrella: replay go/stop graded by the Brain's own model, plus findings 4/7/9/10 (before ~Dec 2, not Oct 20). Perf ideas commented on #143 (1x1 match fast path -38% import, history-bounded Listing loads) and #144 (packed-string scan rows: parse 3.3 s -> 0.06 s).

Next, in order: 1. #143 as planned. 2. Grill #149-#153 together in one session: decide which go before #146 (the guild PoC needs #149 at least) and which wait. Then #138, #146, #85 day-1 checks, #147.

- Gotchas: same as later 99, plus:
  - Review findings are an outsider's read. Some may clash with deliberate ADR choices (e.g. #151 vs ADR-0017). Grill before building; don't treat the review as spec.

2026-10-06 (later 99): #142 built and closed (e22a134, slice B of #116). Each Observation Window's Disappearance candidates and Partial Sales are kept in `FairValueCache` across passes (`kept_for_window`). Repost pairing is redone each pass (memoized in `FairValueCache.this_pass`), because it reads a new Listing's quantity as of its *last* Scan (that quirk is filed as #148, needs-triage, a logic change). `FairValueCache._check_scans` compares each Market's `history.scan_stamps` (requested_at, ID, source, pool ID if Pooled) once a pass and drops everything kept from the first changed Scan on, Fair Values included. That fixed stale Fair Values after an own Scan replaced a Pooled one. Bench (script, not `brain bench`; numbers on #142): new-Scan pass 31.8 s -> 20.5 s, no-Scan 29.1 s -> 18.9 s, byte-identical. The budget is NOT met. `_others_lows` was left alone (not per-window).

Next, in order: 1. #143 (reuse Scan-only results when no Scan changed). Then #138, #146, the #85 day-1 checks, #147 (see later 97's critical path). A new Scan is still ~20 s; the biggest costs left are the `listings` load (~6-7 s), `_others_lows` (~4-7 s), `flips`, and `sell_rates`' own passes over all 1.3M Listings (~3 s). Raise with the user whether a slice for those is worth it before Oct 20.

- Gotchas: same as later 98, plus:
  - #143: key the reuse on `scan_stamps`, not on the latest Scan time alone. A re-match, a roll-back, or an own Scan replacing a Pooled one can change the history without changing the latest time. `FairValueCache._check_scans` already does this comparison; reuse it.
  - New-Scan bench: `brain bench` passes don't bring a Scan. The script used for #142 (described on #142) rewinds the latest Scan on the copy, runs pass 1, imports that Scan back with `import_archived_scans` from `brain/archive`, then runs passes 2 and 3. It writes Recommendations.lua after each pass for `cmp`.
  - Any game running skews the bench a lot (Fair Values 29 s -> 42 s). Check `Get-Process` first, or run before and after back to back.
  - `addon/AzerothQuant/Recommendations.lua` shows as modified because the dev Brain writes it. Don't commit it.
  - `test_sell_rate_tally.py` imports builders from `test_rematch` (the standards review flagged that; move them into a helper module if a third file needs them).

2026-10-06 (later 98): #141 built and closed (slice A of #116). `_way_out` is memoized on the `_Valuer` (`ways_out`), `_post_at` uses `cheapest_without` with the player's own cheapest cached per Valuer, and `FairValueCache.listings` loads each Market's Listings once per pass (reset by `start_pass`). New `brain bench [--out DIR]` runs two passes on a sqlite copy of the history and prints per-stage seconds. Pass 2 Decision Engine went from 62.7 s to 34.6 s. The budget is NOT met, so #142 goes ahead. Bench and the new profile are on #116: `sell_rates` x2 is 25 s (`disappearances` 19 s), then `listings` 8 s, `flips` 8 s, `_others_lows` 7 s, `_buy_unders` 5.5 s.

Next, in order: 1. #142 (incremental Sell Rate evidence), then `brain bench`. 2. #143 (reuse Scan-only results when no Scan changed; it's the only way to get no-Scan under 5 s). Then #138, #146, the #85 day-1 checks, #147 (see later 97's critical path).

- Gotchas: same as later 97, plus:
  - Byte-identical check: run both old and new with `PYTHONHASHSEED=0`. Without it even the old code's Recommendations.lua can differ, because `cli._beta_priors` iterates a `set` of Item Keys, so the `betaPrior.prices` order follows the hash seed. The data is equal. Old code: `git worktree add --detach <scratch>/head HEAD`, then `PYTHONPATH=<scratch>/head/brain/src python script.py`.
  - Bench recipe: a scratchpad folder with the `backup()` copy as history.sqlite, grades.toml copied, and a config.toml with one `[[installs]]` whose folder has `Interface/AddOns/AzerothQuant` created. `brain --config that/config.toml bench` takes ~2 min. Don't run two benches or profiles at once: they share the CPU and skew the numbers.
  - The working tree mixes CRLF and LF (autocrlf=true). Scripted edits that write LF are harmless, since git normalizes on commit.

2026-10-06 (later 97): DEADLINE. Guild-ready proof of concept must work end to end on Beta by ~Oct 20. Beta ends Oct 21, Live launches Nov 4, and it has to be frictionless from day 1 of Live. Oct 21 to Nov 4 has no game, so every in-game check has to happen before Oct 21. QoL gaps are accepted. Rank work by "does a guildie hit this on day 1".

Critical path (the user added: the Scan Pool has to work too):
1. #116 speed: #141, then `brain bench`. Do #142/#143 only if the budget isn't met. Bench a pass with Pooled Scans arriving too, since with several members most imports bring new Scans. #144 is cut unless parsing is still the bottleneck.
2. #138 setup guide (now core). The PoC test needs it.
3. #146 guild PoC on Beta (ready-for-human, by ~Oct 13): a guildie on their own PC, with the exe and a pool key. Pool in both directions, import time with 2+ members, the problem lines. The pool has only been checked from one machine (#124). Failures become core bugs, fixed by Oct 20.
4. #85: only the day-1 checks (#120 clock, #78 deposit, `brain rebuild`, the Beta replay for #83).
5. #147 day 1 of Live (needs-triage, grill first): zero history, Live Era pool, Beta Prior column.
Cut to after Nov 4: #81, #39, #136, #140, #144, #145 and all `later`.

2026-10-06 (later 96): #116 grilled. The spec is a comment on #116 (ready-for-agent), with 4 sub-issues. It's pure optimization: Recommendations.lua must stay byte-identical. The budget is a new Scan under 15 s and no Scan under 5 s, from the reload being noticed to the file written. Profile (cProfile, DB copy): 103 s per pass. `_way_out` (no memo, 132k calls) is 51 s, `without()` in `_post_at` 17 s, `sell_rates` twice 26 s, `_others_lows` 6 s. About 80% is Scan-only. Slices in order: #141 A (memo within a pass + `brain bench`), #142 B (incremental Sell Rate evidence), #143 C (reuse Scan-only results when no Scan changed), #144 D (SavedVariables parser fast paths, moved off #10). #145 (`later`): Fair Values across a Brain restart. No code changed.

Next, in order: 1. #141. After it, run `brain bench` and drop later slices if the budget is met. Then #142, #143, #144, then #138, PC items (#81, #39, #85, #140), #136.

- Gotchas: same as later 95, plus:
  - Profiling recipe: sqlite `backup()` copy plus a scratchpad config with one `[[installs]]` pointing at an empty folder ("The Addon isn't installed" just skips the write). Call `cli._write_recommendations(conn, cfg, fair_value_cache=cache, timings=t)` twice in one process under cProfile. That takes ~4 min.
  - Bash heredocs with apostrophes failed in this shell; write issue bodies with the Write tool and `gh ... -F file`.

2026-10-06 (later 95): #139 built and closed (c2207c4). A break of up to 2 Scans with nothing under the post price (`SHORT_BREAK_SCANS` in recommend.py) no longer ends the cheap stretch, when cheap stock was up again before it. `_Cheap.stretch` returns `_Stretch(since, breaks)`. `WhyNot.cheap_breaks` holds the skipped Scans, and `--why-not` adds "(none at ...)". ADR-0029 is amended and CONTEXT.md updated. The replay numbers are on #139: graded per Flip once per Item Key at Scans 40-63, 1 Scan nets +33g and 2 Scans +64g. On the 10-06 17:51 and 19:46 Scans, 248689 is off the list, plus 1121, 11177, 3182, 2879, 729, 12977 and 5637. The crate-stacking question is now #140 (ready-for-human, in game).

Next, in order: 1. #116: grill/spec first (budget, profile one Decision Engine run, skip or narrow work when no Scan changed). Then #138, PC items (#81, #39, #85, #140), #136.

- Gotchas: same as later 94, plus:
  - Per-Flip grading recipe (faster than a replay): build the Shopping List for each variant in one process (sharing a `FairValueCache`), then grade only the Flips that differ, each on its own with `replay._grade(conn, config, m, replay._Moves(spent=cost, posts=[replay._Post(key, qty, post_at)]), later, deposit, cut, t)`. Grading every row costs ~30 s per Flip, while a recommend pass takes ~30-60 s. Six processes covered 24 Scans x 3 variants in about 25 min.
  - `tests/test_instance_lock.py::test_another_running_brain_holds_the_lock_until_it_is_killed` fails locally: in a Windows venv, `sys.executable` is a launcher, so the PID in the lock file is the child's. It's not related to #139. Deselect it locally (CI is Linux).

2026-10-06 (later 94): #115 Acceptance run on the `aqtest` account; results commented on #115 (it was already closed, on 10-05). #116 moved to `core` with per-stage numbers. No code changed.

- Passed on aqtest: SmartScreen ("unknown publisher"), setup popups (found Z: WoW from the registry, beta + live, no key), autostart after reboot, update to 0.1.1 with data kept, uninstall (shortcuts and both Addons gone).
- Not shown on aqtest, left to the techy-guildie test (ask for `brain.log`): Scan → Load fills the table, and the "Brain isn't running" line. aqtest's one Scan never finished (`nextScanId` stayed 66). The beta client patched at 19:27, but a dev-account Scan on the new build saved and imported fine (#66 at 19:49), so it was a one-off (AH closed or reload too early).
- Also unconfirmed: aqtest's app folder still existed when the uninstall check ran, maybe before the ~5 s delayed delete.
- #116 finding: the Decision Engine takes 67-94 s on every import, even a reload with no new Scan. Fair Values are 28 s after a Brain restart, 0 s after that. SavedVariables parsing is 6-11 s with a Scan.
- The user asked about dropping the `/reload` or using Blizzard's AH API. Answered no: addons can't write files or use the network, so SavedVariables on reload is the only way out of the game, and the web API is hourly (and probably has no beta). The fix is the ~80 s after the reload (#116).

Next, in order: 1. #139 (ready-for-agent, option 1 decided on the issue). 2. #116: grill/spec first (budget, profile one Decision Engine run, skip or narrow work when no Scan changed). Then #138, PC items (#81, #39, #85), #136.

- Gotchas:
  - Windows accounts share the WoW folder (WTF and AddOns). A second-account test needs the dev junction and dev Brain moved aside first: setup skips linked Addons, and two Brains would write the same Recommendations.lua. Uninstall deletes the non-linked `AzerothQuant_Data`.
  - The dev setup is restored (junction, Data addon, `brain-watch.bat` in Startup, Brain running). `Z:\vibing\aqtest-backup\` holds `RESTORE.txt` and the AQProbe addon, moved out of AddOns because its probe buttons were on screen. Bring AQProbe back only if a #39 probe needs it (it'll need new code anyway).
  - The aqtest account and `C:\Users\Public\aqtest\` (both exes, helper .bat files, aqtest's saved log) are still there. Delete them when no longer needed (`net user aqtest /delete` in an admin shell).
  - C: had 0.5 GB free, which stalled Battle.net's patch on aqtest (the game is on Z:, but Battle.net uses C:).
  - `brain/src/brain/__init__.py` is back to `0.1.0`. The 0.1.1 was only for the test build.
  - Never run the exe on the dev account: it sets up autostart and writes to %LOCALAPPDATA%.
  - The dev Brain runs from `.venv` during play (`brain/brain.lock`). Diagnose on a copy: sqlite `backup()` into the scratchpad, plus a config there without the pool secrets (relative paths resolve next to the config).
  - `brain recommend --why-not <name>` takes ~2 min on the real data, and it didn't match 'Waylaid Crate: Journeyman Curiosities' by name. Use the Item Key.

2026-10-06 (later 93): #115 Acceptance steps 1 and 2 done; nothing run. Filed #139.

- Step 1: the v0.1.0 Release exe's sha256 matches the Release, Defender finds no threats, it's NotSigned (expect SmartScreen). The bundle has `_tkinter.pyd`, tcl86t/tk86t DLLs, `_tcl_data` (832) and `_tk_data` (89), the Addon (34 files, Recommendations.lua is the 315-byte stub) and `brain\data\disenchant.toml`.
- Step 2: `brain/src/brain/__init__.py` says `0.1.1` (uncommitted, don't tag). Built with a throwaway venv in the session scratchpad, output there too (not `brain/dist`), so the exe may be gone by the next session. Rebuild with `pyinstaller --noconfirm --distpath <dir> --workpath <dir> AzerothQuantBrain.spec` from `brain/` in a venv with `pyinstaller>=6.10` (the dev `.venv` doesn't have it; leave it that way). Its bundle matches the Release except 4 api-ms-win-core-* shims the CI runner added (Windows 10 has them).
- #139 (option 1 chosen): one dear Scan reset 248689's cheap stretch, and the 24 h unwatched grace kept week-old demand, so the Brain said buy 528 Waylaid Crates. Also open on it: the player says the crate doesn't stack, but ~300 Listings had 2+ units.

Next, in order: 1. The user's step 3 on the `aqtest` account (copy both exes somewhere it can read, like `C:\Users\Public\aqtest\`), then step 4. 2. #139. Then #138, PC items (#81, #39, #85), #136.

- Gotchas:
  - Never run the exe on the dev account: it sets up autostart and writes to %LOCALAPPDATA%.
  - The dev Brain runs from `.venv` during play (`brain/brain.lock`). Diagnose on a copy: sqlite `backup()` into the scratchpad, plus a config there without the pool secrets (relative paths resolve next to the config).
  - `brain recommend --why-not <name>` takes ~2 min on the real data, and it didn't match 'Waylaid Crate: Journeyman Curiosities' by name. Use the Item Key.

2026-10-06 (later 92): Planning only, no code. Plan for the #115 Acceptance, decided in session: don't hand it to a guildie first. The exe, the popups, autostart, update and uninstall have never run outside the dev box.

Next, in order:
1. Agent pre-flight: download the v0.1.0 Release exe, check the bundle has tkinter + Tcl/Tk data, Defender-scan it (`MpCmdRun -Scan -ScanType 3 -File <exe>`), check it's unsigned (expect a SmartScreen warning).
2. Agent: bump `brain/src/brain/__init__.py` to `0.1.1` and build locally from `brain/AzerothQuantBrain.spec`. That's the update-test exe. Don't tag or release it without asking.
3. User: make a local test account (`net user aqtest <pw> /add` in an admin shell). Log in, run steps 1 to 4 of the Acceptance (setup popups, WoW Scan/Reload/Load, reboot, kill), then the 0.1.1 exe for update, then uninstall.
4. Agent: read `C:\Users\aqtest\AppData\Local\AzerothQuant\brain.log` and `/diagnosing-bugs` any failure. Otherwise close #115 and start #138.
PC items as before (#81, #39, #85). #136 whenever.

- Gotchas: same as later 91, plus:
  - Windows Sandbox isn't enabled on the dev PC, and it can't run WoW anyway. Use the test account.
  - Only after the test-account pass: a techy guildie on Discord is a fine second test. Ask them for `brain.log`.

2026-10-05 (later 91): `v0.1.0` tagged and released. The release job's first real run worked: https://github.com/zachmanson/azerothquant/releases/tag/v0.1.0 has `AzerothQuantBrain.exe` (13.4 MB, a 64-bit windowless exe). The first two attempts failed because of a GitHub Actions outage ("job was not acquired by Runner" after 15 min of queueing, and jobs cancelled), not because of our code. "Re-run failed jobs" fixed it once githubstatus.com showed Actions as operational.

Next, in order: the #115 Acceptance on a clean Windows account, using the Release exe (setup popups, reboot, kill, update), then close #115. PC items as before (#81, #39, #85). #136 whenever. #138 after #115 closes.

- Gotchas: same as later 90, plus:
  - Still not run: the setup popups, uninstall and its ~5 s self-delete, and update's 10 s exe-copy retry against a running Brain. The Acceptance covers them.
  - If CI fails with "not acquired by Runner", check githubstatus.com. Don't debug the workflow, and don't re-run while Actions is degraded.
  - The working tree's modified `addon/AzerothQuant/Recommendations.lua` is the dev PC's written copy. Never commit it.

2026-10-05 (later 90): #115 slice 4 built (e358766), commented on #115. `brain/AzerothQuantBrain.spec` freezes `brain.app` into one windowless exe. It bundles the Addon from `git archive HEAD` (so the stub ships, not the dev PC's written Recommendations.lua) plus `brain/data/*.toml`. The `brain-exe` job in ci.yml runs on a `v*` tag after the brain and addon jobs pass. It checks the tag matches `brain.__version__`, builds on windows-latest and attaches the exe to a GitHub Release. In a sandbox (LOCALAPPDATA/APPDATA pointed at a scratchpad), the frozen exe watched, imported, logged and wrote the `brain` table. An update run installed the bundled Addon, made the 4 shortcuts and restarted the Brain, and a second launch showed the popup. A fix along the way: the installed Brain now watches without starting Tk, because the hidden root showed as Not Responding, which can hold up a Windows shutdown.

Next, in order: tag `v0.1.0` and push it, which is the first real run of the release job, then download the exe from the Release. Then the #115 Acceptance on a clean Windows account (setup popups, reboot, kill, update), and close #115. PC items as before (#81, #39, #85). #136 whenever. #138 after #115 closes.

- Gotchas: same as later 89, plus:
  - Not run yet: the setup popups (they need clicks), uninstall and its ~5 s self-delete, update's 10 s exe-copy retry against a running Brain, and the release job itself.
  - To test the frozen exe without touching the real install: set LOCALAPPDATA and APPDATA to scratchpad folders and give it a config whose install points at a fake `_classic_beta_` with a copied SavedVariables. Run the copy in `<LOCALAPPDATA>\AzerothQuant\` to watch, or any other copy to update.
  - A local build bundles the committed Addon. Commit Addon changes before building.
  - With `--noconsole`, `sys.stderr` is None. The console log handler's errors are dropped quietly and the file log works (checked). There's no guard; one wasn't needed.
  - Review items not taken: no unit test of `app.main`'s routing (thin glue, checked on the frozen exe), and the "AzerothQuant" bundle name is shared by the spec and `_bundled_addon` only through a comment.

2026-10-05 (later 89): #115 slice 3 built (9613f90), commented on #115. Every Recommendations write carries `brain = { version, problem }`. There are three problems: the pool is unreachable (`PoolSyncer.problem`, cleared by the next pull that gets through), no Recommendations (`cli.NO_RECOMMENDATIONS`), and watch crashed (`cli.CRASHED`, written in `_watch`'s `except Exception`). They're joined into one line. The Addon side is `Nudge.atLogin` (called in Scanner.lua's ADDON_LOADED), which prints the never-run line or the problem plus the log tail. `BRAIN_BEHIND_LINE` is reworded. "Can't find your WoW folder." is skipped (nowhere to write it).

Next, in order: #115 slice 4 (PyInstaller + the CI release on a `v*` tag; see the later-88 gotchas). PC items as before (#81, #39, #85). #136 whenever. #138 last.

- Gotchas: same as later 88, plus:
  - Restart `brain watch` after this commit. Until it writes once, the dev PC's Recommendations.lua has no `brain` table, so the Addon prints the never-run line.
  - The lines print at every load, `/reload` included, not "once per login". Limiting them to the first login would hide a problem until the next login, because problems only arrive after a reload. The Load button (Data addon) doesn't re-check. `rebuild` and `pool pull` by hand write no problem (dev only).
  - Real-Lua pytest on this PC: the shim is `lua.bat` -> `lua_shim.py` (lupa.lua51, tab-joined print), with LUA pointing at the .bat. Rebuild it in the scratchpad each session.
  - Review items not taken: `problem: str` threaded through 4 signatures (a `BrainStatus` type is overkill for one field), and the duplicated `markets = []` in `_write_recommendations`'s two excepts.

2026-10-05 (later 88): #115 slice 2 built (0fe6b55), commented on #115. The logic is in `brain/installer.py` (20 pytest tests, temp folders). The tkinter glue is in `brain/app.py`, entry `brain.app:main`, which slice 4 freezes. Two decisions from the user: only `_classic_` is Live (`_classic_beta_` is beta, and Classic Era/PTR/retail are left out), and an update looks for game folders again in the same WoW folder and keeps the pool key. Reinstalling keeps the Brain's latest Recommendations.lua, and a linked-in (dev) Addon folder is never touched. The version now lives in `brain/__init__.py` (`__version__`), and pyproject reads it.

Next, in order: #115 slice 3 (`brain` status in Recommendations, and the Addon's problem/never-run/behind lines). Then slice 4 (PyInstaller + CI release). PC items as before (#81, #39, #85). #136 whenever. #138 last.

- Gotchas: same as later 87, plus:
  - `brain.app` refuses to run unfrozen (`sys.frozen`), because from source `sys.executable` is python.exe and setup would copy it in as the Brain. So none of the popup flow has run end to end yet. Slice 4's clean-account Acceptance is the first real run. Only the .lnk writer and the delayed delete were smoke-tested by hand.
  - Slice 4 has to bundle the Addon at `sys._MEIPASS/AzerothQuant`, from a clean checkout. The repo's `addon/AzerothQuant/Recommendations.lua` is dirty on the dev PC (the Brain writes it), and the bundle must carry the stub.
  - A onefile exe is two processes. The lock holds the inner PID, so update's exe copy retries for up to 10 s on PermissionError, and uninstall's self-delete waits ~5 s (`ping -n 6`). Check both on the frozen exe.
  - `POOL_URL` is hard-coded in `brain/app.py`.
  - Cancel on the pool-key popup quits setup. Leaving it empty skips the pool.
  - Review items not taken: the test helpers repeat the 7-argument `install(...)` call, `install`/`update` take a lot of parameters, and watch mode builds a hidden Tk root it only needs for the "already running" popup.

2026-10-05 (later 87): #115 slice 1 built (2fe0042). The config lookup is `--config`, then `./config.toml`, then `%LOCALAPPDATA%\AzerothQuant\config.toml`. The config's folder is the data folder. `brain watch` holds an OS file lock there (`brain.lock`, which holds the PID), so a second watcher exits "already running". Every command logs to `brain.log` there, rotated at 1 MB. The dev setup still works, and both files are gitignored in `brain/`. Commented on #115.

Next, in order: #115 slice 2 (setup/update/uninstall behind a thin tkinter layer). Then slices 3 and 4. PC items as before (#81, #39, #85). #136 whenever. #138 last.

- Gotchas: same as later 86, plus:
  - The "AzerothQuant Brain is already running." popup isn't built yet. Slice 1 only logs it, and slice 2's tkinter layer should show it.
  - The lock file's PID can be stale after a crash. To tell whether a Brain is running, try `instance_lock`; don't trust the PID. Windows also frees a killed process's lock asynchronously, so update's "stop, then restart" should retry the lock for a second or two.
  - Windows file locks are mandatory, so the lock sits on byte 1 TiB to keep the PID readable. Don't move it near the start of the file.
  - The log only opens once a config is found. Setup (slice 2) owns the "no config yet" case. With `--noconsole` (slice 4), `sys.stderr` can be None, so check that `logging.basicConfig` still works in the frozen exe.
  - The lock covers the config's folder, not `history_path`. Two configs pointing at one history file aren't guarded. That's fine for guildies, who only get one config.
  - Review leftovers I chose not to act on: "data folder" isn't in CONTEXT.md, and the lock design has no ADR.

2026-10-05 (later 86): #115 grilled, spec on the issue, now ready-for-agent. One frozen `AzerothQuantBrain.exe` (PyInstaller, built by CI on a `v*` tag, handed out in the guild Discord since the repo stays private). First run is a couple of tkinter popups (confirm WoW folder, paste pool key), then it copies itself to `%LOCALAPPDATA%\AzerothQuant\` (config + data live there too), installs the Addon and `AzerothQuant_Data`, adds Startup + Start menu shortcuts, and watches hidden. Guildies never see a console: Brain problems reach them as in-game chat lines from a `brain = {version, problem}` status in Recommendations, plus a reworded "Brain behind" line and a "never run" line. Rerunning a newer exe updates. Single-instance lock. `--uninstall`. Windows only. Four slices are suggested on the issue.

Next, in order: build #115 slice 1 (config lookup in %LOCALAPPDATA%, single-instance lock, log file), then slices 2-4. PC items as before (#81 in-game check, #39 slice 1 check and slice 2 taint probe, the #85 list). #136 whenever. #138 last, once #115 ships.

- Gotchas: same as later 85, plus:
  - Everything guildies see (popups, chat lines, the guide) has to be short plain language: no domain terms, no commands, and no "Zach" (say "whoever gave you the Brain").
  - The dev setup (repo `brain/config.toml`, `scripts/brain-watch.bat`) must keep working: the config lookup is `--config`, then `./config.toml`, then %LOCALAPPDATA%.

2026-10-05 (later 85): Discussion only, no code. Filed #137 (needs-triage, later): monetization as a free Addon + local Brain with paid access to the pooled Scans, with a comment on handing out opportunities to beat alpha decay. Figure it out much later. Made the `guild-alpha` milestone: a guildie can install it, join the Scan Pool and use it without it breaking. The user widened it to painless setup + use, accurate recommendations and QoL: #115, #116, #85, #81, #39, #134, #136, #97, #130, #112, #113, #58, #110, #109, #76, #10 and the new #138 (setup guide, written after #115), 17 in all. Left off: #91 (the user's own Predictions), #19, #82, #14 and #83 (bound to data or the calendar), #137.

Next, in order: grill #115 (it's needs-info and it's the real guild-alpha blocker; the setup guide #138 depends on it). PC items as before: the #81 in-game check, then #39 slice 1's check and slice 2's taint probe, and the #85 list. #136 is small, so do it whenever. Grill the needs-info ones (#116, #130, #112, #113) as they come up. #138 last.

- Gotchas: same as later 84. Guildies on one realm get the same Buy Unders, so they'll compete with each other (the #137 problem at small scale). Watch for it and note it on #137.

2026-10-04 (later 84): #135 closed, with the replay numbers on the issue. On the 17-Scan replay the Brain went from 20g 08s to 17g 53s. A Brain-only per-Flip grading on a newer DB copy (21 Scans) came out +12g 45s. The 17-Scan copy stopped just before the 5631 cut (−18g avoided). There are false alarms: 248689, 8365 and 6399 get cut on under half an hour of watching with no sale, then sell. The rule stays as is, because the 5631 cut looked the same when it was made. Restarted `brain watch` on the fixed code, and LME is off the live list.

Next, in order: at the PC, the #81 in-game check (Acceptance on #81), then close #81. Then the #39 slice 1 in-game check (gotchas in later 80), then the slice 2 taint probe. #116 warm-pass numbers. Then date items. `later` builds once core is clear: #136 (small), then #134.

- Gotchas: same as later 82, plus:
  - `brain watch` keeps the code it started with. Restart it (`scripts/brain-watch.bat`) after any Brain commit, or the addon keeps showing the old list.
  - A full `brain replay` takes ~107 min. It prints only at the end. For a decision-logic diff, grade per Flip with Brain only at each replayed Scan (`recommend_market` + `replay._brain`/`_grade`/`_taken`). That's still ~3 min per Scan. Use the same DB copy for before and after, because a newer copy adds replayed Scans.

2026-10-04 (later 83): Triaged #134 and #136. Both are now ready-for-agent and `later`, with their specs on the issues. #134 was grilled: the Brain names an own Listing to pull when Pull (Deposit lost now, plus the units valued as held units at the current Post price) beats Leave (what sells at its own price in the time left, behind cheaper stock, plus the rest back at expiry with the Deposit lost). The rows go in a new Listings tab, only the logged-in Character's. Cancel takes the Post button's slot, one `CancelAuction` per click, with auctionIDs matched from `QueryOwnedAuctions` by Item Key + price, and confirmation on `OWNED_AUCTIONS_UPDATED`. ADR-0016 Consequences got a #134 line. #136: a fixed ~1150 px frame with the widths re-budgeted, no resizing.

Next, in order: the #135 replay numbers, if they still aren't posted (see later 82). At the PC: the #81 in-game check (Acceptance on #81), then close #81. Then the #39 slice 1 in-game check (gotchas in later 80), then the slice 2 taint probe. #116 warm-pass numbers. Then date items. `later` builds once core is clear: #136 (small), then #134.

2026-10-04 (later 82): #135 built (f1ae981, ADR-0029), not closed: the beta replay before/after was still running at commit. Its numbers go on #135, and then close it if the P&L holds. Grilled first, and the spec plus an amendment are on #135. The demand cut now dates from the **stretch** of cheap stock: the earliest Scan from which every Scan up to the latest had another player's Listing under the post price. LME's walls kept turning over, so its run's own first_seen was two days late. The expected-sales test is gone. A stretch that is only the latest Scan is never cut. If any Observation Window hours came after the cutoff, it's cut. With none, the whole range counts until the stretch is 24 h old (`UNWATCHED_STRETCH_SECONDS` in sell_rate.py). `--why-not` adds "(not watched since)". Run-size cap (proposal 2): not done, because the demand wasn't inflated, it was out of date. On the 17:54 Scan, 10 Flips drop (10938, 248689, 12992, 12996, 248703, 2236, 248683, 2800, 2911, 6365) and the rest of the list is unchanged.

Next, in order: post the #135 replay numbers and close it (if the P&L dropped, show the user first). Then the later-80 queue: #81 in-game check at the PC, then close #81. The #39 slice 1 in-game check, then the slice 2 taint probe. Triage #134 and #136. #116 warm-pass numbers. Then date items.

- Gotchas: same as later 80, plus:
  - The first try at the rule (cut whenever the stretch spans 2+ Scans) dropped 29 of 49 rows. Today's Scans were 2 h apart, so they gave 0 window hours. Rarely-watched Markets are why the 24 h backstop exists. Don't remove it without re-running the real-data diff.
  - `brain recommend` can freeze grades into grades.toml. For before/after diffs, run on a scratchpad copy of config.toml + history.sqlite + grades.toml, with `PYTHONPATH` pointing at a `git archive HEAD brain/src` copy for "before". One recommend takes about 3 min on the real DB.
  - Review items not taken: a `NamedTuple` for `_Cheap.lows`' (Scan, unit) pairs, and merging `WhyNot.cheap_since`/`watched_since` into one optional field.

2026-10-04 (later 81): FILED #135 (core, bug, needs-triage) and #136 (later, enhancement, needs-triage) from an in-game screenshot. **#135 is the user's top priority, ahead of everything below.** The Shopping List said to buy all 3895 Lesser Magic Essence (10938) at up to 3s 33c and post at 5s 96c. The demand behind it is 32 Sale Events at about 7s 30c from Sep 27–30. The cheap wall was first seen at 13:46 today, after the last Observation Window, so #132's `since_cheap` saw 0 hours since and left the old demand whole. Nothing caps run size either. #136 is widening (or making resizable) the 915 px Recommendation frame, where Qty and Item clip.

Next, in order: grill #135 (two proposals on the issue: reverse #132's default when there's no watching since, and cap run size), then /tdd it. Then the queue below.

2026-10-04 (later 80): #39 slice 1 built, not closed: the in-game check is left, then slice 2's probe. `SearchButton.lua` is pure and has 10 specs (`state` and `liveLine`). A Search button shares the Post button's slot under the frame, and the glue is in RecommendationFrame.lua (`onSearchClick`, `buyKey`, the shared `sendSearch`/`searchResults`). Two decisions were made at the start of the session. First, a Shopping List Flip to Sell shows Post once some of it is in this Character's bags, and Search until then. Second, with no item in the bags, gear searches with `MakeItemKey(itemID, itemLevel)` and keeps only the Listings whose link gives the row's exact Item Key. A commodity (taken to be anything with maxStack > 1) searches with `MakeItemKey(itemID)`. The live line skips the player's own units and compares against the buy price floored to whole copper. Busted 304/0.

Next, in order: at the PC, the #81 in-game check (Acceptance on #81), then close #81. Then the #39 slice 1 in-game check (below), then the slice 2 taint probe (steps on the spec). Triage #134. #116 warm-pass numbers. Then date items.

- Gotchas: same as later 79, plus:
  - #39 in-game check: Search a commodity row (Wool Cloth) and a suffixed gear row. Their live lines must match Blizzard's list. The big unknown is whether `MakeItemKey(itemID, level)` with no suffix finds suffixed gear at all (the probe got 0 with the bare itemID). If it doesn't, find how the AH ItemKey's `itemSuffix` maps from our bonus IDs (dump `GetItemKeyFromItem` on a suffixed item in the bags). Also check that a stackable non-commodity doesn't exist in practice. Also check the results events' arg1: the glue now ignores results for any other itemID (arg1 is the itemID, or an item key's itemID). If neither line ever updates, look at that first.
  - Review items not taken: `refreshPost`/`createPostButton` now drive both buttons (the names are a bit off). `BUY_TABS` keys on tab titles, as the rest of the frame does. Post's automatic undercut search still doesn't wait for the throttle (it didn't before either).

2026-10-04 (later 79): Grilled #39. The spec is on the issue (comment 5984731864), relabelled ready-for-agent, and the ADR-0016 Consequences got a #39 line. No results frame of our own. The Post button's slot reads **Search** on a selected buy-side row with one Item Key (Shopping List, Prediction buys, single-item Buy Under). It searches with the full Item Key and shows a live line ("Live: 59c x73, under your 62c buy"). Slice 1 (Search + live line) is buildable now. Slice 2 (jump Blizzard's AuctionHouseFrame to the item) waits on an AQProbe taint probe: jump, then buy through Blizzard's UI, with no ADDON_ACTION_BLOCKED. The fallback is filling Blizzard's search box.

Next, in order: #81 in-game check at the PC (Acceptance list on #81; import once first), then close #81. Off the PC: /tdd #39 slice 1. At the PC: the #39 slice 2 taint probe (steps on the spec). Triage #134. #116 warm-pass numbers. Then date items.

- Gotchas: same as later 78, plus:
  - #39 slice 1 should reuse `sendSearch` and the search-results handling in RecommendationFrame.lua (Post already searches on select for its undercut line). Keep the pure logic in its own specced module like PostButton.lua. Selecting must still take no action for buy rows; only the button searches.

2026-10-04 (later 78): #81 built (b953b31), not closed: the in-game check is left. `PostButton.lua` (pure, 17 specs) gives the label, disabled reason, undercut line and the one call. The glue is in RecommendationFrame.lua: the button hangs under the frame's bottom right, shown only at a faction AH (not Neutral). `onPostClick` is the only place PostItem/PostCommodity appear, and `protected_calls_spec.lua` checks that over every file in the .toc (plain Lua can't list a folder, so a file left out of the .toc isn't checked, and it isn't loaded either). The Brain writes `postDurationHours` (config `post_duration_hours`). Character.lua exports `ns.Character.bagIds`. Busted 294/0, pytest 1011, ruff clean. CI green (run 37236239953).

Next, in order: #81 in-game check at the PC (the Acceptance list on #81; the Brain must import once first, or Post says "No post duration from the Brain yet"), then close #81. Grill #39's one open decision. Triage #134. #116 warm-pass numbers. Then date items.

- Gotchas: same as later 77, plus:
  - Review items not taken on #81: config.py accepts any `post_duration_hours` > 0, but Post only takes 2/8/24 (worth a Brain-side check). The guardrail's comment stripping also strips `--` inside strings. The search-results events aren't filtered by key (it reads its own key's results, so the result stays right). There's no timeout on "Posting...": it clears on the AH's confirm, a UI error, or the AH closing. A Sell row posts at `postAt` if it has one, otherwise `price`. The Brain never gives a Holdings Sell row a postAt.
  - Any UI_ERROR_MESSAGE while a post is pending ends the wait and shows the error. A late AUCTION_HOUSE_AUCTION_CREATED still counts the units (`lastPost`).
  - Lua shim for the Brain's real-Lua tests: copy lua_shim.py + lua.bat from an older session's scratchpad (fix the path in lua.bat) and set LUA to it.
  - Bash heredocs choke on long Python edit scripts here: write them to the scratchpad with Write.

2026-10-04 (later 77): #81 build spec written (comment on #81), relabelled ready-for-agent and retitled to Post only. The Brain never names an own Listing to pull, so Cancel moved to #134 (needs-triage, later): the Brain names Listings to pull, then the Cancel button. Spec in short: a pure, specced `PostButton.lua` (state + lowestOther), glue in RecommendationFrame.lua with the one protected call in `local function onPostClick`, the Brain writes `postDurationHours` (2/8/24 -> 1/2/3), commodity = one PostCommodity for the units in bags, gear = one unit per click, undercut line from one SendSearchQuery on select, and `protected_calls_spec.lua` as the guardrail (CancelAuction forbidden until #134).

Next, in order: #81 (/tdd, then an in-game check at the PC per its Acceptance list). Grill #39's one open decision (own results frame vs driving Blizzard's AuctionHouseFrame). Triage #134 (grill when it comes up). #116 warm-pass numbers (brain watch is running). Then date items.

- Gotchas: same as later 76, plus:
  - #81's in-game check has three unknowns written into its Acceptance: duration 3 = 24h, a PostCommodity quantity spanning stacks, and whether Forever takes copper in a post price. Each has a fallback written down.

2026-10-04 (later 76): #133 done (1a6260c, issue closed). `ContainerIds.lua` (pure, specced) works out the bag and bank container IDs. Character.lua passes in the client constants. The Beta has the Reagent Bag (container 5, 6 slots) but no `REAGENTBAG_CONTAINER` global, so the glue falls back to `Enum.BagIndex.ReagentBag`. Bank bags start after every equipped bag. Checked in game: Read 249 has 4305 x8 and 2997 x9 in `bags`. #44 batch check re-run: PASS, 4 rows for 4 crafts, quantity 1/NULL/1/1 (results on #44).

Next, in order: off the PC, write #81's build spec from its results comment, then relabel ready-for-agent. Grill #39's one open decision (own results frame vs driving Blizzard's AuctionHouseFrame). #116 warm-pass numbers (brain watch is running). Then date items.

- Gotchas: same as later 75, plus:
  - The Beta's `Enum.BagIndex` has CharacterBankTab_n = 5+n and AccountBankTab_n = 14+n (account tab = -3?). The bank read still uses BANK_CONTAINER plus bags 6..(6+NUM_BANKBAGSLOTS-1). A bank read after the #133 change hasn't been checked against bank tabs yet. If bank items go missing, look there first.
  - A long `/dump` line breaks when pasted into chat. Use short lines.

2026-10-04 (later 75): PC session. Ran every parked probe from later 62 item 2. Results on the issues:
- #81 Post/Cancel: an addon Button's OnClick can PostItem, PostCommodity and CancelAuction, one call each, no Confirm step. Timers and `/run` are blocked (`/run` is ForceTaint_Strong). Duration 1 = 2h. A commodity's AUCTION_CANCELED arg isn't the auctionID. Results comment on #81; the build spec isn't written yet.
- #44 slice 1: one row per craft and recipe_id match PASS. quantity NULL on every row FAIL, because outputs land in the Reagent Bag (container 5), which `Character.lua` `bagIds()` never reads. Filed #133 (needs-triage). It also hides Reagent Bag contents from Holdings, held, uses and Lots.
- #54 Loot Alert: the text and chat line show, and Disenchant loot doesn't alert. PASS. The sound wasn't confirmed.
- #39 search probe: SendSearchQuery works from click or timer, but Blizzard's frame doesn't follow. Gear needs the full Item Key (GetItemKeyFromItem). A search during a Scan is fine. Results comment on #39.

Next, in order: #133 (triage then /tdd, small; the PC is needed to verify, then re-run the #44 batch check). Off the PC: write #81's build spec from its results comment, then relabel ready-for-agent. Grill #39's one open decision (own results frame vs driving Blizzard's AuctionHouseFrame). #116 warm-pass numbers (brain watch is running again). Then date items.

- Gotchas: same as later 74, plus:
  - `brain watch` loads config.toml once at start. For a config-driven in-game test, stop it, edit, run `python -m brain.cli import`, test, restore, import again, then restart `scripts/brain-watch.bat`.
  - The AQProbe addon (outside the repo, in the game's AddOns folder, enabled on Kash-Patel) is now the read-only #39 search probe. The #81 Post/Cancel buttons were removed after one cancelled a real Listing. The original spike #1 file is gone with the session scratchpad. Disable AQProbe when you no longer need it.
  - WoW screenshots are in `Z:\Battle.net\World of Warcraft\_classic_beta_\Screenshots`, so "screenshot" is enough for the agent to read the newest one.

2026-10-03 (later 74): #131 done (e2d088b, CI green, issue closed). `brain watch` and `brain import` log an `Import stages:` line after an import: SavedVariables, Archive, history ingest, Fair Values, Decision Engine, Recommendations.lua (plus `pool pull` first and `pool push ... after` when the pool is on), and the Scans in the history. `brain/src/brain/timings.py` `Timings` is passed down and filled (run_import -> import_file -> archive writes; `FairValueCache.timings` set for the pass by `_write_recommendations`). A stage nested in another counts only toward itself, so "history ingest" excludes parsing and Archive writes, and "Decision Engine" excludes Fair Values. Fair Values only counts cache misses, so warm `brain watch` passes look cheaper than a one-shot import. First real number, one-shot (cold cache) on 56 Scans: SavedVariables 0.3s, Fair Values 20.7s, Decision Engine 63.5s, everything else ~0.

Next, in order: PC items as in later 62 item 2, then date items. Off the PC: #116 now has numbers to work from. Run `brain watch` for a few Scans to get warm-pass stage lines, post the cold and warm numbers on #116, then re-triage it (needs-info -> grill).

- Gotchas: same as later 70. LME check at 19:40: #132's cut still hasn't landed. Still 0.8 watched hours since the 20c Listings went up (15:46), against 12.9 before, so 32/12.9*0.8 = 2.0 expected < 3 and `since_cheap` leaves it whole. It needs Scans no more than 1 h apart. why-not only shows "since cheaper Listings went up" on a failing Sale Events Check, so a made-the-list row never shows the cut: probe `SellRate.since_cheap` with a monkeypatch to see it. `brain watch` wasn't running at handoff. Deviations from the #131 brief, both noted in review: Timings is an out-param, not a return value, and the count is history Scans, not Archive files.

2026-10-03 (later 73): #132 done (8f7c62b), ADR-0028. Flip to Sell, Hold buy Max Loss and why-not cut the Sale Events and Observation Window hours before the earliest other-player Listing under the post price was first seen, once the raw rate before expects `flip_min_sale_events` since. why-not's Sale Events line says "since cheaper Listings went up <time>". `SellRate.sale_prices` is now (price, units, seen_at) and SellRate carries `windows`.

Next, in order: PC items as in later 62 item 2, then date items. Off the PC: #131 (ready-for-agent, /tdd).

- Gotchas: same as later 70. On the real data at 10-03 18:29, LME still made the list: only 0.83 Observation Window hours since the 20c Listings showed up (15:46), expecting 2.07 of the 3 Sale Events. It needs about 1.2 watched hours (Scans no more than 1 h apart) before the cut lands, so check after the next scans. Review notes left as is: the cutoff counts Listings under the post price, so a partly-taken Listing doesn't set it. The cut is only named on a Sale Events failure, not Room. No test pins Flip to Craft or Buy Under unchanged, since they never pass a cutoff.

2026-10-03 (later 72): #132 grilled, brief on the issue, ready-for-agent. A buy that removes the cheap run and posts above it (Flip to Sell, Hold buy Max Loss, `_why_not`) drops Sale Events and Observation Window hours from before the run's earliest first_seen. This only happens once the old rate (raw, no prior) expects at least `flip_min_sale_events` events in the hours since then. Snipes are unaffected. Not Flip to Craft, Buy Under, held units or Beta. ADR-0028 is to be written with it.

Next, in order: #132 (/tdd, it makes the current Shopping List misleading), then PC items as in later 62 item 2, then date items. Off the PC: #131 (ready-for-agent, /tdd).

- Gotchas: same as later 70. `SellRate.sale_prices` drops `SaleEvent.seen_at`, so #132 has to carry event times and split window hours at the cutoff.

2026-10-03 (later 71): Filed #132 (needs-triage): Flips to Sell count Sale Events from before a price drop as demand at the post price, so after a crash the Brain suggests buying the whole cheap wall and reposting at the old price (4807 LME at 47c, post 3.21s, "1.1 days"). Since the cheap Listings showed up, 0 units sold at the post price for 10938, 279965 or 248706. Proposed rule: only Sale Events after the cheap Listings the Flip buys first showed up count. Evidence and open questions are on the issue.

Next, in order: grill #132 (it makes the current Shopping List misleading), then PC items as in later 62 item 2, then date items. Off the PC: #131 (ready-for-agent, /tdd).

- Gotchas: same as later 70.

2026-10-03 (later 70): #114 done (ce082e7, CI green, issue closed). Flips to Craft are graded: `Lot.lineage` records the Lots a craft used up, and `lots_with_crafts` also returns the uncosted crafts. `craft_flips` in flips.py matches reagent Purchases to the frozen `[shown_crafts]` rows and grades through lineage. Grades are frozen in `[craft_flips]`, keyed `<recipe>@<Scan>`, and `FlipGrade` gained `crafted_after`. Not-gradable reasons are "uncosted reagents" and "not crafted by the horizon". `brain flips` has its own section for them, and `brain recommend` has a separate record line. ADR-0027.

Next, in order: PC items as in later 62 item 2, then date items. Off the PC: #131 (ready-for-agent: per-stage timings in brain watch, /tdd).

- Gotchas: same as later 68. The first `brain flips` or `brain recommend` after this reworks any old Scan where a named Purchase matched no Flip to Sell row, which may be slow once. Left out on purpose: a Purchase named only through a Disenchant group's Buy Under never triggers that backfill, and output under a Prediction shows as "not crafted".

2026-10-03 (later 69): #114 grilled, now ready-for-agent (brief on the issue). Flips to Craft are anchored on reagent Purchases matched to the last Scan's Flip to Craft row, and traced through craft Lot lineage (new in lots.py) to the output Lots of that row's recipe. Uncosted-reagent crafts are skipped and counted (#130 is the later fix). Rows are frozen in a new grades.toml section, and the backfill reworks only Scans with a named Purchase that matched no Flip to Sell row. Triage: #112 narrowed to consumables, needs-info (For Use count). #113 needs-info. #115 needs-info (the stale-Brain hint already exists, #104). #116 needs-info, with step 1 split out as #131 (ready-for-agent: per-stage timings in brain watch).

Next, in order: PC items as in later 62 item 2, then date items. Off the PC: #114 (/tdd, big: lots.py lineage first, then freezing, then grading/reporting; split into slices if it runs long), then #131.

- Gotchas: same as later 68. `addon/AzerothQuant/Recommendations.lua` shows as modified in git: that's the Brain's generated output, so don't commit it.

2026-10-03 (later 68): #127 done (6656323, CI green, issue closed). The Brain sends `X-Scan-Realm` and `X-Scan-Faction` as percent-encoded UTF-8 (`urllib.parse.quote(safe="")`), and the Worker decodes them with `decodeURIComponent` before validating them. A malformed escape is a 400. The Worker is redeployed (version fd7388ef). Test helper: `upload` encodes like the Brain, and `uploadRaw` sends headers as given.

Next, in order: PC items as in later 62 item 2, then date items. Off the PC: grill #114 (needs-info, Grade Flips to Craft), then triage #112, #113, #115, #116.

- Gotchas: same as later 62. The `brain rebuild` from later 67 (it cleans up own flags that already spread) still hasn't been run. A space now goes on the wire as `%20`. The Worker decodes an old unencoded header to itself, so nothing already stored moves.

2026-10-03 (later 67): #125 done (61880e1). Listing matching keeps own in the type key and charges 1 per own row that continues a not-own Listing; units sold are weighted by len(current group) + 1, so the tiebreak never changes the pair count or units sold. A Listing only turns own when no own one is left to pair with (#119 unchanged). ADR-0002 amendment updated.

Next, in order: PC items as in later 62 item 2, then #127 (/tdd; Brain + Worker in one commit, then `wrangler deploy`), then date items.

- Gotchas: same as later 62. Run `brain rebuild` (then restart `brain watch`) to clean up own flags that had already spread; not done this session. #127 needs a Worker redeploy after the commit (wrangler env vars in later 62).

2026-10-03 (later 66): Triaged #14, #19, #10, #82, #125, #126, #127. #14, #19, #10 unchanged (ready-for-human, waiting on data or the PC). #82 stays needs-info; added ForeverForge Auction (CurseForge addon, walord3) as another price-only lead. #125 and #127 are ready-for-agent (briefs on the issues). #126 closed wontfix: only Scans use the server clock, Reads keep the PC clock the Brain shares (ADR-0026 line, `.out-of-scope/server-clock-for-all-addon-stamps.md`).

Next, in order: PC items as in later 62 item 2, then #125 (/tdd), then #127 (/tdd; Brain + Worker in one commit, then `wrangler deploy`), then date items.

- Gotchas: same as later 62. #127 needs a Worker redeploy after the commit (wrangler env vars in later 62). #125: after it lands, a `brain rebuild` cleans up own flags that already spread.

2026-10-02 (later 65): #128 and #129 triaged and done (fc73a1a). `pool_url` alone now loads (pool off until `pool_key` is set too), so a fresh admin can run `brain pool key add`. Pooled Scans no longer write `vendor_price`/`item_info` (option B: only own Scans and Character Reads do), so a rollback has nothing to undo there; `strip_scan` is unchanged. Ran `brain rebuild` (52 Scans, 0 rejected; 0 vendor/item rows from Pooled Scans) and restarted `brain watch`.

Next, in order: PC items as in later 62 item 2, then #14, #19, #10, #82, #125, #126, #127 (needs-triage), then date items.

- Gotchas: same as later 62.

2026-10-02 (later 64): #61 done (8b936ca). A Flip to Craft row's `post_at` is its output's post price, None when no unit beats vendoring (gated on `made.selling`: `_outlet` keeps a `post_at` when held units take all the room, the output is bound, or the sale nets under the Vendor Price). The Flips to Craft tab's Post at cell needed no Addon change. Restart `brain watch` so it writes the new field, then /reload.

Next, in order: PC items as in later 62 item 2, then #128 and #129 (needs-triage, small), then #14, #19, #10, #82, #125, #126, #127 (needs-triage).

- Gotchas: same as later 62. `CraftOutput.post_at` (the replay's) still carries a price when `selling` is 0; the replay ignores it there, so it's harmless.

2026-09-30 (later 63): Started `brain watch` (scripts/brain-watch.bat, own console window titled "brain watch"). It syncs the pool, so A's 46 un-pushed Scans drain one per 10 min (about 8 h). Restart it after a reboot.

Next, in order: same as later 62 from item 2 on (PC items, then #61, #128, #129, the needs-triage list, date items).

- Gotchas: same as later 62.

2026-09-30 (later 62): #124 done (3ae5186), so the Scan Pool (#117) is closed. The Worker is live at https://azerothquant-pool.zachmanson9.workers.dev (account 605568062ea9d2f286c97d54929d5432, D1 `azerothquant-pool`, R2 `azerothquant-pool-scans` with a 60-day lifecycle rule, billing alert at 8 GB). `brain/config.toml` has `pool_url`, `pool_key` (member `zach`) and `pool_admin_secret`. Two-member check passed: both directions, re-match, and revoke (`member-b`, `member-b2` are revoked test keys). After the rollback, A's history matched a clean rebuild except vendor_price/item_info seen_at (#129). Two client bugs fixed: a `User-Agent` (Cloudflare 403s Python-urllib, error 1010), and the pool's TLS context now trusts only the Windows ROOT store (an expired ISRG Root X2 cross-sign cached in CurrentUser\CA broke Python's TLS). Re-match timing is on #116. Also ran the pending `brain rebuild` (4m40s, 47 Scans, 0 rejected). A pre-pool backup of the history is at `Z:\vibing\aq-backups\history.pre-pool-backup.sqlite`.

Next, in order (grill first where not ready-for-agent):
1. Start `brain watch` (scripts/brain-watch.bat): it wasn't running, and it now syncs the pool. A's 46 un-pushed Scans drain one per 10 min.
2. PC items: `brain replay` (#80, before Oct 21), #81 Post/Cancel probe, the #85 leftovers (#54 Loot Alert, #50, #33/#75, #78 Copper Bar deposit, #44 craft probe, #120 GetServerTime probe; #39 and #97 slice 2 need probe code first), the For Use line in `brain flips` (#112).
3. #61 (ready-for-agent, small: /tdd). #128 and #129 (needs-triage, small). Then #14, #19, #10, #82, #125, #126, #127 (needs-triage).
4. Date items unchanged from later 54.

- Gotchas: same as later 60, plus:
  - Node isn't on Git Bash PATH: prefix `PATH="/c/Program Files/nodejs:$PATH"`. wrangler needs `CLOUDFLARE_API_TOKEN="$(tr -d ' 

' < pool/.cloudflare-token)"` (gitignored; `wrangler login` didn't hand back to this shell) and `CLOUDFLARE_ACCOUNT_ID=605568062ea9d2f286c97d54929d5432`.
  - Each key uploads one Scan per Market per 10 min, so `brain pool push` showing `pushed 0` right after a push is the rate limit, not a failure.
  - A test Scan copied with a shifted requestedAt makes many new Listings (short time-left buckets can't survive the gap). That's correct matching, not a pool bug.

2026-09-30 (later 61): Grilled #61, now ready-for-agent (small). The Flips to Craft tab's Post at cell shows `made.post_at` (blank when all units are Vendored). A partly sold row shows just the price, because the split is in the Craft Chain panel (#77). It's the same before-cut price as #59. Spec is in the issue comment.

Next, in order (grill first where not ready-for-agent):
1. Scan Pool (#117): #124 (ready-for-human: deploy the Worker, make two keys with `brain pool key add`, check both directions and a revoke).
2. #61 (ready-for-agent, small: /tdd). Then #14, #19, #10, #82, #125, #126, #127 (needs-triage). #81 is ready-for-human: do it at the PC.
3. PC and date items are unchanged from later 55 (including the `brain rebuild` once at the PC), plus the #120 probe on #85.

- Gotchas: same as later 60.

2026-09-30 (later 60): Built #123 (5d423e2). `brain pool key add <name>` prints a new member key and `brain pool key revoke <name>` revokes one, through `PoolAdmin` in `brain/src/brain/pool.py` (shares the module-level `_request` with `HttpPool`). New config `pool_admin_secret` (the Worker's ADMIN_SECRET). The key commands exit 1 with a clear message without `pool_url` and `pool_admin_secret`, and log the Worker's reason on 409/404. Added a test that rolling back an unknown pool ID is a no-op (`FakePool` now lists rollbacks of IDs it never had). The Scan Pool code is done: #117's remaining sub-issue is #124, ready-for-human at the PC.

Next, in order (grill first where not ready-for-agent):
1. Scan Pool (#117): #124 (ready-for-human: deploy the Worker, make two keys with `brain pool key add`, check both directions and a revoke).
2. #61 (needs-info: grill), #14, #19, #10, #82, #125, #126, #127 (needs-triage). #81 is ready-for-human: do it at the PC.
3. PC and date items are unchanged from later 55 (including the `brain rebuild` once at the PC), plus the #120 probe on #85.

- Gotchas: same as later 59, plus:
  - The pool admin needs `pool_key` in the config too: `pool_url` without `pool_key` is still a config error (ADR-0026), even for `brain pool key`.
  - `addon/AzerothQuant/Recommendations.lua` still has the big uncommitted edit. Still left out of commits: ask the user about it.

2026-09-30 (later 59): Built #122 (6252339, CI fix 182b306). The Brain syncs with the Scan Pool: `brain/src/brain/pool.py` (strip_scan, the `Pool` protocol, `HttpPool` on stdlib urllib), `pool_sync.py` (push, pull, `PoolSyncer` for `brain watch`), `brain pool push` / `brain pool pull [--since]`, and config `pool_url`, `pool_key`, `pool_sync_minutes`, `pool_backfill_days`, `pool_min_completeness`, `pool_completeness_window`. Rollback handling is built too (the #117 sync step lists it), so #123 is re-scoped (comment on #123): the key commands, `pool_admin_secret`, and a test that rolling back an unknown ID is a no-op. Decisions are in ADR-0026 Consequences and the ADR-0005 amendment:
  - `lastImported` counts only own Scans.
  - `brain rebuild` copies the own Scans' `pool_id`s and the cursor from the old history.
  - An own Scan beats a Pooled one from the same second.
  - Push goes newest first.
  - A rollback past 48 h stays in history until `brain rebuild`.
  - Setting only one of `pool_url` and `pool_key` is a config error.
  The review filed #127 (needs-triage): non-ASCII realm names in `X-Scan-*` headers.

Next, in order (grill first where not ready-for-agent):
1. Scan Pool (#117): #123 (key commands, re-scoped) is next. Then #124 (ready-for-human: deploy the Worker, hand out keys).
2. #61 (needs-info: grill), #14, #19, #10, #82, #125, #126, #127 (needs-triage). #81 is ready-for-human: do it at the PC.
3. PC and date items are unchanged from later 55 (including the `brain rebuild` once at the PC), plus the #120 probe on #85.

- Gotchas: same as later 58, plus:
  - Test helpers shared between test files go in `brain/tests/<name>.py` and are imported bare (`from fake_pool import FakePool`). CI runs bare `pytest`, so `from tests.x import` fails there even though `python -m pytest` passes locally. Check with `python -P -m pytest`.
  - The Worker sends the list `cursor` as a string. `HttpPool` casts it; the stub Worker in `test_pool.py` sends a string on purpose.
  - A periodic pull in `brain watch` doesn't rewrite Recommendations.lua. Pooled data reaches the Addon at the next own import, which pulls first anyway. `brain pool pull` does rewrite it.
  - `brain watch` logs the pool counts line only when something happened.
  - `addon/AzerothQuant/Recommendations.lua` still has the big uncommitted edit. Still left out of commits: ask the user about it.

2026-09-30 (later 58): Built #121 (9846a50). The Scan Pool Worker is in `pool/` (TypeScript, Cloudflare Worker, D1 for keys and the index, R2 for bodies), with 35 vitest tests under the Workers pool against the real endpoints and a new `pool` CI job (green). `pool/README.md` has the API table, local dev, secrets and `wrangler deploy`. Decisions made this session: the Scan header (era, realm, faction, requestedAt) goes in `X-Scan-*` HTTP headers, so the Worker never gunzips at all. The cursor is the seq of an ordered `events` log (add/rollback), paged by `limit` (max 1000) with a `more` flag. Revoke also deletes the key's R2 bodies. Keys are stored hashed.

Next, in order (grill first where not ready-for-agent):
1. Scan Pool (#117): #122 (Brain sync) is next and can start now. Then #123, then #124 (ready-for-human).
2. #61 (needs-info: grill), #14, #19, #10, #82, #125, #126 (needs-triage). #81 is ready-for-human: do it at the PC.
3. PC and date items are unchanged from later 55 (including the `brain rebuild` once at the PC), plus the #120 probe on #85.

- Gotchas: same as later 56, minus the node one, plus these, which the #121 review flagged for #122:
  - Node 24 is now installed (winget) at `C:\Program Files\nodejs`. A shell started before the install doesn't have it on PATH, so prepend it. npm 11.17 blocks install scripts: `pool/package.json` `allowScripts` approves esbuild and workerd by exact version, so re-approve with `npm approve-scripts` after bumping them. workerd's newest compat date lags; `compatibility_date` is 2026-08-15.
  - The rate limit is wall clock (spec-literal: one upload per key per Market per 10 min), so an offline backlog drains one Scan per Market per 10 minutes. The Brain must treat 429 as "retry next cycle", not as an error.
  - A duplicate upload (same Market + requestedAt) returns another member's pool ID. If that member is revoked, the ID shows up in `rolledBack`. A rollback must never delete an own (`source=own`) Scan; just clear its `pool_id` so it re-pushes.
  - There's no date filter on `GET /scans`. The 30-day backfill pages from cursor 0 (omit `since`) and filters on `requestedAt` in the Brain. Index rows are small; add `since=<time>` to the Worker later if it ever matters.
  - `addon/AzerothQuant/Recommendations.lua` still has a big uncommitted edit that isn't from these sessions. Leave it out of commits and ask the user about it.

2026-09-30 (later 57): Built #120 (83e8643). Every `time()` in Scanner.lua is now `GetServerTime()`: the Scan stamps (`requestedAt`, `firstUpdateAt`, `readAt`, `savedAt` via `Nudge.stampSaved`) and the cooldown and Nudge checks that compare against them, so they stay on one clock. No busted spec for Scanner.lua; checked by reading the diff, and the addon specs pass (264). Probe line added to #85 (Auction House section). The review filed #126 (needs-triage): Reads, Purchase marks and the rest of the Addon still use `time()`, and the Brain compares some of those with Scan `requestedAt`.

Next, in order (grill first where not ready-for-agent):
1. Scan Pool (#117): #121 (Worker, TypeScript, in `pool/`, with a new `pool` CI job) is next. #122 (Brain sync) needs #121. Then #123, then #124 (ready-for-human).
2. #61 (needs-info: grill), #14, #19, #10, #82, #125, #126 (needs-triage). #81 is ready-for-human: do it at the PC.
3. PC and date items are unchanged from later 55 (including the `brain rebuild` once at the PC), plus the #120 probe on #85.

- Gotchas: same as later 56. `addon/AzerothQuant/Recommendations.lua` still has a big uncommitted edit that isn't from these sessions. Leave it out of commits and ask the user about it. #121 is the first TypeScript in the repo: check for node/npm and wrangler on this PC first.

2026-09-30 (later 56): Built #119 (75badf9). Listings match by Item Key and unit buyout only (`matching._identity`). A matched Listing's own is OR'ed in `_insert_scan`, and a new `turned_own` table (one row per Listing, keyed by listing_id) records the Scan where it turned own. `_rewind` sets own back to 0 for Listings that turned own in the tail. `_SEEN_IN_A_SCAN` lists the per-(Listing, Scan) tables that a re-match deletes. Repost pairing (`observation._pair_reposts`) no longer groups by own. Tests: own -> not own -> own stays one own Listing, and the reverse turning (test_history). A Repost pairs regardless of own (test_observation). A re-match takes own back from a Listing it no longer matches to an own row, and the shuffled-order property has own rows, some hidden like a Pooled Scan (test_rematch). With the own restore disabled, 7 of 20 seeds fail. Docs: ADR-0002 amendment, ADR-0026 (re-match restores own), CONTEXT Repost.

Next, in order (grill first where not ready-for-agent):
1. Scan Pool (#117): #120 (GetServerTime) and #121 (Worker, TypeScript) are next, in either order. #122 (Brain sync) needs #121. Then #123, then #124 (ready-for-human).
2. #61 (needs-info: grill), #14, #19, #10, #82, #125 (needs-triage, from the #119 review: own can spread to someone else's identical Listing). #81 is ready-for-human: do it at the PC.
3. PC and date items are unchanged from later 55 below (including the `brain rebuild` once at the PC).

- Gotchas: same as later 55, minus the #119 one. `addon/AzerothQuant/Recommendations.lua` has a big uncommitted edit that isn't from these sessions. Leave it out of commits and ask the user about it.

2026-09-30 (later 55): Built #118 (4a8dd0d). A Scan older than its Market's latest no longer gets rejected. `_import_scan` reads the Market's archived tail (`Archive.market_scans`, from the late Scan on) first. It then `_rewind`s the Market: Listings first seen in the tail are deleted, and a Listing spanning the tail gets back its last Scan, quantity (plus its tail Partial Sales) and time-left. The time-left comes from a new `time_left_drop` table, one row per bucket drop. Then every tail Scan is re-inserted in time order. It gets a `scans_waiting_for_rebuild` warning instead when the Scan is more than `pool_rematch_hours` (48, config) older than the latest, when there's no Archive, or when a tail file can't be read. The report has `scans_rematched`, and `scans_out_of_order` is gone. Tests: `tests/test_rematch.py` (arrival order == time order, including 20 shuffled seeds; the cap; other Markets untouched; an unreadable tail file). ADR-0026 and ADR-0005 wording updated.

Next, in order (grill first where not ready-for-agent):
1. Scan Pool (#117): #119 (own out of the match key) is next. #120 (GetServerTime) and #121 (Worker, TypeScript) can start any time. #122 (Brain sync) needs #119 and #121. Then #123, then #124 (ready-for-human).
2. #61 (needs-info: grill), #14, #19, #10, #82. #81 is ready-for-human: do it at the PC.
3. PC and date items are unchanged from later 54 below. **At the PC, run `brain rebuild` once (stop watch first).** Histories from before #118 have no `time_left_drop` rows, so a re-match within 48 h of upgrading could restore a lowered bucket and make fake Disappearances.

- Gotchas: same as later 54, plus:
  - #119: once `own` is OR'ed into a matched Listing, `_rewind` must also restore `own` as of the Scan before the tail. Record own flips the way `time_left_drop` records bucket drops, and extend the shuffled-order property test with own rows.
  - `git stash` / `stash pop` on this Z: drive empties the git index (every file shows as staged-deleted plus untracked). `git reset -q` restores it without touching files. Use `git worktree add` to run HEAD instead.
  - From review, not taken: `Archive.market_scans` takes era/realm/faction, not `Market` (Market lives in history.py, which imports archive, so that would be circular). `_rewind` builds its SQL from fragments. The test helpers are copied from test_history.py. A tail Scan that was archived but never imported is replayed without counting in the report.

2026-09-30 (later 54): Built #44 slice 2 (92cf42e), so #44 is done. `lots()` takes `craft_results` (`LotCraftResult`, named that because CONTEXT's **Craft** is the Action) next to Sold Outcomes and folds. A craft uses up reagent units from open non-Prediction Lots, oldest first. It opens an output Lot (`Lot.crafted`) only when every reagent unit is costed, from a Lot or a Merchant Cost, and never for an Item Key under a standing Prediction. Each craft snapshots its recipe at import from the same Read's `professions` into `craft` (`output_item_id`, `quantity_min`) and `craft_reagent`. So no-output recipes use up reagents and never become Known Recipes, and Known Recipes are unchanged. `recommend.lot_craft_results` resolves them with Merchant Costs as of the Read that carried the craft, because the Addon records a session's Merchant Costs at logout on that same Read. It's wired into `market_lots` (Paid/ROI, Flip grading) and replay `_realized`. `brain flips` prints `Crafts recorded: N (M with a costed output)`. The docs are done: CONTEXT Lot/Paid, the ADR-0007 amendment, and ADR-0023 pointing to #114.

Next, in order (grill first where not ready-for-agent):
1. Scan Pool (#117) is the priority now (user's call, 2026-09-30), though its tickets are still labeled `later`. Order: #118 (tail re-match) -> #119 (own out of the match key). #120 (GetServerTime) and #121 (Worker, TypeScript) can start any time. #122 (Brain sync) needs #118, #119 and #121. Then #123 (rollback and key commands), then #124 (deploy, ready-for-human). The spec comment is on #117.
2. #61 (needs-info: grill), #14, #19, #10, #82. #81 is ready-for-human: do it at the PC.
3. PC and date items are unchanged from later 51 and 50 below, plus the #44 craft probe on #85. Once real crafts are in, check the `Crafts recorded` line: M well below N means the capture or recipe snapshot has gaps.

- Gotchas: same as later 50. From the #44 review, not taken:
  - The replay's `_realized` passes no Predictions to `lots()`, so there crafts can use up units bought under a Prediction and open output Lots under one. Sales already ignored Predictions there, so this isn't new.
  - Crafts now move Flip to Sell grades through `market_lots`. `_grade` still counts a crafted-away Flip unit as held at exit value. That's for #114.
  - A craft whose recipe isn't readable on its Read is stored with no output or reagents and gives no warning. It shows only as uncosted in the crafts line.
  - Also not taken: `run_flips`'s (recorded, costed) tuple, and the repeated market filter in `history.crafts()`.

2026-09-30 (later 53): Built #44 slice 1 (c2e3c2e). `CraftCapture.lua` (plain Lua, spec/craft_capture_spec.lua) records a Craft Result for each UNIT_SPELLCAST_SUCCEEDED whose spell ID is a recipeID in `Professions.latest()`, the live table of this session's profession-window reads (Known Recipes aren't kept across sessions; the user chose this over persisting them). A Result is `{ recipeID, at, quantity? }`. The quantity is how many more of `outputItemID` the bags hold than at the cast start, or than at success for instant crafts. It waits up to 5 s of bag reads. With no count, or over `quantityMax`, the Brain uses the recipe's minimum. Each new cast settles the one before it (batches, instant crafts in a row). No-output recipes are recorded at once with no quantity. The glue in Character.lua reads the bags only for Known Recipe spells. The Results ride on the Character Read as `crafts` into a `craft` table (`at, recipe_id, quantity NULL`). `history.crafts(conn, market)` returns `CraftResult`s oldest first, by the carrying read's faction. CONTEXT **Craft Result** is added (moved up from slice 2). The probe and a variable-yield addendum are on #85. From review, not taken: the `craft`/`crafts` names (the spec asked for them), CharacterRead.build's 8 positional args, and the 6th copy of `itemID(link)` in the Addon.

Next, in order (grill first where not ready-for-agent):
1. #44 slice 2 (Lots, the `brain flips` "Crafts recorded" line, the Lot/Paid docs, the ADR-0007 amendment, the ADR-0023 line pointing to #114; CONTEXT Craft Result already exists). Then #61, #14, #19, #10, #82. #81 is ready-for-human: do it at the PC.
2. #117 tickets, all `later`, as in later 52 below.
3. PC and date items are unchanged from later 51 and 50 below, plus the #44 craft probe on #85.

- Gotchas: same as later 50. Slice 2: the Brain drops Known Recipes that make no item at import (`_known_recipe` in history.py), so it can't see the reagents of a no-output craft (Enchanting). The spec's "no-output crafts close their reagent Lots" needs those kept, maybe as a new flag, without them becoming Craft Actions. Within a same-recipe batch, output counts can shift one craft down the line if the output lags. Totals stay right, so the Lots are fine.

2026-09-30 (later 52): Grilled #117 (Scan Pool). It's now ready-for-agent (still `later`), with the spec comment on the issue and tickets #118-#124 as sub-issues with native blocking. The pool holds stripped raw Scans (no character, own, names, or itemString level/spec) and each Brain matches them itself. Late Scans re-match the Market's tail, and ones over 48 h wait for `brain rebuild`. `own` leaves the match key, and once own a Listing stays own. The Addon switches to `GetServerTime()`. Hosting is Cloudflare R2 + a TypeScript Worker in `pool/`: member keys, rate limit, revoke rolls back. Pooled Scans below 80% of the Market's median Listing count are rejected. Off by default. Docs: ADR-0026, amendments to ADR-0002 and ADR-0005, and CONTEXT **Scan Pool**, **Pooled Scan** and **Listing**. An outside-data check found no Scan-level Forever source (BBB, AHledger and TheWoWDB publish aggregates only), and I posted it on #82 to widen that issue into a price prior and sanity alarm.

Next, in order (grill first where not ready-for-agent):
1. #44 slice 1 (ready-for-agent, medium), then slice 2. Then #61, #14, #19, #10, #82. #81 is ready-for-human: do it at the PC.
2. #117 tickets, all `later`: #118 (tail re-match; useful on its own, since my own late Scans stop being rejected) -> #119 (own out of the match key). #120 (GetServerTime) and #121 (Worker, TypeScript) can start any time. #122 (Brain sync) needs #118, #119 and #121. Then #123 (rollback and key commands), then #124 (deploy, ready-for-human).
3. PC and date items are unchanged from later 51 and 50 below.

- Gotchas: same as later 50. #121 brings the first TypeScript into the repo and needs Node plus wrangler on this PC. The #118 re-match must give exactly a time-order import (property test).

2026-09-30 (later 51): PC check pass. PASS: #97 slice 1 Bought mark, #89 tab layout (0 Disenchant rows, expected), #38 Holdings location lines, #49 Craft Note/Use lines. Not exercised: #50 (nothing AH-bought held), #33/#75 (no chained or blocked Craft row), #78 deposit (no Copper Bar), #54 Loot Alert (parked; setup to force it is on #85), #39 and #97 slice 2 probes (need probe code). `brain recommend` took ~36s, not 5 min. Scans had stopped importing because `brain watch` wasn't running: `scripts/brain-watch.bat` now starts it from the Windows Startup folder (dev PC only). Filed #115 for other users (installer/tray app, plus an in-game "Brain not running" hint).

2026-09-30 (later 50): Grilled #44. It's now ready-for-agent (still `later`), with a two-slice spec on the issue. The Addon records a Craft Result per craft (UNIT_SPELLCAST_SUCCEEDED where spell ID matches a stored Known Recipe, output count from a bag diff like DisenchantCapture, falling back to the recipe's min). They ride on Character Reads as `crafts` into a `craft` table (slice 1). Slice 2: every craft closes reagent units in `lots()`, oldest open Lot first, next to Sold Outcomes. It opens an output Lot only when every reagent unit is costed (Lot or Merchant Cost). Prediction Lots are untouched. `brain flips` gets a `Crafts recorded` line. Docs: CONTEXT Craft Result, Lot and Paid, an ADR-0007 amendment, and ADR-0023's #44 line pointing to #114. Grading Flips to Craft is the new #114 (needs-info, later). The spell ID == recipeID and batch-craft probe still needs adding to #85 when slice 1 is built.

Next, in order (grill first where not ready-for-agent):
1. #44 slice 1 (ready-for-agent, medium: Addon CraftCapture + specs, glue, Character Read field, Brain table, #85 probe), then slice 2 (Lots, count line, docs). Then #61, #14, #19, #10, #82. #81 is ready-for-human: do it at the PC.
2. When at the PC: remaining #85 checks: #54 Loot Alert (incl. autoloot off), #50 once something AH-bought is held, #33/#75 when a chained/blocked Craft row shows, #78 Copper Bar deposit, `brain rebuild` (#78, stop watch first), `brain replay` (#80, before Oct 21), #39 throttle probe and #97 slice 2 buy-event probe (write probe code first), #44 craft probe once slice 1 is in. Check the For Use count line in `brain flips` (#112). Then grill #39 using the probe results.
3. On dates: Nov 4, #91's list. ~Nov 6: run `brain recommend --beta-ratios` for #91's Item Keys, and set `beta_sell_rate_weight = 0.5` if they're close to 1. Nov 18: look back and close #110.

- Gotchas: The `brain` script isn't on Git Bash PATH: use `python -m brain.cli <cmd>` from `brain/`. The CLI writes the addon's Recommendations.lua on `import`, not `recommend`. `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. Don't use `git stash` on this Z: drive. This PC has no `lua` binary. To run the Brain's real-Lua tests, set `LUA` to a .bat that runs `@python lua_shim.py %*`, where lua_shim.py runs `-e <script>` on a `lupa.lua51` runtime with `print` replaced by one that writes tab-joined `tostring`s to stdout (about 10 lines). `python ../scripts/busted.py` (from `addon/`) runs the addon specs. `ruff` isn't on PATH, so use `python -m ruff`. Several source files are CRLF: Python edit scripts must normalise line endings before matching multi-line strings. Write them to the scratchpad with the Write tool (Bash heredocs mangle backslashes).

2026-09-30 (later 49): Built #54 (50a7f1f, closes it). `recommend_market` values every Item Key in the Scan with `_way_out` against `valuer.after({}, {})` (nothing held) and `_nothing_held` Sources (now shared with `_buy_unders`), keeping those at or over max(`loot_alert_share` x gold, `loot_alert_floor`) as `MarketRecommendations.loot_alert` (`LootAlert(threshold, items={key: LootValue(value, way)})`). `loot_alert_floor` is set in gold and stored as `loot_alert_floor_copper`. Reworks and the replay pass `loot_alert=False` (items skipped: it cost ~15s of a 287s `recommend` run on the real History). `lootAlert` goes into Recommendations.lua per Market. Addon: plain-Lua `LootAlert.forMessage` (spec/loot_alert_spec.lua), glue in Character.lua (CHAT_MSG_LOOT, raid warning, sound, `print`). The Disenchant skip is `DisenchantCapture:isDisenchantLoot`: true while the Disenchant's loot window is open or within 5s of LOOT_CLOSED (`pending` clears too early to use). The #85 note has an autoloot-off check. Review items I didn't take: moving the glue out of Character.lua into its own file.

Next, in order (grill first where not ready-for-agent):
1. #44 (needs-info, later: grill), then #61, #14, #19, #10, #82. #81 is ready-for-human: do it at the PC.
2. When at the PC: the first `brain recommend` after #55 works out every Scan before a Purchase, so expect it to be slow once (about 5 minutes on 2026-09-30's History). Check that the For Use count line in `brain flips` looks sane; if it's big, that argues for #112. Run the #85 checks (#76, #88 and #89 Disenchant checks, #97 slice 1, #39 throttle probe, #97 slice 2 buy-event probe, #54 Loot Alert incl. autoloot off). Optionally glance at a "Room partly from Beta" tooltip once w > 0. Then grill #39 using the probe results.
3. On dates: Nov 4, #91's list. ~Nov 6: run `brain recommend --beta-ratios` for #91's Item Keys, and set `beta_sell_rate_weight = 0.5` if they're close to 1. Nov 18: look back and close #110.

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. Don't use `git stash` on this Z: drive. This PC has no `lua` binary. To run the Brain's real-Lua tests, set `LUA` to a .bat that runs `@python lua_shim.py %*`, where lua_shim.py runs `-e <script>` on a `lupa.lua51` runtime with `print` replaced by one that writes tab-joined `tostring`s to stdout (about 10 lines). `python ../scripts/busted.py` (from `addon/`) runs the addon specs. `ruff` isn't on PATH, so use `python -m ruff`. Several source files are CRLF: Python edit scripts must normalise line endings before matching multi-line strings. Write them to the scratchpad with the Write tool (Bash heredocs mangle backslashes).

2026-09-30 (later 48): Grilled #54. It's now ready-for-agent (still `later`), with the spec on the issue. A Loot Alert fires on the player's own "You receive loot" lines (not crafts, buys, mail or Disenchant results) when one unit's Best Exit Value is at or over max(`loot_alert_share` 0.10 × pooled gold, `loot_alert_floor` 10g). The Brain values every Item Key in the last Scan as one unit alone with `_way_out` and writes only the ones over the threshold, as a per-Market `lootAlert = { threshold, items = { [itemKey] = { value, action } } }`. The Addon's plain-Lua `LootAlert.lua` parses `CHAT_MSG_LOOT` and builds `AQ: [link] x3: 45g each, 135g (Sell)`, adding "(prices Nd old)" past a day from `asOf`. The glue shows raid-warning text, a sound and the chat line. BoP drops get no alert. Follow-up #113 (needs-triage, later) is for valuing them by Disenchant group. Docs: CONTEXT.md **Loot Alert**, no ADR. PC check noted on #85.

Next, in order (grill first where not ready-for-agent):
1. #54 (ready-for-agent, medium: Brain export + config, Addon LootAlert module + glue, docs), then #44, #61, #14, #19, #10, #82. #81 is ready-for-human: do it at the PC.
2. When at the PC: the first `brain recommend` after #55 works out every Scan before a Purchase, so expect it to be slow once. Check that the For Use count line in `brain flips` looks sane; if it's big, that argues for #112. Run the #85 checks (#76, #88 and #89 Disenchant checks, #97 slice 1, #39 throttle probe, #97 slice 2 buy-event probe, #54 Loot Alert). Optionally glance at a "Room partly from Beta" tooltip once w > 0. Then grill #39 using the probe results.
3. On dates: Nov 4, #91's list. ~Nov 6: run `brain recommend --beta-ratios` for #91's Item Keys, and set `beta_sell_rate_weight = 0.5` if they're close to 1. Nov 18: look back and close #110.

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. Don't use `git stash` on this Z: drive. This PC has no `lua` binary, so the Brain's Lua fixture tests skip, but `python scripts/busted.py` (from `addon/`) does run the addon specs through lupa. `ruff` isn't on PATH, so use `python -m ruff`. Bash heredocs mangle backslash escapes in Python strings: write edit scripts to the scratchpad with the Write tool. #54: valuing every Item Key in a Scan through `_way_out` may be slow. If it is, measure before optimizing. The one-unit-alone valuation must not reuse the Holdings' shared outlets.

2026-09-30 (later 47): Built #89 (bb723ab, closes it). `_flips_to_disenchant` is one greedy option per Disenchant source group. Its candidates are other players' Listings of the group's items whose best `_way_out` (with sources) is Disenchant, and items under a Prediction are skipped. `_flip_to_disenchant` buys the cheapest first while `_mats_value` (the marginal way out per mat against a fresh outlet, splitting a mat's quantity across ways as room runs out) less the effort clears the Flip margin and the Budget. Rows are `Row("", Action.DISENCHANT, ...)` with `disenchant=DisenchantFlip(group, (ListingBuy, ...))`, cut to `disenchant_list_rows` (10) in `_options`. `named_set` names each bought Item Key up to its dearest Listing. Replay `_taken` counts only SELL/VENDOR rows toward `flip_rows` and blocks through `_touched` (bought items + mats). `_brain` keeps the bought units. `_row` writes `disenchant = { group, disenchanter, mats, buys }`. The CLI labels the row by group. The Addon has a Flips to Disenchant tab (4th, so later section indices moved up one), with a tooltip of Listings then mats. Its rows are markable Bought and have no Beta column. `heldUnits` skips rows without an itemKey. Docs: ADR-0017 amendment and CONTEXT.md **Flip to Disenchant**. The PC checks are on #85 (the original one plus: six tabs fit, and the skipped real-Lua read test). Review items I didn't take: a second row discriminator (`disenchant` field beside `action == Craft`) now checked in about 8 places; `item_key=""` for a group row; mats/disenchanter written twice in the Lua shape (the spec asked for it); `_options` has 7 params; the named-set test checks `named_set` only, not `is_for_use`; a Craft way's room doesn't shrink as the option's own mats add up (noted in the ADR).

Next, in order (grill first where not ready-for-agent):
1. #54 (needs-info, later: grill), then #44, #61, #14, #19, #10, #82. #81 is ready-for-human: do it at the PC.
2. When at the PC: the first `brain recommend` after #55 works out every Scan before a Purchase, so expect it to be slow once. Check that the For Use count line in `brain flips` looks sane; if it's big, that argues for #112. Run the #85 checks (#76, #88 and #89 Disenchant checks, #97 slice 1, #39 throttle probe, #97 slice 2 buy-event probe). Optionally glance at a "Room partly from Beta" tooltip once w > 0. Then grill #39 using the probe results.
3. On dates: Nov 4, #91's list. ~Nov 6: run `brain recommend --beta-ratios` for #91's Item Keys, and set `beta_sell_rate_weight = 0.5` if they're close to 1. Nov 18: look back and close #110.

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. Don't use `git stash` on this Z: drive. This PC has no `lua` binary, so the Brain's Lua fixture tests skip, but `python scripts/busted.py` (from `addon/`) does run the addon specs through lupa. `ruff` isn't on PATH, so use `python -m ruff`. Bash heredocs mangle backslash escapes in Python strings: write edit scripts to the scratchpad with the Write tool. Brain tests with a Flip need gold on a Read (`money`), or the Budget stops the loop at once.

2026-09-30 (later 46): Grilled #89. It's now ready-for-agent, with the spec on the issue. A Flip to Disenchant is one Shopping List option per Disenchant source group. It's a greedy loop over other players' Listings of the group's items, cheapest first. Each Disenchant's mats are valued by their marginal `_way_out` against a fresh outlet, with held mats first. It stops at the first Listing that doesn't clear effort + Flip margin or the Budget. A Listing only counts if Disenchant is its item's best way out. There's no Craft chaining (the Craft credit comes through `_way_out`). It gets its own Flips to Disenchant tab, cut by Profit to a new `disenchant_list_rows` (10). `shopping` rows carry a `disenchant` field. #55's named set gets each Item Key bought, up to its dearest buyout. Replay takes it like any option, its mats count as made, and it gets no Flip Grade. Docs: an ADR-0017 amendment and CONTEXT.md. The PC check is noted on #85.

Next, in order (grill first where not ready-for-agent):
1. #89 (ready-for-agent, medium-large: Brain loop, Lua output, named set, replay, Addon tab, docs). Then #54, #44, #61, #14, #19, #10, #82. #81 is ready-for-human: do it at the PC.
2. When at the PC: the first `brain recommend` after #55 works out every Scan before a Purchase, so expect it to be slow once. Check that the For Use count line in `brain flips` looks sane; if it's big, that argues for #112. Run the #85 checks (#76 and #88 Disenchant checks, #97 slice 1, #39 throttle probe, #97 slice 2 buy-event probe). Optionally glance at a "Room partly from Beta" tooltip once w > 0. Then grill #39 using the probe results.
3. On dates: Nov 4, #91's list. ~Nov 6: run `brain recommend --beta-ratios` for #91's Item Keys, and set `beta_sell_rate_weight = 0.5` if they're close to 1. Nov 18: look back and close #110.

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. Don't use `git stash` on this Z: drive. This PC has no `lua` binary, so the Lua fixture tests skip. `ruff` isn't on PATH, so use `python -m ruff`. #89: tests whose Purchases should start Lots need a Scan before them and a named set (`named_at_t0`/`named_at`). The replay's "makes" check must count the option's expected mats.

2026-09-30 (later 45): Built #55 (81067f2, closes it). A Purchase not under a Prediction starts a Lot only when the last Scan before it named it: a Flip to Sell or Vendor row (up to its dearest Listing), a Flip to Craft AH reagent (up to `max_unit_price`), or a Buy Under of the Item Key or its Disenchant group (`Group.key`). Every other Purchase is For Use. There's a pure `lots.is_for_use`, plus `recommend.split_purchases` (-> `Split(kept, for_use)`), `recommend.rework` (-> `Reworked(shown, named)`, one recompute that freezes both `shown` and the new `named` key in grades.toml), and `recommend.named_set`. `market_lots` (Paid, Flip Grades) filters. The new `prediction_lots` (Grades, Hold costs) doesn't, so nothing recurses. `recommend_market(paid=False)` is used for past-Scan reworks and for the replay, whose Actions are the same without Paid. A Scan's frozen `shown` rows count as named too, so a Flip frozen before `named` existed keeps its Lot. The `brain flips` and replay output end with "N Purchases (Xg) not named by the Brain, counted as For Use". Docs: ADR-0025, an ADR-0007 amendment, and CONTEXT.md **For Use**. Review items I didn't take: moving `split_purchases`/`rework` out of recommend.py (it's 3.5k lines, and they call `recommend_market`, so they'd need a new module), and sharing the setup `market_lots` and `prediction_lots` have in common.

Next, in order (grill first where not ready-for-agent):
1. #89 (needs-info: grill), then #54, #44, #61, #14, #19, #10, #82. #81 is ready-for-human: do it at the PC.
2. When at the PC: the first `brain recommend` after #55 works out every Scan before a Purchase, so expect it to be slow once. Check that the For Use count line in `brain flips` looks sane; if it's big, that argues for #112. Run the #85 checks (#76 and #88 Disenchant checks, #97 slice 1, #39 throttle probe, #97 slice 2 buy-event probe). Optionally glance at a "Room partly from Beta" tooltip once w > 0. Then grill #39 using the probe results.
3. On dates: Nov 4, #91's list. ~Nov 6: run `brain recommend --beta-ratios` for #91's Item Keys, and set `beta_sell_rate_weight = 0.5` if they're close to 1. Nov 18: look back and close #110.

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. Don't use `git stash` on this Z: drive. This PC has no `lua` binary, so the Lua fixture tests skip. `ruff` isn't on PATH, so use `python -m ruff`. Bash heredocs fed to `python -` can mangle `
` escapes. Use the Edit tool for strings with backslashes. Tests whose Purchases should start Lots now need a Scan before them and a named set (see `named_at_t0` in test_recommend.py and `named_at` in test_replay.py).

2026-09-30 (later 44): Grilled #55. It's now ready-for-agent, with the spec on the issue. For Use is automatic: a Purchase not under a Prediction starts a Lot only if the Brain named it as of the last Scan before it (Flip to Sell/Vendor row, a Flip to Craft AH reagent, or a Buy Under, at or under that price). Every other Purchase is For Use and starts no Lot. Loot needs no change. Named sets are frozen in grades.toml under a new key next to `shown`. It needs a new ADR-0025 amending ADR-0007. Filed #112 (later): the Addon records uses, the correct fix if the For Use count is big.

Next, in order (grill first where not ready-for-agent):
1. #55 (ready-for-agent, medium: classify Purchases, a frozen named set, 3 callers, docs). Then #81, #89, #54, #44, #61, #14, #19, #10, #82.
2. When at the PC: run the #85 checks (#76 and #88 Disenchant checks, #97 slice 1, #39 throttle probe, #97 slice 2 buy-event probe). Optionally glance at a "Room partly from Beta" tooltip once w > 0. Then grill #39 using the probe results.
3. On dates: Nov 4, #91's list. ~Nov 6: run `brain recommend --beta-ratios` for #91's Item Keys, and set `beta_sell_rate_weight = 0.5` if they're close to 1. Nov 18: look back and close #110.

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. Don't use `git stash` on this Z: drive. This PC has no `lua` binary, so the Lua fixture tests skip. `ruff` isn't on PATH, so use `python -m ruff`. #55: past-Scan recomputes must skip Paid (no loop), and `_shown_rows` passes `buy_under=False` today, but the named set needs Buy Unders.

2026-09-30 (later 43): Built #111 (05a9771, closes it). `_spend_on_predictions` now picks a merged row's `BetaRoom` by `(from_beta > 0, room)`. Tests are in test_recommend.py (the merge) and test_recommendations.py (`_row` writes `roomFromBeta`). These are the first tests to import private names (`_HoldBuy`, `_Caps`, `_spend_on_predictions`, `_row`), which the spec allowed. The review suggested two things I didn't do: a `BetaRoom` property for "from Beta" (`from_beta > 0` is now written in both recommend.py and recommendations.py), and a CONTEXT.md line about the tie-break.

Next, in order (grill first where not ready-for-agent):
1. #55, #81, then #89, #54, #44, #61, #14, #19, #10, #82.
2. When at the PC: run the #85 checks (#76 and #88 Disenchant checks, #97 slice 1, #39 throttle probe, #97 slice 2 buy-event probe). Optionally glance at a "Room partly from Beta" tooltip once w > 0. Then grill #39 using the probe results.
3. On dates: Nov 4, #91's list. ~Nov 6: run `brain recommend --beta-ratios` for #91's Item Keys, and set `beta_sell_rate_weight = 0.5` if they're close to 1. Nov 18: look back and close #110.

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. Don't use `git stash` on this Z: drive. A path-limited `stash push`/`pop` emptied `.git/index` (every file showed as deleted and untracked), and `git reset` rebuilt it. This PC has no `lua` binary, so the Lua fixture tests skip. `ruff` isn't on PATH, so use `python -m ruff`.

2026-09-30 (later 42): Grilled #111. It's now ready-for-agent, and the spec is on the issue. The fix is a one-line pick-key change in `_spend_on_predictions` (prefer a BetaRoom with from_beta > 0, then the biggest room), plus two tests. Build it before ~Nov 6.

Next, in order (grill first where not ready-for-agent):
1. #111 (ready-for-agent, small). Then #76, #55, #81, then #89, #54, #44, #61, #14, #19, #10, #82.
2. When at the PC: run the #85 checks (#97 slice 1, #39 throttle probe, #97 slice 2 buy-event probe). Optionally glance at a "Room partly from Beta" tooltip once w > 0. Then grill #39 using the probe results.
3. On dates: Nov 4, #91's list. ~Nov 6: run `brain recommend --beta-ratios` for #91's Item Keys, and set `beta_sell_rate_weight = 0.5` if they're close to 1. Nov 18: look back and close #110.

- Gotchas: `addon/AzerothQuant/Recommendations.lua` is still modified by an import. Don't commit it. This PC has no `lua` binary, so the Brain's `lua` fixture tests skip silently. To run them, point `LUA` at a shim: a .bat that runs a Python script, which runs `-e <script>` on `lupa.lua51` and prints with tabs. `python scripts/busted.py` runs the addon specs.

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
