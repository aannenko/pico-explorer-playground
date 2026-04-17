import micropython
from micropython import const

from machine import Timer


_MIN_PERIOD_MS = const(100)


class TickScheduler:
    """Single hardware timer that drives all periodic work via subscribers."""

    def __init__(
        self,
        period_ms: int = 500,
        schedule=micropython.schedule,
        timer_factory=Timer,
    ) -> None:
        # Using a list for O(n) register/unregister. A dict keyed by stable
        # token would give O(1), but bound methods on MicroPython have unstable
        # hashes (based on id()), so a set/dict with raw callbacks won't work.
        # Fine for the current subscriber count (~7); revisit if it grows.
        self._subscribers: list = []  # list[Callable[[], None]]
        self._schedule = schedule
        self._tick_ref = self._tick
        self._schedule_tick_ref = self._schedule_tick
        self._timer = timer_factory(-1)
        self._period_ms: int = period_ms if period_ms > _MIN_PERIOD_MS else _MIN_PERIOD_MS
        self._pending = False

    @property
    def ms_per_tick(self) -> int:
        return self._period_ms

    def start(self) -> None:
        self._timer.init(
            mode=Timer.PERIODIC,
            period=self._period_ms,
            callback=self._schedule_tick_ref,
        )

    def stop(self) -> None:
        self._timer.deinit()

    def register(self, callback) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unregister(self, callback) -> None:
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def _tick(self, _: int) -> None:
        for callback in self._subscribers:
            callback()
        self._pending = False

    def _schedule_tick(self, _: Timer) -> None:
        if self._pending:
            return
        self._pending = True
        self._schedule(self._tick_ref, 0)
