import subprocess
from dataclasses import replace
from pathlib import Path

from brain import __version__
from brain.beta_prior import BetaPrice, BetaPrior
from brain.config import Config, Era, Install
from brain.disenchant import Group
from brain.history import Market, open_history
from brain.recommend import (
    Action,
    BetaRoom,
    Blocked,
    BlockReason,
    BuyUnder,
    ChainNode,
    CharacterHolding,
    DisenchantFlip,
    ListingBuy,
    LootAlert,
    LootValue,
    MarketRecommendations,
    MatYield,
    NodeKind,
    ReagentBuy,
    ReagentUse,
    Row,
    SubCraft,
    _Caps,
    _HoldBuy,
    _spend_on_predictions,
)
from brain.recommendations import (
    FILE_NAME,
    GLOBAL_NAME,
    _row,
    addon_folder,
    render,
    write_recommendations,
)
from brain.savedvariables import parse_savedvariables

ADDON = Path(__file__).parents[2] / "addon" / "AzerothQuant"


def _load_in_lua(lua: str, file: Path) -> str:
    """Load the file the way the client does and describe what it defined."""
    script = (
        f"dofile([==[{file}]==]) "
        f"local r = {GLOBAL_NAME} "
        "local out = {} "
        "for realm, byFaction in pairs(r.lastImported) do "
        "  for faction, at in pairs(byFaction) do "
        "    out[#out + 1] = realm .. '/' .. faction .. '=' .. at "
        "  end "
        "end "
        "table.sort(out) "
        "print(type(r.recommendations), table.concat(out, ';'))"
    )
    return subprocess.run(
        [lua, "-e", script], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_the_addon_ships_a_file_that_loads(lua):
    # The client only picks up files that exist when it starts, so the Addon ships a stub
    # for the Brain to overwrite. (With the Addon symlinked into WoW, this reads whatever
    # the Brain last wrote, which must load too.)
    assert _load_in_lua(lua, ADDON / FILE_NAME).startswith("table")


def test_a_real_lua_reads_the_last_imported_times(tmp_path, lua):
    file = tmp_path / FILE_NAME
    file.write_text(
        render(
            {
                Market("Quel'Thalas", "Horde", Era.BETA): 1790000000,
                Market("Quel'Thalas", "Neutral", Era.BETA): 1790000100,
                Market('Say "hi"', "Alliance", Era.BETA): 1790000200,
            }
        ),
        encoding="utf-8",
    )

    assert _load_in_lua(lua, file) == (
        "table\tQuel'Thalas/Horde=1790000000;Quel'Thalas/Neutral=1790000100;"
        'Say "hi"/Alliance=1790000200'
    )


def _run_in_lua(lua: str, file: Path, body: str) -> str:
    """Load the file the way the client does, then run `body` with it as `r`."""
    script = f"dofile([==[{file}]==]) local r = {GLOBAL_NAME} {body}"
    return subprocess.run(
        [lua, "-e", script], capture_output=True, text=True, check=True
    ).stdout.strip()


MARKET = Market("Quel'Thalas", "Horde", Era.BETA)


def test_a_real_lua_reads_a_markets_recommendations(tmp_path, lua):
    file = tmp_path / FILE_NAME
    file.write_text(
        render(
            {},
            markets=[
                MarketRecommendations(
                    market=MARKET,
                    as_of=1790000000,
                    gold=123456,
                    window_hours=2.5,
                    holdings=[
                        Row(
                            item_key="4359",
                            action=Action.SELL,
                            quantity=32,
                            price=169.0,
                            profit=5139.0,
                            margin=149.0,
                            sale_events=41,
                            sibling_sales=3,
                        )
                    ],
                    budget=100000,
                    prediction_cost=0,
                )
            ],
        ),
        encoding="utf-8",
    )

    out = _run_in_lua(
        lua,
        file,
        'local m = r.recommendations["Quel\'Thalas"].Horde '
        "local h = m.holdings[1] "
        "print(m.asOf, m.gold, m.windowHours, m.budget, m.predictionCost, #m.holdings) "
        "print(h.itemKey, h.action, h.quantity, h.price, h.profit, h.margin, h.saleEvents, "
        "h.siblingSales)",
    )

    assert out.splitlines() == [
        "1790000000	123456	2.5	100000	0	1",
        "4359	Sell	32	169	5139	149	41	3",
    ]


def test_every_kind_of_row_reaches_lua_with_absent_values_as_nil(tmp_path, lua):
    file = tmp_path / FILE_NAME
    file.write_text(
        render(
            {},
            markets=[
                MarketRecommendations(
                    market=MARKET,
                    as_of=1790000000,
                    gold=500000,
                    holdings=[
                        Row(item_key="1179", action=None, quantity=4, note="no data"),
                        Row(
                            item_key="2996",
                            action=Action.CRAFT,
                            quantity=3,
                            profit=42.0,
                            note="on Kash-Patel: uses 6 of 2589",
                        ),
                        Row(
                            item_key="12360",
                            action=Action.HOLD,
                            quantity=5,
                            cost=90000.0,
                            prediction="BWL opens",
                        ),
                    ],
                    shopping_list=[
                        Row(
                            item_key="2589",
                            action=Action.SELL,
                            quantity=20,
                            price=15.0,
                            profit=300.0,
                            post_at=40.0,
                            cost=300.0,
                            sale_events=12,
                        )
                    ],
                    prediction_buys=[
                        Row(
                            item_key="12359",
                            action=Action.HOLD,
                            quantity=10,
                            price=800.0,
                            cost=8000.0,
                            prediction="BWL opens",
                            max_loss=1500.0,
                        )
                    ],
                    prediction_cost=8000,
                )
            ],
        ),
        encoding="utf-8",
    )

    fields = (
        "itemKey action quantity price profit postAt margin saleEvents note cost prediction maxLoss"
    )
    out = _run_in_lua(
        lua,
        file,
        'local m = r.recommendations["Quel\'Thalas"].Horde '
        "local function show(row) "
        "  local out = {} "
        f"  for field in ('{fields}'):gmatch('%S+') do out[#out + 1] = tostring(row[field]) end "
        "  print(table.concat(out, '|')) "
        "end "
        "for _, list in ipairs({m.holdings, m.shoppingList, m.predictionBuys}) do "
        "  for _, row in ipairs(list) do show(row) end "
        "end",
    )

    assert out.splitlines() == [
        "1179|nil|4|nil|nil|nil|nil|nil|no data|nil|nil|nil",
        "2996|Craft|3|nil|42|nil|nil|nil|on Kash-Patel: uses 6 of 2589|nil|nil|nil",
        "12360|Hold|5|nil|nil|nil|nil|nil|nil|90000|BWL opens|nil",
        "2589|Sell|20|15|300|40|nil|12|nil|300|nil|nil",
        "12359|Hold|10|800|nil|nil|nil|nil|nil|8000|BWL opens|1500",
    ]


def test_a_real_lua_reads_which_prediction_buys_room_came_partly_from_beta(tmp_path, lua):
    def buy(item_key: str, beta_room: BetaRoom | None) -> Row:
        return Row(
            item_key=item_key,
            action=Action.HOLD,
            quantity=10,
            price=800.0,
            prediction="BWL opens",
            max_loss=1500.0,
            beta_room=beta_room,
        )

    file = tmp_path / FILE_NAME
    file.write_text(
        render(
            {},
            markets=[
                MarketRecommendations(
                    market=MARKET,
                    as_of=1790000000,
                    gold=500000,
                    prediction_buys=[
                        buy("12359", BetaRoom(post_at=900.0, room=12, from_beta=4)),
                        # A quiet Beta watered Live's rate down: no room came from it.
                        buy("12360", BetaRoom(post_at=900.0, room=8, from_beta=-2)),
                        buy("12361", BetaRoom(post_at=900.0, room=10, from_beta=0)),
                        buy("12362", None),
                    ],
                    prediction_cost=32000,
                )
            ],
        ),
        encoding="utf-8",
    )

    out = _run_in_lua(
        lua,
        file,
        'for _, row in ipairs(r.recommendations["Quel\'Thalas"].Horde.predictionBuys) do '
        "  print(row.itemKey, tostring(row.roomFromBeta)) "
        "end",
    )

    assert out.splitlines() == [
        "12359	true",
        "12360	nil",
        "12361	nil",
        "12362	nil",
    ]


def test_a_real_lua_reads_a_flip_to_crafts_reagent_buys(tmp_path, lua):
    file = tmp_path / FILE_NAME
    file.write_text(
        render(
            {},
            markets=[
                MarketRecommendations(
                    market=MARKET,
                    as_of=1790000000,
                    gold=500000,
                    shopping_list=[
                        Row(
                            item_key="2996",
                            action=Action.CRAFT,
                            quantity=6,
                            profit=4500.0,
                            post_at=999.0,
                            cost=1250.0,
                            note="on Kash-Patel: uses 12 of 2589 (buy 12), 6 of 2320 (buy 5)",
                            buys=(
                                ReagentBuy("2589", 12, 100),
                                ReagentBuy("2320", 5, 10.0, merchant=True),
                            ),
                            character="Kash-Patel",
                            uses=(ReagentUse("2320", 1),),
                        )
                    ],
                )
            ],
        ),
        encoding="utf-8",
    )

    out = _run_in_lua(
        lua,
        file,
        'local row = r.recommendations["Quel\'Thalas"].Horde.shoppingList[1] '
        "print(row.action, row.quantity, row.postAt, row.cost, #row.buys) "
        "for _, b in ipairs(row.buys) do "
        "  print(b.itemKey, b.quantity, b.maxUnitPrice, tostring(b.merchant)) "
        "end "
        "print(row.character, #row.uses) "
        "for _, u in ipairs(row.uses) do print(u.itemKey, u.quantity) end",
    )

    assert out.splitlines() == [
        "Craft	6	999	1250	2",
        "2589	12	100	nil",
        "2320	5	10	true",
        "Kash-Patel	1",
        "2320	1",
    ]


def test_a_real_lua_reads_a_holdings_paid_and_roi(tmp_path, lua):
    file = tmp_path / FILE_NAME
    sell = Row("2589", Action.SELL, 12, price=99, paid=50.0, paid_units=5, roi=0.881, roi_hint=True)
    vendor = Row("2589", Action.VENDOR, 8, price=10, paid=50.0, paid_units=5, roi=-0.8)
    file.write_text(
        render({}, markets=[MarketRecommendations(MARKET, 1790000000, 0, holdings=[sell, vendor])]),
        encoding="utf-8",
    )

    out = _run_in_lua(
        lua,
        file,
        'for _, row in ipairs(r.recommendations["Quel\'Thalas"].Horde.holdings) do '
        "  print(row.action, row.paid, row.paidUnits, row.roi, tostring(row.roiHint)) "
        "end",
    )

    assert out.splitlines() == [
        "Sell	50	5	0.881	true",
        "Vendor	50	5	-0.8	nil",
    ]


def test_a_real_lua_reads_a_flips_listings_posts_and_days(tmp_path, lua):
    # #98: a Flip to Vendor sells now, so it has no days.
    file = tmp_path / FILE_NAME
    sell = Row("2589", Action.SELL, 5, price=500, profit=2000, cost=2500)
    sell = replace(sell, listings=2, posts=3, days=2.5)
    vendor = replace(
        Row("2770", Action.VENDOR, 4, price=5, profit=20, cost=20), listings=3, posts=0
    )
    file.write_text(
        render(
            {}, markets=[MarketRecommendations(MARKET, 1790000000, 0, shopping_list=[sell, vendor])]
        ),
        encoding="utf-8",
    )

    out = _run_in_lua(
        lua,
        file,
        'for _, row in ipairs(r.recommendations["Quel\'Thalas"].Horde.shoppingList) do '
        "  print(row.action, row.listings, row.posts, tostring(row.days)) "
        "end",
    )

    assert out.splitlines() == [
        "Sell	2	3	2.5",
        "Vendor	3	0	nil",
    ]


def test_a_real_lua_reads_why_a_craft_is_blocked(tmp_path, lua):
    # The Addon names the reagent (#75), so the reason goes as fields, not text.
    file = tmp_path / FILE_NAME
    no_data = Row(
        "2996",
        Action.CRAFT,
        0,
        note="on Kash-Patel: no data for 2770",
        character="Kash-Patel",
        blocked=Blocked(BlockReason.NO_DATA, "2770"),
    )
    unknown = Row(
        "2997",
        Action.CRAFT,
        0,
        note="on Kash-Patel: unknown bind type",
        character="Kash-Patel",
        blocked=Blocked(BlockReason.UNKNOWN_BIND_TYPE),
    )
    file.write_text(
        render(
            {}, markets=[MarketRecommendations(MARKET, 1790000000, 0, holdings=[no_data, unknown])]
        ),
        encoding="utf-8",
    )

    out = _run_in_lua(
        lua,
        file,
        'for _, row in ipairs(r.recommendations["Quel\'Thalas"].Horde.holdings) do '
        "  print(row.blocked.reason, tostring(row.blocked.itemKey)) "
        "end",
    )

    assert out.splitlines() == [
        "noData	2770",
        "unknownBindType	nil",
    ]


def test_a_real_lua_reads_a_crafts_sub_crafts(tmp_path, lua):
    # #33: deepest first, as the Brain lists them.
    file = tmp_path / FILE_NAME
    craft = Row(
        "5762",
        Action.CRAFT,
        1,
        profit=760.95,
        note="on Kash-Patel: uses 2 of 2770, via 2 of 2840 on Alt-One, 1 of 2996 on Kash-Patel",
        character="Kash-Patel",
        uses=(ReagentUse("2770", 2),),
        via=(SubCraft("2840", 2, "Alt-One"), SubCraft("2996", 1, "Kash-Patel")),
    )
    file.write_text(
        render({}, markets=[MarketRecommendations(MARKET, 1790000000, 0, holdings=[craft])]),
        encoding="utf-8",
    )

    out = _run_in_lua(
        lua,
        file,
        'local row = r.recommendations["Quel\'Thalas"].Horde.holdings[1] '
        "for _, v in ipairs(row.via) do print(v.itemKey, v.crafts, v.character) end",
    )

    assert out.splitlines() == [
        "2840	2	Alt-One",
        "2996	1	Kash-Patel",
    ]


def test_a_real_lua_reads_a_crafts_chain(tmp_path, lua):
    # #77: the exits, the last over the craft, over its sources.
    file = tmp_path / FILE_NAME
    blocked = Blocked(BlockReason.NO_DATA, "2320")
    top = ChainNode(
        NodeKind.CRAFT,
        "2841",
        20,
        -3960.0,
        (
            ChainNode(NodeKind.BUY, "3576", 20, -2140.0, max_unit_price=110, effort=0),
            ChainNode(NodeKind.MERCHANT, "3857", 1, -20.0),
            ChainNode(NodeKind.USE, "2320", 1, None, blocked=blocked),
        ),
        crafts=20,
        character="Alt-One",
    )
    sell = ChainNode(
        NodeKind.SELL, "2841", 20, 8500.0, (top,), post_at=450, cut=450.0, deposit=50.0, effort=0
    )
    craft = Row("2841", Action.CRAFT, 20, profit=4540.0, character="Alt-One", chain=(sell,))
    file.write_text(
        render({}, markets=[MarketRecommendations(MARKET, 1790000000, 0, holdings=[craft])]),
        encoding="utf-8",
    )

    out = _run_in_lua(
        lua,
        file,
        'local row = r.recommendations["Quel\'Thalas"].Horde.holdings[1] '
        "local function walk(n, depth) "
        "  print(depth, n.kind, n.itemKey, n.quantity, n.gold, n.crafts, n.character, "
        "    n.postAt, n.maxUnitPrice, n.cut, n.deposit, n.effort, "
        "    n.blocked and (n.blocked.reason .. ' ' .. n.blocked.itemKey)) "
        "  for _, c in ipairs(n.children or {}) do walk(c, depth + 1) end "
        "end "
        "for _, n in ipairs(row.chain) do walk(n, 0) end",
    )

    assert out.splitlines() == [
        "0	sell	2841	20	8500	nil	nil	450	nil	450	50	0	nil",
        "1	craft	2841	20	-3960	20	Alt-One	nil	nil	nil	nil	nil	nil",
        "2	buy	3576	20	-2140	nil	nil	nil	110	nil	nil	0	nil",
        "2	merchant	3857	1	-20	nil	nil	nil	nil	nil	nil	nil	nil",
        "2	use	2320	1	nil	nil	nil	nil	nil	nil	nil	nil	noData 2320",
    ]


def test_a_real_lua_reads_a_disenchants_expected_mats(tmp_path, lua):
    # #76: fractions, since they're expected quantities.
    file = tmp_path / FILE_NAME
    disenchant = Row(
        "9999",
        Action.DISENCHANT,
        2,
        profit=535.0,
        note="on Kash-Patel: expect 3.75 of 10940, 0.60 of 10939",
        character="Kash-Patel",
        mats=(MatYield("10940", 3.75), MatYield("10939", 0.6)),
    )
    file.write_text(
        render({}, markets=[MarketRecommendations(MARKET, 1790000000, 0, holdings=[disenchant])]),
        encoding="utf-8",
    )

    out = _run_in_lua(
        lua,
        file,
        'local row = r.recommendations["Quel\'Thalas"].Horde.holdings[1] '
        "print(row.action, row.character) "
        "for _, m in ipairs(row.mats) do print(m.itemKey, m.quantity) end",
    )

    assert out.splitlines() == [
        "Disenchant	Kash-Patel",
        "10940	3.75",
        "10939	0.6",
    ]


def test_a_real_lua_reads_which_characters_hold_each_item_key(tmp_path, lua):
    # #38: keyed by Item Key, not by row, since a split row can't say whose units go where.
    held = {
        "2589": [
            CharacterHolding("Alt-One", bags=4),
            CharacterHolding("Kash-Patel", bags=17, bank=30, bound=5),
        ]
    }
    file = tmp_path / FILE_NAME
    file.write_text(
        render({}, markets=[MarketRecommendations(MARKET, 1790000000, 0, held=held)]),
        encoding="utf-8",
    )

    out = _run_in_lua(
        lua,
        file,
        'local held = r.recommendations["Quel\'Thalas"].Horde.held '
        'for _, h in ipairs(held["2589"]) do print(h.character, h.bags, h.bank, h.bound) end',
    )

    assert out.splitlines() == [
        "Alt-One	4	0	0",
        "Kash-Patel	17	30	5",
    ]


def test_a_real_lua_reads_the_buy_unders(tmp_path, lua):
    buy_under = [
        BuyUnder(
            "2589",
            2070,
            Action.CRAFT,
            units=12,
            seen=14,
            window_days=7,
            listed_now=True,
            recipe_id=2963,
            output="2996",
            crafter="Kash-Patel",
        ),
        BuyUnder("2770", 833, Action.VENDOR, units=None, seen=1, window_days=7),
    ]
    file = tmp_path / FILE_NAME
    file.write_text(
        render({}, markets=[MarketRecommendations(MARKET, 1790000000, 0, buy_under=buy_under)]),
        encoding="utf-8",
    )

    out = _run_in_lua(
        lua,
        file,
        'for _, b in ipairs(r.recommendations["Quel\'Thalas"].Horde.buyUnder) do '
        "print(b.itemKey, b.price, b.way, b.units, b.seen, b.windowDays, b.listedNow, "
        "b.recipe, b.output, b.crafter) end",
    )

    assert out.splitlines() == [
        "2589	2070	Craft	12	14	7	true	2963	2996	Kash-Patel",
        "2770	833	Vendor	nil	1	7	nil	nil	nil	nil",
    ]


def test_a_real_lua_reads_the_disenchant_buy_unders(tmp_path, lua):
    mats = (MatYield("10940", 1.875), MatYield("10939", 0.3))
    buy_under = [
        BuyUnder(
            None,
            1812,
            Action.DISENCHANT,
            units=3,
            seen=2,
            window_days=7,
            disenchanter="Bob",
            mats=mats,
            group=Group(quality=2, kind="weapon", min_level=16, max_level=20, mats=()),
        ),
        BuyUnder("9999", 1700, Action.DISENCHANT, None, 1, 7, disenchanter="Bob", mats=mats),
    ]
    file = tmp_path / FILE_NAME
    file.write_text(
        render({}, markets=[MarketRecommendations(MARKET, 1790000000, 0, buy_under=buy_under)]),
        encoding="utf-8",
    )

    out = _run_in_lua(
        lua,
        file,
        'for _, b in ipairs(r.recommendations["Quel\'Thalas"].Horde.buyUnder) do '
        "local g = b.group or {} "
        "print(b.itemKey, b.price, b.way, b.units, b.disenchanter, "
        "b.mats[1].itemKey, b.mats[1].quantity, b.mats[2].itemKey, "
        "g.quality, g.class, g.minLevel, g.maxLevel) end",
    )

    assert out.splitlines() == [
        "nil	1812	Disenchant	3	Bob	10940	1.875	10939	2	weapon	16	20",
        "9999	1700	Disenchant	nil	Bob	10940	1.875	10939	nil	nil	nil	nil",
    ]


def test_a_real_lua_reads_what_cant_be_disenchanted(tmp_path, lua):
    # From the data file, for the Addon to put items into Disenchant source groups live.
    file = tmp_path / FILE_NAME
    file.write_text(render({}), encoding="utf-8")

    out = _run_in_lua(
        lua,
        file,
        "local x = r.disenchantExcluded "
        "local ids, locs = {}, {} "
        "for id in pairs(x.itemIDs) do ids[#ids + 1] = id end "
        "for loc in pairs(x.equipLocs) do locs[#locs + 1] = loc end "
        "table.sort(ids) table.sort(locs) "
        "print(table.concat(ids, ',')) print(table.concat(locs, ','))",
    )

    assert out.splitlines() == [
        "11287,11288,11289,11290",
        "INVTYPE_BODY,INVTYPE_NON_EQUIP_IGNORE,INVTYPE_TABARD",
    ]


def test_a_real_lua_reads_the_beta_prior(tmp_path, lua):
    # #90: keyed by Item Key, like held, so every tab's rows can look it up.
    beta = BetaPrior(
        Market("Classic Beta PvP", "Alliance", Era.BETA),
        {
            "2589": BetaPrice(250, sold=True, sale_events=7, units_per_day=1.2),
            "4306": BetaPrice(900, sold=False, sale_events=1, units_per_day=None),
        },
    )
    file = tmp_path / FILE_NAME
    file.write_text(
        render(
            {}, markets=[MarketRecommendations(MARKET, 1790000000, 0)], beta_priors={MARKET: beta}
        ),
        encoding="utf-8",
    )

    out = _run_in_lua(
        lua,
        file,
        'local b = r.recommendations["Quel\'Thalas"].Horde.beta '
        "print(b.realm, b.faction) "
        'for _, k in ipairs({ "2589", "4306" }) do '
        "  local p = b.prices[k] print(k, p.price, p.sold, p.saleEvents, p.perDay) "
        "end",
    )

    assert out.splitlines() == [
        "Classic Beta PvP	Alliance",
        "2589	250	true	7	1.2",
        "4306	900	nil	1	nil",
    ]


def test_a_market_without_a_beta_prior_has_no_beta(tmp_path, lua):
    file = tmp_path / FILE_NAME
    file.write_text(
        render({}, markets=[MarketRecommendations(MARKET, 1790000000, 0)]), encoding="utf-8"
    )

    out = _run_in_lua(lua, file, 'print(r.recommendations["Quel\'Thalas"].Horde.beta)')

    assert out == "nil"


def test_a_real_lua_reads_how_long_every_post_lasts(tmp_path, lua):
    # Deposits are charged as if every post lasts this long, so the Addon's Post button
    # (#81) must post for the same time.
    file = tmp_path / FILE_NAME
    file.write_text(render({}, post_duration_hours=8), encoding="utf-8")

    assert _run_in_lua(lua, file, "print(r.postDurationHours)") == "8"


def test_write_recommendations_passes_on_the_post_duration(tmp_path, lua):
    install = _addon_install(tmp_path)

    conn = open_history(tmp_path / "history.db")
    try:
        written = write_recommendations(conn, install, post_duration_hours=2)
    finally:
        conn.close()

    assert _run_in_lua(lua, written, "print(r.postDurationHours)") == "2"


def test_every_write_tells_the_addon_the_brains_version_and_no_problem(tmp_path, lua):
    # A file with a brain table means the Brain has run; the shipped stub has none (#115).
    install = _addon_install(tmp_path)

    conn = open_history(tmp_path / "history.db")
    try:
        written = write_recommendations(conn, install)
    finally:
        conn.close()

    assert _run_in_lua(lua, written, "print(r.brain.version, r.brain.problem)") == (
        f"{__version__}\tnil"
    )


def test_a_problem_reaches_the_addon_as_written(tmp_path, lua):
    install = _addon_install(tmp_path)

    conn = open_history(tmp_path / "history.db")
    try:
        written = write_recommendations(conn, install, problem='Couldn\'t reach "it".')
    finally:
        conn.close()

    assert _run_in_lua(lua, written, "print(r.brain.problem)") == 'Couldn\'t reach "it".'


def _addon_install(tmp_path: Path) -> Install:
    """An install with the Addon and its TOC in it."""
    install = Install(tmp_path / "wow", Era.BETA)
    addon_folder(install).mkdir(parents=True)
    (addon_folder(install) / "AzerothQuant.toc").write_text(
        "## Interface: 16001\n## Title: AzerothQuant\n", encoding="utf-8"
    )
    return install


def test_the_brain_mirrors_recommendations_into_three_load_on_demand_data_slots(tmp_path):
    # The client reads a LoadOnDemand addon's files when it's loaded, once a session, so
    # three slots give the Addon three tries to pick up this copy without a reload
    # (ADR-0030).
    install = _addon_install(tmp_path)

    conn = open_history(tmp_path / "history.db")
    try:
        written = write_recommendations(conn, install)
    finally:
        conn.close()

    addons = install.path / "Interface" / "AddOns"
    for n in (1, 2, 3):
        data = addons / f"AzerothQuant_Data{n}"
        assert (data / FILE_NAME).read_text(encoding="utf-8") == written.read_text(encoding="utf-8")
        assert (data / f"AzerothQuant_Data{n}.toc").read_text(encoding="utf-8") == (
            "## Interface: 16001\n"
            f"## Title: AzerothQuant Data {n}\n"
            "## Notes: The Brain's latest Recommendations, loaded by the Addon after a reload."
            " Written by the Brain; edits are overwritten.\n"
            "## LoadOnDemand: 1\n"
            "## Dependencies: AzerothQuant\n"
            "\n"
            "Recommendations.lua\n"
        )
    assert not (addons / "AzerothQuant_Data").exists()


def test_a_merged_prediction_buy_is_partly_from_beta_if_any_of_its_rooms_was():
    # #111: a quiet Beta watered the bigger room down, but it grew the other.
    buys = [
        _HoldBuy(
            "12359",
            "BWL opens",
            unit_buyout=100,
            quantity=5,
            unit_max_loss=10.0,
            beta_room=BetaRoom(900.0, room=12, from_beta=-1),
        ),
        _HoldBuy(
            "12359",
            "BWL opens",
            unit_buyout=120,
            quantity=5,
            unit_max_loss=12.0,
            beta_room=BetaRoom(950.0, room=8, from_beta=3),
        ),
    ]
    (row,) = _spend_on_predictions(buys, 100000, _Caps(100000, Config(installs=())))

    assert _row(row)["roomFromBeta"] is True


def flip_to_disenchant():
    group = Group(quality=2, kind="armor", min_level=16, max_level=20, mats=())
    return Row(
        "",
        Action.DISENCHANT,
        2,
        price=300,
        profit=400,
        cost=400,
        character="Bob",
        mats=(MatYield("10940", 3.75),),
        listings=2,
        disenchant=DisenchantFlip(group, (ListingBuy("9999", 100), ListingBuy("9998", 300))),
    )


def test_a_flip_to_disenchant_row_carries_its_group_disenchanter_mats_and_listings():
    out = _row(flip_to_disenchant())

    assert "itemKey" not in out
    assert out["disenchant"] == {
        "group": {"quality": 2, "class": "armor", "minLevel": 16, "maxLevel": 20},
        "disenchanter": "Bob",
        "mats": [{"itemKey": "10940", "quantity": 3.75}],
        "buys": [{"itemKey": "9999", "price": 100}, {"itemKey": "9998", "price": 300}],
    }


def test_a_real_lua_reads_a_flip_to_disenchant(tmp_path, lua):
    m = MarketRecommendations(MARKET, 1790000000, 0, shopping_list=[flip_to_disenchant()])
    file = tmp_path / FILE_NAME
    file.write_text(render({}, markets=[m]), encoding="utf-8")

    out = _run_in_lua(
        lua,
        file,
        'local d = r.recommendations["Quel\'Thalas"].Horde.shoppingList[1].disenchant '
        "print(d.group.class, d.group.minLevel, d.disenchanter, d.mats[1].itemKey, "
        "d.buys[2].itemKey, d.buys[2].price)",
    )

    assert out.splitlines() == ["armor	16	Bob	10940	9998	300"]


def test_a_real_lua_reads_the_loot_alert(tmp_path, lua):
    alert = LootAlert(
        100000,
        {"2770": LootValue(123456.7, Action.SELL), "10940": LootValue(200000, Action.DISENCHANT)},
    )
    m = MarketRecommendations(MARKET, 1790000000, 0, loot_alert=alert)
    file = tmp_path / FILE_NAME
    file.write_text(render({}, markets=[m]), encoding="utf-8")

    out = _run_in_lua(
        lua,
        file,
        'local a = r.recommendations["Quel\'Thalas"].Horde.lootAlert '
        'local i, d = a.items["2770"], a.items["10940"] '
        "print(a.threshold, i.value, i.action, d.value, d.action)",
    )

    # Whole copper, as the Addon's Money.format shows it.
    assert out == "100000	123457	Sell	200000	Disenchant"


def test_a_market_carries_its_stake_and_caps_and_a_capped_row_its_units_before_the_cap():
    # #170, ADR-0034. Rounded down to the copper: the Addon shows gold, not fractions.
    capped = Row(
        "2589", Action.SELL, 55, price=100, profit=500, cost=5500, capped=241, capped_by="loss"
    )
    m = MarketRecommendations(
        MARKET,
        1790000000,
        600000,
        stake=905000.4,
        room=243000.6,
        loss_cap=27150.9,
        shopping_list=[capped],
    )

    data = parse_savedvariables(render({}, markets=[m]))[GLOBAL_NAME]

    lua_m = data["recommendations"]["Quel'Thalas"]["Horde"]
    assert (lua_m["stake"], lua_m["room"], lua_m["lossCap"]) == (905000, 243000, 27150)
    assert (lua_m["shoppingList"][0]["capped"], lua_m["shoppingList"][0]["cappedBy"]) == (
        241,
        "loss",
    )


def test_a_market_without_risk_caps_has_no_room_or_loss_cap():
    m = MarketRecommendations(MARKET, 1790000000, 600000, stake=600000)

    data = parse_savedvariables(render({}, markets=[m]))[GLOBAL_NAME]

    lua_m = data["recommendations"]["Quel'Thalas"]["Horde"]
    assert "room" not in lua_m and "lossCap" not in lua_m
