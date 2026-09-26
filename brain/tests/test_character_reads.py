import dataclasses
from pathlib import Path

import pytest

from brain.archive import Archive
from brain.config import Config, Era, Install
from brain.history import Holding, holdings, import_character_reads, open_history, pooled_gold

T0 = 1_790_000_000
REALM = "Classic Beta PvP"
LINEN = "|cffffffff|Hitem:2589::::::::20:1490:::::::::|h[Linen Cloth]|h|r"
# A random-suffix item: its Item Key includes the bonus ID.
MONKEY = (
    "|cff1eff00|Hitem:9768::::::::20:1490::1:1:12743::::::|h[Scouting Trousers of the Monkey]|h|r"
)
HEARTHSTONE = "|cffffffff|Hitem:6948::::::::20:1490:::::::::|h[Hearthstone]|h|r"
CONFIG = Config(installs=(Install(path=Path("C:/WoW/_classic_beta_"), era=Era.BETA),))


def item(link=LINEN, count=1, bound=False, bag=0, slot=1):
    return {"bag": bag, "slot": slot, "link": link, "count": count, "isBound": bound}


def character_read(
    at=T0, character="Kash-Patel", realm=REALM, faction="Alliance", money=0, bags=(), bank=None
):
    read = {
        "readAt": at,
        "realm": realm,
        "character": character,
        "faction": faction,
        "money": money,
        "bags": list(bags),
    }
    if bank is not None:
        bank_at, items = bank
        read |= {"bankReadAt": bank_at, "bank": list(items)}
    return read


@pytest.fixture
def db():
    conn = open_history(":memory:")
    yield conn
    conn.close()


def archived_config(tmp_path):
    return dataclasses.replace(CONFIG, archive_dir=tmp_path / "archive")


# --- Archive then import ---


def test_every_character_read_is_archived_verbatim_and_imported(db, tmp_path):
    config = archived_config(tmp_path)
    first = character_read(T0, money=100, bags=[item(), {"bag": 0, "slot": 2, "odd": True}])
    second = character_read(T0 + 60, money=200, bank=(T0 + 30, [item(count=5)]))

    report = import_character_reads(db, [second, first], Era.BETA, config)

    assert report.character_reads_imported == 2
    archived = sorted(Archive(config.archive_dir).character_reads(), key=lambda r: r[1]["readAt"])
    assert archived == [(Era.BETA, first), (Era.BETA, second)]


def test_reimporting_the_same_character_read_changes_nothing(db, tmp_path):
    config = archived_config(tmp_path)
    import_character_reads(db, [character_read()], Era.BETA, config)

    report = import_character_reads(db, [character_read()], Era.BETA, config)

    assert report.character_reads_imported == 0
    assert report.character_reads_already_imported == 1
    assert len(list(Archive(config.archive_dir).character_reads())) == 1


def test_a_character_read_that_cant_be_named_is_skipped_and_not_archived(db, tmp_path):
    # Without realm, character and readAt it has no identity or file name, so it stays in
    # SavedVariables where it can at least be looked at.
    config = archived_config(tmp_path)
    no_time = character_read()
    del no_time["readAt"]

    report = import_character_reads(
        db,
        [no_time, character_read(character=None), character_read(at=True), "junk"],
        Era.BETA,
        config,
    )

    assert report.character_reads_unreadable == 4
    assert len(report.warnings) == 4
    assert list(Archive(config.archive_dir).character_reads()) == []


def run(db, *reads, era=Era.BETA):
    return import_character_reads(db, list(reads), era, CONFIG)


# --- Pooled gold ---


def test_gold_is_each_characters_latest_read_summed_over_one_realm_and_faction(db):
    run(
        db,
        character_read(T0, "Kash-Patel", money=100),
        character_read(T0 + 60, "Kash-Patel", money=250),  # latest wins, whatever the order
        character_read(T0 + 30, "Kash-Patel", money=999),
        character_read(T0, "Alt-Patel", money=40),
        character_read(T0, "Horde-Patel", faction="Horde", money=7000),
        character_read(T0, "Kash-Patel", realm="Quel'Thalas", money=8000),
    )
    run(db, character_read(T0, "Kash-Patel", money=5), era=Era.LIVE)

    assert pooled_gold(db, Era.BETA, REALM, "Alliance") == 290
    assert pooled_gold(db, Era.BETA, REALM, "Horde") == 7000
    assert pooled_gold(db, Era.BETA, "Quel'Thalas", "Alliance") == 8000
    assert pooled_gold(db, Era.LIVE, REALM, "Alliance") == 5
    assert pooled_gold(db, Era.LIVE, REALM, "Horde") == 0


def test_a_character_counts_toward_the_faction_of_its_latest_read(db):
    # After a faction change, the old faction's pool no longer has this Character's gold.
    run(
        db,
        character_read(T0, "Kash-Patel", faction="Alliance", money=100),
        character_read(T0 + 60, "Kash-Patel", faction="Horde", money=300),
    )

    assert pooled_gold(db, Era.BETA, REALM, "Alliance") == 0
    assert pooled_gold(db, Era.BETA, REALM, "Horde") == 300


# --- Holdings ---


def test_holdings_are_the_latest_reads_bags_by_item_key_split_by_bound(db):
    run(
        db,
        character_read(T0, bags=[item(LINEN, count=99)]),
        character_read(
            T0 + 60,
            bags=[
                item(LINEN, count=20, slot=1),
                item(LINEN, count=7, slot=2),
                item(MONKEY, count=1, slot=3),
                item(HEARTHSTONE, count=1, bound=True, slot=4),
            ],
        ),
    )

    assert holdings(db, Era.BETA, REALM, "Kash-Patel") == {
        "2589": Holding(bags=27),
        "9768:12743": Holding(bags=1),
        "6948": Holding(bags_bound=1),
    }


def test_a_character_with_no_reads_holds_nothing(db):
    run(db, character_read(character="Alt-Patel", bags=[item()]))

    assert holdings(db, Era.BETA, REALM, "Kash-Patel") == {}
    assert holdings(db, Era.LIVE, REALM, "Alt-Patel") == {}


def test_an_item_the_brain_cant_read_is_counted_and_the_rest_held(db):
    # Say a battle pet cage or a keystone: not an item: link. It stays in the Archive.
    pet = "|cff0070dd|Hbattlepet:39:1:3:152:13:10:0x0|h[Mechanical Squirrel]|h|r"
    report = run(
        db,
        character_read(bags=[item(pet), {"bag": 0, "slot": 2}, item(LINEN, count=3, slot=3)]),
    )

    assert report.character_reads_imported == 1
    assert report.character_items_unreadable == 2
    assert len(report.warnings) == 2
    assert holdings(db, Era.BETA, REALM, "Kash-Patel") == {"2589": Holding(bags=3)}


def test_the_bank_comes_from_the_latest_read_that_has_one(db):
    run(
        db,
        character_read(T0, bank=(T0 - 30, [item(LINEN, count=500, bag=-1)])),
        character_read(
            T0 + 60,
            bags=[item(LINEN, count=2)],
            bank=(T0 + 50, [item(LINEN, count=40, bag=-1), item(HEARTHSTONE, bound=True, bag=5)]),
        ),
        # Bank not opened in the latest session: its bank is left out, not empty.
        character_read(T0 + 120, bags=[item(LINEN, count=5)]),
    )

    assert holdings(db, Era.BETA, REALM, "Kash-Patel") == {
        "2589": Holding(bags=5, bank=40),
        "6948": Holding(bank_bound=1),
    }


def test_a_bank_read_empty_is_empty(db):
    run(
        db,
        character_read(T0, bank=(T0, [item(LINEN, count=40, bag=-1)])),
        character_read(T0 + 60, bank=(T0 + 50, [])),
    )

    assert holdings(db, Era.BETA, REALM, "Kash-Patel") == {}


def test_a_read_with_unreadable_gold_or_faction_adds_nothing_to_the_pool(db):
    report = run(
        db,
        character_read(T0, "Kash-Patel", money=100),
        character_read(T0 + 60, "Kash-Patel", money="lots", bags=[item()]),
        character_read(T0, "Alt-Patel", faction=None, money=40),
    )

    assert report.character_reads_imported == 3
    assert len(report.warnings) == 2
    assert pooled_gold(db, Era.BETA, REALM, "Alliance") == 0
    # Its bags are still the Character's Holdings.
    assert holdings(db, Era.BETA, REALM, "Kash-Patel") == {"2589": Holding(bags=1)}
