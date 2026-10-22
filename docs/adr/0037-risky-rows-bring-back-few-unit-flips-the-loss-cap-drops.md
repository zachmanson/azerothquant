# Risky rows bring back few-unit Flips to Sell the loss cap drops

Amends ADR-0034 (#194). The caps and the sizing stay as they are. But a Flip to Sell that the Unsold Loss cap drops entirely comes back on the Shopping List as a **Risky row** when its run is short: sized without the Unsold Loss cap but still within the gold, the Budget and the room, it buys no more than `risky_max_units` units (5). The run must clear everything a normal row does: the Flip margin on the last unit, the Sale Events minimum, the cheap-stock cutoff, ADR-0011 runs. There's no other ceiling on its loss. The row states it instead.

- Only Flips to Sell. Flips to Craft, to Disenchant and to Vendor, Buy Unders, Holdings and Prediction buys get no Risky rows.
- If the room alone drops it too, there's no Risky row: the room is gold the player can't spare.
- A row the caps only shrank keeps `capped`/`cappedBy` and gets no Risky row.
- Risky rows sit inline, ranked like any row, but they take no place from the rest: the `shopping_list_rows` cut ranks the normal rows among themselves, as before, and keeps a Risky row if it would make that cut among all of them.
- The Lua row has `risky = true` and `unsoldLoss`. The Addon tags it "Risky" and its details say "Over your risk cap: if none of it sells you lose X."
- A Risky row is named: a buy from it starts a Lot (ADR-0025) and gets a Flip Grade. grades.toml's shown rows keep `risky = true`, so its P&L can be split out.
- The Backtest and the replay (`options_taken`) never take a Risky row, so their numbers don't move.

## Why

The cap is a share of the Stake, and the Stake has been about 17g since 2026-10-14, so the cap is about 51s. From then on every Flip to Sell costing more than about 1g was cut, 1 unit or 100: 10603 (1 unit, 1.25g Profit) and 13926 (8 units) at the 10-14 19:43 Scan, 10040 (1 unit) at 10-17, 2800 (1 unit) at 10-20. The Won vs Sold mail record says few-unit dear flips made the money: Troll's Bane Leggings +13.1g on 4 units, The 1 Ring +9.0g on 1, Staff of the Friar +7.8g on 2. The cap keeps exactly these off the list.

ADR-0034 turned down a warning on full-size rows because the Backtest, which takes rows as sized, couldn't judge them. That still holds, so Risky rows stay out of the Backtest, and their record comes from Flip Grades instead. The unit limit keeps the case ADR-0034 was written for out: the Cured Medium Hide (241 units) and runs that size never come back this way.

## Considered options

- **A floor on the Unsold Loss cap**: would let every option grow, long runs included. Out of scope, as in ADR-0034.
- **Risky rows in the Backtest**: it would grade a risk the player chooses as if the Brain chose it, and move the numbers ADR-0034 was judged on.
- **A separate Risky section**: the player compares options by the same measures, so they sit inline with a tag.

## Consequences

- `risky_max_units` 0 turns Risky rows off.
- `--why-not` sizes without the caps, so an Item Key shown as risky isn't called a failure.
- How Risky rows do is judged by their Flip Grades, split out by the `risky` flag.
