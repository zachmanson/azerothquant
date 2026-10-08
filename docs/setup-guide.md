# AzerothQuant setup guide

AzerothQuant tells you what to buy and sell on the Auction House, and at what price. It has two parts:

- **The addon**, inside WoW. It looks at the Auction House and shows you a table of what to do.
- **The Brain**, a small app on your PC. It does the math and hands the answers back to the addon. It runs in the background, so you set it up once and forget it.

It only works on Windows.

## 1. Install

1. Close WoW.
2. Get `AzerothQuantBrain.exe` from whoever gave you this guide.
3. Double-click it. Windows will probably say "Windows protected your PC". That's because the app isn't signed. Click **More info**, then **Run anyway**.
4. It asks if it found your World of Warcraft folder. Click **Yes**. If it's wrong, click **No** and pick the folder WoW is in (the one with `_classic_` or `_classic_beta_` inside).
5. It asks for a code to share scans with the guild. Paste the code you were given and click **OK**. No code? Leave it empty and click **OK**. You can still use it alone.
6. It says "All set". Done.

That also installed the addon, so you don't need CurseForge or anything else. The Brain now starts by itself every time Windows starts. You never need to open it again.

## 2. Your first scan

1. Start WoW. If the addon list on the character screen shows AzerothQuant as out of date, tick **Load out of date AddOns**.
2. Go to an auctioneer and open the Auction House.
3. Click **Scan** (just above the top right corner of the Auction House window). Keep the Auction House open until chat says `Scan #... saved`. It takes a minute or two. If you close it early, nothing is saved, and you just scan again.
4. The AzerothQuant window opens next to the Auction House. Click its **Reload** button. Your screen reloads.
5. Wait about a minute. The button changes to **Load** and starts to glow. Click it.

Your table is now filled in. That's the loop from now on: **Scan, Reload, wait, Load.**

You can scan once every 15 minutes. The Scan button shows a countdown until the next one.

The first table may be short. It gets better the more you (and the guild, if you used a code) scan, because the Brain learns how fast things sell.

## 3. Reading the table

The window opens by itself when you visit the Auction House. Anywhere else, type `/aq recs` to open or close it.

Each tab is a list:

- **Holdings**: what you already own, in bags and bank on all your characters, and what to do with each: Sell (and at what price), Vendor, or Hold.
- **Shopping List**: things on the Auction House that are cheap enough to buy and resell (or vendor) for a profit. **Max price** is the most to pay, **Post at** is what to sell it for.
- **Flips to Craft**: things to buy so you can craft something worth more.
- **Flips to Disenchant**: items worth buying to disenchant.
- **Prediction buys**: usually empty for you. Ignore it.
- **Buy Under**: the most an item is worth paying. Anything listed at or under that price shows green on the Auction House, so you can grab it as it appears.

Some handy things:

- **Hover** over a row to see why.
- **Click** a row to select it. On a Sell row, the **Post** button then posts it at the right price. Each click posts once.
- **Search** looks up the selected item on the Auction House.
- **Right-click** a row on a buy list once you've bought it. It greys out so you don't buy it twice.
- **Budget** at the top: type the most gold you want to spend on one buy. Leave it blank to use all your gold.
- Item tooltips in your bags show a short `AQ:` line with what to do with that item.

**You always do the buying and selling yourself.** The addon never buys anything, and only posts when you click Post. If a price looks off, don't buy. Check the Auction House first.

## 4. When something looks wrong

**The table says "No Recommendations yet".** Do a Scan, click Reload, wait a minute, click Load.

**Chat says "Your Scan from X min ago hasn't reached the Brain. Is AzerothQuant Brain running?"** The Brain isn't running. Open the Start menu, click **AzerothQuant Brain**, then Reload in game.

**Chat says "AzerothQuant is downloading recent Scans".** With a guild code, the Brain downloads recent scans the first time it runs, and after a long break. It takes a few minutes. Keep playing, then Reload.

**Chat says "AzerothQuant needs its Brain app".** The Brain was never set up on this PC. Go back to step 1.

**The button says Reload again instead of Load.** You clicked too early. Reload once more and wait the minute.

**Chat says "Auction House closed before the Scan finished".** Scan again and keep the Auction House open until it says saved.

**A popup says "Something went wrong".** Take a screenshot of it.

## 5. Sending feedback

Something broke, or a number looks crazy? Send these to whoever gave you the Brain:

1. A screenshot of what looked wrong (the table, the chat, or the popup).
2. The Brain's log file. Open the Start menu and click **AzerothQuant Brain log**. A folder opens. Send the file called `brain.log`.

Say roughly when it happened. That helps a lot.

## Updating and removing

**Update:** when you get a newer `AzerothQuantBrain.exe`, double-click it. It updates itself and the addon and keeps your data.

**Remove:** Start menu, **Uninstall AzerothQuant Brain**. It asks if you want to delete your saved data too.
