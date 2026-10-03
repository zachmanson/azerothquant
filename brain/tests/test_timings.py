import pytest

from brain.timings import Timings


def clock_at(*readings: float):
    return iter(readings).__next__


def test_a_stage_is_the_time_its_block_took():
    timings = Timings(clock_at(10.0, 12.5))

    with timings.stage("Archive"):
        pass

    assert timings.seconds == {"Archive": 2.5}


def test_a_stage_timed_again_adds_to_its_time():
    timings = Timings(clock_at(0.0, 1.0, 5.0, 7.0))

    with timings.stage("Archive"):
        pass
    with timings.stage("Archive"):
        pass

    assert timings.seconds == {"Archive": 3.0}


def test_a_stage_inside_another_counts_only_toward_itself():
    # ingest runs 0 to 10, with an Archive write 2 to 5 inside it: 7s of ingest, 3s of
    # Archive, adding up to the 10s they cover.
    timings = Timings(clock_at(0.0, 2.0, 5.0, 10.0))

    with timings.stage("history ingest"):
        with timings.stage("Archive"):
            pass

    assert timings.seconds == {"history ingest": 7.0, "Archive": 3.0}


def test_a_stage_that_raises_is_still_timed():
    timings = Timings(clock_at(0.0, 4.0))

    with pytest.raises(OSError), timings.stage("Archive"):
        raise OSError("disk full")

    assert timings.seconds == {"Archive": 4.0}
