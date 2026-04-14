import time

from breakout_bme69x import (  # type: ignore
    BreakoutBME69X,
    STATUS_HEATER_STABLE,
    FILTER_COEFF_3,
    OVERSAMPLING_1X,
    OVERSAMPLING_2X,
    STANDBY_TIME_1000_MS,
)
from pimoroni import PICO_EXPLORER_I2C_PINS  # type: ignore
from pimoroni_i2c import PimoroniI2C  # type: ignore


class PimoroniBME690:
    def __init__(
        self,
        temp_offset: float,
        hum_offset: float,
        sensor_read_delay_ms: int = 5000,
        tick_scheduler=None,
    ) -> None:
        self._temp_offset = temp_offset
        self._hum_offset = hum_offset
        self._read_interval_ms = sensor_read_delay_ms

        self._bme = BreakoutBME69X(PimoroniI2C(**PICO_EXPLORER_I2C_PINS))
        self._bme.configure(
            FILTER_COEFF_3,
            STANDBY_TIME_1000_MS,
            OVERSAMPLING_2X,
            OVERSAMPLING_2X,
            OVERSAMPLING_1X,
        )

        self._last_reading: tuple[float, float, float, float, str] = (0.0, 0.0, 0.0, 0.0, "Unstable")
        self._last_read_ticks: int = 0
        self._do_read()

        if tick_scheduler is not None:
            tick_scheduler.register(self._tick)

    def _tick(self) -> None:
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_read_ticks) >= self._read_interval_ms:
            self._do_read()

    def _do_read(self) -> None:
        temp, press, hum, gas_r, status = self._bme.read()[0:5]
        temp += self._temp_offset
        hum += self._hum_offset
        heater = "Stable" if status & STATUS_HEATER_STABLE else "Unstable"
        self._last_reading = (temp, press / 100, hum, gas_r / 1000, heater)
        self._last_read_ticks = time.ticks_ms()

    def read(self) -> tuple[float, float, float, float, str]:
        return self._last_reading
