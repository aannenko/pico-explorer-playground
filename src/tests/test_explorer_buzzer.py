from __future__ import annotations

from dataclasses import dataclass

import machine

from services.utilities.explorer_buzzer import ExplorerBuzzer


class FakePin:
    def __init__(self, pin_id):
        self.pin_id = pin_id


class FakePWM:
    def __init__(self, pin):
        self.pin = pin
        self._freq = 0
        self._duty = 0

    def freq(self, f=None):
        if f is not None:
            self._freq = f
        return self._freq

    def duty_u16(self, d=None):
        if d is not None:
            self._duty = d
        return self._duty


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


def _mk_buzzer():
    timer_factory, timers = _mk_timer_factory()
    buzzer = ExplorerBuzzer(
        pin_id=0,
        pwm_factory=FakePWM,
        pin_factory=FakePin,
        schedule=lambda fn, arg: fn(arg),
        timer_factory=timer_factory,
    )
    return buzzer, timers


# ── initial state ──────────────────────────────────────────────────────


def test_init_sets_duty_to_zero() -> None:
    buzzer, _ = _mk_buzzer()
    assert buzzer._pwm._duty == 0


# ── play_alert ─────────────────────────────────────────────────────────


def test_play_alert_starts_beeping() -> None:
    buzzer, timers = _mk_buzzer()
    buzzer.play_alert()

    # PWM should be active (first beep)
    assert buzzer._pwm._duty > 0
    assert buzzer._pwm._freq == 1000

    # Alert timer should be set up as periodic
    alert_timer = timers[0]
    assert any(
        c.get("mode") == machine.Timer.PERIODIC
        and c.get("period") == 150
        for c in alert_timer.init_calls
    )


def test_play_alert_custom_params() -> None:
    buzzer, timers = _mk_buzzer()
    buzzer.play_alert(count=3, freq=2000, interval_ms=200)

    assert buzzer._pwm._freq == 2000
    assert buzzer._alert_remaining == 6  # 3 beeps * 2 toggles

    alert_timer = timers[0]
    assert any(
        c.get("period") == 200
        for c in alert_timer.init_calls
    )


def test_play_alert_full_pattern() -> None:
    """Run through the complete toggle pattern for 2 beeps (4 toggles)."""
    buzzer, timers = _mk_buzzer()
    buzzer.play_alert(count=2, freq=1000, interval_ms=100)

    # Initial state: beeping, remaining=4
    assert buzzer._pwm._duty > 0
    assert buzzer._alert_remaining == 4

    gen = buzzer._alert_generation

    # Toggle 1: remaining=3 (odd) → off
    buzzer._toggle_alert(gen)
    assert buzzer._pwm._duty == 0
    assert buzzer._alert_remaining == 3

    # Toggle 2: remaining=2 (even) → beep
    buzzer._toggle_alert(gen)
    assert buzzer._pwm._duty > 0
    assert buzzer._alert_remaining == 2

    # Toggle 3: remaining=1 (odd) → off
    buzzer._toggle_alert(gen)
    assert buzzer._pwm._duty == 0
    assert buzzer._alert_remaining == 1

    # Toggle 4: remaining=0 → off + deinit
    buzzer._toggle_alert(gen)
    assert buzzer._pwm._duty == 0
    assert buzzer._alert_remaining == 0
    alert_timer = timers[0]
    assert alert_timer.deinit_calls >= 1


# ── stop_alert ─────────────────────────────────────────────────────────


def test_stop_alert_silences_buzzer() -> None:
    buzzer, timers = _mk_buzzer()
    buzzer.play_alert()
    assert buzzer._pwm._duty > 0

    buzzer.stop_alert()
    assert buzzer._pwm._duty == 0
    assert buzzer._alert_remaining == 0
    alert_timer = timers[0]
    assert alert_timer.deinit_calls >= 1


def test_stop_alert_is_idempotent() -> None:
    buzzer, _ = _mk_buzzer()
    buzzer.stop_alert()  # No alert playing — should not crash
    assert buzzer._pwm._duty == 0


def test_stop_alert_mid_pattern() -> None:
    buzzer, timers = _mk_buzzer()
    buzzer.play_alert(count=5)

    gen = buzzer._alert_generation

    # Advance a couple toggles
    buzzer._toggle_alert(gen)
    buzzer._toggle_alert(gen)

    buzzer.stop_alert()
    assert buzzer._pwm._duty == 0
    assert buzzer._alert_remaining == 0


def test_stale_toggle_ignored_after_stop_and_restart() -> None:
    buzzer, _ = _mk_buzzer()
    buzzer.play_alert(count=2, freq=1000, interval_ms=100)
    stale_gen = buzzer._alert_generation

    buzzer.stop_alert()
    buzzer.play_alert(count=3, freq=1000, interval_ms=100)

    # Stale toggle from the first alert should be ignored
    buzzer._toggle_alert(stale_gen)
    assert buzzer._alert_remaining == 6  # unchanged (3 beeps * 2)


# ── schedule wrapper ──────────────────────────────────────────────────


def test_schedule_wrapper_forwards_generation() -> None:
    scheduled: list[tuple[object, int]] = []

    def schedule(fn, arg):
        scheduled.append((fn, arg))

    timer_factory, _ = _mk_timer_factory()
    buzzer = ExplorerBuzzer(
        pin_id=0,
        pwm_factory=FakePWM,
        pin_factory=FakePin,
        schedule=schedule,
        timer_factory=timer_factory,
    )

    buzzer._schedule_toggle_alert(None)

    assert scheduled == [
        (buzzer._toggle_alert_ref, buzzer._alert_generation),
    ]
