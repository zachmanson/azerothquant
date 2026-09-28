# Deposits are charged per expected expiry

Posting on the Auction House costs a deposit, refunded on a sale and lost each time a posting expires unsold. Nothing charged it (#78), so a slow seller looked as good as a fast one, both as a Flip and as a held unit's Sell over Vendor.

The Decision Engine now charges every unit it would post the deposits it expects that unit to lose.

**Deposit per unit.** The latest Sold invoice of the Item Key, `deposit / count`. The Addon always stored the invoice's `deposit`; `parse_mail` now keeps it, and the mail table has a `deposit` column. The Sold mail's Item Key is resolved by name as for Lots (ADR-0007), and a name that doesn't resolve to exactly one Item Key isn't used. With no Sold invoice, it's `ah_deposit_share` (0.60) of the Vendor Price, and nothing without one.

**Expected expiries: the queue model.** An Item Key's units sell in the order that already takes the Sale Horizon: unbound held units first (#67), then Flips to Sell, then Flip to Craft outputs. Unit i of that queue (0-based) waits i / units_per_hour hours and loses floor(wait / `post_duration_hours`) deposits (24 h by default, which must match what the player posts at). units_per_hour is the same prior-discounted Sell Rate the Sale Horizon room uses: the Flip priors for Flips, Flip to Craft outputs and a Hold buy's Max Loss, the Holdings priors for Holdings. Units past the Sale Horizon are never posted, so they never pay.

**Where.** A Flip to Sell's run profit, its margin test (on the run's last unit, which is both the dearest and the one that waits longest, so if it clears, every unit does) and the Shopping List's reprice. A Flip to Craft output that Sells, while its resale less its deposits beats the Vendor Price. A held unit Sells only while its price after the cut less its deposits beats the Vendor Price, so Selling is a prefix of the queue and the tail is Vendored; its Sell profit is net of them. A Hold buy's Max Loss takes the deposit-adjusted resale. Best Exit Value, Grades and held-at-writing follow through ADR-0010's single definition. Holdings still pay no non-stacking effort (#73): a deposit is real copper, not hassle.

## Considered Options

- **The formula (Vendor Price x a rate per duration), as in Classic.** Forever runs the retail `C_AuctionHouse` UI and nobody publishes its rates (Classic Era is 5% of Vendor Price per 2 h, retail 15/30/60% for 12/24/48 h), and a beta forum report says one Copper Bar was charged 1s, so there may be a minimum. The invoice is ground truth and picks that up; the formula only fills in for Item Keys never sold.
- **One deposit at risk per posting, flat.** Charges fast sellers for expiries they won't have, and doesn't grow with how far down the queue a unit is.
- **Reading `C_AuctionHouse.CalculateCommodityDeposit` in the Addon.** Possible later, if the fallback turns out to matter.

## Consequences

- No UI change: the deposit only shows inside profit and margin. A Holdings Sell's margin is its average profit per unit over the Vendor Price.
- `ah_deposit_share` checked in game 2026-09-28: Forever offers 2, 8 or 24 h (no 48 h) and charges floor(Vendor Price x 5%) x 1, 4 or 12, as Classic Era. So 0.60 is the 24 h rate, the default duration is 24 h, and there is no 1s minimum (one Copper Bar, 10c Vendor Price, costs 0c).
- Cancels aren't modelled; a cancelled posting loses its deposit too.
- `deposit` isn't part of what identifies a mail across Mailbox Reads, so a history built before it was kept still matches its live Sold mail. Those mails keep no deposit until `brain rebuild`.
