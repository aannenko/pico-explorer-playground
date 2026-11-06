import micropython
from micropython import const

from machine import Timer


_MIN_PERIOD_MS = const(100)


class TickScheduler:
    """Fixed-period tick on one ``machine.Timer``, shared by registered callbacks.

    A ``period_ms`` below ``_MIN_PERIOD_MS`` is raised to it.
    """

    def __init__(
        self,
        period_ms: int = 500,
        schedule=micropython.schedule,  # (callback, arg) -> None
        timer_factory=Timer,  # (int) -> Timer
    ) -> None:
        self._subscribers: list = []  # list[Callable[[], None]]
        self._schedule = schedule
        self._tick_ref = self._tick
        self._schedule_tick_ref = self._schedule_tick
        self._timer = timer_factory(-1)
        self._period_ms = period_ms if period_ms > _MIN_PERIOD_MS else _MIN_PERIOD_MS
        self._pending = False

    @property
    def ms_per_tick(self) -> int:
        """Effective tick period in milliseconds."""
        return self._period_ms

    def start(self) -> None:
        self._timer.init(
            mode=Timer.PERIODIC,
            period=self._period_ms,
            callback=self._schedule_tick_ref,
        )

    def stop(self) -> None:
        """A tick already queued still runs."""
        self._timer.deinit()

    def register(self, callback) -> None:  # callback: () -> None
        """Call ``callback()`` on every tick; registering it again has no effect.

        Callbacks run from the ``schedule`` queue on the main thread, not in an
        IRQ, so they may allocate but should return quickly: blocking work
        freezes rendering and buttons.  One that raises skips the rest of that
        tick's callbacks.
        """
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unregister(self, callback) -> None:  # callback: () -> None
        """A callback that isn't registered is ignored."""
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def _tick(self, _: int) -> None:
        try:
            for callback in self._subscribers:
                callback()
        finally:
            # Always clear _pending so one bad subscriber can't wedge
            # the scheduler permanently.
            self._pending = False

    def _schedule_tick(self, _: Timer) -> None:
        # _pending collapses firings queued behind blocking work into one scheduled run.
        if self._pending:
            return
        self._pending = True
        try:
            self._schedule(self._tick_ref, 0)
        except Exception:
            self._pending = False
