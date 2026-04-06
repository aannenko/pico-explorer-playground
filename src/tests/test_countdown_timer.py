from __future__ import annotations

from dataclasses import dataclass

import machine

from services.countdown_timer import (
    CountdownTimer,
    INITIAL,
    RUNNING,
    PAUSED,
    DONE,
)


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


def _mk_engine(**overrides):
    timer_factory, timers = _mk_timer_factory()
    on_done_calls: list[int] = []
    on_configure_calls: list[int] = []
    defaults = dict(
        on_done=lambda: on_done_calls.append(1),
        on_configure=lambda: on_configure_calls.append(1),
        get_time=lambda: 1000,
        schedule=lambda fn, arg: fn(arg),
        timer_factory=timer_factory,
    )
    defaults.update(overrides)
    e = CountdownTimer(**defaults)
    return e, on_done_calls, on_configure_calls, timers


# ── initial state ──────────────────────────────────────────────────────


def test_initial_state() -> None:
    e, *_ = _mk_engine()
    assert e.state == INITIAL
    assert e.name == ""
    assert e.total_sec == 0
    assert e.elapsed_sec == 0
    assert e.remaining_sec == 0


# ── configure ──────────────────────────────────────────────────────────


def test_configure_sets_name_and_total_sec() -> None:
    e, *_ = _mk_engine()
    e.configure("5 min", 300)
    assert e.state == INITIAL
    assert e.name == "5 min"
    assert e.total_sec == 300


def test_configure_from_running_resets_to_initial() -> None:
    e, _, on_configure_calls, timers = _mk_engine()
    e.configure("5 min", 300)
    e.start()
    assert e.state == RUNNING

    e.configure("10 min", 600)
    assert e.state == INITIAL
    assert e.name == "10 min"
    assert e.total_sec == 600
    # Done timer should be deinited
    done_timer = timers[0]
    assert done_timer.deinit_calls >= 2  # once from configure while running


def test_configure_from_done_calls_on_configure() -> None:
    e, on_done_calls, on_configure_calls, _ = _mk_engine()
    e.configure("5 min", 300)
    e.start()
    e._fire_on_done(e._generation)
    assert e.state == DONE

    on_configure_calls.clear()
    e.configure("10 min", 600)
    assert len(on_configure_calls) == 1
    assert e.state == INITIAL


def test_configure_always_calls_on_configure() -> None:
    e, _, on_configure_calls, _ = _mk_engine()
    on_configure_calls.clear()
    e.configure("5 min", 300)
    assert len(on_configure_calls) == 1  # fires even from INITIAL


def test_configure_always_deinits_done_timer() -> None:
    e, _, _, timers = _mk_engine()
    e.configure("5 min", 300)
    done_timer = timers[0]
    assert done_timer.deinit_calls >= 1


# ── start ──────────────────────────────────────────────────────────────


def test_start_transitions_to_running() -> None:
    e, *_ = _mk_engine()
    e.configure("2 hours", 7200)
    e.start()

    assert e.state == RUNNING
    assert e.elapsed_sec == 0
    assert e.remaining_sec == 7200


def test_start_sets_up_done_timer() -> None:
    e, _, _, timers = _mk_engine()
    e.configure("2 hours", 7200)
    e.start()

    done_timer = timers[0]
    assert any(
        c.get("mode") == machine.Timer.ONE_SHOT
        and c.get("period") == 7200 * 1000
        for c in done_timer.init_calls
    )


def test_start_ignored_when_not_initial() -> None:
    e, *_ = _mk_engine()
    e.configure("5 min", 300)
    e.start()
    e.start()  # should be ignored
    assert e.state == RUNNING


def test_start_rejected_with_zero_total_sec() -> None:
    e, *_ = _mk_engine()
    e.configure("zero", 0)
    e.start()
    assert e.state == INITIAL


def test_start_rejected_with_negative_total_sec() -> None:
    e, *_ = _mk_engine()
    e.configure("neg", -1)
    e.start()
    assert e.state == INITIAL


# ── pause / resume ────────────────────────────────────────────────────


def test_pause_stores_remaining_time() -> None:
    now = 1000
    e, *_ = _mk_engine(get_time=lambda: now)
    e.configure("2 hours", 7200)
    e.start()

    now = 1060
    e._get_time = lambda: now
    e.pause()

    assert e.state == PAUSED
    assert e.remaining_sec == 7200 - 60
    assert e.elapsed_sec == 60


def test_pause_deinits_done_timer() -> None:
    e, _, _, timers = _mk_engine()
    e.configure("5 min", 300)
    e.start()
    e.pause()

    done_timer = timers[0]
    assert done_timer.deinit_calls >= 1


def test_pause_ignored_when_not_running() -> None:
    e, *_ = _mk_engine()
    e.configure("5 min", 300)
    e.pause()
    assert e.state == INITIAL


def test_resume_recalculates_timestamps() -> None:
    now = 1000
    e, *_ = _mk_engine(get_time=lambda: now)
    e.configure("2 hours", 7200)
    e.start()

    now = 1060
    e._get_time = lambda: now
    e.pause()

    now = 2000
    e._get_time = lambda: now
    e.resume()

    assert e.state == RUNNING
    remaining = 7200 - 60
    assert e.remaining_sec == remaining
    assert e.elapsed_sec == 60


def test_resume_restarts_done_timer() -> None:
    e, _, _, timers = _mk_engine()
    e.configure("5 min", 300)
    e.start()
    e.pause()

    for t in timers:
        t.init_calls.clear()

    e.resume()

    done_timer = timers[0]
    assert any(
        c.get("mode") == machine.Timer.ONE_SHOT
        for c in done_timer.init_calls
    )


def test_resume_ignored_when_not_paused() -> None:
    e, *_ = _mk_engine()
    e.configure("5 min", 300)
    e.resume()
    assert e.state == INITIAL


# ── reset ──────────────────────────────────────────────────────────────


def test_reset_from_running() -> None:
    e, *_ = _mk_engine()
    e.configure("5 min", 300)
    e.start()
    e.reset()

    assert e.state == INITIAL
    assert e.name == "5 min"
    assert e.total_sec == 300
    assert e.elapsed_sec == 0
    assert e.remaining_sec == 0


def test_reset_from_paused() -> None:
    e, *_ = _mk_engine()
    e.configure("5 min", 300)
    e.start()
    e.pause()
    e.reset()

    assert e.state == INITIAL
    assert e.name == "5 min"


def test_reset_from_done() -> None:
    e, on_done_calls, on_configure_calls, _ = _mk_engine()
    e.configure("5 min", 300)
    e.start()
    e._fire_on_done(e._generation)

    on_configure_calls.clear()
    e.reset()

    assert e.state == INITIAL
    assert e.name == "5 min"
    assert len(on_configure_calls) == 1


def test_reset_from_initial_is_noop_equivalent() -> None:
    e, *_ = _mk_engine()
    e.configure("5 min", 300)
    e.reset()
    assert e.state == INITIAL
    assert e.name == "5 min"


# ── on_done callback ──────────────────────────────────────────────────


def test_fire_on_done_transitions_to_done_and_calls_callback() -> None:
    e, on_done_calls, *_ = _mk_engine()
    e.configure("5 min", 300)
    e.start()
    e._fire_on_done(e._generation)

    assert e.state == DONE
    assert len(on_done_calls) == 1


def test_fire_on_done_ignored_when_not_running() -> None:
    e, on_done_calls, *_ = _mk_engine()
    e.configure("5 min", 300)
    e._fire_on_done(e._generation)
    assert e.state == INITIAL
    assert len(on_done_calls) == 0


def test_fire_on_done_ignored_with_stale_generation() -> None:
    e, on_done_calls, *_ = _mk_engine()
    e.configure("5 min", 300)
    e.start()
    stale_gen = e._generation
    e.pause()
    e.resume()  # increments generation
    e._fire_on_done(stale_gen)
    assert e.state == RUNNING
    assert len(on_done_calls) == 0


# ── schedule wrapper ──────────────────────────────────────────────────


def test_schedule_wrapper_forwards_generation() -> None:
    scheduled: list[tuple[object, int]] = []

    def schedule(fn, arg):
        scheduled.append((fn, arg))

    e, *_ = _mk_engine(schedule=schedule)
    e.configure("5 min", 300)
    e.start()

    e._schedule_fire_on_done(None)

    assert scheduled == [
        (e._fire_on_done_ref, e._generation),
    ]


# ── elapsed/remaining accessors ───────────────────────────────────────


def test_elapsed_and_remaining_while_running() -> None:
    now = 1000
    e, *_ = _mk_engine(get_time=lambda: now)
    e.configure("2 hours", 7200)
    e.start()

    now = 1060
    e._get_time = lambda: now

    assert e.elapsed_sec == 60
    assert e.remaining_sec == 7200 - 60


def test_elapsed_and_remaining_while_paused() -> None:
    now = 1000
    e, *_ = _mk_engine(get_time=lambda: now)
    e.configure("2 hours", 7200)
    e.start()

    now = 1060
    e._get_time = lambda: now
    e.pause()

    # Time advances while paused but accessors stay frozen
    now = 9999
    e._get_time = lambda: now

    assert e.elapsed_sec == 60
    assert e.remaining_sec == 7200 - 60


def test_elapsed_and_remaining_in_done() -> None:
    e, *_ = _mk_engine()
    e.configure("5 min", 300)
    e.start()
    e._fire_on_done(e._generation)

    assert e.state == DONE
    assert e.elapsed_sec == 300
    assert e.remaining_sec == 0
