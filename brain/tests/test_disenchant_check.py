import pytest

from brain.disenchant import DisenchantResult, load_table
from brain.disenchant_check import Verdict, check_disenchants

T0 = 1_790_000_000
UNCOMMON, ARMOR, WEAPON = 2, 4, 2
# Green armor of item level 16-20: 75% 2-3 Strange Dust, 20% 1-2 Greater Magic Essence,
# 5% 1 Small Glimmering Shard.
DUST, GREATER_ESSENCE, SHARD = 10940, 10939, 10978


@pytest.fixture(scope="module")
def table():
    return load_table()


def green_armor(mats, level=18, class_id=ARMOR):
    return DisenchantResult(
        at=T0,
        character="Bob-Patel",
        mats=mats,
        item_id=9999,
        item_level=level,
        quality=UNCOMMON,
        class_id=class_id,
    )


def results(with_dust, without_dust, dust=(2, 3)):
    """with_dust Results yielding Strange Dust (quantities cycling through dust), then
    without_dust yielding a Greater Magic Essence instead."""
    return [green_armor({DUST: dust[i % len(dust)]}) for i in range(with_dust)] + [
        green_armor({GREATER_ESSENCE: 1}) for _ in range(without_dust)
    ]


def dust_row(table, rs, min_results=20):
    (row,) = [r for r in check_disenchants(table, rs, min_results).rows if r.item_id == DUST]
    return row


def test_a_few_results_are_too_few_to_judge_the_table_by(table):
    # 5 of 5 got dust against the table's 75%: a lucky run, not a wrong table.
    row = dust_row(table, results(5, 0))

    assert row.n == 5
    assert row.chance == 1.0
    assert row.table_chance == 0.75
    assert row.verdict is Verdict.TOO_FEW


@pytest.mark.parametrize(
    ("with_dust", "verdict"),
    [
        (100, Verdict.DIFFERS),  # 50%: the table's 75% is far outside the interval
        (146, Verdict.CONSISTENT),  # 73%: the table's 75% is inside it
    ],
)
def test_the_table_differs_only_when_its_chance_lies_outside_the_wilson_interval(
    table, with_dust, verdict
):
    row = dust_row(table, results(with_dust, 200 - with_dust))

    assert row.n == 200
    assert row.chance_verdict is verdict
    assert row.verdict is verdict  # the mean quantity, 2.5, is the table's


def test_the_wilson_interval_of_a_chance(table):
    # 146 of 200: Wilson 95% is 0.6646 to 0.7868, the chances p where |0.73 - p| is
    # 1.96 standard errors sqrt(p(1-p)/200), found by bisection rather than the formula.
    low, high = dust_row(table, results(146, 54)).chance_interval

    assert low == pytest.approx(0.6646, abs=1e-4)
    assert high == pytest.approx(0.7868, abs=1e-4)


def test_the_table_differs_when_its_mean_quantity_lies_outside_the_t_interval(table):
    # 75% got dust, as the table says, but always 2 where the table says 2-3 (mean 2.5).
    row = dust_row(table, results(150, 50, dust=(2,)))

    assert row.chance_verdict is Verdict.CONSISTENT
    assert row.qty == 2.0
    assert row.table_qty == 2.5
    assert row.qty_verdict is Verdict.DIFFERS
    assert row.verdict is Verdict.DIFFERS


def test_the_t_interval_of_a_mean_quantity(table):
    # Dust quantities 2, 3, 3: mean 2.667, s = 0.577, and t(0.975, 2 df) = 4.303 from a
    # t table, so 2.667 ± 4.303 × 0.577 / √3 = 1.232 to 4.101.
    row = dust_row(table, results(3, 0, dust=(2, 3, 3)))

    assert row.qty == pytest.approx(2.6667, abs=1e-4)
    low, high = row.qty_interval
    assert low == pytest.approx(1.2324, abs=1e-3)
    assert high == pytest.approx(4.1009, abs=1e-3)


def test_a_mat_that_dropped_once_has_no_quantity_interval(table):
    row = dust_row(table, results(1, 30))

    assert row.qty_interval is None
    assert row.qty_verdict is None


def test_a_mat_the_table_doesnt_list_for_the_group_differs_once_there_are_enough(table):
    # Say Forever's "Arcane Salvager" adds a mat: the table's chance for it is 0.
    NEW_MAT = 99999
    rs = results(150, 50) + [green_armor({NEW_MAT: 1}) for _ in range(20)]

    (row,) = [r for r in check_disenchants(table, rs, 20).rows if r.item_id == NEW_MAT]

    assert row.n == 220
    assert row.table_chance == 0.0
    assert row.verdict is Verdict.DIFFERS


def test_results_are_grouped_by_band_and_those_with_no_group_are_counted_apart(table):
    rs = [
        green_armor({DUST: 2}, level=16),
        green_armor({DUST: 3}, level=20),
        green_armor({GREATER_ESSENCE: 1}, level=18, class_id=WEAPON),
        DisenchantResult(at=T0, character="Bob-Patel", mats={DUST: 2}),  # item unknown
        green_armor({DUST: 2}, level=200),  # no band that high
    ]

    check = check_disenchants(table, rs, 20)

    armor = {(r.group.kind, r.group.min_level): r.n for r in check.rows if r.item_id == DUST}
    assert armor == {("armor", 16): 2, ("weapon", 16): 1}
    assert check.unplaced == 2
