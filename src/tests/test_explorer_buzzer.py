from __future__ import annotations

import machine

from services.explorer_buzzer import ExplorerBuzzer

from conftest import make_timer_factory


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


def _mk_buzzer():
    timer_factory, timers = make_timer_factory()
    buzzer = ExplorerBuzzer(
        pin_id=0,
        pwm_factory=FakePWM,
        pin_factory=FakePin,
        timer_factory=timer_factory,
    )
    return buzzer, timers


def _fire(timer) -> None:
    timer.init_calls[-1]["callback"](timer)


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
    buzzer.play_alert(beep_count=3, freq_hz=2000, beep_toggle_ms=200)

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
    buzzer.play_alert(beep_count=2, freq_hz=1000, beep_toggle_ms=100)

    # Initial state: beeping, remaining=4
    assert buzzer._pwm._duty > 0
    assert buzzer._alert_remaining == 4

    alert_timer = timers[0]

    # Toggle 1: remaining=3 (odd) → off
    _fire(alert_timer)
    assert buzzer._pwm._duty == 0
    assert buzzer._alert_remaining == 3

    # Toggle 2: remaining=2 (even) → beep
    _fire(alert_timer)
    assert buzzer._pwm._duty > 0
    assert buzzer._alert_remaining == 2

    # Toggle 3: remaining=1 (odd) → off
    _fire(alert_timer)
    assert buzzer._pwm._duty == 0
    assert buzzer._alert_remaining == 1
    assert alert_timer.deinit_calls == 0

    # Toggle 4: remaining=0 → off + deinit
    _fire(alert_timer)
    assert buzzer._pwm._duty == 0
    assert buzzer._alert_remaining == 0
    assert alert_timer.deinit_calls == 1


def test_play_alert_reuses_cached_toggle_ref() -> None:
    buzzer, timers = _mk_buzzer()
    buzzer.play_alert()
    buzzer.play_alert()

    callbacks = [c["callback"] for c in timers[0].init_calls]
    assert len(callbacks) == 2
    assert all(cb is buzzer._toggle_alert_ref for cb in callbacks)


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
    buzzer.play_alert(beep_count=5)

    # Advance a couple toggles
    _fire(timers[0])
    _fire(timers[0])

    buzzer.stop_alert()
    assert buzzer._pwm._duty == 0
    assert buzzer._alert_remaining == 0


def test_late_toggles_after_stop_keep_buzzer_silent() -> None:
    buzzer, timers = _mk_buzzer()
    buzzer.play_alert(beep_count=2)
    buzzer.stop_alert()

    _fire(timers[0])
    _fire(timers[0])

    assert buzzer._pwm._duty == 0
