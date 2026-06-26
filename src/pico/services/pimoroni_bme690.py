import micropython

from machine import Timer

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
    """BME690 reader paced by its own ``machine.Timer``.

    Gas-resistance accuracy depends on constant inter-read spacing
    (the hot plate must cool between measurements), so this service
    can't share the ``TickScheduler``. The Timer IRQ schedules
    ``_do_read`` via ``micropython.schedule``; the blocking I2C read
    runs in normal context.
    """

    def __init__(
        self,
        temp_offset: float,
        hum_offset: float,
        prsr_offset: float,
        sensor_read_delay_ms: int = 5000,
        schedule=micropython.schedule,
        timer_factory=Timer,
    ) -> None:
        self._temp_offset = temp_offset
        self._hum_offset = hum_offset
        self._prsr_offset = prsr_offset
        self._read_interval_ms = sensor_read_delay_ms
        self._schedule = schedule

        self._bme = BreakoutBME69X(PimoroniI2C(**PICO_EXPLORER_I2C_PINS))
        self._bme.configure(
            FILTER_COEFF_3,
            STANDBY_TIME_1000_MS,
            OVERSAMPLING_2X,
            OVERSAMPLING_2X,
            OVERSAMPLING_1X,
        )

        self._last_reading: tuple[float, float, float, float, str] = (0.0, 0.0, 0.0, 0.0, "Unstable")
        self._pending: bool = False

        # Cache bound methods used from IRQ context to avoid heap
        # allocation (and possible MemoryError) inside the timer callback.
        self._timer_callback_ref = self._timer_callback
        self._do_read_scheduled_ref = self._do_read_scheduled

        self._do_read()

        self._timer = timer_factory(-1)
        self._timer.init(
            mode=Timer.PERIODIC,
            period=self._read_interval_ms,
            callback=self._timer_callback_ref,
        )

    def read(self) -> tuple[float, float, float, float, str]:
        return self._last_reading

    def deinit(self) -> None:
        self._timer.deinit()

    def _do_read(self) -> None:
        # Index the driver's result directly rather than slicing ``[0:5]`` — the
        # slice would allocate a throwaway tuple on every read (~5 s, runs even
        # when the Sensors view isn't active).
        reading = self._bme.read()
        heater_stable = reading[4] & STATUS_HEATER_STABLE
        self._last_reading = (
            reading[0] + self._temp_offset,
            reading[1] / 100 + self._prsr_offset,
            reading[2] + self._hum_offset,
            reading[3] / 1000 if heater_stable else float("nan"),
            "Stable" if heater_stable else "Unstable",
        )

    def _do_read_scheduled(self, _: int) -> None:
        try:
            self._do_read()
        finally:
            self._pending = False

    def _timer_callback(self, _: Timer) -> None:
        """Timer IRQ handler. Defers the blocking I2C read to main thread."""
        if self._pending:
            return
        self._pending = True
        try:
            self._schedule(self._do_read_scheduled_ref, 0)
        except Exception:
            # RuntimeError if schedule queue is full; MemoryError if the
            # heap is locked.  Either way, clear _pending so the next
            # timer tick can retry instead of wedging the reader.
            self._pending = False
