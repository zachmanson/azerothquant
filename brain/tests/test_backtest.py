from dataclasses import replace
from pathlib import Path

import pytest

from brain.backtest import Buy, Terms, backtest, options_taken, simulate
from brain.config import Config, Era, Install
from brain.disenchant import Group
from brain.history import Market, import_character_reads, import_scans, open_history
from brain.observation import SaleRecord
from brain.recommend import (
    Action,
    DisenchantFlip,
    HoldingsAdvice,
    ListingBuy,
    MarketRecommendations,
    MatYield,
    ReagentBuy,
    Row,
    holdings_advice,
    recommend_market,
)

T0 = 1_790_000_000
HOUR = 3600
DAY = 24 * HOUR
LINEN = "2589"
SILK = "4306"


def advice(post_at=None, room=10**9, lost=lambda i: 0):
    """The Brain's Holdings advice at every Scan: by default keep every unit posted at its
    price."""
    return lambda item_key, at: HoldingsAdvice(post_at, room, lost)


# 5% cut, 1c deposit a unit, vendors pay 10c, other players' cheapest ask 150c.
TERMS = Terms(
    cut=0.05,
    deposit=lambda item_key: 1,
    vendor=lambda item_key: 10,
    cheapest_ask=lambda item_key, at: 150,
    holdings=advice(),
)


def scripted(buys_at):
    """A policy that buys what `buys_at` names at each Scan, whatever its gold."""
    return lambda at, gold, posted, tied_up: buys_at.get(at, [])


def record(at, unit=100, units=1, item_key=LINEN, last_seen=None):
    return SaleRecord(item_key, unit, units, at - HOUR if last_seen is None else last_seen, at)


def test_a_post_sells_to_a_later_sale_record_at_or_above_its_price_after_the_cut():
    result = simulate(
        [T0, T0 + HOUR],
        scripted({T0: [Buy(LINEN, units=2, cost=120, post_at=100)]}),
        [record(T0 + HOUR, unit=110, units=5)],
        TERMS,
        start_gold=1000,
    )

    [trade] = result.trades
    assert trade.sold == 2
    assert trade.proceeds == pytest.approx(2 * 95)
    assert result.gold == pytest.approx(1000 - 120 + 190)


def run(buys_at, records, times=(T0, T0 + HOUR), start_gold=10_000, **kwargs):
    return simulate(list(times), scripted(buys_at), records, TERMS, start_gold=start_gold, **kwargs)


def test_our_cheapest_post_fills_first():
    dear, cheap = (
        Buy(LINEN, units=1, cost=50, post_at=120),
        Buy(LINEN, units=1, cost=50, post_at=100),
    )

    result = run({T0: [dear, cheap]}, [record(T0 + HOUR, unit=130, units=1)])

    assert [t.sold for t in result.trades] == [0, 1]


def test_a_sale_record_under_our_price_sells_nothing():
    result = run({T0: [Buy(LINEN, units=1, cost=50, post_at=100)]}, [record(T0 + HOUR, unit=99)])

    assert result.trades[0].sold == 0


def test_a_sale_record_of_a_listing_gone_before_we_posted_sells_nothing():
    # Last seen in the Scan before ours, so it may have sold before we posted.
    times = (T0, T0 + HOUR, T0 + 2 * HOUR)
    late = record(T0 + 2 * HOUR, unit=100, last_seen=T0)

    result = run({T0 + HOUR: [Buy(LINEN, units=1, cost=50, post_at=100)]}, [late], times=times)

    assert result.trades[0].sold == 0


@pytest.mark.parametrize(("hours", "deposits"), [(10, 0), (30, 1), (60, 2)])
def test_a_sold_unit_loses_a_deposit_for_each_earlier_posting_that_expired(hours, deposits):
    # Postings from T0, T0 + 25 h and T0 + 50 h; the unit sells in the first, second or
    # third.
    times = (T0, T0 + 25 * HOUR, T0 + 50 * HOUR, T0 + 70 * HOUR)

    result = run(
        {T0: [Buy(LINEN, units=1, cost=50, post_at=100)]}, [record(T0 + hours * HOUR)], times=times
    )

    [trade] = result.trades
    assert (trade.postings, trade.deposits) == (deposits, deposits)
    assert trade.profit() == pytest.approx(95 - deposits - 50)


def test_a_posting_run_out_reposts_at_the_holdings_price_up_to_the_room_and_vendors_the_rest():
    # At the first Scan after the 24 h posting runs out, the Holdings advice posts at 180
    # with room for 2: those 2 repost, the third is vendored, and all 3 lost a Deposit.
    terms = replace(TERMS, holdings=advice(post_at=180, room=2))

    result = simulate(
        [T0, T0 + 25 * HOUR],
        scripted({T0: [Buy(LINEN, units=3, cost=150, post_at=200)]}),
        [],
        terms,
        start_gold=10_000,
    )

    [trade] = result.trades
    assert (trade.price, trade.posted_at, trade.left) == (180, T0 + 25 * HOUR, 2)
    assert (trade.vendored, trade.postings, trade.deposits) == (1, 1, 3)
    # The vendored one, and the 2 still posted marked at the vendor at the end.
    assert trade.salvage == 10 + 2 * 10
    assert result.gold == pytest.approx(10_000 - 150 - 3 + 10 + 2 * 10)


def test_a_unit_keeps_posting_only_while_it_beats_vendor_less_the_deposits_its_turn_loses():
    # 190 after the cut, 10 at the vendor; unit i of the queue expects to lose 100i: units
    # 0 and 1 beat the vendor, unit 2 (190 - 200) doesn't. No Holdings price (only our
    # own post up, say), so the 2 keep theirs.
    terms = replace(TERMS, holdings=advice(lost=lambda i: 100 * i))

    result = simulate(
        [T0, T0 + DAY],
        scripted({T0: [Buy(LINEN, units=3, cost=150, post_at=200)]}),
        [],
        terms,
        start_gold=10_000,
    )

    [trade] = result.trades
    assert (trade.price, trade.left, trade.vendored) == (200, 2, 1)


@pytest.mark.parametrize(("last_seen_hours", "sold"), [(23, 1), (24, 0), (26, 0)])
def test_a_sale_record_after_a_posting_ran_out_and_before_the_next_scan_sells_nothing(
    last_seen_hours, sold
):
    # The posting runs out at 24 h, but the next Scan is at 30 h: a Listing last seen up
    # at 24 h or later sold while ours was off the AH.
    late = record(T0 + 30 * HOUR, last_seen=T0 + last_seen_hours * HOUR)

    result = run(
        {T0: [Buy(LINEN, units=1, cost=50, post_at=100)]}, [late], times=(T0, T0 + 30 * HOUR)
    )

    [trade] = result.trades
    assert trade.sold == sold
    assert trade.proceeds == pytest.approx(95 * sold)  # sold in its first posting


def test_nothing_is_bought_after_the_last_buy():
    result = run(
        {T0: [Buy(LINEN, 1, 50, 100)], T0 + HOUR: [Buy(SILK, 1, 50, 100)]}, [], last_buy=T0
    )

    assert [t.item_key for t in result.trades] == [LINEN]


def test_an_item_key_still_posted_is_not_bought_again_and_the_policy_is_told():
    told = []

    def policy(at, gold, posted, tied_up):
        told.append(posted)
        return (
            [Buy(LINEN, 1, 50, 100), Buy(SILK, 1, 50, 100)]
            if at == T0 + HOUR
            else [Buy(LINEN, 1, 50, 100)]
        )

    result = simulate([T0, T0 + HOUR], policy, [], TERMS, start_gold=10_000)

    assert [t.item_key for t in result.trades] == [LINEN, SILK]
    assert told == [frozenset(), frozenset({LINEN})]


def test_the_policy_is_told_what_its_units_still_unsold_cost():
    # #170: the Stake's own Listings up at cost. 1 of the 4 Linen bought for 400 sold.
    told = []

    def policy(at, gold, posted, tied_up):
        told.append(tied_up)
        return [Buy(LINEN, 4, 400, 100)] if at == T0 else []

    simulate([T0, T0 + HOUR], policy, [record(T0 + HOUR, unit=110)], TERMS, start_gold=10_000)

    assert told == [0, 300]


@pytest.mark.parametrize(("post_at", "market_unit"), [(200, 149 * 0.95), (100, 100 * 0.95)])
def test_units_still_posted_at_the_end_are_marked_at_vendor_and_at_market(post_at, market_unit):
    # 2 days posted but one Scan after the 24 h ran out: one posting expired, so 1 Deposit a
    # unit lost either way.
    result = run(
        {T0: [Buy(LINEN, units=2, cost=100, post_at=post_at)]}, [], times=(T0, T0 + 2 * DAY)
    )

    [trade] = result.trades
    assert not trade.closed
    assert trade.profit() == pytest.approx(2 * 10 - 2 * 1 - 100)
    assert trade.profit(market=True) == pytest.approx(2 * market_unit - 2 * 1 - 100)
    assert result.gold == pytest.approx(10_000 - 100 + 2 * 10 - 2 * 1)


def test_gold_a_buy_brings_back_at_once_is_its_proceeds():
    # A Flip to Vendor: nothing posted, every unit vendored as bought.
    result = run({T0: [Buy(LINEN, units=0, cost=50, post_at=0, back=80)]}, [])

    [trade] = result.trades
    assert trade.closed
    assert trade.profit() == trade.profit(market=True) == 30
    assert result.gold == 10_000 + 30


# --- the Brain backtested on a history ---

REALM = "Classic Beta PvP"
MARKET = Market(realm=REALM, faction="Alliance", era=Era.BETA)
LINEN_ITEM = "item:2589::::::::20:1490"
# No priors, so hourly Scans make a Sell Rate taken at its word.
CONFIG = replace(
    Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),)),
    sale_horizon_seconds=3 * HOUR,
    sell_rate_prior_hours_holdings=0,
    sell_rate_prior_hours_flips=0,
    sale_size_prior_events_holdings=0,
    sale_size_prior_events_flips=0,
    flip_min_sale_events=1,
    risk_caps=False,  # sized by the gold alone, as written (ADR-0034)
    row_min_profit_share=0.0,  # no Minimum Profit (#197), as written
    row_min_profit_copper=0,
    row_min_profit_per_click=0,
)


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def history_scan(at, *rows):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "droppedRows": 0,
        "listings": list(rows),
        "vendorPrices": {},
    }


def history_row(quantity=1, unit=100, item_id="2589"):
    return {
        "itemString": f"item:{item_id}::::::::20:1490",
        "quantity": quantity,
        "buyout": quantity * unit,
        "timeLeft": 4,
    }


def test_the_brain_buys_with_its_simulated_gold_and_is_graded_by_the_sale_records_after(db):
    # 2 Linen sell at 1000 each hour. At T0 + 1 h, 5 turn up at 200: the Brain, with no gold
    # of its own but 10,000 simulated, buys them and posts at 999. The 2 that sell in the
    # next hour are over 1.2x that Scan's Fair Value (200), so not believed; the 4 after
    # take 4 of its 5, and the last is marked at the end.
    scans = [
        history_scan(T0, history_row(quantity=20, unit=1000)),
        history_scan(
            T0 + HOUR, history_row(quantity=18, unit=1000), history_row(quantity=5, unit=200)
        ),
        history_scan(T0 + 2 * HOUR, history_row(quantity=16, unit=1000)),
        history_scan(T0 + 3 * HOUR, history_row(quantity=14, unit=1000)),
        history_scan(T0 + 4 * HOUR, history_row(quantity=12, unit=1000)),
    ]
    read = {
        "readAt": T0,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 0,
        "bags": [],
        "vendorPrices": {"2589": 10},
    }
    import_scans(db, scans, Era.BETA, CONFIG)
    import_character_reads(db, [read], Era.BETA, CONFIG)

    [result] = backtest(db, CONFIG, [], start_gold=10_000, no_buys_in_last_seconds=0)

    assert result.market == MARKET
    [trade] = result.runs["brain"].trades
    assert (trade.item_key, trade.units, trade.price, trade.sold) == (LINEN, 5, 999, 4)
    assert trade.profit() == pytest.approx(4 * 999 * 0.95 + 10 - 5 * 200)
    # The grader's bounds: 0.65 and 1.2 of each of the 2 believed records of 2 units.
    low, high = result.bounds["brain"]
    assert [t.sold for t in low.trades] == pytest.approx([2 * 2 * 0.65])
    assert [t.sold for t in high.trades] == pytest.approx([2 * 2 * 1.2])
    # No own Listings, so nothing to check the grader on.
    assert (result.grader_calibration.matched, result.grader_calibration.sold_mails) == (0, 0)
    assert (result.sell_rate_calibration.matched, result.sell_rate_calibration.sold_mails) == (0, 0)


def test_the_holdings_advice_the_backtest_exits_by_is_the_brains_holdings_rows(db):
    # #204: 2 Linen sell at 1000 each hour, so with a 3 h Sale Horizon 6 of the 10 held
    # Sell, posted 1c under, and 4 are Vendored.
    at = T0 + 3 * HOUR
    scans = [
        history_scan(T0 + h * HOUR, history_row(quantity=20 - 2 * h, unit=1000)) for h in range(4)
    ]
    linen = {
        "bag": 0,
        "slot": 1,
        "count": 10,
        "isBound": False,
        "link": "|cffffffff|Hitem:2589::::::::20:1490|h[Linen Cloth]|h|r",
    }
    read = {
        "readAt": T0,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 0,
        "bags": [linen],
        "vendorPrices": {"2589": 10},
    }
    import_scans(db, scans, Era.BETA, CONFIG)
    import_character_reads(db, [read], Era.BETA, CONFIG)

    advice = holdings_advice(db, CONFIG, MARKET)(LINEN, at)
    rows = recommend_market(db, CONFIG, MARKET, [], at, as_of=at, buy_under=False).holdings

    assert [(r.action, r.quantity, r.price) for r in rows] == [
        (Action.SELL, 6, 999),
        (Action.VENDOR, 4, 10),
    ]
    assert (advice.post_at, advice.room, advice.lost(5)) == (999, 6, 0)


def test_the_brains_risk_caps_are_on_its_simulated_stake_and_uncapped_has_none(db):
    # #170, ADR-0034: 2 Linen turn up at 2s and 3 at 4s. Posted at 9s 99c, all 5 would
    # lose 15s 80c unsold (16s less 50c at the Vendor Price, plus 30c of Deposits), over
    # 5% of the 1g Stake. The 2 at 2s lose 3s 92c, posted 1c under the 4s.
    scans = [
        history_scan(T0, history_row(quantity=20, unit=1000)),
        history_scan(
            T0 + HOUR,
            history_row(quantity=18, unit=1000),
            history_row(quantity=2, unit=200),
            history_row(quantity=3, unit=400),
        ),
        history_scan(T0 + 2 * HOUR, history_row(quantity=16, unit=1000)),
    ]
    read = {
        "readAt": T0,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 0,
        "bags": [],
        "vendorPrices": {"2589": 10},
    }
    capped = replace(CONFIG, risk_caps=True, flip_unsold_loss_share=0.05)
    import_scans(db, scans, Era.BETA, capped)
    import_character_reads(db, [read], Era.BETA, capped)

    [result] = backtest(
        db,
        capped,
        [],
        policies=("brain", "uncapped"),
        start_gold=10_000,
        no_buys_in_last_seconds=0,
    )

    [brain] = result.runs["brain"].trades
    assert (brain.units, brain.price) == (2, 399)
    [uncapped] = result.runs["uncapped"].trades
    assert (uncapped.units, uncapped.price) == (5, 999)


ORE_ITEM = "item:2770::::::::20:1490"


@pytest.mark.parametrize(
    ("dump", "policy", "linen"),
    [
        # Nothing else under the 9s 99c it was valued at: bought, posted at that.
        (False, "buyunder", [(2, 1400, 999)]),
        (False, "buyunder_unchecked", [(2, 1400, 999)]),
        # 5 more turned up at 9s 50c: the market moved, so it's left alone, or unchecked
        # bought and posted 1c under them.
        (True, "buyunder", []),
        (True, "buyunder_unchecked", [(2, 1400, 949)]),
    ],
)
def test_the_buy_under_policies_buy_under_the_previous_scans_buy_unders(db, dump, policy, linen):
    # #173: at T0 + 1 h, Linen has a Sell way (it sold under the 10s) and Ore a Vendor way
    # (a 10s Vendor Price, so 8s 33c). At T0 + 2 h, 2 Linen at 7s and 3 Ore at 5s are up.
    ore = {"itemString": ORE_ITEM, "quantity": 3, "buyout": 1500, "timeLeft": 4}
    scans = [
        history_scan(T0, history_row(quantity=20, unit=1000), history_row(quantity=5, unit=500)),
        history_scan(
            T0 + HOUR, history_row(quantity=18, unit=1000), {**ore, "quantity": 1, "buyout": 500}
        ),
        history_scan(
            T0 + 2 * HOUR,
            history_row(quantity=16, unit=1000),
            history_row(quantity=2, unit=700),
            *([history_row(quantity=5, unit=950)] if dump else []),
            ore,
        ),
    ]
    read = {
        "readAt": T0,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 0,
        "bags": [],
        "vendorPrices": {"2589": 10, "2770": 1000},
    }
    import_scans(db, scans, Era.BETA, CONFIG)
    import_character_reads(db, [read], Era.BETA, CONFIG)

    [result] = backtest(
        db, CONFIG, [], policies=(policy,), start_gold=10_000, no_buys_in_last_seconds=0
    )

    trades = result.runs[policy].trades
    assert [(t.units, t.cost, t.price) for t in trades if t.way is Action.SELL] == linen
    [vendored] = [t for t in trades if t.way is Action.VENDOR]
    assert (vendored.item_key, vendored.units, vendored.cost, vendored.profit()) == (
        "2770",
        0,
        1500,
        1500,
    )


def test_the_minimum_profit_holds_but_in_the_relaxed_policy(db):
    # #197: the 5 Linen above, posted at 9s 99c, make 31s 45c. A 40s Minimum Profit leaves
    # them off for the Brain and uncapped alike; relaxed loosens every buy-side gate and
    # takes them.
    scans = [
        history_scan(T0, history_row(quantity=20, unit=1000)),
        history_scan(
            T0 + HOUR,
            history_row(quantity=18, unit=1000),
            history_row(quantity=2, unit=200),
            history_row(quantity=3, unit=400),
        ),
        history_scan(T0 + 2 * HOUR, history_row(quantity=16, unit=1000)),
    ]
    read = {
        "readAt": T0,
        "realm": REALM,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 0,
        "bags": [],
        "vendorPrices": {"2589": 10},
    }
    config = replace(CONFIG, row_min_profit_copper=4000)
    import_scans(db, scans, Era.BETA, config)
    import_character_reads(db, [read], Era.BETA, config)

    [result] = backtest(
        db,
        config,
        [],
        policies=("brain", "uncapped", "relaxed"),
        start_gold=10_000,
        no_buys_in_last_seconds=0,
    )

    assert result.runs["brain"].trades == []
    assert result.runs["uncapped"].trades == []
    assert [t.units for t in result.runs["relaxed"].trades] == [5]


# --- the Auctionator baseline (#196, ADR-0039) ---

SELLER_READ = {
    "readAt": T0,
    "realm": REALM,
    "character": "Kash-Patel",
    "faction": "Alliance",
    "money": 0,
    "bags": [],
    "vendorPrices": {"2589": 10, "2770": 10},
}


def auctionator_trades(db, scans, start_gold=10_000, config=CONFIG, read=SELLER_READ):
    import_scans(db, scans, Era.BETA, config)
    import_character_reads(db, [read], Era.BETA, config)
    [result] = backtest(
        db,
        config,
        [],
        policies=("auctionator",),
        start_gold=start_gold,
        no_buys_in_last_seconds=0,
    )
    return [(t.item_key, t.units, t.cost, t.price) for t in result.runs["auctionator"].trades]


def test_auctionator_buys_the_cheapest_ask_and_posts_1c_under_the_next_lowest(db):
    # At T0, Linen has one ask, so nothing under a next-lowest. At T0 + 1 h, 2 Listings of
    # 1 at 2s sit far under the 10s: both are bought and posted at 9s 99c.
    scans = [
        history_scan(T0, history_row(quantity=20, unit=1000)),
        history_scan(
            T0 + HOUR,
            history_row(quantity=18, unit=1000),
            history_row(quantity=1, unit=200),
            history_row(quantity=1, unit=200),
        ),
    ]

    assert auctionator_trades(db, scans) == [(LINEN, 2, 400, 999)]


@pytest.mark.parametrize(("cheapest", "bought"), [(800, [("2770", 1, 800, 999)]), (900, [])])
def test_auctionator_buys_only_when_the_next_ask_beats_the_cheapest_by_the_cut_and_deposit(
    db, cheapest, bought
):
    # Posted at 9s 99c, an Ore brings 9s 49.05c after the 5% cut, less a 50c Deposit:
    # 8s 99.05c. That beats an 8s ask, but not a 9s one, though the cut alone would.
    config = replace(CONFIG, ah_deposit_share=1.0, ah_deposit_min_copper=0)
    read = {**SELLER_READ, "vendorPrices": {"2589": 10, "2770": 50}}
    scans = [
        history_scan(
            T0,
            history_row(quantity=5, unit=1000, item_id="2770"),
            history_row(unit=cheapest, item_id="2770"),
        )
    ]

    assert auctionator_trades(db, scans, config=config, read=read) == bought


def test_auctionator_spends_at_most_a_fifth_of_its_stake_on_an_item_key(db):
    # From 10s, a fifth is 2s: 2 of the 3 Linen at 80c. Then 8s 40c of gold and 1s 60c
    # posted still make a 10s Stake, so 2 of the 3 Ore at 90c fit too (not on the gold
    # alone: a fifth of 8s 40c is 1s 68c).
    scans = [
        history_scan(
            T0, history_row(quantity=5, unit=1000), *[history_row(unit=80) for _ in range(3)]
        ),
        history_scan(
            T0 + HOUR,
            history_row(quantity=5, unit=1000, item_id="2770"),
            *[history_row(unit=90, item_id="2770") for _ in range(3)],
        ),
    ]

    assert auctionator_trades(db, scans, start_gold=1000) == [
        (LINEN, 2, 160, 999),
        ("2770", 2, 180, 999),
    ]


def test_auctionator_buys_at_most_a_stack_of_an_item_key(db):
    # 30 Listings of 1 Linen at 1c, far under the 10s and well within a fifth of 10s: a
    # stack of 20 is bought, not all 30.
    rows = [history_row(quantity=5, unit=1000), *[history_row(unit=1) for _ in range(30)]]

    assert auctionator_trades(db, [history_scan(T0, *rows)]) == [(LINEN, 20, 20, 999)]


def test_auctionator_spends_its_gold_most_profit_first_and_the_last_on_what_fits(db):
    # 6 Item Keys each have 2 at 1s under a next ask of 10s to 15s, within a fifth of 11s:
    # the 5 with the most profit take 10s, and the 1s left buys 1 of the Linen under 10s.
    ids = ["2589", "2770", "2771", "2772", "2775", "2776"]
    rows = [
        row
        for i, item_id in enumerate(ids)
        for row in (
            history_row(unit=100, item_id=item_id),
            history_row(unit=100, item_id=item_id),
            history_row(unit=1000 + 100 * i, item_id=item_id),
        )
    ]

    trades = auctionator_trades(db, [history_scan(T0, *rows)], start_gold=1100)

    assert [(item_key, units, price) for item_key, units, _, price in trades] == [
        ("2776", 2, 1499),
        ("2775", 2, 1399),
        ("2772", 2, 1299),
        ("2771", 2, 1199),
        ("2770", 2, 1099),
        (LINEN, 1, 999),
    ]


def test_auctionator_leaves_its_gold_for_others_than_the_item_keys_it_still_has_posted(db):
    # The 2 Linen it bought at T0 are still up in the Scan at T0 + 1 h (the Scans don't
    # show our buys), with the most profit, but the 8s left all go on the other 4.
    others = ["2770", "2771", "2772", "2775"]
    linen = [history_row(unit=100), history_row(unit=100), history_row(unit=2000)]
    scans = [
        history_scan(T0, *linen),
        history_scan(
            T0 + HOUR,
            *linen,
            *[
                row
                for item_id in others
                for row in (
                    history_row(unit=100, item_id=item_id),
                    history_row(unit=100, item_id=item_id),
                    history_row(unit=1000, item_id=item_id),
                )
            ],
        ),
    ]

    trades = auctionator_trades(db, scans, start_gold=1000)

    assert sorted(item_key for item_key, *_ in trades) == ["2589", *others]


def test_the_lots_split_into_sold_out_part_vendored_and_still_posted():
    # Linen sells out in its first posting and the Flip to Vendor is done at once. The
    # Holdings advice has room for 1 Silk only: when its first posting runs out, 1 of 2 is
    # vendored and the other sells in its second. The fourth is still posted at the end.
    times = (T0, T0 + DAY, T0 + 2 * DAY)
    ore = "2770"
    buys = {
        T0: [
            Buy(LINEN, 1, 50, 100),
            Buy(SILK, 2, 100, 200),
            Buy(ore, 0, 5, 0, back=10),
        ],
        T0 + DAY: [Buy("2771", 1, 100, 140)],
    }
    records = [record(T0 + HOUR, unit=100), record(T0 + 2 * DAY, unit=200, item_key=SILK)]
    rooms = {SILK: 1}
    terms = replace(
        TERMS, holdings=lambda k, at: HoldingsAdvice(None, rooms.get(k, 99), lambda i: 0)
    )

    result = simulate(list(times), scripted(buys), records, terms, start_gold=10_000)

    split = result.split()
    assert [t.item_key for t in split.sold_out] == [LINEN, ore]
    assert [t.item_key for t in split.part_vendored] == [SILK]
    assert [t.item_key for t in split.still_posted] == ["2771"]
    assert [(t.postings, t.deposits) for t in split.part_vendored] == [(1, 2)]


@pytest.mark.parametrize(("share", "sold"), [(0.65, 6.5), (1.2, 10)])
def test_the_grader_believes_only_its_share_of_each_records_units(share, sold):
    # 10 posted; a record of 10 units fills 6.5 at 0.65x, and all 10 (not 12) at 1.2x.
    result = run(
        {T0: [Buy(LINEN, units=10, cost=500, post_at=100)]},
        [record(T0 + HOUR, unit=100, units=10)],
        grade_share=share,
    )

    assert result.trades[0].sold == pytest.approx(sold)


def test_the_gold_low_is_the_least_gold_after_a_scans_buys():
    # 1,000 -> 600 after buying at T0; the sale at T0 + 1 h brings 95 back.
    result = run(
        {T0: [Buy(LINEN, units=4, cost=400, post_at=100)]},
        [record(T0 + HOUR, unit=100, units=1)],
        start_gold=1000,
    )

    assert result.gold_low == pytest.approx(600)


def test_the_max_drawdown_is_the_deepest_fall_from_a_peak_of_gold_and_unsold_units_at_cost():
    # Gold plus unsold units at cost: 1,000 at T0 (bought 4 for 400), then the Holdings
    # advice has no room after the first posting, and the lot is vendored for
    # 4 x (10 - 1 Deposit) = 36: 636.
    result = simulate(
        [T0, T0 + DAY],
        scripted({T0: [Buy(LINEN, units=4, cost=400, post_at=1000)]}),
        [],
        replace(TERMS, holdings=advice(room=0)),
        start_gold=1000,
    )

    assert result.max_drawdown == pytest.approx(364 / 1000)


# --- the options a player would take ---

GREENS = Group(2, "armor", 16, 20, ())
DUST_KEY = "10940"


def flip_to_disenchant(profit=500):
    """A Flip to Disenchant of 2 Green Chests (9999) and another green (9998)."""
    flip = DisenchantFlip(
        GREENS, (ListingBuy("9999", 100), ListingBuy("9998", 150), ListingBuy("9999", 300))
    )
    return Row(
        "",
        Action.DISENCHANT,
        3,
        price=300,
        profit=profit,
        cost=550,
        character="Bob",
        mats=(MatYield(DUST_KEY, 5.625),),
        listings=3,
        disenchant=flip,
    )


def test_a_taken_flip_to_disenchant_blocks_later_options_on_its_items_or_mats():
    dust_craft = Row(DUST_KEY, Action.CRAFT, 1, profit=300, cost=50, buys=(ReagentBuy("2", 1, 50),))
    other_green = Row("9998", Action.SELL, 1, price=160, profit=200, cost=160)
    linen = Row("2589", Action.SELL, 1, price=10, profit=100, cost=10)
    m = MarketRecommendations(
        MARKET, T0, 10000, shopping_list=[flip_to_disenchant(), dust_craft, other_green, linen]
    )

    # A Flip to Disenchant isn't one of the Flips to Sell and Vendor the row cap counts.
    shopping, _ = options_taken(m, flip_rows=2)

    assert shopping == [flip_to_disenchant(), linen]


def test_options_are_taken_while_the_room_lasts_as_well_as_the_gold():
    # #170, ADR-0034: 1g of gold but 50s of room, so after the 40s Ore only the 10s Linen
    # fits, not the 30s Bolt.
    ore = Row("2770", Action.SELL, 4, price=10, profit=300, cost=4000)
    bolt = Row("2996", Action.SELL, 3, price=10, profit=200, cost=3000)
    linen = Row("2589", Action.SELL, 1, price=10, profit=100, cost=1000)
    m = MarketRecommendations(MARKET, T0, 10000, room=5000, shopping_list=[ore, bolt, linen])

    shopping, _ = options_taken(m, flip_rows=50)

    assert shopping == [ore, linen]


def test_a_risky_row_is_never_taken_nor_counted_in_the_rows_kept():
    # #194, ADR-0037: the Backtest takes only the rows the risk caps leave. The
    # Risky Ore is the most profit, but it's skipped and takes none of the 2 places, so both
    # the Bolt and the Linen are taken.
    ore = Row("2770", Action.SELL, 4, price=10, profit=300, cost=4000, risky=True)
    bolt = Row("2996", Action.SELL, 3, price=10, profit=200, cost=3000)
    linen = Row("2589", Action.SELL, 1, price=10, profit=100, cost=1000)
    m = MarketRecommendations(MARKET, T0, 10000, shopping_list=[ore, bolt, linen])

    shopping, _ = options_taken(m, flip_rows=2)

    assert shopping == [bolt, linen]


def test_a_risky_row_for_too_few_sale_events_is_never_taken_nor_counted():
    # #224, ADR-0043: as above, for a Risky row a Flip to Sell under the minimum of Sale
    # Events gets.
    boe = Row(
        "4827", Action.SELL, 1, price=1600, profit=662399, cost=1600, risky=True, sales_seen=0
    )
    bolt = Row("2996", Action.SELL, 3, price=10, profit=200, cost=3000)
    linen = Row("2589", Action.SELL, 1, price=10, profit=100, cost=1000)
    m = MarketRecommendations(MARKET, T0, 10000, shopping_list=[boe, bolt, linen])

    shopping, _ = options_taken(m, flip_rows=2)

    assert shopping == [bolt, linen]
