import micropython
from micropython import const

from machine import Timer

from utilities.log import log_exception


_MIN_PERIOD_MS = const(100)


class TickScheduler:
    """Fixed-period tick on one ``machine.Timer``, shared by registered callbacks, and one deferred job.

    A ``tick_period_ms`` below ``_MIN_PERIOD_MS`` is raised to it.
    """

    def __init__(
        self,
        tick_period_ms: int = 500,
        schedule=micropython.schedule,  # (callback, arg) -> None
        timer_factory=Timer,  # (int) -> Timer
    ) -> None:
        self._subscribers: list = []  # list[Callable[[], None]]
        self._job = None  # Callable[[], None] | None
        self._schedule = schedule
        self._tick_ref = self._tick
        self._schedule_tick_ref = self._schedule_tick
        self._timer = timer_factory(-1)
        self._tick_period_ms = tick_period_ms if tick_period_ms > _MIN_PERIOD_MS else _MIN_PERIOD_MS
        self._pending = False

    @property
    def tick_period_ms(self) -> int:
        return self._tick_period_ms

    def start(self) -> None:
        self._timer.init(
            mode=Timer.PERIODIC,
            period=self._tick_period_ms,
            callback=self._schedule_tick_ref,
        )

    def stop(self) -> None:
        """A tick already queued still runs."""
        self._timer.deinit()

    def register(self, callback) -> None:  # callback: () -> None
        """Call ``callback()`` on every tick; registering it again has no effect.

        Callbacks run from the ``schedule`` queue on the main thread, not in an
        IRQ, so they may allocate but should return quickly: blocking work
        freezes rendering and delays button actions, so defer it with
        ``try_defer``.  One that raises skips the rest of that tick's callbacks.
        """
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unregister(self, callback) -> None:  # callback: () -> None
        """A callback that isn't registered is ignored."""
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def try_defer(self, job) -> bool:  # job: () -> None
        """Run ``job()`` once, after every subscriber of the tick in progress, or else of the next tick; return
        whether it was accepted.

        For blocking work, such as a network fetch: the display, a subscriber, has had its turn to draw before the job
        blocks.  One job is held at a time, and another is refused until it returns, so a refused caller should retry
        on a later tick, which leaves a tick of rendering between two jobs.  The job runs even if a subscriber raised,
        and what the job raises is logged rather than propagated, so it can't hide a subscriber's exception.
        """
        if self._job is not None:
            return False
        self._job = job
        return True

    def _tick(self, _: int) -> None:
        try:
            for callback in self._subscribers:
                callback()
        finally:
            # Always clear _pending so one bad subscriber can't wedge
            # the scheduler permanently.
            self._pending = False
            if self._job is not None:
                self._run_job()

    def _run_job(self) -> None:
        # Its own method, so the frame _tick allocates on every tick doesn't grow.
        try:
            self._job()
        except Exception as exc:
            log_exception("[tick] job err:", exc)
        finally:
            self._job = None

    def _schedule_tick(self, _: Timer) -> None:
        # _pending collapses firings queued behind blocking work into one scheduled run.
        if self._pending:
            return
        self._pending = True
        try:
            self._schedule(self._tick_ref, 0)
        except Exception:
            self._pending = False
