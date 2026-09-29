"""The Disenchant tables checked against the player's own Disenchant Results (#76,
ADR-0018): `brain disenchants`.

Per Disenchant source group and mat, the observed chance and mean quantity sit next to
the table's, each with a 95% interval: Wilson for the chance, a t-interval for the mean
quantity when it dropped. The table only **differs** when its value lies outside the
interval, and nothing is judged below `disenchant_check_min_results` Results, so a lucky
run never reads as a wrong table. Nothing here changes the table: a person edits it.
"""

import math
from dataclasses import dataclass
from enum import StrEnum
from statistics import NormalDist

from brain.disenchant import DisenchantResult, DisenchantTable, Group, Mat


class Verdict(StrEnum):
    TOO_FEW = "too few Results"
    DIFFERS = "differs"
    CONSISTENT = "consistent"


_Z = NormalDist().inv_cdf(0.975)  # two-sided 95%


def wilson(successes: int, n: int) -> tuple[float, float]:
    """The 95% Wilson score interval of a chance seen `successes` times in n. Unlike
    p ± 1.96 standard errors, it stays inside 0..1 and works for a 0% or 100% run."""
    p = successes / n
    z2 = _Z * _Z
    center = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = _Z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return center - half, center + half


def _t_within(t: float, df: int) -> float:
    """P(|T| < t) for Student's t with df degrees of freedom: the closed forms for a whole
    df (Abramowitz & Stegun 26.7.3 and 26.7.4)."""
    theta = math.atan(t / math.sqrt(df))
    cos2 = math.cos(theta) ** 2
    if df % 2 == 0:
        term, total = 1.0, 1.0
        for j in range(1, df // 2):
            term *= (2 * j - 1) / (2 * j) * cos2
            total += term
        return math.sin(theta) * total
    if df == 1:
        return 2 * theta / math.pi
    term = total = math.cos(theta)
    for j in range(1, (df - 1) // 2):
        term *= (2 * j) / (2 * j + 1) * cos2
        total += term
    return 2 / math.pi * (theta + math.sin(theta) * total)


def t_critical(df: int) -> float:
    """The two-sided 95% critical value of Student's t, found by bisection."""
    low, high = 0.0, 1000.0
    for _ in range(100):
        mid = (low + high) / 2
        low, high = (mid, high) if _t_within(mid, df) < 0.95 else (low, mid)
    return (low + high) / 2


def t_interval(values: list[int]) -> tuple[float, float] | None:
    """The 95% t-interval of the mean of values, or None for fewer than 2."""
    k = len(values)
    if k < 2:
        return None
    mean = sum(values) / k
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (k - 1))
    half = t_critical(k - 1) * sd / math.sqrt(k)
    return mean - half, mean + half


def _judge(table_value: float, interval: tuple[float, float]) -> Verdict:
    low, high = interval
    return Verdict.CONSISTENT if low <= table_value <= high else Verdict.DIFFERS


@dataclass(frozen=True)
class MatCheck:
    group: Group
    item_id: int
    n: int  # Results in the group
    chance: float  # share of them that yielded the mat
    table_chance: float  # 0 for a mat the table doesn't list for the group
    chance_interval: tuple[float, float]
    chance_verdict: Verdict
    qty: float | None  # mean quantity when it dropped; None if it never did
    table_qty: float | None  # (min + max) / 2; None for a mat the table doesn't list
    qty_interval: tuple[float, float] | None  # None below 2 drops
    qty_verdict: Verdict | None  # None when there's no interval or table value to judge
    verdict: Verdict  # too few Results, or differs if either differs


@dataclass(frozen=True)
class DisenchantCheck:
    rows: list[MatCheck]
    unplaced: int  # Results with no group: the item unknown, or no band for it


def check_disenchants(
    table: DisenchantTable, results: list[DisenchantResult], min_results: int
) -> DisenchantCheck:
    """Each group's table mats, and any mat its Results yielded that the table doesn't
    list, checked against the Results. Groups with no Results are left out."""
    by_group: dict[Group, list[DisenchantResult]] = {}
    unplaced = 0
    for r in results:
        group = table.group_of(r.quality, r.class_id, r.item_level)
        if group is None:
            unplaced += 1
        else:
            by_group.setdefault(group, []).append(r)
    rows = []
    for group, rs in by_group.items():
        listed = {mat.item_id: mat for mat in group.mats}
        seen = sorted({item_id for r in rs for item_id in r.mats} - listed.keys())
        for mat in group.mats:
            rows.append(_check(group, mat.item_id, mat, rs, min_results))
        for item_id in seen:
            rows.append(_check(group, item_id, None, rs, min_results))
    return DisenchantCheck(rows=rows, unplaced=unplaced)


def _check(
    group: Group, item_id: int, mat: Mat | None, rs: list[DisenchantResult], min_results: int
) -> MatCheck:
    n = len(rs)
    qtys = [r.mats[item_id] for r in rs if item_id in r.mats]
    table_chance = mat.chance if mat else 0.0
    table_qty = (mat.min_qty + mat.max_qty) / 2 if mat else None
    interval = wilson(len(qtys), n)
    qty_interval = t_interval(qtys)
    judgeable = qty_interval is not None and table_qty is not None
    if n < min_results:
        chance_verdict = verdict = Verdict.TOO_FEW
        qty_verdict = Verdict.TOO_FEW if judgeable else None
    else:
        chance_verdict = _judge(table_chance, interval)
        qty_verdict = _judge(table_qty, qty_interval) if judgeable else None
        differs = Verdict.DIFFERS in (chance_verdict, qty_verdict)
        verdict = Verdict.DIFFERS if differs else Verdict.CONSISTENT
    return MatCheck(
        group=group,
        item_id=item_id,
        n=n,
        chance=len(qtys) / n,
        table_chance=table_chance,
        chance_interval=interval,
        chance_verdict=chance_verdict,
        qty=sum(qtys) / len(qtys) if qtys else None,
        table_qty=table_qty,
        qty_interval=qty_interval,
        qty_verdict=qty_verdict,
        verdict=verdict,
    )
