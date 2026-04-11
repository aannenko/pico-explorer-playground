from __future__ import annotations

from scheduling.event import Event
from services.event_service import EventService


class _FakeTime:
    def __init__(self, fn, utc_fn=None):
        self.now = fn
        self.utc_now = utc_fn if utc_fn is not None else fn

    def to_utc(self, local_epoch):
        return local_epoch


def _mk_event(name: str, start: int, duration: int, real_duration: int = -1) -> Event:
    return Event(name=name, start_timestamp=start, wall_clock_duration_sec=duration, real_duration_sec=real_duration)


class _FakeScheduler:
    def __init__(self):
        self.callbacks = []

    def register(self, cb):
        self.callbacks.append(cb)


def _mk_service(events, now=1000, **overrides):
    time_val = [now]
    defaults = dict(
        events_iter=iter(events),
        time_service=_FakeTime(lambda: time_val[0]),
        tick_scheduler=_FakeScheduler(),
    )
    defaults.update(overrides)
    svc = EventService(**defaults)
    return svc, time_val


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
    svc, time_val = _mk_service(events, now=1000)
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


def test_future_event_stored_as_pending() -> None:
    events = [_mk_event("Future", 2000, 300)]
    svc, _ = _mk_service(events, now=1000)
    assert svc.current_event is None


def test_future_event_becomes_current_after_tick() -> None:
    events = [_mk_event("Future", 2000, 300), _mk_event("After", 2300, 200)]
    svc, time_val = _mk_service(events, now=1000)
    assert svc.current_event is None

    time_val[0] = 2000
    svc._tick()
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
    svc, time_val = _mk_service(events, now=1000)
    assert svc.name == "First"

    time_val[0] = 1100
    svc._advance()
    assert svc.name == "Second"
    assert svc.total_sec == 300


# ── elapsed/remaining are time-dependent ─────────────────────────────


def test_elapsed_remaining_update_with_time() -> None:
    events = [_mk_event("Meeting", 900, 200)]
    svc, time_val = _mk_service(events, now=1000)

    assert svc.elapsed_sec == 100
    assert svc.remaining_sec == 100

    time_val[0] = 1050
    assert svc.elapsed_sec == 150
    assert svc.remaining_sec == 50

    time_val[0] = 1100
    assert svc.elapsed_sec == 200
    assert svc.remaining_sec == 0


# ── tick() ───────────────────────────────────────────────────────────


def test_tick_advances_when_event_expires() -> None:
    events = [
        _mk_event("First", 900, 200),    # ends 1100
        _mk_event("Second", 1100, 300),   # ends 1400
    ]
    svc, time_val = _mk_service(events, now=1000)
    assert svc.name == "First"

    time_val[0] = 1100
    svc._tick()
    assert svc.name == "Second"
    assert svc.total_sec == 300


def test_tick_activates_pending_future_event() -> None:
    events = [_mk_event("Future", 2000, 300)]
    svc, time_val = _mk_service(events, now=1000)
    assert svc.current_event is None

    time_val[0] = 2000
    svc._tick()
    assert svc.name == "Future"
    assert svc.total_sec == 300


def test_tick_does_nothing_when_event_still_active() -> None:
    events = [_mk_event("Meeting", 900, 200)]
    svc, time_val = _mk_service(events, now=1000)
    assert svc.name == "Meeting"

    time_val[0] = 1050
    svc._tick()
    assert svc.name == "Meeting"
    assert svc.elapsed_sec == 150
    assert svc.remaining_sec == 50


def test_tick_does_nothing_with_no_events() -> None:
    svc, time_val = _mk_service([], now=1000)
    assert svc.current_event is None

    time_val[0] = 2000
    svc._tick()
    assert svc.current_event is None
