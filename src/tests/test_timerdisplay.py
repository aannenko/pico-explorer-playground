from __future__ import annotations

from dataclasses import dataclass

import machine
import pytest

from displays.timerdisplay import TimerDisplay
from graphics.timergraphics import TimerGraphics
from scheduling.event import Event


class FakeDisplay:
    def __init__(self) -> None:
        self.update_calls = 0

    def update(self) -> None:
        self.update_calls += 1


class FakeGraphics:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def reset(self) -> None:
        self.calls.append(("reset", (), {}))

    def ring_clear_segments(self, count: int) -> None:
        self.calls.append(("ring_clear_segments", (count,), {}))

    def ring_clear_next_segment(self) -> None:
        self.calls.append(("ring_clear_next_segment", (), {}))

    def text_write(self, position: int, text: str) -> None:
        self.calls.append(("text_write", (position, text), {}))


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


def test_initialize_starts_clock_timer_and_is_idempotent() -> None:
    timer_factory, timers = _mk_timer_factory()
    display = FakeDisplay()
    graphics = FakeGraphics()

    td = TimerDisplay(
        display=display,
        graphics=graphics,
        timezone_offset_hours=0,
        get_time=lambda: 0,
        gmtime=lambda _now: (0, 0, 0, 0, 0, 0, 0, 0),
        schedule=lambda fn, arg: fn(arg),
        timer_factory=timer_factory,
    )

    td.initialize(iter(()))

    assert len(timers) == 3
    clock_timer = timers[0]
    assert clock_timer.init_calls == [
        {
            "mode": machine.Timer.PERIODIC,
            "period": 1000,
            "callback": td._schedule_update_clock_ref,
        }
    ]

    # Second initialize should do nothing
    td.initialize(iter(()))
    assert clock_timer.init_calls == [
        {
            "mode": machine.Timer.PERIODIC,
            "period": 1000,
            "callback": td._schedule_update_clock_ref,
        }
    ]


def test_deinitialize_deinits_all_timers_and_resets_state() -> None:
    timer_factory, timers = _mk_timer_factory()
    display = FakeDisplay()
    graphics = FakeGraphics()

    td = TimerDisplay(
        display=display,
        graphics=graphics,
        timezone_offset_hours=0,
        get_time=lambda: 0,
        gmtime=lambda _now: (0, 0, 0, 0, 0, 0, 0, 0),
        schedule=lambda fn, arg: fn(arg),
        timer_factory=timer_factory,
    )

    td.initialize(iter(()))
    # initialize() triggers _chain_event(), which deinit()s ring/event timers to
    # stop any previous periodic updates.
    td.deinitialize()

    assert td._active is False
    assert td._event_end_timestamp == 0

    assert [t.deinit_calls for t in timers] == [1, 2, 2]

    # Idempotent
    td.deinitialize()
    assert [t.deinit_calls for t in timers] == [1, 2, 2]


def test_update_ring_advances_ring_and_updates_display() -> None:
    timer_factory, _timers = _mk_timer_factory()
    display = FakeDisplay()
    graphics = FakeGraphics()

    td = TimerDisplay(
        display=display,
        graphics=graphics,
        timezone_offset_hours=0,
        get_time=lambda: 0,
        gmtime=lambda _now: (0, 0, 0, 0, 0, 0, 0, 0),
        schedule=lambda fn, arg: fn(arg),
        timer_factory=timer_factory,
    )

    td._update_ring(0)

    assert ("ring_clear_next_segment", (), {}) in graphics.calls
    assert display.update_calls == 1


def test_update_clock_formats_local_time_and_remaining_time() -> None:
    timer_factory, _timers = _mk_timer_factory()
    display = FakeDisplay()
    graphics = FakeGraphics()

    now = 1000

    td = TimerDisplay(
        display=display,
        graphics=graphics,
        timezone_offset_hours=1,
        get_time=lambda: now,
        gmtime=lambda _now: (0, 0, 0, 1, 2, 3, 0, 0),
        schedule=lambda fn, arg: fn(arg),
        timer_factory=timer_factory,
    )

    td._event_end_timestamp = now + 3661
    td._update_clock(0)

    assert ("text_write", (TimerGraphics.TEXT_ABOVE_CENTER, "02:02:03"), {}) in graphics.calls
    assert ("text_write", (TimerGraphics.TEXT_BELOW_CENTER, "-01:01:01"), {}) in graphics.calls
    assert display.update_calls == 1


def test_schedule_wrappers_forward_to_schedule() -> None:
    timer_factory, _timers = _mk_timer_factory()
    display = FakeDisplay()
    graphics = FakeGraphics()
    scheduled: list[tuple[object, int]] = []

    def schedule(fn, arg):
        scheduled.append((fn, arg))

    td = TimerDisplay(
        display=display,
        graphics=graphics,
        timezone_offset_hours=0,
        get_time=lambda: 0,
        gmtime=lambda _now: (0, 0, 0, 0, 0, 0, 0, 0),
        schedule=schedule,
        timer_factory=timer_factory,
    )

    td._schedule_update_ring(None)  # type: ignore[arg-type]
    td._schedule_update_clock(None)  # type: ignore[arg-type]
    td._schedule_chain_event(None)  # type: ignore[arg-type]

    assert scheduled == [
        (td._update_ring_ref, 0),
        (td._update_clock_ref, 0),
        (td._chain_event_ref, 0),
    ]


def test_chain_event_future_event_schedules_check_only() -> None:
    timer_factory, timers = _mk_timer_factory()
    display = FakeDisplay()
    graphics = FakeGraphics()

    now = 1000
    td = TimerDisplay(
        display=display,
        graphics=graphics,
        timezone_offset_hours=0,
        get_time=lambda: now,
        gmtime=lambda _now: (0, 0, 0, 0, 0, 0, 0, 0),
        schedule=lambda fn, arg: fn(arg),
        timer_factory=timer_factory,
    )

    td._events = iter([Event("future", 1100, 10)])
    td._chain_event(0)

    clock_timer, ring_timer, event_timer = timers

    assert ring_timer.init_calls == []
    assert event_timer.init_calls == [
        {
            "mode": machine.Timer.ONE_SHOT,
            "period": (1100 - now) * 1000,
            "callback": td._schedule_chain_event_ref,
        }
    ]

    # No drawing yet
    assert graphics.calls == []
    assert display.update_calls == 0


def test_chain_event_active_event_draws_and_schedules_ring_and_next_event() -> None:
    timer_factory, timers = _mk_timer_factory()
    display = FakeDisplay()
    graphics = FakeGraphics()

    now = 1000
    td = TimerDisplay(
        display=display,
        graphics=graphics,
        timezone_offset_hours=0,
        get_time=lambda: now,
        gmtime=lambda _now: (0, 0, 0, 0, 0, 0, 0, 0),
        schedule=lambda fn, arg: fn(arg),
        timer_factory=timer_factory,
    )

    td._events = iter(
        [
            Event("bad", 900, 0),
            Event("old", 800, 100),
            Event("good", 900, 200),
        ]
    )

    td._chain_event(0)

    clock_timer, ring_timer, event_timer = timers

    assert ("reset", (), {}) in graphics.calls
    assert ("text_write", (TimerGraphics.TEXT_CENTER, "good"), {}) in graphics.calls

    # elapsed = 100 sec, duration = 200 sec -> cleared = 120 * 100 // 200 = 60
    assert ("ring_clear_segments", (60,), {}) in graphics.calls

    assert display.update_calls == 1

    assert ring_timer.init_calls == [
        {
            "mode": machine.Timer.PERIODIC,
            "period": 200 * 1000 // 120,
            "callback": td._schedule_update_ring_ref,
        }
    ]

    assert event_timer.init_calls == [
        {
            "mode": machine.Timer.ONE_SHOT,
            "period": 100 * 1000,
            "callback": td._schedule_chain_event_ref,
        }
    ]


def test_chain_event_iterator_exhaustion_is_safe() -> None:
    timer_factory, timers = _mk_timer_factory()
    display = FakeDisplay()
    graphics = FakeGraphics()

    td = TimerDisplay(
        display=display,
        graphics=graphics,
        timezone_offset_hours=0,
        get_time=lambda: 0,
        gmtime=lambda _now: (0, 0, 0, 0, 0, 0, 0, 0),
        schedule=lambda fn, arg: fn(arg),
        timer_factory=timer_factory,
    )

    td._events = iter(())
    td._chain_event(0)

    _clock_timer, ring_timer, event_timer = timers

    assert ring_timer.init_calls == []
    assert event_timer.init_calls == []
    assert graphics.calls == []
    assert display.update_calls == 0


@pytest.mark.parametrize(
    "end_timestamp,expected_below_calls",
    [
        (0, 0),  # negative remaining -> no below-center text
        (1000 + 604800 + 1, 0),  # too large -> no below-center text
        (1000 + 1, 1),  # within window -> yes
    ],
)
def test_update_clock_remaining_time_window(end_timestamp: int, expected_below_calls: int) -> None:
    timer_factory, _timers = _mk_timer_factory()
    display = FakeDisplay()
    graphics = FakeGraphics()

    now = 1000
    td = TimerDisplay(
        display=display,
        graphics=graphics,
        timezone_offset_hours=0,
        get_time=lambda: now,
        gmtime=lambda _now: (0, 0, 0, 0, 0, 0, 0, 0),
        schedule=lambda fn, arg: fn(arg),
        timer_factory=timer_factory,
    )

    td._event_end_timestamp = end_timestamp
    td._update_clock(0)

    below = [c for c in graphics.calls if c[0] == "text_write" and c[1][0] == TimerGraphics.TEXT_BELOW_CENTER]
    assert len(below) == expected_below_calls
