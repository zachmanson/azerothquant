import gzip
import json

from brain.archive import Archive
from brain.config import Era

T0 = 1_790_000_000


def raw_scan(at=T0, realm="Classic Beta PvP", faction="Alliance", **extra):
    return {
        "id": 1,
        "requestedAt": at,
        "realm": realm,
        "character": "Kash-Patel",
        "faction": faction,
        "droppedRows": 0,
        "listings": [
            {
                "itemString": "item:2589::::::::20:1490",
                "quantity": 20,
                "buyout": 1940,
                "timeLeft": 4,
            },
            {"itemString": "not an item", "quantity": 1, "buyout": 5, "timeLeft": 9, "own": True},
        ],
        **extra,
    }


def test_writes_one_gzipped_json_file_per_scan_under_its_era_and_market(tmp_path):
    raw = raw_scan()

    path = Archive(tmp_path).write(Era.BETA, raw)

    assert path == tmp_path / "beta" / "Classic Beta PvP-Alliance" / f"{T0}.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as f:
        assert json.load(f) == {"era": "beta", "scan": raw}


def test_keeps_the_scan_verbatim_including_rows_and_fields_the_brain_cant_read(tmp_path):
    raw = raw_scan(someFutureField={"nested": [1, 2, 3]})
    archive = Archive(tmp_path)

    archive.write(Era.BETA, raw)

    assert list(archive.scans()) == [(Era.BETA, raw)]


def test_never_overwrites_a_scan_already_archived(tmp_path):
    archive = Archive(tmp_path)
    first = archive.write(Era.BETA, raw_scan(character="First"))

    second = archive.write(Era.BETA, raw_scan(character="Second"))

    assert second == first
    assert list(archive.scans()) == [(Era.BETA, raw_scan(character="First"))]


def test_leaves_no_partial_file_behind(tmp_path):
    Archive(tmp_path).write(Era.BETA, raw_scan())

    names = [p.name for p in tmp_path.rglob("*") if p.is_file()]
    assert names == [f"{T0}.json.gz"]


def test_markets_whose_names_windows_cant_use_still_get_a_folder(tmp_path):
    path = Archive(tmp_path).write(Era.LIVE, raw_scan(realm='Odd:Realm/"Name"?'))

    assert path.parent.name == "Odd_Realm__Name__-Alliance"


def test_reads_back_every_scan_in_every_era_and_market(tmp_path):
    archive = Archive(tmp_path)
    a = raw_scan(at=T0)
    b = raw_scan(at=T0 + 900, faction="Horde")
    c = raw_scan(at=T0 + 60)
    for era, raw in [(Era.BETA, a), (Era.BETA, b), (Era.LIVE, c)]:
        archive.write(era, raw)

    found = list(archive.scans())

    assert sorted(found, key=lambda s: s[1]["requestedAt"]) == [
        (Era.BETA, a),
        (Era.LIVE, c),
        (Era.BETA, b),
    ]


def test_an_empty_or_missing_archive_has_no_scans(tmp_path):
    assert list(Archive(tmp_path / "nowhere").scans()) == []
