from __future__ import annotations

import pytest

from services.tick_scheduler import TickScheduler

from conftest import make_timer_factory


def _mk_scheduler(**overrides):
    timer_factory, timer_factory_created = make_timer_factory()

    scheduled: list[tuple] = []
    defaults = dict(
        tick_period_ms=100,
        schedule=lambda fn, arg: fn(arg),
        timer_factory=timer_factory,
    )
    defaults.update(overrides)
    sched = TickScheduler(**defaults)
    return sched, timer_factory_created, scheduled


def test_start_initializes_periodic_timer() -> None:
    sched, timers, _ = _mk_scheduler()
    sched.start()
    timer = timers[0]
    assert len(timer.init_calls) == 1
    call = timer.init_calls[0]
    assert call["period"] == 100
    import machine
    assert call["mode"] == machine.Timer.PERIODIC


def test_tick_period_ms_exposes_period() -> None:
    sched, _, _ = _mk_scheduler(tick_period_ms=250)
    assert sched.tick_period_ms == 250


def test_period_below_floor_is_clamped() -> None:
    sched, _, _ = _mk_scheduler(tick_period_ms=1)
    # Clamp protects against schedule-queue pressure from absurdly
    # short periods; see _MIN_PERIOD_MS in tick_scheduler.
    assert sched.tick_period_ms >= 100
    sched.start()
    assert sched.tick_period_ms >= 100


def test_stop_deinits_timer() -> None:
    sched, timers, _ = _mk_scheduler()
    sched.start()
    sched.stop()
    assert timers[0].deinit_calls == 1


def test_register_and_tick_calls_subscribers() -> None:
    sched, _, _ = _mk_scheduler()
    calls: list[str] = []
    sched.register(lambda: calls.append("a"))
    sched.register(lambda: calls.append("b"))

    sched._tick(0)

    assert calls == ["a", "b"]


def test_unregister_removes_subscriber() -> None:
    sched, _, _ = _mk_scheduler()
    calls: list[str] = []
    cb = lambda: calls.append("a")
    sched.register(cb)
    sched._tick(0)
    assert calls == ["a"]

    calls.clear()
    sched.unregister(cb)
    sched._tick(0)
    assert calls == []


def test_register_is_idempotent() -> None:
    sched, _, _ = _mk_scheduler()
    calls: list[str] = []
    cb = lambda: calls.append("x")
    sched.register(cb)
    sched.register(cb)

    sched._tick(0)

    assert calls == ["x"]


def test_unregister_nonexistent_no_error() -> None:
    sched, _, _ = _mk_scheduler()
    sched.unregister(lambda: None)  # should not raise


def test_schedule_tick_forwards_to_schedule() -> None:
    scheduled: list[tuple] = []
    sched, _, _ = _mk_scheduler(
        schedule=lambda fn, arg: scheduled.append((fn, arg)),
    )

    sched._schedule_tick(None)

    assert len(scheduled) == 1
    assert scheduled[0] == (sched._tick_ref, 0)


def test_schedule_tick_clears_pending_if_schedule_raises() -> None:
    def raising_schedule(_fn, _arg):
        raise RuntimeError("queue full")

    sched, _, _ = _mk_scheduler(schedule=raising_schedule)
    sched._schedule_tick(None)
    assert sched._pending is False
    calls = {"n": 0}

    def counting_schedule(_fn, _arg):
        calls["n"] += 1

    sched._schedule = counting_schedule
    sched._schedule_tick(None)
    assert calls["n"] == 1


def test_tick_clears_pending_even_if_subscriber_raises() -> None:
    sched, _, _ = _mk_scheduler()
    sched.register(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    sched._pending = True
    try:
        sched._tick(0)
    except RuntimeError:
        pass
    assert sched._pending is False


def test_a_job_deferred_by_a_subscriber_runs_once_after_every_subscriber_of_that_tick() -> None:
    sched, _, _ = _mk_scheduler()
    calls: list[str] = []

    def submit() -> None:
        calls.append("submit")
        if len(calls) == 1:
            assert sched.try_defer(lambda: calls.append("job")) is True

    sched.register(submit)
    sched.register(lambda: calls.append("render"))

    sched._tick(0)
    sched._tick(0)

    assert calls == ["submit", "render", "job", "submit", "render"]


def test_a_job_deferred_between_ticks_runs_after_the_next_tick_s_subscribers() -> None:
    sched, _, _ = _mk_scheduler()
    calls: list[str] = []
    sched.register(lambda: calls.append("render"))

    assert sched.try_defer(lambda: calls.append("job")) is True
    assert calls == []

    sched._tick(0)

    assert calls == ["render", "job"]


def test_the_slot_refuses_another_job_while_one_is_held_or_running() -> None:
    sched, _, _ = _mk_scheduler()
    calls: list[str] = []

    def second() -> None:
        calls.append("second")

    def first() -> None:
        calls.append("first")
        assert sched.try_defer(second) is False

    assert sched.try_defer(first) is True
    assert sched.try_defer(second) is False

    sched._tick(0)
    sched._tick(0)
    assert calls == ["first"]

    assert sched.try_defer(second) is True
    sched._tick(0)
    assert calls == ["first", "second"]


def test_a_raising_job_is_logged_and_frees_the_slot(capsys) -> None:
    sched, _, _ = _mk_scheduler()
    calls: list[str] = []

    def fail() -> None:
        raise RuntimeError("fetch failed")

    sched.try_defer(fail)
    sched._tick(0)

    out = capsys.readouterr().out
    assert out.startswith("[tick] job err:")
    assert "RuntimeError: fetch failed" in out
    assert sched.try_defer(lambda: calls.append("recovered")) is True
    sched._tick(0)
    assert calls == ["recovered"]


def test_a_raising_subscriber_still_runs_the_deferred_job() -> None:
    sched, _, _ = _mk_scheduler()
    calls: list[str] = []

    def fail() -> None:
        raise RuntimeError("boom")

    sched.register(fail)
    sched.try_defer(lambda: calls.append("job"))

    with pytest.raises(RuntimeError, match="boom"):
        sched._tick(0)

    assert calls == ["job"]
    assert sched.try_defer(lambda: None) is True


def test_a_raising_job_does_not_hide_a_raising_subscriber(capsys) -> None:
    sched, _, _ = _mk_scheduler()

    def fail_subscriber() -> None:
        raise RuntimeError("subscriber failed")

    def fail_job() -> None:
        raise ValueError("job failed")

    sched.register(fail_subscriber)
    sched.try_defer(fail_job)

    with pytest.raises(RuntimeError, match="subscriber failed"):
        sched._tick(0)

    assert "ValueError: job failed" in capsys.readouterr().out
    assert sched._pending is False
