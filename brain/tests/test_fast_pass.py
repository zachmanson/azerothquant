"""#141: the speedups inside one Decision Engine pass give the same answers as before."""

import random

import pytest

from brain.recommend import cheapest_without, without


def _old_cheapest_without(supply, bought):
    """The slow path it replaces: build the whole supply left, sorted, and take its head."""
    left = without(supply, bought)
    return left[0][0] if left else None


@pytest.mark.parametrize(
    "supply, bought, expected",
    [
        ([], [], None),
        ([(100, 2)], [], 100),
        # Duplicates of a price merge: buying 2 of 3 at 100 leaves one there.
        ([(100, 1), (100, 2), (150, 1)], [(100, 2)], 100),
        ([(100, 1), (100, 2), (150, 1)], [(100, 3)], 150),
        # Bought more than offered at a price leaves none there, and doesn't eat another.
        ([(100, 1), (150, 1)], [(100, 5)], 150),
        ([(100, 1)], [(100, 1)], None),
        # Bought at a price not on offer changes nothing.
        ([(150, 1), (100, 1)], [(90, 4)], 100),
    ],
)
def test_the_cheapest_left_after_buying(supply, bought, expected):
    assert cheapest_without(supply, bought) == expected


def test_the_cheapest_left_matches_building_the_whole_supply_left():
    rng = random.Random(141)
    for _ in range(2000):
        prices = [rng.randint(1, 12) * 10 for _ in range(rng.randint(0, 8))]
        supply = [(p, rng.randint(1, 4)) for p in prices]
        # The player's own Listings out of the supply, or a Flip's buys: some at prices on
        # offer, some for more units than offered, some at prices that aren't.
        bought = [
            (
                rng.choice(prices) if prices and rng.random() < 0.8 else rng.randint(1, 12) * 10,
                rng.randint(1, 6),
            )
            for _ in range(rng.randint(0, 5))
        ]
        assert cheapest_without(supply, bought) == _old_cheapest_without(supply, bought)
