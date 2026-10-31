# Outside Auction House data sources for Forever (#56)

Researched 2026-09-29.

**How this was sourced.** Blizzard's developer docs were read in full from the JSON the docs portal loads (`community.developer.battle.net/api/pages/content/...`), since the portal page itself is rendered by script. Blizzard's API forum threads were read in full through the forum's JSON. TradeSkillMaster's help articles, Terms, blog and public-data page were read in full, and real TSM CSV files were downloaded to see their columns. Auctionator's source was read from a recent public mirror on GitHub (the official repo isn't on GitHub under any name I tried), and the player's own Auctionator SavedVariables file from the Beta install was opened read only. The Undermine Exchange API page, warcraftforever.games and the auction-hound and Auctioneer-Forever repos were read in full. The proxy blocked or returned nothing for bootybaybroker.com, ahledger.com, thewowdb.com, nexushub.co, curseforge.com and api.tradeskillmaster.com (expired certificate). Claims about those come from search snippets and are marked **unverified (snippet)**.

## Verdict for #56

**Nothing can replace our Scans, and nothing available today is worth importing as a supplement. Two sources could become useful after Live, and only one of them could ever give a Sell Rate.**

1. **Does anything cover Forever?** Only player-run sites that crowdsource Scans: Booty Bay Broker, TheWoWDB, AHledger and warcraftforever.games. Blizzard's API has no Forever namespace. TSM has no Forever data. Undermine Exchange and Saddlebag are Retail only.
2. **Snapshot prices or sales?** Every Forever source is listing snapshots: a min price, sometimes a median or weighted value, a quantity and a scan time. None measures sales. None scans often enough, or keeps raw Listings, to rebuild Disappearances inside Observation Windows. So none can give a Sell Rate.
3. **Could any of them fill gaps?** Barely. Our Scans are full Scans, so every Item Key that is listed in a Market we scan is already captured. The real gaps are time (hours nobody is at the AH) and Markets we don't scan (the other faction, neutral, other rulesets). The crowdsourced sites could give a Fair Value reference for those other Markets, but their coverage is thin and their access is closed or unclear. History from before we started is moot: Beta history can't feed Live decisions (Era), and we will scan Live from day one.

**What to watch for after Live (Nov 4):**

- **Blizzard adds a Forever namespace to the Game Data API.** This is the only thing that could improve Sell Rate. The Retail and Classic auction endpoints give every auction with a unique auction `id`, `quantity`, `buyout` (or `unit_price`), and a `time_left` bucket, refreshed about hourly, around the clock. With auction IDs, a Disappearance is tied to one exact auction, so the Listing identity guessing we do (Item Key, unit buyout, own flag) and the Repost pairing get much easier. Hourly snapshots sit right at our 1 h Observation Window cap, and they cover the hours we don't play, which would remove the prime-time bias ADR-0004 accepts. The catch: the Terms say data pulled from the API may be kept for no longer than 30 days, which clashes with ADR-0005 (the Scan Archive is the source of truth). Nobody at Blizzard has said a Forever namespace is coming.
- **TSM adds Forever.** TSM's region files carry `saleRate`, `soldPerDay` and `avgSalePrice`, built from its users' own sales records uploaded by the TSM desktop app, not from snapshots. That is real sales data, but region wide rather than per Market. Per ADR-0015 it would come in as a prior for thin Item Keys (a Sell Rate Prior and a Fair Value prior), never as a replacement, and the replay decides whether it helps. It can be read from TSM's public CSV files (no key, no sign-in) or from the AppHelper file. TSM has said nothing about Forever.

**Not worth doing:** reading the player's Auctionator SavedVariables. It holds a daily min price and max quantity per item from the same player's scans, keyed by ruleset with Alliance, Horde and neutral mixed together, and no sales. Our Scan Archive already has everything in it at a finer grain.

## 1. Booty Bay Broker (already researched, #82)

Full write-up: [booty-bay-broker.md](booty-bay-broker.md).

- Crowdsourced Forever listing data from players running its Companion, split by region, ruleset and faction, with Beta kept apart from Live. Metrics are Min Buyout, a quantity-weighted Market Value and Listed Quantity, with scan times.
- It says it doesn't measure sales, so it can't be a Sell Rate source. At most it's a Fair Value prior.
- No public API or download was found, and the Terms forbid scrapers without written permission. The one possible route is a local price file the Companion may write, which hasn't been confirmed.

## 2. Blizzard's official Game Data API

**Endpoints and fields.**

- Retail has two auction endpoints. `/data/wow/connected-realm/{connectedRealmId}/auctions` "Returns all active auctions for a connected realm", and `/data/wow/auctions/commodities` "Returns all active auctions for commodity items for the entire game region". Both say: "Auction house data updates at a set interval. The value was initially set at 1 hour; however, it might change over time without notice." https://community.developer.battle.net/api/pages/content/documentation/world-of-warcraft/game-data-apis.json (docs for https://community.developer.battle.net/documentation/world-of-warcraft/game-data-apis)
- Classic has `/data/wow/connected-realm/{connectedRealmId}/auctions/index` and `/data/wow/connected-realm/{connectedRealmId}/auctions/{auctionHouseId}`, the second returning "all active auctions for a specific auction house on a connected realm" with the same hourly note. The per-auction-house split is how Classic separates Alliance, Horde and neutral. https://community.developer.battle.net/api/pages/content/documentation/world-of-warcraft-classic/game-data-apis.json
- Blizzard's docs describe the endpoints but I found no response schema in them. A typed community client lists the fields. Retail items: `id`, `item` (id, bonus lists, modifiers), `quantity`, `bid`, `buyout`, `time_left` (`SHORT`, `MEDIUM`, `LONG`, `VERY_LONG`). Retail commodities: `id`, `item.id`, `quantity`, `unit_price`, `time_left`. Classic: `id`, `item` (id, `rand`, `seed`), `quantity`, `bid`, `buyout`, `time_left`. No seller field in any of them. https://raw.githubusercontent.com/Pewtro/blizzard-api/main/packages/wow/src/auction-house/types.ts, https://raw.githubusercontent.com/Pewtro/blizzard-api/main/packages/classic-wow/src/auction-house/types.ts (third-party, not Blizzard)
- The commodities endpoint updates "every hour (same cadence as the other auction data)" and costs 25 quota points per call. Posted by a Blizzard developer, 2022-08-18. https://us.forums.blizzard.com/en/blizzard/t/immediate-change-to-auction-apis-for-commodities-with-927/31522

**Coverage.**

- The Classic namespaces guide lists exactly three game versions: Classic (Era) as `dynamic-classic1x-{region}`, Mists of Pandaria Classic (Progression) as `dynamic-classic-{region}`, and Burning Crusade Classic (Anniversary) as `dynamic-classicann-{region}`. Retail uses `dynamic-{region}`. Forever isn't listed anywhere. https://community.developer.battle.net/api/pages/content/documentation/world-of-warcraft-classic/guides/namespaces.json
- A forum thread from 2026-09-18 asks "When will we gain API access to WoW: Forever Beta and WoW: Forever?" A community reply says "Blizzard has never provided an API for beta or PTR" and to wait for release. No Blizzard staff answered. A second thread on 2026-09-29 asks what namespace Forever will use; an MVP (a volunteer, not staff) replied "its in beta we wont know till its released and i wouldent count on it". https://us.forums.blizzard.com/en/blizzard/t/59595, https://us.forums.blizzard.com/en/blizzard/t/59774
- Two Forever fan sites say the same from the other side: their prices come "from our own scans of the beta realm with an addon, not from an API", because "the beta client does not expose one" (warcraftforever.games, read in full), and "Blizzard publishes no auction data for World of Warcraft: Forever" (TheWoWDB, **unverified (snippet)**). https://warcraftforever.games/guides/auction-house, https://thewowdb.com/
- Reliability warning: Blizzard's Classic Era auction endpoints have returned 404 since late 2024, per a developer thread. A Blizzard developer replied in March 2025 that it "is on the radar. No ETA on resolution". Users were still asking for news in August 2025. So even an announced namespace isn't a promise of working data. https://us.forums.blizzard.com/en/blizzard/t/404-for-all-classic-era-namespace-auction-house-endpoints/54307

**Could it give a Sell Rate?** Only if a Forever namespace appears. An hourly snapshot with auction IDs lets you see exactly which auctions vanished and which shrank. That's our Disappearance and Partial Sale, with cleaner identity than our Scans have. The `time_left` bucket plays the same role as ours for ruling out expiry. The limits: a gap of about an hour is at our Observation Window cap, so it would count, but cancellations still look like sales (no seller field and no cancel flag), and an auction posted and bought inside one hour is never seen. Retail commodities are region wide; how Forever's per-ruleset, per-faction houses would map onto the API is unknown.

**Terms.** The Blizzard Developer API Terms of Use (read via fetch): https://www.blizzard.com/en-us/legal/a2989b50-5f16-43b1-abec-2ae17cc09dd6/blizzard-developer-api-terms-of-use

- 2.q: "You are limited to thirty-six thousand (36,000) calls to the Blizzard Developer API per hour".
- 2.r: "You must retain data pulled from Blizzard Developer APIs for no longer than 30 days."
- 2.i: "The Data is for Your use to enhance the experience of the players of Blizzard's games and You are not allowed to sell, license or otherwise transfer the Data to any third party."
- 2.b: no paid features or charging players.
- 2.m: no scraping or automated queries to Blizzard outside the API.
- For us: a personal, free tool fits 2.b and 2.i. The 30-day retention rule is the problem. Keeping raw API snapshots in the Scan Archive forever would break it. Whether keeping only derived Sale Events past 30 days is allowed isn't clear from the text.

## 3. TradeSkillMaster

**Coverage.** TSM's site and public data have three game types: `retail`, `classic` and `classic-progression` (shown as "Mists of Pandaria"). There's no Forever game type; `forever` and `wow-forever` paths return 404. Nothing on TSM's blog, news page or help center mentions Forever. https://tradeskillmaster.com/public-data (read in full; game types from the page's own data), https://blog.tradeskillmaster.com/2026/09/

**Where the numbers come from.**

- Realm data comes from Blizzard's API: "DBMinBuyout is the lowest priced auction on your realms Auction House, as of the last pricing update processed from Blizzard's Auction House API." So TSM realm prices for Forever would need Blizzard to add Forever first. https://support.tradeskillmaster.com/en_US/custom-strings/which-price-sources-can-i-use-and-what-do-they-mean
- "DBMarket is a weighted 14-day average of the auctions listed ... favoring the most recent 3 days ... Note this value does not indicate what an item will sell for, only what the item is currently being listed for". DBRecent applies the market value method to the latest snapshot only. DBHistorical is a 60-day average of DBMarket. Same URL.
- Sales data comes from users, not Blizzard: "DBRegionSaleAvg is the average sale and purchase price for a particular item in your region. This data is collected from TSM Accounting data via the TSM Desktop Application." Same URL.
- "DBRegionSaleRate ... indicates the Sale Rate of a particular item averaged across all Auction Houses in your Region i.e a DBRegionSaleRate of 0.4 indicates an item will sell on average 40% of the times it is posted". "DBRegionSoldPerDay will return a decimal number indicating the volume of an item that is sold on average per Auction House per day in your Region." Both are labeled "via TSM App". https://support.tradeskillmaster.com/en_US/custom-strings/which-value-sources-can-i-use-and-what-do-they-mean

**Access.**

- Public CSV files, "static and public with no API key, sign-in, or rate limits", at `https://public-data.tradeskillmaster.com/{gameType}/{regionSlug}/realm/{realmSlug}/items.csv`, `.../commodities.csv`, `.../region/items.csv` and pets files. Realm and commodity files "change every few hours", region files daily. https://tradeskillmaster.com/public-data
- Downloaded headers (2026-09-29). Realm and commodity files: `itemId,name,marketValue,minBuyout,recent,historical,updatedAt`. Region files: `itemId,name,marketValue,historical,avgSalePrice,saleRate,soldPerDay,updatedAt`. Example Classic region row: `118,Minor Healing Potion,39,0,18,0.192,1.92,...`. https://public-data.tradeskillmaster.com/retail/us/region/items.csv, https://public-data.tradeskillmaster.com/classic/us/region/items.csv
- The older Swagger pricing API is still up at https://pricing-api.tradeskillmaster.com/public, but TSM's help article now points people to the CSV files and says to email for "more programmatic usage". https://support.tradeskillmaster.com/en_US/api-documentation/tsm-public-web-api
- The AppHelper file. The TSM desktop app writes `TradeSkillMaster_AppHelper/AppData.lua`, which the addon loads. A public sample (Classic, 2020) has one line per data set: `select(2, ...).LoadData("AUCTIONDB_MARKET_DATA","Bloodfang-Alliance",[[return {downloadTime=1606655156,fields={"itemString","marketValue","minBuyout","historical","numAuctions"},data={{117,513,1109,1109,1},...}}]])`, and a region line with `regionMarketValue, regionMinBuyout, regionHistorical, regionSale, regionSoldPerDay, regionSalePercent`. The keys are realm plus faction, which matches our Market grain better than the public CSVs do. https://raw.githubusercontent.com/ichibsah/AddOnsClassic/HEAD/TradeSkillMaster_AppHelper/AppData.lua. The format may have changed since 2020.
- The in-game TSM_API has `GetCustomPriceValue(customPriceStr, itemString)`, so an addon could read TSM prices inside the game. https://api.tradeskillmaster.com/addon/

**Terms.** TSM's Terms of Service cover purchases, accounts and intellectual property ("The Service and its original content, features and functionality are and will remain the exclusive property of TradeSkillMaster LLC"). They have no clause on scraping, on data use, or on reading AppData.lua. https://tradeskillmaster.com/terms. The public CSVs are offered openly, which is the cleanest route. The addon code (including AppHelper) is "All rights are reserved" with an exception for personal modification, but that covers the code, not the price data it carries. https://raw.githubusercontent.com/MrUnstable/TSM/HEAD/TradeSkillMaster_AppHelper/LICENSE.txt (an old mirror)

**For us.** If TSM ever covers Forever, `soldPerDay` (units per AH per day) is the closest thing to our Sell Rate anywhere. But it's a region average across every Market, built from TSM users' own sales, and it can't be split to one Market. It fits as a Sell Rate Prior for Item Keys where our own Sale Events are thin, and `avgSalePrice` as a Fair Value prior. Per ADR-0015, our own Sale Events override it, and the replay decides whether it earns its place.

## 4. Auctionator

- **Source.** The official repo wasn't found on GitHub. I read a recent vendored copy (TOC Version 321, interfaces 120005 through 11508, pushed 2026-04-30). Its LICENSE is "All Rights Reserved, Copyright (c) 2020-2025 plusmouse, borjamacare". https://github.com/qyh214/wow_addons_private_use/tree/master/AddOns/Auctionator
- **What it stores.** `AUCTIONATOR_PRICE_DATABASE[realmKey][itemKey]` holds `m` ("Last seen minimum price"), and per day: `l` ("Lowest low price on a given day"), `h` ("Highest low price on a given day") and `a` ("Highest quantity seen on a given day"). Days are counted from 2020-01-01. After each scan it stores only the minimum price and total quantity per item. Days older than `price_history_days` (default 21) are pruned. https://raw.githubusercontent.com/qyh214/wow_addons_private_use/master/AddOns/Auctionator/Source/Database/Mixin.lua, https://raw.githubusercontent.com/qyh214/wow_addons_private_use/master/AddOns/Auctionator/Source/Config/Main.lua
- **Nothing about sales.** No per-Listing data is kept, so Disappearances can't be rebuilt. `AUCTIONATOR_POSTING_HISTORY` holds only the player's own posts.
- **Market key mixes factions on Forever.** The modern-AH flavor keys the database by `GetConnectedRealmRoot()`, which returns the realm name with no faction (`Source_ModernAH/Variables/Main.lua`). Only the legacy-AH flavor appends `UnitFactionGroup("player")` (`Source_LegacyAH/Variables/Main.lua`). The player's own file confirms it: the only key is `"ClassicBetaPvP"`, with no faction. So on Forever, Alliance, Horde and neutral scans land in one bucket.
- **Encoding.** Realms other than the current one, and on newer clients the current one too at logout, are stored as CBOR strings (`C_EncodingUtil.SerializeCBOR`), not Lua tables. Reading it needs a CBOR decoder. `Source_ModernAH/Variables/Main.lua`
- **The player's file.** `_classic_beta_/WTF/Account/<account>/SavedVariables/Auctionator.lua`, 53 KB, last written 2026-09-19. Auctionator isn't in the AddOns folder any more, so it won't grow.
- **For us.** Not a useful gap filler. It's the same player's scans at a coarser grain (daily min per item, factions mixed), with no sales. The only thing it has that we don't is days before our Addon ran, and those are Beta.

## 5. Undermine Exchange, Saddlebag Exchange, NexusHub

- **Undermine Exchange.** "Historical pricing data covering all items on all realms for the latest version of World of Warcraft (Retail, not Classic)." Its source is Blizzard's API. Free API key via Patreon login, 3,000 points per hour. https://undermine.exchange/api.html
- **Saddlebag Exchange.** Its WoW tools are built on Blizzard's hourly Retail API updates (sniper, upload timers, region-wide undercut checks). The page mentions Classic only in search keywords. https://saddlebagexchange.com/wow
- **NexusHub.** A Classic AH database powered by TSM data since 2020, with a free API. https://blog.tradeskillmaster.com/tradeskillmaster-to-power-classic-ah-database-by-nexushub/. The site couldn't be reached, so its current state and any Forever coverage are unknown. It gets its data from TSM, so it can't cover Forever before TSM does.
- **For us.** None covers Forever, and none can without Blizzard's API or TSM.

## 6. Forever-specific sources

- **TheWoWDB.** "Players scan the Auction House in game with the TheWoWDB addon and the prices land here". Each number is "one scan of one realm's Auction House". It's "not Blizzard data, not a feed, and not live", and "coverage is uneven because scans only cover what the players who scan actually look at". **unverified (snippet)** https://thewowdb.com/ (the page returned an empty body to fetch)
- **AHledger.** Per-market item pages with "the cheapest listing, the median across all units, how many are listed, and 7, 30 and 90 day history", from "players scanning the auction house with the addon". Uses "no third-party price data". No mention of sales, an API or terms was found. **unverified (snippet)** https://ahledger.com/, https://ahledger.com/guides/how-auction-house-prices-work (TLS error on fetch)
- **warcraftforever.games.** "The lowest price per item, per faction, scanned in-game with our ForeverAH addon." The page on 2026-09-29 showed one snapshot, from realm Classic Beta PvP 2 on Sep 21, 2026 at 10:47 AM UTC, with 1,299 items listed. So it's one realm, a lowest price, and it isn't refreshed often. No API, export or terms link on the page. https://warcraftforever.games/ah (read in full)
- **Local addons, not data sources.** auction-hound (created 2026-09-26, no license) keeps its own scan history and shows "estimated units moved per day" from the player's own scans. https://github.com/peligwen/auction-hound. Auctioneer-Forever is a GPL-2.0 port of Auctioneer for the Forever client. https://github.com/NoobyGains/Auctioneer-Forever. Both only know what the player's own client scanned, the same as our Addon.
- **A Beta client bug that affected all SavedVariables readers.** Forever Beta builds from 1.60.1.69913 wrote SavedVariables but didn't load them back. It was reported fixed in build 70009 on 2026-09-24. https://github.com/ClassicWoWCommunity/forever-bugs/issues/34

## 7. Comparison

| Source | Covers Forever? | Prices | Sales / Sell Rate signal | Access | Terms |
|---|---|---|---|---|---|
| Our Scans | Yes, the Markets we scan | Every Listing, per Scan | Yes: Partial Sales and Probable Sales inside Observation Windows | Our own SavedVariables | Ours |
| Blizzard Game Data API | No. No Forever namespace; Beta and PTR never had one | Every auction with `id`, `quantity`, `buyout`/`unit_price`, `time_left`, about hourly | None given, but auction IDs every hour would let us infer Disappearances, if Forever is ever added | OAuth client, 36,000 calls per hour | Free and personal use OK; keep data at most 30 days (2.r) |
| TSM | No. Game types are retail, classic and classic-progression | marketValue, minBuyout, recent, historical (realm); marketValue, historical (region) | Region only: `soldPerDay`, `saleRate`, `avgSalePrice`, from TSM users' uploaded sales | Public CSVs with no key; AppHelper `AppData.lua`; in-game TSM_API | No data-use clause; CSVs offered openly |
| Auctionator (player's own file) | Yes, but only the player's own scans | Last min, daily lowest and highest min, daily max quantity; 21 days; factions mixed | None | Local SavedVariables, CBOR-encoded | Code "All Rights Reserved"; the data is the player's |
| Booty Bay Broker | Yes, crowdsourced, per ruleset and faction | Min Buyout, weighted Market Value, Listed Quantity | None ("does not measure sales") | No public API found; maybe a local Companion file | No scraping without written permission |
| TheWoWDB | Yes, crowdsourced **(snippet)** | Per-scan prices **(snippet)** | None found | Unknown | Unknown |
| AHledger | Yes, crowdsourced, per ruleset and faction **(snippet)** | Cheapest, median, quantity, 7/30/90-day history **(snippet)** | None found | Unknown | Unknown |
| warcraftforever.games | Yes, one Beta realm, one snapshot | Lowest price per item per faction | None | Website only | No terms found |
| Undermine Exchange | No (Retail only) | Min, median, quantity, hourly history | None | API key via Patreon | Not checked |
| Saddlebag Exchange | No (Retail) | Retail AH via Blizzard | None relevant | Website and API | Not checked |
| NexusHub | No (Classic, via TSM) | TSM-derived | TSM-derived | Free API (not reachable) | Not checked |

## Open questions and unverified items

1. Will Blizzard add a Forever namespace to the Game Data API at Live? Nobody at Blizzard has said. Watch https://us.forums.blizzard.com/en/blizzard/c/api-discussion after Nov 4. If it arrives, the next research is how Forever's ruleset and faction houses map onto `connected-realm` and `auctionHouseId`, and whether `time_left` buckets are fine enough to rule out expiry inside an hour.
2. Does the 30-day retention rule (2.r) cover things we derive from the API, like Sale Events, or only the raw pulled data? This decides whether API data could live in the Scan Archive at all.
3. The Retail auction response schema came from a third-party typed client, not from Blizzard's docs. The field list, and the absence of a seller field, should be checked against a real response.
4. Will TSM support Forever? If so, will its AppHelper region lines for Forever be per ruleset and faction, or region wide? What does `AppData.lua` look like today (the sample is from 2020)?
5. TSM's `soldPerDay` and `saleRate` come from TSM users' uploaded sales. How many Forever players would run the TSM app is unknown, so the numbers could be thin.
6. TheWoWDB and AHledger were not readable. Their data fields, update rates, whether they expose any API or export, and their terms are unverified.
7. The official Auctionator repository location wasn't found. The Auctionator notes come from a vendored copy (version 321), and may differ from the Forever-flagged release on CurseForge.
8. NexusHub couldn't be reached. Whether it's still running is unknown.
9. Booty Bay Broker's open questions are still open. See [booty-bay-broker.md](booty-bay-broker.md).

## 2026-10-31 refresh

Three questions re-checked four days before Live: TSM, Blizzard's API, and Booty Bay Broker's local file.

### Verdicts

1. **TSM: unchanged.** Still no Forever data. The public-data page still lists Retail, Classic and Mists of Pandaria only, Forever CSV paths return 404, and TSM's own Wago listing has no Forever build. For us: no region `soldPerDay` or `saleRate` prior at launch. Our own Sale Events are the only Sell Rate source.
2. **Blizzard API: changed, but not for auctions yet.** Blizzard has still announced and documented nothing. But a player probing the API reports that `dynamic-forever-{region}` started answering on Oct 30 for regions and realms, while connected realms, auctions and commodities all return 404. This is third-party, and I could not confirm it without credentials. For us: the namespace seems to exist, so auction data at or after Live is now plausible rather than a long shot. It is worth a few minutes on Nov 4 or 5 with a free API client to check the auction paths. Nothing to build until auctions actually answer.
3. **Booty Bay Broker: partly changed.** The CurseForge addon called "BootyBayBroker Companion" is only a bag export tool. Its own changelog says the AH scanning addon is a different, "newer desktop-paired" addon that the desktop app installs. That one is not on CurseForge, Wago or public GitHub, so whether it writes a readable price file, and in what format, is still unknown. The Terms still could not be read. For us: no change to the plan in booty-bay-broker.md. Install the desktop Companion on the PC and look at what lands in `WTF\...\SavedVariables`, then ask the developer before using it.

**New sales sources:** none found. Every Forever source seen is still listing snapshots or the player's own ledger.

### 1. TradeSkillMaster

- The public-data page's own data defines three game types: `gameTypes.retail`, `gameTypes.classic`, `gameTypes.classicProgression` (shown as "Mists of Pandaria"). The word "Forever" does not appear on the page. https://tradeskillmaster.com/public-data (read in full, 2026-10-31)
- `https://public-data.tradeskillmaster.com/forever/us/region/items.csv`, `.../classic-forever/...` and `.../wow-forever/...` all return 404. The Classic region file still returns 200 as a control. https://public-data.tradeskillmaster.com/classic/us/region/items.csv
- TSM's Wago listing (current version v4.14.78) carries `"supported_forever_patches":null` and `"supported_forever_patch":null` in its page data, next to filled-in values for Retail, MoP 5.5.4, BC 2.5.6 and Classic 1.15.9. So TSM has not shipped a Forever build of the addon, which the AppHelper route and in-game TSM prices would both need. https://addons.wago.io/addons/tradeskillmaster
- No mention of Forever on TSM's blog front page, home page or help center front page. The newest blog posts are about public groups, the new website and Premium plans, and the 4.14 beta. https://blog.tradeskillmaster.com/, https://tradeskillmaster.com/, https://support.tradeskillmaster.com/en_US. There is no `/changelog` page on tradeskillmaster.com (404), and `blog.tradeskillmaster.com/2026/10/` returns 404, so there were no October posts.
- Third-party guides disagree. Most say TSM has no Forever data. One tier-list site says TSM has a Forever build with Forever price data, while also saying it had none as of Oct 8. TSM's own Wago listing contradicts that page. **unverified (snippet)** https://wowforevertierlist.com/addons/tsm, https://mmonster.co/wow-forever/guides/addons/tradeskillmaster

### 2. Blizzard Game Data API

- **Official docs: unchanged.** The Classic namespaces guide still lists only Classic (Era) `classic1x`, MoP Classic `classic`, and Anniversary `classicann`. Neither "Forever" nor "CAMWOW" appears in the Classic namespaces guide, the Classic Game Data APIs page, or the Retail Game Data APIs page. Doc paths under `world-of-warcraft-forever/` return 404. https://community.developer.battle.net/api/pages/content/documentation/world-of-warcraft-classic/guides/namespaces.json, https://community.developer.battle.net/api/pages/content/documentation/world-of-warcraft-classic/game-data-apis.json, https://community.developer.battle.net/api/pages/content/documentation/world-of-warcraft/game-data-apis.json
- **API forum: no staff reply.** Thread 59595 ("When will we gain API access to Forever APIs?") now has 10 posts, all from players. Thread 60236 (2026-10-30) asks Blizzard for Forever API support. No post in either has the staff flag. Thread 59774 (namespace question) is unchanged since the MVP reply. https://us.forums.blizzard.com/en/blizzard/t/59595, https://us.forums.blizzard.com/en/blizzard/t/60236, https://us.forums.blizzard.com/en/blizzard/t/59774
- **The new finding (third-party).** On 2026-10-31 a player posted in both threads that something "popped up" in the API, and linked notes from his own probing with a normal client-credentials token, last checked 2026-10-31 17:29 UTC. https://mhuijskens.com/WoWForever/Api/ (read in full). His notes say:
  - "Blizzard hasn't announced or documented a Forever API."
  - `dynamic-forever-{region}` has been "Open since Oct 30, 23:46 GMT. Regions and realms work." `profile-forever-{region}` is accepted but has no characters yet. `static-forever-{region}` is refused with 403 (no items, spells or other game data).
  - Region ids are 93 (EU) and 91 (US), named "CAMWOW Europe" and "CAMWOW North America", with `patch_string` 1.60.1. "CAMWOW looks like Blizzard's internal name for Forever."
  - Forever's hidden realms are listed as normal realms (for example `camwow-us1-realm-2-pvp`), with the ruleset in the realm `type`: NORMAL, PVP, RP, PVP_RP. US and AU have 34 player realms, EU has 20, plus service entries. Each realm links to a connected realm.
  - `/data/wow/connected-realm/index`, `/connected-realm/{id}`, `/connected-realm/{id}/auctions`, `/data/wow/auctions/commodities` and `/data/wow/token/index` all return 404. His reading: "Auctions hang off connected realms, so the auction house won't be there until they do."
  - His method: a made-up namespace gives 403 on every path, while a real namespace with nothing at a path gives 404.
  - He did not list the Classic-style `/connected-realm/{id}/auctions/index` and `/auctions/{auctionHouseId}` paths, which are the ones Classic uses to split factions.
- **My own probe.** Without a token, `us.api.blizzard.com` returns a bare 404 for `dynamic-forever-us`, `dynamic-classic1x-us` and a made-up namespace alike, so an unauthenticated request can't tell them apart. I could not confirm his findings.
- **What it would mean.** Forever has many hidden realms behind each ruleset, not one realm per ruleset. If auctions open, the question is how those realms share an AH. Do all realms of one ruleset form one connected realm (one Market), or is the AH per realm? That decides whether an API pull maps onto our Market grain. The 30-day retention rule (2.r) and the open questions above still apply.
- **Related, unanswered.** Thread 59996 (2026-10-12) asks whether a private, single-user AH addon project may use the Developer API, given the Terms' community-benefit clause 2(e) and privacy-policy clause 2(o). No replies. That is our exact case. Thread 60153 asks about 2(r) retention for a private app; no replies either. https://us.forums.blizzard.com/en/blizzard/t/59996, https://us.forums.blizzard.com/en/blizzard/t/60153

### 3. Booty Bay Broker local price file

- **The CurseForge addon is not the AH scanner.** I downloaded BootyBayBrokerCompanion-0.7.2.zip (2026-10-06, the newest file listed) from CurseForge's CDN and read it. Its TOC says "Exports your bags (and optionally your bank) as a copy/paste JSON string for the BootyBayBroker website", lists interfaces 120005, 50504, 40402, 30403, 20505 and 11508 (no Forever build), has `## SavedVariables: BootyBayBrokerCompanionDB`, and is MIT licensed. The README says "No network calls". Its SavedVariables hold settings and bank snapshots, not prices. https://www.curseforge.com/wow/addons/bootybaybroker-companion/files/9078663 (file read in full)
- **The scanner is a separate addon.** That zip's `CHANGELOG.md`, 0.7.2: "`/bbb` now belongs to the BootyBayBroker companion addon ... it collided with the slash namespace of the newer desktop-paired BootyBayBroker companion addon, which now owns `/bbb`." So the addon that scans the AH and delivers prices is installed by the desktop app, and it's a different addon.
- **Its source is not public.** No CurseForge or Wago project for it was found. Wago has no BootyBayBroker addon at all. The CurseForge addon's TOC points to `github.com/TheMizeGuy/BootyBayBrokerInventoryExport`, which returns 404 (private or gone). The developer's public GitHub repos include neither addon nor the site. https://api.github.com/users/TheMizeGuy/repos
- **What the site says about it.** The site's own AI guide, read in full: "BootyBayBroker Companion: A free Windows desktop app and its in-game addon that track gold, items and auctions and scan WoW Forever and Classic auction houses." "Companion addon: The free in-game addon the Companion installs, for WoW Forever and the Classic editions: auction house scans, plus prices in tooltips and bags." So prices do come back into the game, which is the local data we'd want. The file name, format and fields are still unknown. https://bootybaybroker.com/llms.txt
- **Possibly a paid tier now.** The same file lists "Plans: What a free account includes, and what the optional BBB Character Plus subscription adds for your own characters and the Companion." Older snippets said there was no premium tier. Which Companion features sit behind the subscription isn't known. https://bootybaybroker.com/llms.txt
- **Forever item pages are off limits to crawlers.** `robots.txt` has `Disallow: /forever/item/` (and each language copy), `Disallow: /api/` and `Crawl-delay: 2`. https://bootybaybroker.com/robots.txt (read in full)
- **Terms: still not read.** /terms, /forever, /companion, /companion/addon and /changelog return 403 behind a Cloudflare check. Search snippets of the Terms now show only that the Service is free and that price data is used "in accordance with Blizzard's API Terms of Use and the principle of fair use". Nothing on personal use of delivered prices. **unverified (snippet)** https://bootybaybroker.com/terms. The scraping clause from the 09-28 doc is still the last known text.

### Other Forever sources (search only)

- WoW Forever Tracker has an addon and an "Auction trends" page built from uploaded scans. Hammerprice is a local addon whose ledger shows a sell rate from the player's own sales. Goblin Terminal, Forever Ledger and Grimlight Auctions are other Forever AH addons. None was read, and none is described as having cross-player sales data. **unverified (snippet)** https://www.curseforge.com/wow/addons/wow-forever-tracker, https://www.curseforge.com/wow/addons/hammerprice

### How this was sourced

Read in full: TSM's public-data page and its Wago listing, Blizzard's docs JSON (three pages), the Blizzard API forum threads through the forum's JSON, the third-party API notes page, Booty Bay Broker's robots.txt, llms.txt and rss.xml, and the CurseForge Companion zip (from the CDN; the file list came from api.cfwidget.com, a third-party mirror of CurseForge). Blocked: bootybaybroker.com page routes (Cloudflare 403) and curseforge.com pages (403). Not possible: confirming the Forever API namespace, since no Battle.net client credentials were used. Snippet only: the TSM third-party guides, Booty Bay Broker's Terms, and the other Forever addons. The desktop Companion is not installed on this PC (no BootyBayBroker folder in `_forever_\Interface\AddOns`), so its local file could not be looked at.
