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
