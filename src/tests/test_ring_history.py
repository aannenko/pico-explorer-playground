from __future__ import annotations

import math

import pytest

from services.ring_history import RingHistory


class _FakeReader:
    """Stub reader returning a configurable 5-tuple (BME690-shaped).

    Tests pass ``reader.read`` (the bound method) as the ``RingHistory``
    sampler — exercising the same pattern ``app.py`` uses with the real
    ``PimoroniBME690``.
    """

    def __init__(self, reading=(20.0, 1010.0, 50.0, 100.0, "Stable")) -> None:
        self._reading = reading

    def read(self):
        return self._reading

    def set(self, reading) -> None:
        self._reading = reading


def _make(
    reader=None,
    *,
    num_metrics: int = 4,
    capacity: int = 8,
    ticks_per_commit: int = 10,
) -> RingHistory:
    return RingHistory(
        (reader or _FakeReader()).read,
        num_metrics=num_metrics,
        capacity=capacity,
        ticks_per_commit=ticks_per_commit,
    )


def test_constructor_does_one_immediate_commit() -> None:
    reader = _FakeReader((22.4, 963.1, 45.6, 75.7, "Stable"))
    h = _make(reader)
    assert h.commit_count == 1
    for metric in range(4):
        assert h.filled(metric) == 1
    assert h.value_at(0, 0) == pytest.approx(22.4)
    assert h.value_at(1, 0) == pytest.approx(963.1)
    assert h.value_at(2, 0) == pytest.approx(45.6)
    assert h.value_at(3, 0) == pytest.approx(75.7)


def test_constructor_rejects_zero_num_metrics() -> None:
    with pytest.raises(ValueError, match="num_metrics must be >= 1"):
        RingHistory(_FakeReader().read, num_metrics=0, capacity=8, ticks_per_commit=10)


def test_constructor_rejects_zero_capacity() -> None:
    with pytest.raises(ValueError, match="capacity must be >= 1"):
        RingHistory(_FakeReader().read, num_metrics=4, capacity=0, ticks_per_commit=10)


def test_constructor_rejects_zero_ticks_per_commit() -> None:
    with pytest.raises(ValueError, match="ticks_per_commit must be >= 1"):
        RingHistory(_FakeReader().read, num_metrics=4, capacity=8, ticks_per_commit=0)


def test_tick_counter_commits_every_ticks_per_commit() -> None:
    reader = _FakeReader((10.0, 1000.0, 30.0, 50.0, "Stable"))
    h = _make(reader, capacity=8, ticks_per_commit=5)
    assert h.commit_count == 1  # construct-time commit

    for _ in range(4):
        h._tick_ref()
    assert h.commit_count == 1
    assert h.filled(0) == 1

    reader.set((11.0, 1001.0, 31.0, 51.0, "Stable"))
    h._tick_ref()
    assert h.commit_count == 2
    assert h.filled(0) == 2
    assert h.value_at(0, 0) == pytest.approx(11.0)
    assert h.value_at(0, 1) == pytest.approx(10.0)


def test_tick_counter_resets_after_commit() -> None:
    reader = _FakeReader()
    h = _make(reader, capacity=8, ticks_per_commit=3)
    for _ in range(3):
        h._tick_ref()
    assert h.commit_count == 2
    for _ in range(3):
        h._tick_ref()
    assert h.commit_count == 3


def test_filled_clamps_at_capacity() -> None:
    reader = _FakeReader()
    h = _make(reader, capacity=4, ticks_per_commit=1)
    # 1 construct-time commit + 10 ticks → 11 commits, but filled clamps at 4.
    for i in range(10):
        reader.set((float(i), 0.0, 0.0, 0.0, "Stable"))
        h._tick_ref()
    assert h.commit_count == 11
    assert h.filled(0) == 4


def test_value_at_returns_newest_first() -> None:
    reader = _FakeReader((1.0, 0.0, 0.0, 0.0, "Stable"))
    h = _make(reader, capacity=4, ticks_per_commit=1)
    for v in (2.0, 3.0, 4.0):
        reader.set((v, 0.0, 0.0, 0.0, "Stable"))
        h._tick_ref()
    assert h.value_at(0, 0) == pytest.approx(4.0)
    assert h.value_at(0, 1) == pytest.approx(3.0)
    assert h.value_at(0, 2) == pytest.approx(2.0)
    assert h.value_at(0, 3) == pytest.approx(1.0)


def test_value_at_after_ring_wrap_preserves_order() -> None:
    """The oldest filled slot is the (capacity-1)-th most-recent value, not
    a leaked stale entry from before the wrap."""
    reader = _FakeReader((1.0, 0.0, 0.0, 0.0, "Stable"))
    h = _make(reader, capacity=4, ticks_per_commit=1)
    # 8 more samples wraps the 4-slot ring twice.
    for v in (2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0):
        reader.set((v, 0.0, 0.0, 0.0, "Stable"))
        h._tick_ref()
    assert h.commit_count == 9
    assert h.filled(0) == 4
    # 9, 8, 7, 6 — all later than the original 1.0.
    assert [h.value_at(0, i) for i in range(4)] == [
        pytest.approx(9.0),
        pytest.approx(8.0),
        pytest.approx(7.0),
        pytest.approx(6.0),
    ]


def test_partial_fill_only_advertises_committed_samples() -> None:
    reader = _FakeReader()
    h = _make(reader, capacity=10, ticks_per_commit=1)
    # 1 commit from construct + 2 from ticks = 3 filled.
    for _ in range(2):
        h._tick_ref()
    assert h.filled(0) == 3


def test_capacity_property() -> None:
    h = _make(capacity=42, ticks_per_commit=1)
    assert h.capacity == 42


def test_tick_ref_is_cached_bound_method() -> None:
    """The cached ``_tick_ref`` must be the SAME object across reads — required
    for MicroPython identity-based dedup in ``TickScheduler.register``."""
    h = _make(ticks_per_commit=1)
    ref_a = h._tick_ref
    ref_b = h._tick_ref
    assert ref_a is ref_b
    before = h.commit_count
    ref_a()
    assert h.commit_count == before + 1


def test_tick_is_zero_arg() -> None:
    """TickScheduler invokes subscribers as ``callback()`` — _tick must
    accept no positional args."""
    h = _make()
    h._tick()


def test_each_metric_stored_in_own_buffer() -> None:
    """Per-metric buffers are isolated — no cross-contamination across commits."""
    reader = _FakeReader((10.0, 100.0, 50.0, 200.0, "Stable"))
    h = _make(reader, capacity=2, ticks_per_commit=1)
    reader.set((11.0, 101.0, 51.0, 201.0, "Stable"))
    h._tick_ref()
    assert h.value_at(0, 0) == pytest.approx(11.0)
    assert h.value_at(0, 1) == pytest.approx(10.0)
    assert h.value_at(1, 0) == pytest.approx(101.0)
    assert h.value_at(1, 1) == pytest.approx(100.0)
    assert h.value_at(2, 0) == pytest.approx(51.0)
    assert h.value_at(2, 1) == pytest.approx(50.0)
    assert h.value_at(3, 0) == pytest.approx(201.0)
    assert h.value_at(3, 1) == pytest.approx(200.0)


def test_nan_value_is_stored_and_retrievable() -> None:
    """NaN flows through the buffer untouched (display layer is responsible
    for skipping NaN columns)."""
    reader = _FakeReader((float("nan"), 1000.0, 50.0, 100.0, "Stable"))
    h = _make(reader, capacity=2, ticks_per_commit=1)
    v = h.value_at(0, 0)
    assert math.isnan(v)


def test_constructor_does_not_register_on_tick_scheduler() -> None:
    """RingHistory must NOT self-register; app.py is the single registration
    site.  Proof: the constructor takes no scheduler-shaped arg, so it can't."""
    import inspect

    sig = inspect.signature(RingHistory.__init__)
    assert "tick_scheduler" not in sig.parameters
    assert "scheduler" not in sig.parameters


def test_sampler_can_be_a_plain_callable_returning_a_tuple() -> None:
    """Sampler contract is just ``() -> sequence[float]`` — any callable
    whose result is indexable by 0..num_metrics-1 works."""
    counter = {"n": 0}

    def sampler():
        counter["n"] += 1
        return (counter["n"] * 1.0, counter["n"] * 10.0)

    h = RingHistory(sampler, num_metrics=2, capacity=4, ticks_per_commit=1)
    assert h.value_at(0, 0) == pytest.approx(1.0)
    assert h.value_at(1, 0) == pytest.approx(10.0)
    h._tick_ref()
    assert h.value_at(0, 0) == pytest.approx(2.0)
    assert h.value_at(1, 0) == pytest.approx(20.0)


def test_num_metrics_smaller_than_reading_length_ignores_extras() -> None:
    """Only the leading ``num_metrics`` entries are captured — extras
    (e.g. BME690's trailing status string) are silently ignored."""
    reader = _FakeReader((1.0, 2.0, 3.0, 4.0, "Stable"))
    h = RingHistory(reader.read, num_metrics=3, capacity=2, ticks_per_commit=1)
    assert h.value_at(0, 0) == pytest.approx(1.0)
    assert h.value_at(1, 0) == pytest.approx(2.0)
    assert h.value_at(2, 0) == pytest.approx(3.0)


def test_num_metrics_one_works() -> None:
    """Degenerate case: a single-metric history is valid."""
    counter = {"n": 0}

    def sampler():
        counter["n"] += 1
        return (counter["n"] * 1.0,)

    h = RingHistory(sampler, num_metrics=1, capacity=3, ticks_per_commit=1)
    h._tick_ref()
    h._tick_ref()
    assert h.commit_count == 3
    assert [h.value_at(0, i) for i in range(3)] == [
        pytest.approx(3.0),
        pytest.approx(2.0),
        pytest.approx(1.0),
    ]
