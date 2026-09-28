# Booty Bay Broker as outside Forever market data (#82)

Researched 2026-09-28.

**How this was sourced.** The egress proxy blocks bootybaybroker.com, curseforge.com, wago.io and web.archive.org, so no page could be fetched. Every claim about the site below comes from web-search snippets of the site's own pages. The snippets are primary-source text, but they are excerpts, some are the search engine's paraphrase, and none were read in full. Treat each one as **unverified (snippet)** until someone opens the page. The one source read in full is the developer's GitHub profile README (raw.githubusercontent.com). GitHub search was run through the GitHub API.

## Verdict for #82

**Unclear. It probably can't be used today, but it may be able to supply a Fair Value prior later. It can never supply a Sell Rate.**

- **What it has.** Forever listing data, split by region, ruleset and faction. The metrics are Min Buyout, a quantity-weighted Market Value and Listed Quantity, with scan times. That matches our Market grain and could act as a Fair Value prior for thin Item Keys.
- **What it lacks.** Sales. The site says it doesn't measure sales, so it can't be a prior for Sell Rate. Sell Rate is the metric ADR-0004 and ADR-0015 care about most.
- **Access.** There is no public API or download that I could find. The Terms forbid scrapers and bots without prior written permission. So scraping bootybaybroker.com is out.
- **A possible route.** The Companion delivers Forever prices back into the game ("each delivered item carries its own last-scan time"). That suggests a local price table on the player's PC, most likely a SavedVariables file the desktop helper writes for the addon. If so, the import would work like the Beta Prior or the TSM AppHelper plan in ADR-0015. The Brain would read that file from the user's own WoW folder and map each (ruleset, faction, itemID) row to Min Buyout, Market Value, Quantity and scan time. It would be a Fair Value prior only, and Beta rows would be kept apart from Live rows (the Era rule). None of this is confirmed. The file's name, format and license are unknown, and the addon's source isn't public.
- **Next step.** Install the Companion on the PC, find the file it writes, and read its format. Separately, email the developer (support@bootybaybroker.com) and ask whether personal use of the delivered prices in a private tool is fine.

## 1. Download, API or local file

- **No public API or data download was found.** No snippet names an API page, endpoints, keys, rate limits or an export. The FAQ snippets name Blizzard's API (Retail) and TSM's API (Classic) as the site's *inputs*, not as anything it offers. https://bootybaybroker.com/faq (snippet)
- **"Open source" is claimed but not confirmed.** The About page says "the entire codebase is open source on GitHub … anyone can inspect … the API endpoints." https://bootybaybroker.com/about (snippet). But GitHub search finds no public repo for it: a repo search for "bootybaybroker" or "booty bay broker" and a Lua code search for "BootyBayBroker" all return nothing. Guessed repo names under TheMizeGuy all return 404 on raw.githubusercontent.com. One of the developer's public files refers to a local checkout at `~/Dev/BootyBayBroker/`, which suggests the repo exists but is private. https://raw.githubusercontent.com/TheMizeGuy/ui-craft-public/main/.coderabbit.yaml
- **Who runs it.** The developer is TheMizeGuy (Meipath LLC, a one-person studio). The README lists "bootybaybroker.com — auction-house price analytics for World of Warcraft, 13,000 monthly users". https://raw.githubusercontent.com/TheMizeGuy/TheMizeGuy/main/README.md (read in full)
- **How Forever data is collected.** A player runs the free Companion. The in-game addon it installs reads the whole auction house while the player is logged in, and the desktop helper uploads that scan. https://bootybaybroker.com/forever (snippet)
- **The desktop app.** It "watches the game's saved data and does the uploading an addon can't do alone" and "picks the scan up, compresses it, and ships it." It runs on Windows, with macOS "coming later". https://bootybaybroker.com/beta (snippet). So the addon writes its scan to SavedVariables, but the file name and format are unpublished.
- **Prices come back into the game.** Changelog: "Forever in-game price access no longer requires renewing a scan window; each delivered item carries its own last-scan time for the updated companion." https://bootybaybroker.com/changelog (snippet). So the Companion delivers a per-item price table to the game, and access was once gated on the user scanning. This is the likeliest local file to import. Its format is unknown.
- **Consent switches.** Market scans and character sync are separate consent switches, and both start off. https://bootybaybroker.com/beta (snippet)
- **The CurseForge addon.** "BootyBayBroker Companion" (by TheMizeGuy, v0.6.2 seen) exports bags and bank as a paste code for /inventory-price-check. Its slash commands are /bbb, /bbbinventory, /bbbexport and /bbbinv. https://www.curseforge.com/wow/addons/bootybaybroker-companion (snippet; CurseForge is blocked). It isn't clear whether this is the same addon the desktop Companion installs for AH scanning.

## 2. Coverage

- **Version.** WoW Forever. Every Forever price so far came from a Beta client. https://bootybaybroker.com/forever (snippet)
- **Beta vs Live.** "Beta scans stay filed as beta data, and the launch market starts its own price history on day one." https://bootybaybroker.com/forever (snippet). This matches our Era rule.
- **No realms, only rulesets.** "Forever has no realms. Instead, you pick a ruleset: Normal, PvP or Roleplaying, with Hardcore arriving after launch." Prices are stored per ruleset, exactly as the client reports it in the realm-name field, and are never averaged across rulesets. https://bootybaybroker.com/forever, https://bootybaybroker.com/forever/ah (snippets)
- **Factions.** "The two factions stay separate in Forever, so their prices are separate rows," and an item page shows one faction at a time. https://bootybaybroker.com/forever (snippet). No snippet mentions the neutral AH.
- **A shared AH may be coming.** The changelog mentions "groundwork for Forever's shared auction house". https://bootybaybroker.com/changelog (snippet). What "shared" means (cross-faction, or cross-ruleset) is unverified.
- **Regions.** The site uses its usual US/EU split. The coverage block lists only the regions scans have actually come from, and it "can legitimately read zero". The Forever AH page title says "US auction-house prices for WoW Forever (Beta)". https://bootybaybroker.com/forever, https://bootybaybroker.com/forever/ah (snippets)
- **Freshness.** Prices update "as scans arrive" and "as beta players scan". Forever prices show their scan time "without promising hourly updates", and each item carries its own last-scan time. https://bootybaybroker.com/forever/ah, https://bootybaybroker.com/changelog (snippets). The hourly pipeline described on the About page applies to Retail and Classic, not to Forever. https://bootybaybroker.com/about (snippet)
- **Size.** At least 2,544 items have Forever (Beta) data. https://bootybaybroker.com/forever (snippet; the date of that count is unknown)

## 3. Sales or listings

- **Listings only.** The changelog says item pages "no longer show an estimated daily sales figure because the site does not measure sales, so those numbers were not real." https://bootybaybroker.com/changelog (snippet)
- **Min Buyout.** "The lowest buyout at each snapshot", or "the lowest active listing for the item on the selected realm/faction". https://bootybaybroker.com/forever/ah (snippet)
- **Market Value (Weighted).** "The quantity-weighted average." Market Value is "an estimate from the current listings, not from completed sales". On Retail it is quantity-weighted with high outliers discarded. On Classic editions it is TSM's own market value. The definition used for Forever isn't stated beyond "quantity-weighted average". Whether outliers are trimmed on Forever is unverified. https://bootybaybroker.com/forever/ah, https://bootybaybroker.com/faq (snippets)
- **Listed Quantity.** "How many units are currently posted." https://bootybaybroker.com/forever/ah (snippet)
- **Other statistics.** For Retail and Classic, the site computes market value, median, min, max, standard deviation and listing count per item per snapshot. https://bootybaybroker.com/about (snippet). Whether Forever gets the same set is unverified.
- **For us.** It can serve as a Fair Value prior at most. It can't be a Sell Rate or Sale Event source. Listing-disappearance inference from their snapshots would be possible only with raw listings, and they don't expose them.

## 4. Terms

- **No scraping.** The Terms prohibit "using bots, scrapers, crawlers, or any other automated means to access, extract, or collect data from the Service without prior written permission". They also prohibit bypassing rate limits or access controls. They apply to anyone browsing price data, with or without an account. https://bootybaybroker.com/terms (snippet)
- **No other data-use clause was found.** No snippet shows a license that grants or limits personal use or redistribution of the price data. The license clause that did turn up covers content users submit. https://bootybaybroker.com/terms (snippet)
- **Recent update.** The Privacy Policy, Terms and Disclaimer were updated to cover Companion uploads and "WoW Forever's player-scanned prices". https://bootybaybroker.com/changelog (snippet). That wording wasn't seen.
- **For us.** Scraping the website or its internal JSON endpoints needs written permission. Reading a file the Companion puts on the user's own PC isn't clearly covered by the scraping clause, but the Terms may say more about it. Ask first.

## 5. Other

- **Addon-to-addon use.** No snippet mentions a TSM-style price-source API, a global Lua table, or any other hook another addon could call. Without the addon's source, we can't tell whether its delivered prices sit in a readable global or SavedVariables table.
- **Classic data comes from TSM.** On the other Classic editions, the site's prices come from the TSM API, and Companion uploads there are "used only to check the market feed". So for Forever, Booty Bay Broker is the only source, and its depth depends entirely on how many players run the Companion. https://bootybaybroker.com/faq, https://bootybaybroker.com/changelog (snippets)

## Open questions and unverified items

1. Every bootybaybroker.com claim above is from a search snippet. Nobody has read the full /forever, /forever/ah, /beta, /faq, /terms, /privacy or /changelog pages. A browser on the user's PC can.
2. The local file: its name, location (SavedVariables of which addon?), format, whether it holds the user's own raw scan or the site's delivered prices, and which fields each row has.
3. Is the addon the Companion installs the CurseForge "BootyBayBroker Companion" addon? Which game versions is it flagged for?
4. The "open source on GitHub" claim contradicts GitHub search. Is the repo private or gone?
5. Is Forever Market Value trimmed for outliers? Over what window? One snapshot, or several?
6. What is "Forever's shared auction house": cross-faction, or cross-ruleset? This affects how their rows map onto our Markets.
7. Is the neutral AH covered?
8. How many Forever scans per ruleset per faction per day, and how many contributors? Coverage may be too thin to be a useful prior.
9. Do the Terms allow personal use of Companion-delivered prices in a private tool? Ask support@bootybaybroker.com.
10. Does in-game price access still require contributing scans (the old "scan window")?
