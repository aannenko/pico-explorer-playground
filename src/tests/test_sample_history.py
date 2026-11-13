from __future__ import annotations

import inspect

import pytest

from services.sample_history import MISSING, SampleHistory


class _FakeReader:
    def __init__(self, reading=(200, 10100, 500, 1000, "Stable")) -> None:
        self._reading = reading

    def read(self):
        return self._reading

    def set(self, reading) -> None:
        self._reading = reading


def _make(
    reader=None,
    *,
    metric_count: int = 4,
    capacity: int = 8,
    ticks_per_commit: int = 10,
) -> SampleHistory:
    return SampleHistory(
        (reader or _FakeReader()).read,
        metric_count=metric_count,
        capacity=capacity,
        ticks_per_commit=ticks_per_commit,
    )


def test_constructor_does_one_immediate_commit() -> None:
    h = _make(_FakeReader((224, 9631, 456, 757, "Stable")))
    assert h.commit_count == 1
    assert [metric[-1] for metric in h.samples] == [224, 9631, 456, 757]


def test_slots_no_commit_has_reached_hold_missing() -> None:
    h = _make(capacity=4)
    assert all(list(metric[:-1]) == [MISSING] * 3 for metric in h.samples)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"metric_count": 0}, "metric_count must be >= 1"),
        ({"capacity": 0}, "capacity must be >= 1"),
        ({"ticks_per_commit": 0}, "ticks_per_commit must be >= 1"),
    ],
)
def test_constructor_rejects_a_zero_size(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        _make(**kwargs)


def test_commits_every_ticks_per_commit_ticks() -> None:
    reader = _FakeReader((100, 10000, 300, 500, "Stable"))
    h = _make(reader, ticks_per_commit=5)
    for _ in range(4):
        h.tick()
    assert h.commit_count == 1

    reader.set((110, 10010, 310, 510, "Stable"))
    h.tick()
    assert h.commit_count == 2
    assert list(h.samples[0][-2:]) == [100, 110]

    for _ in range(5):
        h.tick()
    assert h.commit_count == 3


def test_a_full_history_drops_its_oldest_sample() -> None:
    reader = _FakeReader((1, 0, 0, 0, "Stable"))
    h = _make(reader, capacity=4, ticks_per_commit=1)
    for v in (2, 3, 4, 5, 6):
        reader.set((v, 0, 0, 0, "Stable"))
        h.tick()
    assert h.commit_count == 6
    assert list(h.samples[0]) == [3, 4, 5, 6]


def test_each_metric_keeps_its_own_samples() -> None:
    reader = _FakeReader((10, 100, 50, 200, "Stable"))
    h = _make(reader, capacity=2, ticks_per_commit=1)
    reader.set((11, 101, 51, 201, "Stable"))
    h.tick()
    assert [list(metric) for metric in h.samples] == [[10, 11], [100, 101], [50, 51], [200, 201]]


def test_the_extreme_samples_keep_their_values() -> None:
    reader = _FakeReader((MISSING, -MISSING - 1, 0, 0, "Stable"))
    h = _make(reader, capacity=2, ticks_per_commit=1)
    assert [h.samples[0][-1], h.samples[1][-1]] == [MISSING, -MISSING - 1]


def test_commits_shift_the_same_arrays_so_references_stay_valid() -> None:
    reader = _FakeReader((1, 2, 3, MISSING, "Unstable"))
    h = _make(reader, ticks_per_commit=1)
    gas = h.samples[3]

    gas[-1] = 99
    reader.set((1, 2, 3, 120, "Stable"))
    h.tick()

    assert h.samples[3] is gas
    assert list(gas[-2:]) == [99, 120]


def test_constructor_does_not_register_on_tick_scheduler() -> None:
    """``app.py`` registers every service on the scheduler."""
    parameters = inspect.signature(SampleHistory.__init__).parameters
    assert "tick_scheduler" not in parameters
    assert "scheduler" not in parameters


def test_sampler_can_be_a_plain_callable() -> None:
    counter = {"n": 0}

    def sampler():
        counter["n"] += 1
        return (counter["n"], counter["n"] * 10)

    h = SampleHistory(sampler, metric_count=2, capacity=4, ticks_per_commit=1)
    h.tick()
    assert [list(metric[-2:]) for metric in h.samples] == [[1, 2], [10, 20]]


def test_entries_beyond_metric_count_are_ignored() -> None:
    h = SampleHistory(_FakeReader((1, 2, 3, 4, "Stable")).read, metric_count=3, capacity=2, ticks_per_commit=1)
    assert len(h.samples) == 3
    assert [metric[-1] for metric in h.samples] == [1, 2, 3]


def test_a_single_slot_history_keeps_the_newest_sample() -> None:
    reader = _FakeReader((1, 0, 0, 0, "Stable"))
    h = _make(reader, metric_count=1, capacity=1, ticks_per_commit=1)
    reader.set((2, 0, 0, 0, "Stable"))
    h.tick()
    assert list(h.samples[0]) == [2]
