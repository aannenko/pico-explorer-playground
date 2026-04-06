from __future__ import annotations

from dataclasses import dataclass

import machine

from scheduling.event import Event
from services.event_service import EventService


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


def _mk_event(name: str, start: int, duration: int) -> Event:
    return Event(name=name, start_timestamp=start, duration_sec=duration)


def _mk_service(events, now=1000, **overrides):
    time_val = [now]
    timer_factory, timers = _mk_timer_factory()
    defaults = dict(
        events_iter=iter(events),
        get_time=lambda: time_val[0],
        schedule=lambda fn, arg: fn(arg),
        timer_factory=timer_factory,
    )
    defaults.update(overrides)
    svc = EventService(**defaults)
    return svc, timers, time_val


# ── initial state ──────────────────────────────────────────────────────


def test_initial_state_finds_active_event() -> None:
    # start=900 duration=200 → ends 1100, now=1000 → active
    events = [_mk_event("Meeting", 900, 200)]
    svc, *_ = _mk_service(events, now=1000)
    assert svc.current_event is not None
    assert svc.name == "Meeting"


# ── properties for active event ───────────────────────────────────────


def test_properties_for_active_event() -> None:
    events = [_mk_event("Meeting", 900, 200)]
    svc, _, time_val = _mk_service(events, now=1000)
    assert svc.name == "Meeting"
    assert svc.total_sec == 200
    assert svc.elapsed_sec == 100   # 1000 - 900
    assert svc.remaining_sec == 100  # 1100 - 1000


# ── default properties when no current event ──────────────────────────


def test_properties_default_when_no_event() -> None:
    svc, *_ = _mk_service([], now=1000)
    assert svc.current_event is None
    assert svc.name == ""
    assert svc.total_sec == 0
    assert svc.elapsed_sec == 0
    assert svc.remaining_sec == 0


# ── skipping expired events ──────────────────────────────────────────


def test_skips_expired_events() -> None:
    events = [
        _mk_event("Expired", 100, 50),   # ends 150 < 1000
        _mk_event("Active", 900, 200),   # ends 1100 > 1000
    ]
    svc, *_ = _mk_service(events, now=1000)
    assert svc.name == "Active"


def test_skips_zero_duration_events() -> None:
    events = [
        _mk_event("Zero", 900, 0),
        _mk_event("Active", 900, 200),
    ]
    svc, *_ = _mk_service(events, now=1000)
    assert svc.name == "Active"


# ── future event ─────────────────────────────────────────────────────


def test_future_event_schedules_timer() -> None:
    events = [_mk_event("Future", 2000, 300)]
    svc, timers, _ = _mk_service(events, now=1000)
    assert svc.current_event is None

    timer = timers[0]
    assert any(
        c.get("mode") == machine.Timer.ONE_SHOT
        and c.get("period") == (2000 - 1000) * 1000
        for c in timer.init_calls
    )


def test_future_event_becomes_current_after_timer_fires() -> None:
    events = [_mk_event("Future", 2000, 300), _mk_event("After", 2300, 200)]
    svc, _, time_val = _mk_service(events, now=1000)
    assert svc.current_event is None

    time_val[0] = 2000
    svc._advance()
    assert svc.name == "Future"
    assert svc.total_sec == 300


# ── iterator exhaustion ──────────────────────────────────────────────


def test_iterator_exhaustion_no_crash() -> None:
    svc, *_ = _mk_service([], now=1000)
    assert svc.current_event is None
    assert svc.name == ""
    # Calling _advance again after exhaustion must not raise.
    svc._advance()
    assert svc.current_event is None


# ── auto-advance ─────────────────────────────────────────────────────


def test_auto_advance_moves_to_next_event() -> None:
    events = [
        _mk_event("First", 900, 200),    # ends 1100
        _mk_event("Second", 1100, 300),   # ends 1400
    ]
    svc, _, time_val = _mk_service(events, now=1000)
    assert svc.name == "First"

    time_val[0] = 1100
    svc._advance()
    assert svc.name == "Second"
    assert svc.total_sec == 300


# ── timer deinit on each _advance ────────────────────────────────────


def test_timer_deinit_on_each_advance() -> None:
    events = [
        _mk_event("First", 900, 200),
        _mk_event("Second", 1100, 300),
    ]
    svc, timers, time_val = _mk_service(events, now=1000)
    timer = timers[0]
    deinits_after_init = timer.deinit_calls
    assert deinits_after_init >= 1  # constructor _advance calls deinit

    time_val[0] = 1100
    svc._advance()
    assert timer.deinit_calls == deinits_after_init + 1


# ── timer deinit on StopIteration ────────────────────────────────────


def test_timer_deinit_on_stop_iteration() -> None:
    events = [_mk_event("Only", 900, 200)]
    svc, timers, time_val = _mk_service(events, now=1000)
    timer = timers[0]
    deinits_after_init = timer.deinit_calls

    time_val[0] = 1100
    svc._advance()
    assert timer.deinit_calls == deinits_after_init + 1
    assert svc.current_event is None


# ── schedule wrapper ─────────────────────────────────────────────────


def test_schedule_advance_forwards_to_schedule() -> None:
    scheduled: list[tuple[object, int]] = []

    events = [_mk_event("Meeting", 900, 200)]
    svc, *_ = _mk_service(
        events,
        now=1000,
        schedule=lambda fn, arg: scheduled.append((fn, arg)),
    )

    scheduled.clear()
    svc._schedule_advance(None)

    assert len(scheduled) == 1
    assert scheduled[0] == (svc._advance_ref, 0)


# ── elapsed/remaining are time-dependent ─────────────────────────────


def test_elapsed_remaining_update_with_time() -> None:
    events = [_mk_event("Meeting", 900, 200)]
    svc, _, time_val = _mk_service(events, now=1000)

    assert svc.elapsed_sec == 100
    assert svc.remaining_sec == 100

    time_val[0] = 1050
    assert svc.elapsed_sec == 150
    assert svc.remaining_sec == 50

    time_val[0] = 1100
    assert svc.elapsed_sec == 200
    assert svc.remaining_sec == 0


# ── active event schedules expiry timer ──────────────────────────────


def test_active_event_schedules_expiry_timer() -> None:
    events = [_mk_event("Meeting", 900, 200)]
    svc, timers, _ = _mk_service(events, now=1000)

    timer = timers[0]
    # remaining_ms = (1100 - 1000) * 1000 = 100_000
    assert any(
        c.get("mode") == machine.Timer.ONE_SHOT
        and c.get("period") == 100_000
        for c in timer.init_calls
    )
