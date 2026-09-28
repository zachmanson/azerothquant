# Disenchant tables are static, checked by Disenchant Results

Disenchant (#76) needs to know what Disenchanting an item yields. Nothing in the game client says so, and the player's own Disenchants are far too few to learn it from: a 5% shard needs hundreds of Disenchants per Disenchant source group before its rate means anything. So the yields are a static data file, `brain/src/brain/data/disenchant.toml`, re-derived by hand from the public WoWWiki tables (CC BY-SA). An item's Disenchant source group is its quality (uncommon, rare or epic), armor or weapon, and item-level band. Each group lists its mats with a chance and a quantity range, and the expected quantity per Disenchant is `chance × (min + max) / 2`. The Enchanting skill a group needs comes from its item level, the same gate as a Known Recipe: a Character whose latest-read Enchanting skill falls short, or who has no Enchanting read at all, has no Disenchant way out.

The player's own Disenchant Results are recorded and reported next to the tables (`brain disenchants`, a later slice of #76), but they never replace the tables on their own. The report only says a value **differs** when the table's value falls outside a 95% interval of the Results (Wilson for chances, a t-interval for mean quantity), and says **too few Results** below `disenchant_check_min_results` (20 by default). When it differs, a person edits the data file.

## Considered Options

- TSM's `DisenchantInfo.lua`: complete and maintained, but its header says All Rights Reserved, so it can't be copied.
- Learning the yields from Disenchant Results: the true source for Forever, which may differ from Classic (its "Arcane Salvager"), but it takes a lot of Disenchants per group, and a lucky or unlucky run would move the Recommendations.
- Updating the table automatically once a Result differs: the same sample-size problem, and the file would stop saying where its numbers came from.

## Consequences

- Only the Classic item levels are in the file, and the wiki lists nothing for epics above item level 80, so those have no Disenchant way until a row is added.
- Item Info (item level, quality, class, equip slot) is recorded for uncommon to epic armor and weapons from Scans and from Character Reads, since a bound item never shows up on the Auction House. Anything that can't be equipped, shirts, tabards and enchanter-made wands can't be Disenchanted.
- A held unit Disenchants by the same marginal rule as Craft (ADR-0008): each step Disenchants the one unit that gains the most, its expected mats' worth less what the unit would bring by Sell or Vendor, until nothing gains. A mat's worth is that of its Holdings with the expected mats added, on top of the ones earlier steps are expected to yield. Mats come in fractions, and a fraction of a unit counts that fraction of the next whole unit, so a Disenchant that pushes a mat past the Sale Horizon is only credited for the part that still sells. Bound units go first, since they could only be Vendored.
- Best Exit Value gains the Disenchant way, so a Prediction's Held units, Grades and the replay value Disenchantable items by their mats too. A Craft's output and reagents are still valued by Sell and Vendor only (ADR-0014).
- Item Keys under a Prediction are Held, never Disenchanted, like Craft outputs.
- The Holdings are pooled, so a bound unit held by a Character who can't Disenchant it is still counted as Disenchantable by the one who can. It can't be mailed, so the player has to skip that row.
- The replay treats a Disenchant row's units as held and values them at the horizon by Best Exit Value, which is their mats' worth then.
