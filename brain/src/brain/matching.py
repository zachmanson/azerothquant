"""Match the Listings of one Scan to those of the previous Scan in the same Market.

There's no auction ID or seller, so Listings with the same Item Key and unit buyout are
interchangeable (CONTEXT.md: Listing, ADR-0002). Own isn't part of that: a Pooled Scan
shows my auctions as someone else's. Within each such group
we pick the matching with the fewest new Listings, then the fewest units counted as
Partial Sales. That is a min-cost maximum matching, solved here as a min-cost max-flow
over (quantity, time-left) types, because identical Listings don't need their own nodes.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

_INFINITY = float("inf")


class Side(Protocol):
    """What matching needs from a Listing on either side."""

    @property
    def item_key(self) -> str: ...
    @property
    def unit_buyout(self) -> int: ...
    @property
    def quantity(self) -> int: ...
    @property
    def time_left(self) -> int: ...


@dataclass(frozen=True)
class Matching[P: Side, C: Side]:
    matched: list[tuple[P, C]]
    new: list[C]
    disappeared: list[P]


def match[P: Side, C: Side](
    previous: Sequence[P],
    current: Sequence[C],
    gap_seconds: int,
    time_left_max_seconds: Sequence[int],
) -> Matching[P, C]:
    """Pair previous Listings with current rows, gap_seconds apart.

    A previous Listing can become a current row only if its quantity didn't go up, its
    time-left bucket didn't go up, and its bucket could have lasted gap_seconds.
    """

    def can_match(p: P, c: C) -> bool:
        return (
            c.quantity <= p.quantity
            and c.time_left <= p.time_left
            and time_left_max_seconds[p.time_left - 1] >= gap_seconds
        )

    prev_groups: dict[tuple, list[P]] = defaultdict(list)
    for p in previous:
        prev_groups[_identity(p)].append(p)
    cur_groups: dict[tuple, list[C]] = defaultdict(list)
    for c in current:
        cur_groups[_identity(c)].append(c)

    result: Matching[P, C] = Matching(matched=[], new=[], disappeared=[])
    for key in prev_groups.keys() | cur_groups.keys():
        ps, cs = prev_groups.get(key, []), cur_groups.get(key, [])
        pairs = _match_group(ps, cs, can_match) if ps and cs else []
        result.matched.extend(pairs)
        used_p = {id(p) for p, _ in pairs}
        used_c = {id(c) for _, c in pairs}
        result.disappeared.extend(p for p in ps if id(p) not in used_p)
        result.new.extend(c for c in cs if id(c) not in used_c)
    return result


def _identity(listing: Side) -> tuple:
    return (listing.item_key, listing.unit_buyout)


def _match_group[P: Side, C: Side](ps: list[P], cs: list[C], can_match) -> list[tuple[P, C]]:
    """Min-cost max matching within one group of interchangeable Listings."""
    # Collapse identical Listings into types; a type is (quantity, time_left).
    p_types: dict[tuple[int, int], list[P]] = defaultdict(list)
    for p in ps:
        p_types[(p.quantity, p.time_left)].append(p)
    c_types: dict[tuple[int, int], list[C]] = defaultdict(list)
    for c in cs:
        c_types[(c.quantity, c.time_left)].append(c)

    p_keys, c_keys = list(p_types), list(c_types)
    graph = _FlowGraph(2 + len(p_keys) + len(c_keys))
    source, sink = 0, 1
    p_node = {k: 2 + i for i, k in enumerate(p_keys)}
    c_node = {k: 2 + len(p_keys) + i for i, k in enumerate(c_keys)}

    for k, members in p_types.items():
        graph.add_edge(source, p_node[k], len(members), 0)
    for k, members in c_types.items():
        graph.add_edge(c_node[k], sink, len(members), 0)
    pair_edges = []
    for pk in p_keys:
        for ck in c_keys:
            if can_match(p_types[pk][0], c_types[ck][0]):
                units_sold = pk[0] - ck[0]
                edge = graph.add_edge(p_node[pk], c_node[ck], len(p_types[pk]), units_sold)
                pair_edges.append((pk, ck, edge))

    graph.min_cost_max_flow(source, sink)

    pairs = []
    for pk, ck, edge in pair_edges:
        for _ in range(graph.flow(edge)):
            pairs.append((p_types[pk].pop(), c_types[ck].pop()))
    return pairs


class _FlowGraph:
    """Min-cost max-flow by successive shortest paths (Bellman-Ford, so residual
    edges with negative cost are fine). Groups are small, so simple beats fast."""

    def __init__(self, n: int):
        self.n = n
        # Each edge: [to, capacity left, cost, index of reverse edge in edges]
        self.edges: list[list[int]] = []
        self.adjacent: list[list[int]] = [[] for _ in range(n)]
        self.capacity: dict[int, int] = {}

    def add_edge(self, u: int, v: int, capacity: int, cost: int) -> int:
        forward = len(self.edges)
        self.edges.append([v, capacity, cost, forward + 1])
        self.edges.append([u, 0, -cost, forward])
        self.adjacent[u].append(forward)
        self.adjacent[v].append(forward + 1)
        self.capacity[forward] = capacity
        return forward

    def flow(self, edge: int) -> int:
        return self.capacity[edge] - self.edges[edge][1]

    def min_cost_max_flow(self, source: int, sink: int) -> None:
        while True:
            dist = [_INFINITY] * self.n
            via_edge = [-1] * self.n
            dist[source] = 0
            for _ in range(self.n - 1):
                changed = False
                for u in range(self.n):
                    if dist[u] == _INFINITY:
                        continue
                    for e in self.adjacent[u]:
                        v, cap, cost, _ = self.edges[e]
                        if cap > 0 and dist[u] + cost < dist[v]:
                            dist[v] = dist[u] + cost
                            via_edge[v] = e
                            changed = True
                if not changed:
                    break
            if dist[sink] == _INFINITY:
                return

            # Push as much as the path's tightest edge allows.
            push, v = None, sink
            while v != source:
                e = via_edge[v]
                push = self.edges[e][1] if push is None else min(push, self.edges[e][1])
                v = self.edges[self.edges[e][3]][0]
            v = sink
            while v != source:
                e = via_edge[v]
                self.edges[e][1] -= push
                self.edges[self.edges[e][3]][1] += push
                v = self.edges[self.edges[e][3]][0]
