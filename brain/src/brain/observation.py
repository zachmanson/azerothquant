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
from brain.history import (
    Listing,
    Market,
    dropped_item_ids,
    listings,
    outcomes,
    partial_sales,
    scan_times,
)
from brain.mailbox import MailKind
from brain.scan import item_id_of


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
        result.append(_disappearance(listing, times[after], config))
    return result


def _disappearance(listing: Listing, gone_at: int, config: Config) -> Disappearance:
    """`listing` as a Disappearance, missing from the Scan at `gone_at`."""
    gap = gone_at - listing.last_seen
    return Disappearance(
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
    `fair_value_cache` is the past Scans' Fair Values, when the caller keeps them, and
    the tally of what each window adds (#142). Each window's evidence is its own: its
    Disappearances can only pair with Listings new in it, and their Sale Events are its.
    Reposts and coincidences come window by window, not ordered across them."""
    seen = listings(conn, market) if seen is None else seen
    cache = FairValueCache() if fair_value_cache is None else fair_value_cache
    windows = observation_windows_between(conn, market, config, since, until)
    ends = _ends_of_windows(conn, market, config, windows, seen, cache)
    new = _new_listings(market, seen, cache)
    evidence = [_window_evidence(conn, market, config, w, ends[w], new, cache) for w in windows]
    return SellRateEvidence(
        window_hours=window_hours(windows),
        sale_events=[e for w in evidence for e in w.sale_events],
        reposts=[d for w in evidence for d in w.reposts],
        coincidences=[d for w in evidence for d in w.coincidences],
        windows=windows,
    )


@dataclass(frozen=True)
class _EndsOfWindow:
    """What an Observation Window's evidence takes from the Listings as of its two Scans:
    the Disappearances that could be sales, in the order of `listings`, and the Partial
    Sales seen at its end, as (Item Key, window end, unit buyout, units). Each Scan is
    matched only against the one before it, so these don't change until a re-match
    imports those Scans again. Items either Scan dropped rows of are left out of both
    (#150): a Listing missing from a Scan may only have been missed."""

    candidates: list[Disappearance]
    partial_sales: list[tuple[str, int, int, int]]


def _ends_of_windows(
    conn: sqlite3.Connection,
    market: Market,
    config: Config,
    windows: list[ObservationWindow],
    seen: Sequence[Listing],
    cache: FairValueCache,
) -> dict[ObservationWindow, _EndsOfWindow]:
    """Each window's `_EndsOfWindow`, from the cache when it kept them, and kept there."""
    fields = (config.time_left_max_seconds,)
    found = {w: cache.kept_for_window(conn, market, w.start, w.end, fields) for w in windows}
    result = {w: ends for w, ends in found.items() if isinstance(ends, _EndsOfWindow)}
    missing = {w.start: w for w in windows if w not in result}
    if not missing:
        return result
    dropped = dropped_item_ids(conn, market)
    left_out = {
        w: dropped.get(w.start, frozenset()) | dropped.get(w.end, frozenset())
        for w in missing.values()
    }
    # A Listing last seen at a window's start is missing from the Scan at its end, the
    # next one.
    candidates: dict[ObservationWindow, list[Disappearance]] = defaultdict(list)
    for listing in seen:
        w = missing.get(listing.last_seen)
        if w is not None and item_id_of(listing.item_key) not in left_out[w]:
            d = _disappearance(listing, w.end, config)
            if not d.expiry_possible:
                candidates[w].append(d)
    by_end = {w.end: w for w in missing.values()}
    sales: dict[int, list[tuple[str, int, int, int]]] = defaultdict(list)
    for p in partial_sales(conn, market):
        w = by_end.get(p.seen_at)
        if w is not None and item_id_of(p.item_key) not in left_out[w]:
            sales[p.seen_at].append((p.item_key, p.seen_at, p.unit_buyout, p.units_sold))
    for w in missing.values():
        result[w] = _EndsOfWindow(candidates[w], sales[w.end])
        cache.keep_for_window(market, w.start, w.end, fields, result[w])
    return result


@dataclass(frozen=True)
class _WindowEvidence:
    sale_events: list[SaleEvent]
    reposts: list[Disappearance]
    coincidences: list[Disappearance]


@dataclass(frozen=True)
class _NewListings:
    """This pass's Listings by the Scan they were first seen in, and each window's
    evidence worked out from them. A Repost pairs with a new Listing's quantity as of
    its last Scan, so a Partial Sale long after a window can change its Reposts: unlike
    `_EndsOfWindow`, this is only good for the pass."""

    seen: Sequence[Listing]
    by_first_seen: dict[int, list[Listing]]
    evidence: dict[tuple, _WindowEvidence] = field(default_factory=dict)


def _new_listings(market: Market, seen: Sequence[Listing], cache: FairValueCache) -> _NewListings:
    """`seen` by the Scan each was first seen in, worked out once a pass (again if a
    caller brings other Listings)."""
    key = (_NewListings, market)
    new = cache.this_pass.get(key)
    if not isinstance(new, _NewListings) or new.seen is not seen:
        by_first_seen: dict[int, list[Listing]] = defaultdict(list)
        for listing in seen:
            by_first_seen[listing.first_seen].append(listing)
        new = _NewListings(seen, by_first_seen)
        cache.this_pass[key] = new
    return new


def _window_evidence(
    conn: sqlite3.Connection,
    market: Market,
    config: Config,
    window: ObservationWindow,
    ends: _EndsOfWindow,
    new: _NewListings,
    cache: FairValueCache,
) -> _WindowEvidence:
    """One Observation Window's Sale Events, Reposts and coincidences, once a pass."""
    key = (
        window,
        config.time_left_max_seconds,
        config.probable_sale_max_fair_value_multiple,
        config.fair_value_slice_share,
        config.fair_value_outlier_share,
    )
    if key in new.evidence:
        return new.evidence[key]
    pairing = _pair_reposts(ends.candidates, new.by_first_seen.get(window.end, []))
    # Priced by the Scans either side of the sale, not today's: a sale is judged against
    # the market it sold into. The lower Fair Value wins, since a buyer paying well over
    # what was up when it went missing is the unlikely story (#74). If it sold the Item
    # Key out, only the Scan it was last seen in has a Fair Value.
    fair_value_in = (
        {at: cache.fair_values(conn, market, config, at) for at in (window.start, window.end)}
        if pairing.sales
        else {}
    )

    def priced_like_a_sale(d: Disappearance) -> bool:
        last_seen = fair_value_in[d.last_seen][d.item_key]
        fair_value = min(last_seen, fair_value_in[d.gone_at].get(d.item_key, last_seen))
        return d.unit_buyout <= config.probable_sale_max_fair_value_multiple * fair_value

    probable_sales = [d for d in pairing.sales if priced_like_a_sale(d)]
    # (Item Key, window end, unit buyout, units) of every Partial Sale and Probable Sale.
    sales = ends.partial_sales + [
        (d.item_key, d.gone_at, d.unit_buyout, d.quantity) for d in probable_sales
    ]
    evidence = _WindowEvidence(
        sale_events=_sale_events(sales),
        reposts=pairing.reposts,
        coincidences=[d for d in pairing.coincidences if priced_like_a_sale(d)],
    )
    new.evidence[key] = evidence
    return evidence


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


@dataclass(frozen=True, order=True)
class SaleRecord:
    """Units of another player's Listing seen to sell between two Scans in any gap, not
    only an Observation Window: the Backtest's evidence of what a post would have sold
    (#167, ADR-0032). Not used by the Sell Rate."""

    item_key: str
    unit_buyout: int
    units: int
    last_seen: int  # requested_at of the Scan before the sale
    seen_at: int  # requested_at of the Scan it was seen sold in


# A Listing gone over a longer gap may have been cancelled as likely as sold (ADR-0032).
SALE_RECORD_MAX_GAP_SECONDS = 12 * 3600


def sale_records(
    conn: sqlite3.Connection,
    market: Market,
    config: Config,
    fair_value_cache: FairValueCache | None = None,
) -> list[SaleRecord]:
    """Every Sale Record of the Market, by the Scan it was seen sold in: other players'
    Partial Sales in any gap, and their Disappearances in a gap of at most 12 h whose
    time-left bucket rules out expiry and no Repost explains. Each is priced at most the
    Probable Sale multiple of the Fair Value in the Scan before it (none there, or 0: no cap).
    `fair_value_cache` as in `sell_rate_evidence`."""
    cache = FairValueCache() if fair_value_cache is None else fair_value_cache
    seen = cache.listings(conn, market)
    after = dict(pairwise(scan_times(conn, market)))
    before = {b: a for a, b in after.items()}
    dropped = dropped_item_ids(conn, market)

    candidates: dict[int, list[Disappearance]] = defaultdict(list)
    new_in: dict[int, list[Listing]] = defaultdict(list)
    for listing in seen:
        new_in[listing.first_seen].append(listing)
        gone_at = after.get(listing.last_seen)
        if (
            not listing.own
            and gone_at is not None
            and _gone_like_a_sale(listing, gone_at, dropped, config)
        ):
            candidates[gone_at].append(_disappearance(listing, gone_at, config))
    records = [
        SaleRecord(d.item_key, d.unit_buyout, d.quantity, d.last_seen, d.gone_at)
        for gone_at, ds in candidates.items()
        for d in _pair_reposts(ds, new_in[gone_at]).sales
    ]
    records += [
        SaleRecord(p.item_key, p.unit_buyout, p.units_sold, before[p.seen_at], p.seen_at)
        for p in partial_sales(conn, market)
        if not p.own
        and p.seen_at in before
        and not _left_out(p.item_key, before[p.seen_at], p.seen_at, dropped)
    ]

    def priced_like_a_sale(r: SaleRecord) -> bool:
        fair_value = cache.fair_values(conn, market, config, r.last_seen).get(r.item_key)
        return (
            not fair_value
            or r.unit_buyout <= config.probable_sale_max_fair_value_multiple * fair_value
        )

    return sorted((r for r in records if priced_like_a_sale(r)), key=lambda r: r.seen_at)


def _gone_like_a_sale(
    listing: Listing, gone_at: int, dropped: dict[int, frozenset[int]], config: Config
) -> bool:
    """Whether `listing`, missing from the Scan at `gone_at`, went the way a Sale Record's
    Listing must: in a gap of at most 12 h its time-left bucket rules out expiring in,
    and not maybe just missed by a Scan that dropped rows."""
    return (
        gone_at - listing.last_seen <= SALE_RECORD_MAX_GAP_SECONDS
        and not _left_out(listing.item_key, listing.last_seen, gone_at, dropped)
        and not _disappearance(listing, gone_at, config).expiry_possible
    )


def _left_out(
    item_key: str, last_seen: int, seen_at: int, dropped: dict[int, frozenset[int]]
) -> bool:
    """The Scan may only have missed it (#150)."""
    either = dropped.get(last_seen, frozenset()) | dropped.get(seen_at, frozenset())
    return item_id_of(item_key) in either


@dataclass(frozen=True)
class GraderCalibration:
    """The Sale Record rule tried on the player's own Listings, whose mail says what
    became of them (#167): of the own Listings it calls gone that a mail matched,
    how many sold, and how many Sold mails matched an own Listing that went missing at
    all (the sales it could have caught)."""

    matched: int
    sold: int
    sold_mails: int


def grader_calibration(
    conn: sqlite3.Connection, market: Market, config: Config
) -> GraderCalibration:
    """Each own Listing that went missing, oldest last seen first, matched to the first
    Sold, Cancelled or Expired mail not matched yet with its item name and count (and,
    when Sold, its stack price) read after it was last seen. Only those the Sale Record
    rule calls gone are counted. It doesn't move the grader's bounds."""
    after = dict(pairwise(scan_times(conn, market)))
    dropped = dropped_item_ids(conn, market)
    mails = outcomes(conn, market)
    used: set[int] = set()
    matched = sold = sold_mails = 0
    gone = [x for x in listings(conn, market) if x.own and x.last_seen in after]
    for listing in sorted(gone, key=lambda x: x.last_seen):
        match = next(
            (
                i
                for i, o in enumerate(mails)
                if i not in used
                and o.item_name == listing.item_name
                and o.count == listing.quantity
                and o.first_seen >= listing.last_seen
                and (o.kind is not MailKind.SOLD or o.price == listing.unit_buyout * o.count)
            ),
            None,
        )
        if match is None:
            continue
        used.add(match)
        sold_mails += mails[match].kind is MailKind.SOLD
        if _gone_like_a_sale(listing, after[listing.last_seen], dropped, config):
            matched += 1
            sold += mails[match].kind is MailKind.SOLD
    return GraderCalibration(matched, sold, sold_mails)
