import os
import subprocess
import sys

from brain.instance_lock import LOCK_FILE, instance_lock


def test_a_second_brain_is_refused_while_the_first_holds_the_lock(tmp_path):
    with instance_lock(tmp_path) as first:
        with instance_lock(tmp_path) as second:
            assert first is True
            assert second is False


def test_the_lock_file_holds_the_running_brains_pid(tmp_path):
    with instance_lock(tmp_path):
        assert (tmp_path / LOCK_FILE).read_text(encoding="ascii").strip() == str(os.getpid())


def test_the_lock_frees_up_when_the_brain_stops(tmp_path):
    with instance_lock(tmp_path):
        pass

    with instance_lock(tmp_path) as again:
        assert again is True


def test_a_lock_file_left_by_a_crashed_brain_does_not_block(tmp_path):
    (tmp_path / LOCK_FILE).write_text("99999", encoding="ascii")

    with instance_lock(tmp_path) as held:
        assert held is True


HOLD_THE_LOCK = """
import sys, time
from pathlib import Path
from brain.instance_lock import instance_lock
with instance_lock(Path(sys.argv[1])) as held:
    print(held, flush=True)
    time.sleep(60)
"""


def test_another_running_brain_holds_the_lock_until_it_is_killed(tmp_path):
    with subprocess.Popen(
        [sys.executable, "-c", HOLD_THE_LOCK, str(tmp_path)], stdout=subprocess.PIPE, text=True
    ) as other:
        try:
            assert other.stdout.readline().strip() == "True"
            # Read with a big buffer, the way cat or an updater might.
            with open(tmp_path / LOCK_FILE, "rb") as f:
                assert f.read(1 << 20) == str(other.pid).encode("ascii")
            with instance_lock(tmp_path) as held:
                assert held is False
        finally:
            other.kill()

    with instance_lock(tmp_path) as held:
        assert held is True
