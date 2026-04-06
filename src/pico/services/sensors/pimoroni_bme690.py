import micropython

from breakout_bme69x import BreakoutBME69X, STATUS_HEATER_STABLE, FILTER_COEFF_3, OVERSAMPLING_1X, OVERSAMPLING_2X, STANDBY_TIME_1000_MS  # type: ignore
from machine import Timer
from pimoroni import PICO_EXPLORER_I2C_PINS  # type: ignore
from pimoroni_i2c import PimoroniI2C  # type: ignore


class PimoroniBME690:
    def __init__(
        self,
        temp_offset: float,
        hum_offset: float,
        sensor_read_delay_ms: int = 5000,
        schedule = micropython.schedule,
        timer_factory = Timer,
    ) -> None:
        self._temp_offset = temp_offset
        self._hum_offset = hum_offset
        self._sensor_read_delay_ms = sensor_read_delay_ms

        self._bme = BreakoutBME69X(PimoroniI2C(**PICO_EXPLORER_I2C_PINS))
        self._bme.configure(
            FILTER_COEFF_3,
            STANDBY_TIME_1000_MS,
            OVERSAMPLING_2X,
            OVERSAMPLING_2X,
            OVERSAMPLING_1X,
        )

        self._last_reading: tuple[float, float, float, float, str] = (0.0, 0.0, 0.0, 0.0, "Unstable")
        self._do_read(0)

        self._schedule = schedule
        self._do_read_ref = self._do_read
        self._schedule_read_ref = self._schedule_read

        self._timer = timer_factory(-1)
        self._timer.init(
            mode=Timer.PERIODIC,
            period=self._sensor_read_delay_ms,
            callback=self._schedule_read_ref,
        )

    def _do_read(self, _: int) -> None:
        temp, press, hum, gas_r, status = self._bme.read()[0:5]
        temp += self._temp_offset
        hum += self._hum_offset
        heater = "Stable" if status & STATUS_HEATER_STABLE else "Unstable"
        self._last_reading = (temp, press / 100, hum, gas_r / 1000, heater)

    def _schedule_read(self, _: Timer) -> None:
        self._schedule(self._do_read_ref, 0)

    def read(self) -> tuple[float, float, float, float, str]:
        return self._last_reading
