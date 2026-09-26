import json
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from brain.archive import Archive
from brain.cli import RebuildError, run_import, run_rebuild, run_recommend, savedvariables_files
from brain.config import Config, Era, Install
from brain.history import (
    Holding,
    Market,
    holdings,
    import_character_reads,
    import_scans,
    listings,
    open_history,
    outcomes,
    pooled_gold,
    vendor_prices,
)
from brain.recommendations import FILE_NAME, GLOBAL_NAME, addon_folder
from brain.savedvariables import parse_savedvariables

FIXTURE = Path(__file__).parent / "fixtures" / "AzerothQuant.lua"
MARKET = Market(realm="Classic Beta PvP", faction="Alliance", era=Era.BETA)


def install_with_savedvariables(root: Path, account: str = "ACCOUNT1") -> Path:
    """A WoW install folder with the fixture as one account's SavedVariables file."""
    folder = root / "WTF" / "Account" / account / "SavedVariables"
    folder.mkdir(parents=True)
    shutil.copy(FIXTURE, folder / "AzerothQuant.lua")
    return folder / "AzerothQuant.lua"


def config_for(tmp_path: Path, *installs: Install) -> Config:
    return Config(
        installs=installs,
        history_path=tmp_path / "history.sqlite",
        archive_dir=tmp_path / "archive",
    )


def test_finds_the_savedvariables_file_of_every_account_in_every_install(tmp_path):
    beta = tmp_path / "_classic_beta_"
    live = tmp_path / "_classic_"
    a = install_with_savedvariables(beta, "ACCOUNT1")
    b = install_with_savedvariables(beta, "ACCOUNT2")
    c = install_with_savedvariables(live, "ACCOUNT1")
    # WoW keeps the previous version as a .bak, which is never imported.
    shutil.copy(FIXTURE, a.with_suffix(".lua.bak"))
    config = config_for(tmp_path, Install(beta, Era.BETA), Install(live, Era.LIVE))

    assert sorted(savedvariables_files(config)) == sorted([a, b, c])


def test_imports_every_savedvariables_file_into_the_history(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))

    results = run_import(config, [file])

    assert [r.path for r in results] == [file]
    assert results[0].error is None
    assert results[0].report.scans_imported > 0
    with closing(open_history(config.history_path)) as conn:
        assert listings(conn, MARKET)


def test_a_half_written_file_is_reported_without_stopping_the_others(tmp_path):
    install = tmp_path / "_classic_beta_"
    good = install_with_savedvariables(install, "ACCOUNT1")
    half = install_with_savedvariables(install, "ACCOUNT2")
    text = half.read_text(encoding="utf-8")
    half.write_text(text[: len(text) // 2], encoding="utf-8")
    config = config_for(tmp_path, Install(install, Era.BETA))

    results = run_import(config, [half, good])

    assert results[0].path == half
    assert results[0].error is not None
    assert results[1].error is None
    assert results[1].report.scans_imported > 0


def test_a_file_outside_every_install_is_reported_as_an_error(tmp_path):
    install = tmp_path / "_classic_beta_"
    stray = install_with_savedvariables(tmp_path / "elsewhere")
    config = config_for(tmp_path, Install(install, Era.BETA))

    [result] = run_import(config, [stray])

    assert "isn't inside any install folder" in result.error


def install_addon(install: Path) -> None:
    addon_folder(Install(install, Era.BETA)).mkdir(parents=True)


def read_recommendations(install: Path) -> dict:
    file = addon_folder(Install(install, Era.BETA)) / FILE_NAME
    return parse_savedvariables(file.read_text(encoding="utf-8"))[GLOBAL_NAME]


def test_import_tells_the_addon_the_latest_scan_imported_for_each_market(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    install_addon(install)
    config = config_for(tmp_path, Install(install, Era.BETA))

    run_import(config, [file])

    # The fixture holds two Alliance Scans on "Classic Beta PvP"; the later one is 1790001200.
    # Its two Mailbox Reads are Kash-Patel's; the later one is 1790001800.
    # So are its two Character Reads; the later one is 1790002000.
    assert read_recommendations(install) == {
        "lastImported": {"Classic Beta PvP": {"Alliance": 1790001200}},
        "lastMailboxRead": {"Classic Beta PvP": {"Kash-Patel": 1790001800}},
        "lastCharacterRead": {"Classic Beta PvP": {"Kash-Patel": 1790002000}},
        "recommendations": [],
    }


def test_each_install_only_hears_about_its_own_era(tmp_path):
    beta = tmp_path / "_classic_beta_"
    live = tmp_path / "_classic_"
    file = install_with_savedvariables(beta)
    install_addon(beta)
    install_addon(live)
    config = config_for(tmp_path, Install(beta, Era.BETA), Install(live, Era.LIVE))

    run_import(config, [file])

    assert read_recommendations(beta)["lastImported"] == {
        "Classic Beta PvP": {"Alliance": 1790001200}
    }
    assert read_recommendations(live)["lastImported"] == []
    assert read_recommendations(beta)["lastMailboxRead"] == {
        "Classic Beta PvP": {"Kash-Patel": 1790001800}
    }
    assert read_recommendations(live)["lastMailboxRead"] == []
    assert read_recommendations(live)["lastCharacterRead"] == []


def test_an_install_without_the_addon_gets_no_file(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))

    [result] = run_import(config, [file])

    assert result.error is None
    assert not (install / "Interface").exists()


# --- Archive and rebuild (ADR-0005) ---


def dump(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as conn:
        return list(conn.iterdump())


def test_import_archives_every_scan_in_the_file(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))

    run_import(config, [file])

    archived = sorted(s["requestedAt"] for _, s in Archive(config.archive_dir).scans())
    assert archived == [1790000000, 1790001200]


def test_import_archives_every_mailbox_read_in_the_file_verbatim(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    saved = parse_savedvariables(file.read_text(encoding="utf-8"))["AzerothQuantDB"]

    results = run_import(config, [file])

    assert results[0].report.mailbox_reads_imported == 2
    archived = sorted(Archive(config.archive_dir).mailbox_reads(), key=lambda r: r[1]["readAt"])
    assert archived == [(Era.BETA, raw) for raw in saved["mailboxReads"]]
    # Kept apart from the Scans.
    assert len(list(Archive(config.archive_dir).scans())) == 2


def test_import_archives_every_character_read_in_the_file_verbatim(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    saved = parse_savedvariables(file.read_text(encoding="utf-8"))["AzerothQuantDB"]

    results = run_import(config, [file])

    assert results[0].report.character_reads_imported == 2
    archived = sorted(Archive(config.archive_dir).character_reads(), key=lambda r: r[1]["readAt"])
    # As JSON holds it: the vendorPrices keys become strings, which is all that changes.
    as_json = json.loads(json.dumps(saved["characterReads"]))
    assert archived == [(Era.BETA, raw) for raw in as_json]
    # Kept apart from the Scans and Mailbox Reads.
    assert len(list(Archive(config.archive_dir).scans())) == 2
    assert len(list(Archive(config.archive_dir).mailbox_reads())) == 2
    with closing(open_history(config.history_path)) as conn:
        # Bags from the later Read; the bank from the earlier one, the only one with a bank.
        assert holdings(conn, Era.BETA, "Classic Beta PvP", "Kash-Patel") == {
            "2589": Holding(bags=12, bank=40),
        }
        assert pooled_gold(conn, Era.BETA, "Classic Beta PvP", "Alliance") == 1200000


def test_rebuilding_from_the_archive_gives_the_same_history_as_importing(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    run_import(config, [file])
    imported = dump(config.history_path)

    report = run_rebuild(config)

    assert report.scans_imported == 2
    assert report.outcomes_found > 0
    assert report.character_reads_imported == 2
    assert dump(config.history_path) == imported
    with closing(open_history(config.history_path)) as conn:
        assert outcomes(conn, MARKET)
        # The fixture's Scans are from before #17: its own Listing has no name.
        assert [entry.item_name for entry in listings(conn, MARKET) if entry.own] == [None]
    assert not list(tmp_path.glob("*.rebuild*"))


def test_vendor_prices_come_back_the_same_from_the_archive(tmp_path):
    # The Archive is JSON, which turns the itemID keys into strings, and an empty Lua
    # table reads as a list. Neither may change what the rebuilt history holds.
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    expected = {2589: 10, 2592: 25, 6948: 0, 9768: 245}
    run_import(config, [file])
    with closing(open_history(config.history_path)) as conn:
        assert vendor_prices(conn, Era.BETA) == expected

    run_rebuild(config)

    with closing(open_history(config.history_path)) as conn:
        assert vendor_prices(conn, Era.BETA) == expected


def test_rebuild_replaces_a_history_that_has_drifted_from_the_archive(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    run_import(config, [file])
    imported = dump(config.history_path)
    with closing(sqlite3.connect(config.history_path)) as conn, conn:
        conn.execute("DELETE FROM partial_sale")

    run_rebuild(config)

    assert dump(config.history_path) == imported


def test_rebuild_refuses_an_empty_archive_rather_than_wipe_the_history(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    run_import(config, [file])
    imported = dump(config.history_path)
    shutil.rmtree(config.archive_dir)

    with pytest.raises(RebuildError, match="no Scans"):
        run_rebuild(config)

    assert dump(config.history_path) == imported


def test_rebuild_tells_the_addon_what_is_in_the_rebuilt_history(tmp_path):
    install = tmp_path / "_classic_beta_"
    file = install_with_savedvariables(install)
    install_addon(install)
    config = config_for(tmp_path, Install(install, Era.BETA))
    run_import(config, [file])
    (addon_folder(Install(install, Era.BETA)) / FILE_NAME).unlink()

    run_rebuild(config)

    assert read_recommendations(install)["lastImported"] == {
        "Classic Beta PvP": {"Alliance": 1790001200}
    }


def test_recommend_prints_holdings_and_the_shopping_list_as_tables(tmp_path):
    config = config_for(tmp_path, Install(tmp_path / "_classic_beta_", Era.BETA))
    linen = "item:2589::::::::20:1490"

    def scan(at, quantity, *extra):
        rows = [
            {"itemString": linen, "quantity": quantity, "buyout": quantity * 1000, "timeLeft": 4},
            *extra,
        ]
        return {
            "requestedAt": at,
            "realm": MARKET.realm,
            "faction": "Alliance",
            "character": "Kash-Patel",
            "listings": rows,
        }

    cheap = {"itemString": linen, "quantity": 2, "buyout": 1400, "timeLeft": 4}
    read = {
        "readAt": 1_790_000_000,
        "realm": MARKET.realm,
        "character": "Kash-Patel",
        "faction": "Alliance",
        "money": 123456,
        "vendorPrices": {2589: 10},
        "bags": [
            {
                "bag": 0,
                "slot": 1,
                "count": 3,
                "isBound": False,
                "link": "|cffffffff|Hitem:2589::::::::20:1490|h[Linen Cloth]|h|r",
            }
        ],
    }
    with closing(open_history(config.history_path)) as conn:
        # 2 Linen sold in an hour, so the 3 held all sell within the 7-day horizon.
        import_scans(
            conn, [scan(1_790_000_000, 20), scan(1_790_003_600, 18, cheap)], Era.BETA, config
        )
        import_character_reads(conn, [read], Era.BETA, config)

    text = run_recommend(config)

    lines = [re.split(r"\s{2,}", line.strip()) for line in text.splitlines()]
    assert "Classic Beta PvP Alliance (beta)" in text
    # The one Observation Window every Sell Rate here rests on.
    assert "Sell Rate observed for 1.0 h in the last 14 days" in text
    # Fair Value (700 + 700 + 1000) / 3 = 800, less the 5% cut: 760 each, 750 more than a
    # vendor pays. The Flip resells at 950, once the two 700s are bought.
    assert ["2589", "Sell", "3", "8s 00c", "22s 80c", "7s 50c", "1"] in lines
    assert "Shopping List: 12g 34s 56c to spend, 14s 00c in total" in text
    assert ["2589", "Sell", "2", "7s 00c", "5s 00c", "14s 00c", "1"] in lines
