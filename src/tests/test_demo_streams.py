"""Tests for the placeholder demo streams.

The substantive guarantee is the per-row ``color_index`` assignment:
the four demo rows are 1..4.
"""

import demo_streams


class _FakeTimeService:
    """Minimal stand-in: demo streams need now() + real_duration()."""

    def now(self) -> int:
        return 1_000_000

    def real_duration(self, local_start: int, wall_clock_sec: int) -> int:
        return wall_clock_sec


def _first_event(stream):
    return next(stream.events_iter)


def test_demo_streams_assign_sequential_color_indices():
    streams = demo_streams.build_demo_streams(_FakeTimeService())

    assert [_first_event(s).color_index for s in streams] == [1, 2, 3, 4]


def test_demo_streams_returns_four_rows():
    streams = demo_streams.build_demo_streams(_FakeTimeService())
    assert len(streams) == 4


def test_random_event_loop_stamps_color_index_on_every_event():
    ts = _FakeTimeService()
    gen = demo_streams._random_event_loop(
        names=("a", "b"),
        durations=(60, 120),
        gap_chance=0,  # no gaps → deterministic yields
        start_timestamp=0,
        time_service=ts,
        color_index=3,
    )

    events = [next(gen) for _ in range(5)]
    assert all(e.color_index == 3 for e in events)
