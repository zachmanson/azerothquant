import dataclasses
from pathlib import Path

import pytest

from brain.archive import ScanArchive
from brain.config import Config, Era, Install
from brain.history import (
    ImportFileError,
    Listing,
    Market,
    PartialSale,
    import_file,
    import_scans,
    listings,
    open_history,
    partial_sales,
)

T0 = 1_790_000_000
MINUTE = 60
HOUR = 60 * MINUTE

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


def row(item=LINEN, quantity=1, unit=100, time_left=4, own=False):
    r = {"itemString": item, "quantity": quantity, "buyout": quantity * unit, "timeLeft": time_left}
    if own:
        r["own"] = True
    return r


def listing(first_seen, last_seen, quantity=1, unit=100, time_left=4, own=False, key=LINEN_KEY):
    return Listing(
        item_key=key,
        unit_buyout=unit,
        own=own,
        quantity=quantity,
        time_left=time_left,
        first_seen=first_seen,
        last_seen=last_seen,
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


def test_after_more_than_48_hours_everything_is_new(db):
    later = T0 + 48 * HOUR + 1
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


def test_scan_older_than_the_latest_imported_is_rejected(db):
    t1 = T0 + 20 * MINUTE
    run(db, scan(t1, row(quantity=15)))

    report = run(db, scan(T0, row(quantity=20)))

    assert report.scans_out_of_order == 1
    assert "older" in report.warnings[0]
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


# --- Scan Archive (ADR-0005) ---


def archived_config(tmp_path):
    return dataclasses.replace(CONFIG, archive_dir=tmp_path / "archive")


def test_every_imported_scan_is_archived_verbatim(db, tmp_path):
    config = archived_config(tmp_path)
    first = scan(T0, row(quantity=20), {"itemString": "garbage", "quantity": 1})
    second = scan(T0 + 20 * MINUTE, row(quantity=15))

    import_scans(db, [first, second], Era.BETA, config)

    archived = sorted(ScanArchive(config.archive_dir).scans(), key=lambda s: s[1]["requestedAt"])
    assert archived == [(Era.BETA, first), (Era.BETA, second)]


def test_a_scan_older_than_the_history_is_still_archived(db, tmp_path):
    config = archived_config(tmp_path)
    import_scans(db, [scan(T0 + HOUR, row())], Era.BETA, config)

    report = import_scans(db, [scan(T0, row())], Era.BETA, config)

    assert report.scans_out_of_order == 1
    assert len(list(ScanArchive(config.archive_dir).scans())) == 2


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
