from brain.watch import Watcher

SETTLE = 2.0


def test_reports_a_file_once_it_has_been_stable_for_the_settle_time(tmp_path):
    file = tmp_path / "AzerothQuant.lua"
    file.write_text("AzerothQuantDB = {}")
    watcher = Watcher(settle_seconds=SETTLE)

    assert watcher.poll([file], now=0.0) == []
    assert watcher.poll([file], now=1.9) == []
    assert watcher.poll([file], now=2.0) == [file]


def test_does_not_report_an_unchanged_file_again(tmp_path):
    file = tmp_path / "AzerothQuant.lua"
    file.write_text("AzerothQuantDB = {}")
    watcher = Watcher(settle_seconds=SETTLE)
    watcher.poll([file], now=0.0)
    watcher.poll([file], now=2.0)

    assert watcher.poll([file], now=60.0) == []


def test_waits_for_a_file_that_changes_mid_write_to_settle(tmp_path):
    # The client can write the file in several steps; reading between them would see
    # half a file.
    file = tmp_path / "AzerothQuant.lua"
    file.write_text("AzerothQuantDB = {")
    watcher = Watcher(settle_seconds=SETTLE)
    watcher.poll([file], now=0.0)

    file.write_text('AzerothQuantDB = {["scans"] = {')
    assert watcher.poll([file], now=1.5) == []
    assert watcher.poll([file], now=2.5) == []  # 1s since the last write, not 2

    file.write_text('AzerothQuantDB = {["scans"] = {}}')
    assert watcher.poll([file], now=3.0) == []
    assert watcher.poll([file], now=5.0) == [file]


def test_reports_a_file_again_after_it_is_rewritten(tmp_path):
    file = tmp_path / "AzerothQuant.lua"
    file.write_text("AzerothQuantDB = {}")
    watcher = Watcher(settle_seconds=SETTLE)
    watcher.poll([file], now=0.0)
    watcher.poll([file], now=2.0)

    file.write_text('AzerothQuantDB = {["scans"] = {}}')
    assert watcher.poll([file], now=10.0) == []
    assert watcher.poll([file], now=12.0) == [file]


def test_a_file_that_changed_while_being_read_is_reported_again(tmp_path):
    # poll() reports the file as it was when stat'ed, so a write landing during the
    # import that follows still counts as a new change.
    file = tmp_path / "AzerothQuant.lua"
    file.write_text("AzerothQuantDB = {")
    watcher = Watcher(settle_seconds=SETTLE)
    watcher.poll([file], now=0.0)
    assert watcher.poll([file], now=2.0) == [file]

    file.write_text('AzerothQuantDB = {["scans"] = {}}')  # finishes during the import

    assert watcher.poll([file], now=2.5) == []
    assert watcher.poll([file], now=4.5) == [file]


def test_ignores_a_missing_file_until_it_appears(tmp_path):
    file = tmp_path / "AzerothQuant.lua"
    watcher = Watcher(settle_seconds=SETTLE)

    assert watcher.poll([file], now=0.0) == []
    assert watcher.poll([file], now=5.0) == []

    file.write_text("AzerothQuantDB = {}")
    assert watcher.poll([file], now=6.0) == []
    assert watcher.poll([file], now=8.0) == [file]


def test_tracks_each_file_separately(tmp_path):
    beta = tmp_path / "beta.lua"
    live = tmp_path / "live.lua"
    beta.write_text("AzerothQuantDB = {}")
    watcher = Watcher(settle_seconds=SETTLE)
    watcher.poll([beta, live], now=0.0)

    live.write_text("AzerothQuantDB = {}")
    assert watcher.poll([beta, live], now=1.0) == []
    assert watcher.poll([beta, live], now=2.0) == [beta]
    assert watcher.poll([beta, live], now=3.0) == [live]


def test_a_file_whose_import_failed_is_reported_again_after_settling(tmp_path):
    # Say the client still had the file open: nothing about the file changes, but the
    # import should be tried again rather than wait for the next /reload.
    file = tmp_path / "AzerothQuant.lua"
    file.write_text("AzerothQuantDB = {}")
    watcher = Watcher(settle_seconds=SETTLE)
    watcher.poll([file], now=0.0)
    assert watcher.poll([file], now=2.0) == [file]

    watcher.retry(file, now=2.0)

    assert watcher.poll([file], now=3.0) == []
    assert watcher.poll([file], now=4.0) == [file]
