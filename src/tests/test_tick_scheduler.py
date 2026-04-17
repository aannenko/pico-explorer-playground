from __future__ import annotations

from services.tick_scheduler import TickScheduler

from conftest import make_timer_factory


def _mk_scheduler(**overrides):
    timer_factory, timer_factory_created = make_timer_factory()

    scheduled: list[tuple] = []
    defaults = dict(
        period_ms=100,
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


def test_ms_per_tick_exposes_period() -> None:
    sched, _, _ = _mk_scheduler(period_ms=250)
    assert sched.ms_per_tick == 250


def test_period_below_floor_is_clamped() -> None:
    sched, _, _ = _mk_scheduler(period_ms=1)
    # Clamp protects against IRQ/schedule queue pressure from absurdly
    # short periods; see _MIN_PERIOD_MS in tick_scheduler.
    assert sched.ms_per_tick >= 100
    sched.start()
    assert sched.ms_per_tick >= 100


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
    # _pending must roll back so the next IRQ can retry.
    assert sched._pending is False
    # And a follow-up IRQ must be able to try scheduling again.
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
