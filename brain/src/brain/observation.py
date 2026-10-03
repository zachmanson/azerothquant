"""Which parts of a Market's history count toward Sell Rate (ADR-0004).

Only Observation Windows (gaps between consecutive Scans no longer than the configured
cap) count, and within one a Disappearance is a Probable Sale candidate only if its
time-left bucket rules out expiry over the gap and no Repost explains it. Everything
here is computed from the raw history on read, so changing the cap recomputes the past
(ADR-0002).
"""

import sqlite3
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from brain.config import Config
from brain.fair_value import FairValueCache
from brain.history import Listing, Market, listings, partial_sales, scan_times


@dataclass(frozen=True, order=True)
class ObservationWindow:
    start: int  # requested_at of the earlier Scan
    end: int  # requested_at of the later Scan


def observation_windows(
    conn: sqlite3.Connection, market: Market, config: Config
) -> list[ObservationWindow]:
    """Every consecutive pair of the Market's Scans close enough to be an Observation
    Window, oldest first."""
    return [
        ObservationWindow(start, end)
        for start, end in pairwise(scan_times(conn, market))
        if end - start <= config.observation_window_max_seconds
    ]


@dataclass(frozen=True, order=True)
class Disappearance:
    item_key: str
    unit_buyout: int
    own: bool
    quantity: int
    time_left: int  # bucket in the last Scan it was seen in
    last_seen: int  # requested_at of the last Scan it was in
    gone_at: int  # requested_at of the next Scan, where it was missing
    in_window: bool  # the gap between the two Scans is an Observation Window
    expiry_possible: bool  # the gap was long enough for its bucket to run out


def disappearances(
    conn: sqlite3.Connection,
    market: Market,
    config: Config,
    seen: Sequence[Listing] | None = None,
) -> list[Disappearance]:
    """Every Listing that was in one Scan of the Market and missing from the next, in
    the order the Listings were first seen. `seen` is the Market's `listings`, when the
    caller has them already (#105)."""
    seen = listings(conn, market) if seen is None else seen
    times = scan_times(conn, market)
    result = []
    for listing in seen:
        after = bisect_right(times, listing.last_seen)
        if after == len(times):
            continue  # still in the latest Scan
        gone_at = times[after]
        gap = gone_at - listing.last_seen
        result.append(
            Disappearance(
                item_key=listing.item_key,
                unit_buyout=listing.unit_buyout,
                own=listing.own,
                quantity=listing.quantity,
                time_left=listing.time_left,
                last_seen=listing.last_seen,
                gone_at=gone_at,
                in_window=gap <= config.observation_window_max_seconds,
                expiry_possible=gap >= _least_time_left(listing.time_left, config),
            )
        )
    return result


def _least_time_left(bucket: int, config: Config) -> int:
    """The least time a Listing in this bucket can have left, in seconds: the previous
    bucket's longest, or 0 for bucket 1."""
    return config.time_left_max_seconds[bucket - 2] if bucket > 1 else 0


@dataclass(frozen=True)
class _Pairing:
    sales: list[Disappearance]  # candidates no Repost explains
    reposts: list[Disappearance]
    # Sales that failed to pair only because every new Listing like them was priced
    # higher: a baseline for how often a real sale sits next to an unrelated post.
    coincidences: list[Disappearance]


def _pair_reposts(candidates: list[Disappearance], new: list[Listing]) -> _Pairing:
    """Pair off every Repost the data allows.

    A Repost pairs a candidate with a new Listing from the same Observation Window with
    the same Item Key and quantity, at the same or a lower unit buyout. Own doesn't
    count, since a Pooled Scan sees my auctions as someone else's. Going from the most
    expensive candidate down, each takes the most expensive unpaired new Listing it can.
    That pairs as many as possible and leaves the cheapest candidates as the sales, the
    way buyers clear the Auction House.
    """
    new_prices: dict[tuple, list[int]] = defaultdict(list)
    for n in new:
        new_prices[(n.item_key, n.quantity, n.first_seen)].append(n.unit_buyout)
    for prices in new_prices.values():
        prices.sort()
    cheapest_new = {group: prices[0] for group, prices in new_prices.items()}

    pairing = _Pairing(sales=[], reposts=[], coincidences=[])
    for d in sorted(candidates, key=lambda d: d.unit_buyout, reverse=True):
        group = (d.item_key, d.quantity, d.gone_at)
        prices = new_prices.get(group, [])
        cheaper = bisect_right(prices, d.unit_buyout)
        if cheaper:
            del prices[cheaper - 1]
            pairing.reposts.append(d)
            continue
        pairing.sales.append(d)
        if group in cheapest_new and cheapest_new[group] > d.unit_buyout:
            pairing.coincidences.append(d)
    return pairing


@dataclass(frozen=True, order=True)
class SaleEvent:
    """Every unit of one Item Key seen to sell in one Observation Window: its Partial
    Sales and Probable Sales together (ADR-0012)."""

    item_key: str
    unit_buyout: int  # the dearest unit
    seen_at: int  # requested_at of the Scan that ends the Observation Window
    units: int


@dataclass(frozen=True)
class SellRateEvidence:
    window_hours: float  # total length of the Observation Windows in the range
    sale_events: list[SaleEvent] = field(default_factory=list)  # oldest first
    reposts: list[Disappearance] = field(default_factory=list)
    # Disappearances left as sales only because every new Listing like them was priced
    # higher (ADR-0004).
    coincidences: list[Disappearance] = field(default_factory=list)
    windows: list[ObservationWindow] = field(default_factory=list)  # behind window_hours

    def event_counts(self) -> dict[str, int]:
        """How many sale events each Item Key has, so thin evidence can be discounted."""
        return dict(Counter(e.item_key for e in self.sale_events))

    def repost_counts(self) -> dict[str, int]:
        return dict(Counter(d.item_key for d in self.reposts))

    def coincidence_counts(self) -> dict[str, int]:
        return dict(Counter(d.item_key for d in self.coincidences))


def observation_windows_between(
    conn: sqlite3.Connection, market: Market, config: Config, since: int, until: int
) -> list[ObservationWindow]:
    """The Observation Windows whose later Scan falls in [since, until)."""
    return [w for w in observation_windows(conn, market, config) if since <= w.end < until]


def window_hours(windows: list[ObservationWindow]) -> float:
    return sum(w.end - w.start for w in windows) / 3600


def sell_rate_evidence(
    conn: sqlite3.Connection,
    market: Market,
    config: Config,
    since: int,
    until: int,
    seen: Sequence[Listing] | None = None,
    fair_value_cache: FairValueCache | None = None,
) -> SellRateEvidence:
    """What Sell Rate is built from over [since, until): the Observation Windows whose
    later Scan falls in the range. Windows aren't clipped at the edges, so the hours
    and the sales always cover the same windows. `seen` as in `disappearances`.
    `fair_value_cache` is the past Scans' Fair Values, when the caller keeps them."""
    seen = listings(conn, market) if seen is None else seen
    cache = FairValueCache() if fair_value_cache is None else fair_value_cache
    windows = observation_windows_between(conn, market, config, since, until)
    window_ends = {w.end for w in windows}
    # (Item Key, window end, unit buyout, units) of every Partial Sale and Probable Sale.
    sales = [
        (p.item_key, p.seen_at, p.unit_buyout, p.units_sold)
        for p in partial_sales(conn, market)
        if p.seen_at in window_ends
    ]
    candidates = [
        d
        for d in disappearances(conn, market, config, seen)
        if d.gone_at in window_ends and not d.expiry_possible
    ]
    new = [n for n in seen if n.first_seen in window_ends]
    pairing = _pair_reposts(candidates, new)
    # Priced by the Scans either side of the sale, not today's: a sale is judged against
    # the market it sold into. The lower Fair Value wins, since a buyer paying well over
    # what was up when it went missing is the unlikely story (#74). If it sold the Item
    # Key out, only the Scan it was last seen in has a Fair Value.
    scans_either_side = {at for d in pairing.sales for at in (d.last_seen, d.gone_at)}
    fair_value_in = {at: cache.fair_values(conn, market, config, at) for at in scans_either_side}

    def priced_like_a_sale(d: Disappearance) -> bool:
        last_seen = fair_value_in[d.last_seen][d.item_key]
        fair_value = min(last_seen, fair_value_in[d.gone_at].get(d.item_key, last_seen))
        return d.unit_buyout <= config.probable_sale_max_fair_value_multiple * fair_value

    probable_sales = [d for d in pairing.sales if priced_like_a_sale(d)]
    sales += [(d.item_key, d.gone_at, d.unit_buyout, d.quantity) for d in probable_sales]
    return SellRateEvidence(
        window_hours=window_hours(windows),
        sale_events=_sale_events(sales),
        reposts=pairing.reposts,
        coincidences=[d for d in pairing.coincidences if priced_like_a_sale(d)],
        windows=windows,
    )


def _sale_events(sales: list[tuple[str, int, int, int]]) -> list[SaleEvent]:
    """One Sale Event per Item Key per Observation Window, oldest first. A buyer takes
    units cheapest-first across price points, so one sweep shows up as many sales."""
    units: Counter[tuple[str, int]] = Counter()
    dearest: dict[tuple[str, int], int] = {}
    for item_key, seen_at, unit_buyout, quantity in sales:
        group = (item_key, seen_at)
        units[group] += quantity
        dearest[group] = max(dearest.get(group, 0), unit_buyout)
    events = [
        SaleEvent(item_key, dearest[(item_key, seen_at)], seen_at, n)
        for (item_key, seen_at), n in units.items()
    ]
    return sorted(events, key=lambda e: e.seen_at)
