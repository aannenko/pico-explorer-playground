from __future__ import annotations

from dataclasses import dataclass

import machine
import pytest

import displays.events as events
from displays.events import Display, RING_SEGMENTS, TEXT_ABOVE_CENTER, TEXT_BELOW_CENTER, TEXT_CENTER
from scheduling.event import Event


class FakeRenderer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.update_calls = 0

    def reset(self) -> None:
        self.calls.append(("reset", (), {}))

    def ring_clear_segments(self, count: int) -> None:
        self.calls.append(("ring_clear_segments", (count,), {}))

    def ring_clear_next_segment(self) -> None:
        self.calls.append(("ring_clear_next_segment", (), {}))

    def text_write(self, position: int, text: str) -> None:
        self.calls.append(("text_write", (position, text), {}))

    def update(self) -> None:
        self.update_calls += 1


@dataclass
class FakeTimer:
    timer_id: int

    init_calls: list[dict] = None  # type: ignore[assignment]
    deinit_calls: int = 0

    def __post_init__(self) -> None:
        if self.init_calls is None:
            self.init_calls = []

    def init(self, **kwargs) -> None:
        self.init_calls.append(dict(kwargs))

    def deinit(self) -> None:
        self.deinit_calls += 1


def _mk_timer_factory():
    created: list[FakeTimer] = []

    def factory(timer_id: int) -> FakeTimer:
        t = FakeTimer(timer_id)
        created.append(t)
        return t

    return factory, created


class FakeEventService:
    def __init__(
        self,
        current_event: Event | None = None,
        elapsed_sec: int = 0,
        remaining_sec: int = 0,
        total_sec: int = 0,
    ) -> None:
        self.current_event = current_event
        self.elapsed_sec = elapsed_sec
        self.remaining_sec = remaining_sec
        self.total_sec = total_sec

    @property
    def name(self) -> str:
        event = self.current_event
        return event.name if event is not None else ""


def _mk_event(name: str = "test", start: int = 0, duration: int = 100) -> Event:
    return Event(name=name, start_timestamp=start, duration_sec=duration)


def _mk_display(
    event: Event | None = None,
    elapsed: int = 0,
    remaining: int = 0,
    total: int = 0,
):
    service = FakeEventService(
        current_event=event,
        elapsed_sec=elapsed,
        remaining_sec=remaining,
        total_sec=total,
    )
    timer_factory, timers = _mk_timer_factory()
    renderer = FakeRenderer()

    display = Display(
        renderer=renderer,
        event_service=service,
        schedule=lambda fn, arg: fn(arg),
        timer_factory=timer_factory,
    )

    return display, service, renderer, timers


# ── initialize ─────────────────────────────────────────────────────────


def test_initialize_shows_current_event_with_ring_progress() -> None:
    event = _mk_event("Meeting", start=0, duration=200)
    d, service, renderer, timers = _mk_display(
        event=event, elapsed=100, remaining=100, total=200,
    )

    d.initialize()

    assert d._active is True
    assert d._last_event is event
    assert ("reset", (), {}) in renderer.calls
    assert ("text_write", (TEXT_CENTER, "Meeting"), {}) in renderer.calls
    # elapsed=100, total=200 → segments = 100 * 120 // 200 = 60
    assert ("ring_clear_segments", (60,), {}) in renderer.calls
    assert d._segments_cleared == 60
    assert ("text_write", (TEXT_ABOVE_CENTER, "00:01:40"), {}) in renderer.calls
    assert ("text_write", (TEXT_BELOW_CENTER, "-00:01:40"), {}) in renderer.calls
    assert renderer.update_calls >= 1


def test_initialize_with_no_event_shows_no_events() -> None:
    d, service, renderer, timers = _mk_display()

    d.initialize()

    assert d._active is True
    assert ("reset", (), {}) in renderer.calls
    assert ("text_write", (TEXT_CENTER, "No events"), {}) in renderer.calls
    assert renderer.update_calls >= 1


def test_initialize_is_idempotent() -> None:
    event = _mk_event("Meeting", start=0, duration=200)
    d, service, renderer, timers = _mk_display(
        event=event, elapsed=50, remaining=150, total=200,
    )

    d.initialize()
    calls_after_first = len(renderer.calls)
    update_calls_after_first = renderer.update_calls

    d.initialize()
    assert len(renderer.calls) == calls_after_first
    assert renderer.update_calls == update_calls_after_first


def test_initialize_starts_seconds_timer() -> None:
    d, service, renderer, timers = _mk_display()

    d.initialize()

    seconds_timer = timers[0]
    assert seconds_timer.init_calls == [
        {
            "mode": machine.Timer.PERIODIC,
            "period": 1000,
            "callback": d._schedule_update_each_second_ref,
        }
    ]


# ── deinitialize ───────────────────────────────────────────────────────


def test_deinitialize_stops_timer_and_resets_state() -> None:
    event = _mk_event("Meeting", start=0, duration=200)
    d, service, renderer, timers = _mk_display(
        event=event, elapsed=50, remaining=150, total=200,
    )

    d.initialize()
    d.deinitialize()

    assert d._active is False
    assert d._segments_cleared == 0
    assert d._last_event is None

    seconds_timer = timers[0]
    assert seconds_timer.deinit_calls == 1


def test_deinitialize_is_idempotent() -> None:
    d, service, renderer, timers = _mk_display()

    d.initialize()
    d.deinitialize()
    seconds_timer = timers[0]
    deinit_count = seconds_timer.deinit_calls

    d.deinitialize()
    assert seconds_timer.deinit_calls == deinit_count


# ── incremental update ─────────────────────────────────────────────────


def test_incremental_update_advances_ring_segments() -> None:
    event = _mk_event("Meeting", start=0, duration=120)
    d, service, renderer, timers = _mk_display(
        event=event, elapsed=60, remaining=60, total=120,
    )

    d.initialize()
    renderer.calls.clear()
    renderer.update_calls = 0

    # Advance time
    service.elapsed_sec = 90
    service.remaining_sec = 30

    d._incremental_update()

    # expected = 90 * 120 // 120 = 90, was 60 → ring_clear_segments(90)
    assert ("ring_clear_segments", (90,), {}) in renderer.calls
    assert renderer.update_calls == 1


def test_incremental_update_writes_time_texts() -> None:
    event = _mk_event("Meeting", start=0, duration=7200)
    d, service, renderer, timers = _mk_display(
        event=event, elapsed=3661, remaining=3539, total=7200,
    )

    d.initialize()
    renderer.calls.clear()
    renderer.update_calls = 0

    d._incremental_update()

    assert ("text_write", (TEXT_ABOVE_CENTER, "01:01:01"), {}) in renderer.calls
    assert ("text_write", (TEXT_BELOW_CENTER, "-00:58:59"), {}) in renderer.calls
    assert renderer.update_calls == 1


def test_incremental_update_skipped_when_no_event() -> None:
    d, service, renderer, timers = _mk_display()

    d.initialize()
    renderer.calls.clear()
    renderer.update_calls = 0

    d._incremental_update()

    assert renderer.calls == []
    assert renderer.update_calls == 0


# ── update each second ─────────────────────────────────────────────────


def test_event_change_triggers_full_redraw() -> None:
    event_a = _mk_event("Event A", start=0, duration=100)
    event_b = _mk_event("Event B", start=100, duration=200)
    d, service, renderer, timers = _mk_display(
        event=event_a, elapsed=50, remaining=50, total=100,
    )

    d.initialize()
    assert d._last_event is event_a

    # Event changes
    service.current_event = event_b
    service.elapsed_sec = 10
    service.remaining_sec = 190
    service.total_sec = 200
    renderer.calls.clear()
    renderer.update_calls = 0

    d._update_each_second(0)

    assert d._last_event is event_b
    assert ("reset", (), {}) in renderer.calls
    assert ("text_write", (TEXT_CENTER, "Event B"), {}) in renderer.calls
    assert renderer.update_calls >= 1


def test_same_event_triggers_incremental_update() -> None:
    event = _mk_event("Meeting", start=0, duration=120)
    d, service, renderer, timers = _mk_display(
        event=event, elapsed=60, remaining=60, total=120,
    )

    d.initialize()
    renderer.calls.clear()
    renderer.update_calls = 0

    # Same event object, time advanced
    service.elapsed_sec = 90
    service.remaining_sec = 30

    d._update_each_second(0)

    # Should NOT have reset (incremental, not full redraw)
    assert ("reset", (), {}) not in renderer.calls
    assert renderer.update_calls >= 1


def test_update_each_second_ignored_when_inactive() -> None:
    """Stale scheduled callback after deinitialize should be ignored."""
    event = _mk_event("Meeting", start=0, duration=100)
    d, service, renderer, timers = _mk_display(
        event=event, elapsed=50, remaining=50, total=100,
    )

    d.initialize()
    d.deinitialize()
    renderer.calls.clear()
    renderer.update_calls = 0

    d._update_each_second(0)

    assert renderer.calls == []
    assert renderer.update_calls == 0


# ── schedule wrapper ───────────────────────────────────────────────────


def test_schedule_update_each_second_forwards_to_schedule() -> None:
    scheduled: list[tuple[object, int]] = []

    def schedule(fn, arg):
        scheduled.append((fn, arg))

    timer_factory, timers = _mk_timer_factory()
    renderer = FakeRenderer()
    service = FakeEventService()

    d = Display(
        renderer=renderer,
        event_service=service,
        schedule=schedule,
        timer_factory=timer_factory,
    )

    d._schedule_update_each_second(None)  # type: ignore[arg-type]

    assert scheduled == [(d._update_each_second_ref, 0)]


# ── time formatting ───────────────────────────────────────────────────


def test_time_formatting_elapsed_and_remaining() -> None:
    event = _mk_event("Meeting", start=0, duration=10000)
    d, service, renderer, timers = _mk_display(
        event=event, elapsed=3661, remaining=6339, total=10000,
    )

    d.initialize()

    assert ("text_write", (TEXT_ABOVE_CENTER, "01:01:01"), {}) in renderer.calls
    assert ("text_write", (TEXT_BELOW_CENTER, "-01:45:39"), {}) in renderer.calls


def test_time_formatting_zero_elapsed() -> None:
    event = _mk_event("Fresh", start=0, duration=3600)
    d, service, renderer, timers = _mk_display(
        event=event, elapsed=0, remaining=3600, total=3600,
    )

    d.initialize()

    assert ("text_write", (TEXT_ABOVE_CENTER, "00:00:00"), {}) in renderer.calls
    assert ("text_write", (TEXT_BELOW_CENTER, "-01:00:00"), {}) in renderer.calls


@pytest.mark.parametrize(
    "elapsed,remaining,expected_above,expected_below",
    [
        (1, 99, "00:00:01", "00:01:39"),
        (events._MAX_PRINTED_SEC + 1, 0, "1000 h", "00:00:00"),
        (0, events._MAX_PRINTED_SEC + 1, "00:00:00", "1000 h"),
    ],
)
def test_time_formatting_edge_cases(
    elapsed: int,
    remaining: int,
    expected_above: str,
    expected_below: str,
) -> None:
    event = _mk_event("Edge", start=0, duration=elapsed + remaining)
    d, service, renderer, timers = _mk_display(
        event=event, elapsed=elapsed, remaining=remaining, total=elapsed + remaining,
    )

    d.initialize()

    above = [c for c in renderer.calls if c[0] == "text_write" and c[1][0] == TEXT_ABOVE_CENTER]
    assert len(above) == 1
    assert above[0][1][1] == expected_above

    below = [c for c in renderer.calls if c[0] == "text_write" and c[1][0] == TEXT_BELOW_CENTER]
    assert len(below) == 1
    assert below[0][1][1] == f"-{expected_below}"
