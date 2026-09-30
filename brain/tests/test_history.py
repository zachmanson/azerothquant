import dataclasses
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from brain.archive import Archive
from brain.config import Config, Era, Install
from brain.history import (
    ImportFileError,
    Listing,
    Market,
    Outcome,
    PartialSale,
    Purchase,
    import_file,
    import_mailbox_reads,
    import_scans,
    listings,
    open_history,
    outcomes,
    partial_sales,
    purchases,
)
from brain.mailbox import MailKind

T0 = 1_790_000_000
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR

CONFIG = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))
MARKET = Market(realm="Classic Beta PvP", faction="Alliance", era=Era.BETA)
LINEN = "item:2589::::::::20:1490"
LINEN_KEY = "2589"


def scan(at, *rows, faction="Alliance", realm="Classic Beta PvP"):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": realm,
        "character": "Kash-Patel",
        "faction": faction,
        "droppedRows": 0,
        "listings": list(rows),
    }


def row(item=LINEN, quantity=1, unit=100, time_left=4, own=False, name=None):
    r = {"itemString": item, "quantity": quantity, "buyout": quantity * unit, "timeLeft": time_left}
    if own:
        r["own"] = True
    if name is not None:
        r["name"] = name
    return r


def listing(
    first_seen, last_seen, quantity=1, unit=100, time_left=4, own=False, key=LINEN_KEY, name=None
):
    return Listing(
        item_key=key,
        unit_buyout=unit,
        own=own,
        quantity=quantity,
        time_left=time_left,
        first_seen=first_seen,
        last_seen=last_seen,
        item_name=name,
    )


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def run(db, *scans, era=Era.BETA):
    return import_scans(db, list(scans), era, CONFIG)


# --- Listing lifetimes ---


def test_first_scan_creates_new_listings(db):
    run(db, scan(T0, row(quantity=20, unit=97), row(unit=500)))

    assert sorted(listings(db, MARKET)) == [
        listing(T0, T0, quantity=20, unit=97),
        listing(T0, T0, quantity=1, unit=500),
    ]


def test_listing_seen_again_is_extended(db):
    run(db, scan(T0, row(time_left=4)), scan(T0 + 20 * MINUTE, row(time_left=3)))

    assert listings(db, MARKET) == [listing(T0, T0 + 20 * MINUTE, time_left=3)]


def test_listing_missing_from_next_scan_is_a_disappearance(db):
    run(db, scan(T0, row(unit=100), row(unit=200)), scan(T0 + 20 * MINUTE, row(unit=100)))

    # Last seen in the first Scan, and the Market has moved on: it disappeared.
    assert sorted(listings(db, MARKET)) == [
        listing(T0, T0 + 20 * MINUTE, unit=100),
        listing(T0, T0, unit=200),
    ]


def test_quantity_drop_is_a_partial_sale(db):
    run(db, scan(T0, row(quantity=20)), scan(T0 + 20 * MINUTE, row(quantity=15)))

    assert listings(db, MARKET) == [listing(T0, T0 + 20 * MINUTE, quantity=15)]
    assert partial_sales(db, MARKET) == [
        PartialSale(
            item_key=LINEN_KEY, unit_buyout=100, own=False, seen_at=T0 + 20 * MINUTE, units_sold=5
        )
    ]


def test_same_quantity_records_no_partial_sale(db):
    run(db, scan(T0, row(quantity=20)), scan(T0 + 20 * MINUTE, row(quantity=20)))

    assert partial_sales(db, MARKET) == []


# --- matching rules ---


def test_quantity_going_up_is_a_new_listing(db):
    run(db, scan(T0, row(quantity=5)), scan(T0 + 20 * MINUTE, row(quantity=8)))

    assert sorted(listings(db, MARKET)) == [
        listing(T0, T0, quantity=5),
        listing(T0 + 20 * MINUTE, T0 + 20 * MINUTE, quantity=8),
    ]
    assert partial_sales(db, MARKET) == []


def test_time_left_going_up_never_matches(db):
    run(db, scan(T0, row(time_left=2)), scan(T0 + 20 * MINUTE, row(time_left=3)))

    assert sorted(listings(db, MARKET)) == [
        listing(T0, T0, time_left=2),
        listing(T0 + 20 * MINUTE, T0 + 20 * MINUTE, time_left=3),
    ]


def test_no_match_when_the_gap_is_longer_than_the_bucket_allows(db):
    # Bucket 1 is under 30 minutes: it can't still be there an hour later.
    run(db, scan(T0, row(time_left=1)), scan(T0 + HOUR, row(time_left=1)))

    assert sorted(listings(db, MARKET)) == [
        listing(T0, T0, time_left=1),
        listing(T0 + HOUR, T0 + HOUR, time_left=1),
    ]


def test_bucket_that_can_last_the_gap_still_matches(db):
    run(db, scan(T0, row(time_left=1)), scan(T0 + 30 * MINUTE, row(time_left=1)))

    assert listings(db, MARKET) == [listing(T0, T0 + 30 * MINUTE, time_left=1)]


def test_after_more_than_24_hours_everything_is_new(db):
    later = T0 + 24 * HOUR + 1
    run(db, scan(T0, row(time_left=4)), scan(later, row(time_left=4)))

    assert sorted(listings(db, MARKET)) == [
        listing(T0, T0),
        listing(later, later),
    ]


def test_prefers_the_match_that_needs_no_partial_sale(db):
    # Previous x10 and x5, current x5: the x5 is still there and the x10 disappeared,
    # rather than 5 of the x10 selling and the x5 disappearing.
    t1 = T0 + 20 * MINUTE
    run(db, scan(T0, row(quantity=10), row(quantity=5)), scan(t1, row(quantity=5)))

    assert sorted(listings(db, MARKET)) == [
        listing(T0, t1, quantity=5),
        listing(T0, T0, quantity=10),
    ]
    assert partial_sales(db, MARKET) == []


def test_fewest_new_listings_wins_over_fewest_partial_sale_units(db):
    # Previous x10 and x5, current x5 and x7. Only the x10 can become the x7, so matching
    # both (a Partial Sale of 3) beats keeping the x5 and calling the x7 new.
    t1 = T0 + 20 * MINUTE
    run(
        db,
        scan(T0, row(quantity=10), row(quantity=5)),
        scan(t1, row(quantity=5), row(quantity=7)),
    )

    assert sorted(listings(db, MARKET)) == [
        listing(T0, t1, quantity=5),
        listing(T0, t1, quantity=7),
    ]
    assert partial_sales(db, MARKET) == [
        PartialSale(item_key=LINEN_KEY, unit_buyout=100, own=False, seen_at=t1, units_sold=3)
    ]


def test_fewest_new_listings_considers_time_left(db):
    # The bucket-3 row can only come from the bucket-3 Listing, so the bucket-2 row
    # must take the bucket-2 one, even though either previous Listing could become it.
    t1 = T0 + 20 * MINUTE
    run(
        db,
        scan(T0, row(time_left=3), row(time_left=2)),
        scan(t1, row(time_left=2), row(time_left=3)),
    )

    assert all(entry.first_seen == T0 and entry.last_seen == t1 for entry in listings(db, MARKET))
    assert len(listings(db, MARKET)) == 2


def test_identical_listings_are_interchangeable(db):
    t1 = T0 + 20 * MINUTE
    run(db, scan(T0, *[row(quantity=20)] * 3), scan(t1, *[row(quantity=20)] * 2))

    assert sorted(listings(db, MARKET)) == [
        listing(T0, T0, quantity=20),
        listing(T0, t1, quantity=20),
        listing(T0, t1, quantity=20),
    ]


def test_own_and_not_own_at_the_same_price_never_match(db):
    t1 = T0 + 20 * MINUTE
    run(db, scan(T0, row(own=True)), scan(t1, row(own=False)))

    assert sorted(listings(db, MARKET)) == [
        listing(t1, t1, own=False),
        listing(T0, T0, own=True),
    ]


def test_different_prices_or_item_keys_never_match(db):
    t1 = T0 + 20 * MINUTE
    run(db, scan(T0, row(unit=100)), scan(t1, row(unit=99), row(item="item:2592", unit=100)))

    assert [entry.last_seen for entry in listings(db, MARKET)] == [T0, t1, t1]


# --- item names (#17) ---


def test_own_listings_keep_the_item_name_and_others_dont(db):
    run(
        db,
        scan(
            T0,
            row(own=True, name="Linen Cloth"),
            # A name on someone else's row isn't an error; it's just not kept.
            row(unit=90, name="Linen Cloth"),
            row(unit=80),
        ),
    )

    assert sorted(listings(db, MARKET)) == [
        listing(T0, T0, unit=80),
        listing(T0, T0, unit=90),
        listing(T0, T0, own=True, name="Linen Cloth"),
    ]


def test_scans_from_before_names_import_with_no_name(db):
    # Archive files from before #17 have no name on any row, own or not.
    run(db, scan(T0, row(own=True)))

    assert listings(db, MARKET) == [listing(T0, T0, own=True)]


def test_an_own_listing_first_seen_without_a_name_gets_it_when_seen_with_one(db):
    # A Listing still up when the Addon starts recording names can then be matched too.
    t1 = T0 + 20 * MINUTE
    run(db, scan(T0, row(own=True)), scan(t1, row(own=True, name="Linen Cloth")))

    assert listings(db, MARKET) == [listing(T0, t1, own=True, name="Linen Cloth")]


def test_a_history_from_before_names_gets_the_column(tmp_path):
    path = tmp_path / "history.sqlite"
    with closing(sqlite3.connect(path)) as old:
        # The listing table as it was before #17. Frozen on purpose: don't sync it with _SCHEMA.
        old.executescript(
            "CREATE TABLE listing (id INTEGER PRIMARY KEY, market_id INTEGER NOT NULL,"
            " item_key TEXT NOT NULL, unit_buyout INTEGER NOT NULL, own INTEGER NOT NULL,"
            " first_seen_scan_id INTEGER NOT NULL, last_seen_scan_id INTEGER NOT NULL,"
            " quantity INTEGER NOT NULL, time_left INTEGER NOT NULL);"
        )

    with closing(open_history(path)) as conn:
        run(conn, scan(T0, row(own=True, name="Linen Cloth")))

        assert listings(conn, MARKET) == [listing(T0, T0, own=True, name="Linen Cloth")]


# --- flagged rows ---


def test_row_with_inexact_unit_buyout_is_counted_and_left_out(db):
    report = run(db, scan(T0, {"itemString": LINEN, "quantity": 20, "buyout": 1941, "timeLeft": 4}))

    assert listings(db, MARKET) == []
    assert report.inexact_rows == 1
    assert any("whole number of copper" in w for w in report.warnings)


def test_unreadable_row_is_counted_and_left_out(db):
    report = run(db, scan(T0, row(item="item:9768::::::77"), row()))

    assert len(listings(db, MARKET)) == 1
    assert report.unreadable_rows == 1


def test_scan_missing_its_header_is_rejected_with_a_warning(db):
    bad = scan(T0, row())
    del bad["realm"]

    report = run(db, bad, scan(T0, row()))

    assert report.scans_unreadable == 1
    assert report.scans_imported == 1
    assert "realm" in report.warnings[0]


# --- import rules ---


def test_reimporting_the_same_scans_changes_nothing(db):
    t1 = T0 + 20 * MINUTE
    scans = [scan(T0, row(quantity=20), row(unit=500)), scan(t1, row(quantity=15))]
    run(db, *scans)
    before = (listings(db, MARKET), partial_sales(db, MARKET))

    report = run(db, *scans)

    assert (listings(db, MARKET), partial_sales(db, MARKET)) == before
    assert report.scans_imported == 0
    assert report.scans_already_imported == 2


def test_scans_in_a_file_are_imported_oldest_first(db):
    t1 = T0 + 20 * MINUTE
    run(db, scan(t1, row(quantity=15)), scan(T0, row(quantity=20)))

    assert listings(db, MARKET) == [listing(T0, t1, quantity=15)]


def test_without_an_archive_a_late_scan_waits_for_rebuild(db):
    # A re-match reads the Market's Scans back from the Archive (tests/test_rematch.py).
    t1 = T0 + 20 * MINUTE
    run(db, scan(t1, row(quantity=15)))

    report = run(db, scan(T0, row(quantity=20)))

    assert report.scans_waiting_for_rebuild == 1
    assert "brain rebuild" in report.warnings[0]
    assert listings(db, MARKET) == [listing(t1, t1, quantity=15)]


def test_markets_are_kept_separate(db):
    t1 = T0 + 20 * MINUTE
    horde = Market(realm="Classic Beta PvP", faction="Horde", era=Era.BETA)
    run(db, scan(T0, row()), scan(t1, row(), faction="Horde"))

    # The Horde Scan neither extends nor ends the Alliance Listing.
    assert listings(db, MARKET) == [listing(T0, T0)]
    assert listings(db, horde) == [listing(t1, t1)]


def test_eras_are_different_markets(db):
    run(db, scan(T0, row()), era=Era.BETA)
    run(db, scan(T0 + 20 * MINUTE, row()), era=Era.LIVE)

    live = Market(realm="Classic Beta PvP", faction="Alliance", era=Era.LIVE)
    assert listings(db, MARKET) == [listing(T0, T0)]
    assert listings(db, live) == [listing(T0 + 20 * MINUTE, T0 + 20 * MINUTE)]


# --- importing a SavedVariables file ---

FIXTURE = Path(__file__).parent / "fixtures" / "AzerothQuant.lua"


def install_fixture(tmp_path):
    install = tmp_path / "_classic_beta_"
    saved = install / "WTF" / "Account" / "ACCOUNT" / "SavedVariables" / "AzerothQuant.lua"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(FIXTURE.read_bytes())
    return Config(installs=(Install(path=install, era=Era.BETA),)), saved


def test_imports_a_savedvariables_file_with_the_era_of_its_install(db, tmp_path):
    config, saved = install_fixture(tmp_path)

    report = import_file(db, saved, config)

    assert report.scans_imported == 2
    assert report.inexact_rows == 1
    assert sorted(listings(db, MARKET)) == [
        listing(1790000000, 1790001200, quantity=15, unit=97),
        Listing("9768:12743", 45000, True, 1, 3, 1790000000, 1790000000),
    ]
    assert partial_sales(db, MARKET) == [PartialSale(LINEN_KEY, 97, False, 1790001200, 5)]


def test_rejects_a_file_outside_every_install(db, tmp_path):
    config, _ = install_fixture(tmp_path)
    stray = tmp_path / "elsewhere" / "AzerothQuant.lua"
    stray.parent.mkdir()
    stray.write_bytes(FIXTURE.read_bytes())

    with pytest.raises(ImportFileError, match="install"):
        import_file(db, stray, config)


# --- Archive (ADR-0005) ---


def archived_config(tmp_path):
    return dataclasses.replace(CONFIG, archive_dir=tmp_path / "archive")


def test_every_imported_scan_is_archived_verbatim(db, tmp_path):
    config = archived_config(tmp_path)
    first = scan(T0, row(quantity=20), {"itemString": "garbage", "quantity": 1})
    second = scan(T0 + 20 * MINUTE, row(quantity=15))

    import_scans(db, [first, second], Era.BETA, config)

    archived = sorted(Archive(config.archive_dir).scans(), key=lambda s: s[1]["requestedAt"])
    assert archived == [(Era.BETA, first), (Era.BETA, second)]


def test_scan_timings_are_imported_past_and_archived_verbatim(db, tmp_path):
    # firstUpdateAt and readAt (#15) are diagnostic only: the Brain doesn't use them,
    # but must import the Scan as usual and keep them in the Archive.
    config = archived_config(tmp_path)
    timed = scan(T0, row(quantity=20)) | {"firstUpdateAt": T0 + 5, "readAt": T0 + 31}

    report = import_scans(db, [timed], Era.BETA, config)

    assert report.scans_imported == 1
    assert listings(db, MARKET) == [listing(T0, T0, quantity=20)]
    assert list(Archive(config.archive_dir).scans()) == [(Era.BETA, timed)]


def test_a_late_scan_is_archived_too(db, tmp_path):
    config = archived_config(tmp_path)
    import_scans(db, [scan(T0 + HOUR, row())], Era.BETA, config)

    report = import_scans(db, [scan(T0, row())], Era.BETA, config)

    assert report.scans_rematched == 1
    assert len(list(Archive(config.archive_dir).scans())) == 2


def test_a_scan_that_cant_be_archived_isnt_imported(db, tmp_path):
    config = archived_config(tmp_path)
    config.archive_dir.write_text("a file where the archive folder should be")

    with pytest.raises(OSError):
        import_scans(db, [scan(T0, row())], Era.BETA, config)

    # Not in the history, so the Addon keeps it and the Brain tries again later.
    assert listings(db, MARKET) == []
    assert db.execute("SELECT COUNT(*) FROM scan").fetchone() == (0,)


def test_without_an_archive_folder_nothing_is_archived(db, tmp_path):
    run(db, scan(T0, row()))

    assert list(tmp_path.iterdir()) == []


# --- Mailbox Reads (#15) ---


def mailbox_read(at=T0, character="Kash-Patel", **extra):
    return {
        "readAt": at,
        "realm": "Classic Beta PvP",
        "character": character,
        "shownCount": 0,
        "totalCount": 0,
        "skippedMails": 0,
        "mails": [],
        **extra,
    }


def test_reimporting_the_same_mailbox_read_changes_nothing(db, tmp_path):
    config = archived_config(tmp_path)
    import_mailbox_reads(db, [mailbox_read()], Era.BETA, config)

    report = import_mailbox_reads(db, [mailbox_read()], Era.BETA, config)

    assert report.mailbox_reads_imported == 0
    assert report.mailbox_reads_already_imported == 1
    assert len(list(Archive(config.archive_dir).mailbox_reads())) == 1


def test_a_mailbox_read_that_cant_be_named_is_skipped_and_not_archived(db, tmp_path):
    # Without realm, character and readAt it has no identity or file name, so it stays in
    # SavedVariables where it can at least be looked at.
    config = archived_config(tmp_path)
    no_time = mailbox_read()
    del no_time["readAt"]

    report = import_mailbox_reads(
        db, [no_time, mailbox_read(character=None), "junk"], Era.BETA, config
    )

    assert report.mailbox_reads_unreadable == 3
    assert len(report.warnings) == 3
    assert list(Archive(config.archive_dir).mailbox_reads()) == []


# --- Outcomes and Purchases from Mailbox Reads (#15) ---


def sold_mail(name="Tigerseye", count=1, price=110, sender="Alliance Auction House", days=30):
    return {
        "index": 1,
        "sender": sender,
        "subject": f"Auction successful: {name}" + (f" ({count})" if count > 1 else ""),
        "money": price - price // 20 + 100,
        "daysLeft": days,
        "invoice": {"invoiceType": "seller", "itemName": name, "bid": price, "count": count},
    }


def won_mail(price=1, days=29.9):
    return {
        "index": 1,
        "sender": "Alliance Auction House",
        "subject": "Auction won: Heavy Shot",
        "money": 0,
        "daysLeft": days,
        "firstItemQuantity": 1,
        "firstItemLink": "|cnIQ1:|Hitem:2519::::::::20:1490:::::::::|h[Heavy Shot]|h|r",
        "invoice": {"invoiceType": "buyer", "itemName": "Heavy Shot", "bid": price, "count": 1},
    }


def read_with(at, *mails, character="Kash-Patel", shown=None, total=None):
    shown = len(mails) if shown is None else shown
    return mailbox_read(
        at,
        character=character,
        mails=list(mails),
        shownCount=shown,
        totalCount=shown if total is None else total,
    )


def read_mail(db, *reads):
    return import_mailbox_reads(db, list(reads), Era.BETA, CONFIG)


def test_a_sale_seen_again_mid_take_is_one_outcome(db):
    # Seen on the client (#100): the money leaves the mail a moment before the mail goes.
    sold = sold_mail(days=29.99)
    read_mail(
        db,
        read_with(T0, sold),
        read_with(T0 + 1, {**sold, "money": 0}),
        read_with(T0 + 2),
    )

    assert len(outcomes(db, MARKET)) == 1


def test_mail_becomes_outcomes_and_purchases_in_the_senders_market(db):
    read_mail(db, read_with(T0, sold_mail(count=8, price=2304), won_mail(days=29.5)))

    assert outcomes(db, MARKET) == [
        Outcome(
            character="Kash-Patel",
            kind=MailKind.SOLD,
            item_name="Tigerseye",
            item_key=None,
            count=8,
            price=2304,
            money=2304 - 115 + 100,
            arrived_at=None,
            first_seen=T0,
        )
    ]
    assert purchases(db, MARKET) == [
        Purchase(
            character="Kash-Patel",
            item_name="Heavy Shot",
            item_key="2519",
            count=1,
            price=1,
            arrived_at=T0 - DAY // 2,
            first_seen=T0,
        )
    ]
    horde = dataclasses.replace(MARKET, faction="Horde")
    assert outcomes(db, horde) == [] and purchases(db, horde) == []


def test_mail_still_there_in_the_next_read_isnt_counted_again(db):
    # Sold mail stayed at exactly 30 days in the spike, so this can't lean on arrival times.
    read_mail(db, read_with(T0, sold_mail()), read_with(T0 + HOUR, sold_mail()))

    assert len(outcomes(db, MARKET)) == 1


def test_a_second_identical_mail_is_a_second_outcome(db):
    read_mail(db, read_with(T0, sold_mail()), read_with(T0 + HOUR, sold_mail(), sold_mail()))

    assert len(outcomes(db, MARKET)) == 2


def test_mail_taken_and_then_sent_again_is_new(db):
    # Tigerseye sells, is taken, and a second one sells before the next visit.
    read_mail(
        db,
        read_with(T0, sold_mail()),
        read_with(T0 + HOUR),
        read_with(T0 + 2 * HOUR, sold_mail()),
    )

    assert len(outcomes(db, MARKET)) == 2


def test_an_identical_mail_that_arrived_later_is_new_even_without_an_empty_read_between(db):
    # Won at T0 - 1 day, taken; another won at T0 + 1 hour. Their arrivals give them away.
    read_mail(
        db,
        read_with(T0, won_mail(days=29)),
        read_with(T0 + 2 * HOUR, won_mail(days=30 - 1 / 24)),
    )

    assert [p.arrived_at for p in purchases(db, MARKET)] == [T0 - DAY, T0 + HOUR]


def test_mail_hidden_by_a_full_inbox_isnt_counted_again_when_it_shows(db):
    # Only 50 mails show; a mail left out of an incomplete read is still in the inbox.
    read_mail(
        db,
        read_with(T0, sold_mail()),
        read_with(T0 + HOUR, shown=0, total=60),
        read_with(T0 + 2 * HOUR, sold_mail()),
    )

    assert len(outcomes(db, MARKET)) == 1


def test_a_mail_that_cant_be_read_yet_isnt_counted_again_when_it_can(db):
    # A header or invoice the client hasn't loaded yet (#100) may be a mail already
    # known, so a Read with an unreadable mail takes nothing out of the inbox.
    sold = sold_mail(days=29.99)
    loading = {**sold, "subject": "Retrieving data"}
    no_invoice = {k: v for k, v in sold.items() if k != "invoice"}
    read_mail(
        db,
        read_with(T0, sold),
        read_with(T0 + 1, loading),
        read_with(T0 + 2, no_invoice),
        read_with(T0 + 3, sold),
    )

    assert len(outcomes(db, MARKET)) == 1


def test_each_characters_inbox_is_separate(db):
    read_mail(db, read_with(T0, sold_mail()), read_with(T0 + HOUR, sold_mail(), character="Alt"))

    assert [o.character for o in outcomes(db, MARKET)] == ["Kash-Patel", "Alt"]


def test_reads_are_interpreted_oldest_first_whatever_their_order(db):
    read_mail(db, read_with(T0 + HOUR, sold_mail()), read_with(T0, sold_mail()))

    assert [o.first_seen for o in outcomes(db, MARKET)] == [T0]


def test_a_read_older_than_one_already_interpreted_waits_for_a_rebuild(db):
    read_mail(db, read_with(T0 + HOUR))

    report = read_mail(db, read_with(T0, sold_mail()))

    assert report.mailbox_reads_imported == 1
    assert report.mailbox_reads_out_of_order == 1
    assert "brain rebuild" in report.warnings[0]
    assert outcomes(db, MARKET) == []


def test_reimporting_a_read_doesnt_interpret_it_again(db):
    read_mail(db, read_with(T0, sold_mail()))
    read_mail(db, read_with(T0, sold_mail(), sold_mail()))

    assert len(outcomes(db, MARKET)) == 1


def test_mail_from_an_unknown_sender_is_flagged_and_left_out_of_every_market(db):
    report = read_mail(db, read_with(T0, sold_mail(sender="Blackwater Auction House")))

    assert report.mails_unassigned == 1
    assert "Blackwater Auction House" in report.warnings[0]
    for faction in ("Alliance", "Horde", "Neutral"):
        assert outcomes(db, dataclasses.replace(MARKET, faction=faction)) == []


def test_unassigned_mail_is_still_matched_across_reads(db):
    unknown = sold_mail(sender="Blackwater Auction House")

    report = read_mail(db, read_with(T0, unknown), read_with(T0 + HOUR, unknown))

    assert report.mails_unassigned == 1


def test_mail_the_brain_cant_read_is_counted_and_the_rest_imported(db):
    report = read_mail(db, read_with(T0, sold_mail(), {"sender": "Alliance Auction House"}))

    assert report.mails_unreadable == 1
    assert len(report.warnings) == 1
    assert len(outcomes(db, MARKET)) == 1


def test_counts_new_outcomes_and_purchases(db):
    report = read_mail(db, read_with(T0, sold_mail(), won_mail()), read_with(T0 + 1, sold_mail()))

    assert (report.outcomes_found, report.purchases_found) == (1, 1)
