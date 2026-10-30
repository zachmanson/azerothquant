# azerothquant

An Auction House trading tool for World of Warcraft: Forever. It tells you what to buy, what to sell, and at what price, based on what actually sells on your realm.

It has two halves:

- **The Addon**, in game. It scans the Auction House, reads your bags, bank and AH mail, and shows the Recommendation Table.
- **The Brain**, a small Windows app that runs in the background. It keeps the full price history, works out how fast each item really sells, and sends the answers back to the Addon.

You always do the buying and selling yourself. The Addon never buys, bids or takes mail. It only posts the row you clicked, one click per post.

## Features

- **Holdings:** everything you own across all your characters, with Sell (and the price), Vendor or Hold for each.
- **Shopping List:** listings cheap enough to buy and resell or vendor at a profit, with the most to pay and what to post at. Sized to your gold, a budget and how many days you'll wait to sell.
- **Flips to Craft and Flips to Disenchant:** buys that are worth more once crafted or disenchanted.
- **Buy Under:** a standing price per item. Anything at or under it shows green on the Auction House.
- **Predictions:** your own calls that something will jump after a raid or phase release, with the downside capped.
- **Sell Rate from real sales:** the Brain watches listings disappear between Scans to tell sales from cancels and expiries, so prices come from what sold, not what's listed.
- **Guild Scan Pool:** guildies with a code share their Scans, so everyone's Brain learns faster. Only the Scans are shared, nothing about your characters.
- **Beta Prior:** early in Live, each row shows what the item went for on Beta.
- **Post button and tooltips:** post the selected row at the right price, and an `AQ:` line on item tooltips.
- **Grading:** the Brain grades the Flips you made, and backtests buy-side changes and its own picks against an Auctionator player on past sales.
- **One-file install:** a single `AzerothQuantBrain.exe` installs the Brain and the Addon, starts with Windows, and updates both when you run a newer one.

## More

- `CONTEXT.md`: the domain language.
- `docs/adr/`: the design decisions and why.
- `docs/development.md`: building, testing, running and releasing.
- `docs/setup-guide.md`: the full player guide (install, first Scan, reading the table, troubleshooting).
