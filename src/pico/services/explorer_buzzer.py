from machine import Pin, PWM, Timer
from micropython import const

from hardware.explorer import BUZZER_PIN
# Note: You must bridge the pin you use over to the AUDIO pin
# on the Pico Explorer header in order to drive the onboard Piezo.

_DEFAULT_BEEP_COUNT = const(5)
_DEFAULT_BEEP_TOGGLE_MS = const(150)
_DEFAULT_BEEP_FREQ_HZ = const(1000)


class ExplorerBuzzer:
    """Pico Explorer piezo buzzer (PWM) for non-blocking beep alerts."""

    def __init__(
        self,
        pin_id: int = BUZZER_PIN,
        pwm_factory=PWM,  # (Pin) -> PWM
        pin_factory=Pin,  # (int) -> Pin
        timer_factory=Timer,  # (int) -> Timer
    ) -> None:
        self._pwm = pwm_factory(pin_factory(pin_id))
        self._pwm.duty_u16(0)

        self._alert_remaining = 0
        self._alert_freq_hz = 0

        self._toggle_alert_ref = self._toggle_alert

        self._alert_timer = timer_factory(-1)

    def play_alert(
        self,
        beep_count: int = _DEFAULT_BEEP_COUNT,
        freq_hz: int = _DEFAULT_BEEP_FREQ_HZ,
        beep_toggle_ms: int = _DEFAULT_BEEP_TOGGLE_MS,
    ) -> None:
        """Each beep, and each gap between beeps, lasts ``beep_toggle_ms``."""
        self._alert_remaining = beep_count * 2
        self._alert_freq_hz = freq_hz
        self._beep(freq_hz)
        self._alert_timer.init(
            mode=Timer.PERIODIC,
            period=beep_toggle_ms,
            callback=self._toggle_alert_ref,
        )

    def stop_alert(self) -> None:
        self._alert_timer.deinit()
        self._alert_remaining = 0
        self._off()

    def _beep(self, freq_hz: int, duty: int = 32768) -> None:
        self._pwm.freq(freq_hz)
        self._pwm.duty_u16(duty)

    def _off(self) -> None:
        self._pwm.duty_u16(0)

    def _toggle_alert(self, _: Timer) -> None:
        self._alert_remaining -= 1
        if self._alert_remaining <= 0:
            self._off()
            self._alert_timer.deinit()
            return
        if self._alert_remaining % 2 == 0:
            self._beep(self._alert_freq_hz)
        else:
            self._off()
