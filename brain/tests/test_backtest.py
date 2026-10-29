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
    ListingBuy,
    MarketRecommendations,
    MatYield,
    ReagentBuy,
    Row,
)

T0 = 1_790_000_000
HOUR = 3600
DAY = 24 * HOUR
LINEN = "2589"
SILK = "4306"

# 5% cut, 1c deposit a unit, vendors pay 10c, other players' cheapest ask 150c.
TERMS = Terms(
    cut=0.05,
    deposit=lambda item_key: 1,
    vendor=lambda item_key: 10,
    cheapest_ask=lambda item_key, at: 150,
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


@pytest.mark.parametrize(("hours", "deposits"), [(24, 0), (25, 1), (49, 2)])
def test_a_sold_unit_loses_a_deposit_for_every_24_hours_posting_it_waited_through(hours, deposits):
    times = (T0, T0 + hours * HOUR)

    result = run(
        {T0: [Buy(LINEN, units=1, cost=50, post_at=100)]}, [record(T0 + hours * HOUR)], times=times
    )

    assert result.trades[0].proceeds == pytest.approx(95 - deposits)


def test_a_lot_unsold_after_a_week_is_relisted_1c_under_the_cheapest_ask():
    times = (T0, T0 + 7 * DAY, T0 + 8 * DAY)

    result = run(
        {T0: [Buy(LINEN, units=1, cost=50, post_at=200)]},
        [record(T0 + 8 * DAY, unit=149)],
        times=times,
    )

    [trade] = result.trades
    assert trade.relisted
    # 7 deposits: it waited through the first 7 postings.
    assert trade.proceeds == pytest.approx(149 * 0.95 - 7)


def test_a_relisted_lot_still_unsold_after_another_week_is_vendored_less_a_deposit_a_day():
    times = (T0, T0 + 7 * DAY, T0 + 14 * DAY)

    result = run({T0: [Buy(LINEN, units=2, cost=100, post_at=200)]}, [], times=times)

    [trade] = result.trades
    assert trade.salvage == pytest.approx(2 * 10 - 2 * 14)
    assert result.gold == pytest.approx(10_000 - 100 + 2 * 10 - 2 * 14)


def test_a_lot_whose_relist_would_not_beat_its_vendor_price_is_vendored_after_a_week():
    terms = Terms(
        cut=0.05, deposit=lambda k: 1, vendor=lambda k: 150, cheapest_ask=lambda k, at: 150
    )
    times = (T0, T0 + 7 * DAY)

    result = simulate(
        list(times),
        scripted({T0: [Buy(LINEN, units=1, cost=50, post_at=200)]}),
        [],
        terms,
        start_gold=0,
    )

    [trade] = result.trades
    assert not trade.relisted
    assert trade.salvage == pytest.approx(150 - 7)


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
    # 2 days posted: 2 Deposits a unit lost either way.
    result = run(
        {T0: [Buy(LINEN, units=2, cost=100, post_at=post_at)]}, [], times=(T0, T0 + 2 * DAY)
    )

    [trade] = result.trades
    assert not trade.closed
    assert trade.profit() == pytest.approx(2 * 10 - 2 * 2 - 100)
    assert trade.profit(market=True) == pytest.approx(2 * market_unit - 2 * 2 - 100)
    assert result.gold == pytest.approx(10_000 - 100 + 2 * 10 - 2 * 2)


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


def history_row(quantity=1, unit=100):
    return {
        "itemString": LINEN_ITEM,
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


def test_the_lots_split_into_sold_out_in_week_1_relisted_and_the_rest():
    # Linen sells out on day 1, Silk only after its relist, and the Flip to Vendor is
    # done at once; the third Item Key never sells and is vendored after its week.
    times = (T0, T0 + DAY, T0 + 7 * DAY, T0 + 8 * DAY)
    ore = "2770"
    buys = {
        T0: [
            Buy(LINEN, 1, 50, 100),
            Buy(SILK, 1, 100, 200),
            Buy(ore, 0, 5, 0, back=10),
            Buy("2771", 1, 100, 140),
        ]
    }
    records = [record(T0 + DAY, unit=100), record(T0 + 8 * DAY, unit=149, item_key=SILK)]
    terms = Terms(
        cut=0.05,
        deposit=lambda k: 1,
        vendor=lambda k: 10,
        cheapest_ask=lambda k, at: 150 if k == SILK else 5,
    )

    result = simulate(list(times), scripted(buys), records, terms, start_gold=10_000)

    split = result.split()
    assert [t.item_key for t in split.sold_out_in_week_1] == [LINEN, ore]
    assert [t.item_key for t in split.relisted] == [SILK]
    assert [t.item_key for t in split.rest] == ["2771"]


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
    # Gold plus unsold units at cost: 1,000 at T0 (bought 4 for 400) and when relisted at
    # T0 + 7 days, then the lot is vendored for 4 x (10 - 14 Deposits) = -16: 584.
    times = (T0, T0 + 7 * DAY, T0 + 14 * DAY)
    result = run(
        {T0: [Buy(LINEN, units=4, cost=400, post_at=1000)]},
        [],
        times=times,
        start_gold=1000,
    )

    assert result.max_drawdown == pytest.approx(416 / 1000)


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
