import time

from micropython import const

from scheduling.event import Event
from services.tick_scheduler import TickScheduler
from utilities.log import log_exception

_DEFAULT_BACKOFF_BASE_MS = const(5_000)
_DEFAULT_BACKOFF_MAX_MS = const(600_000)


class EventStreamService:
    """Refresh/publish loop for ``stream_count`` network-backed streams, with retry backoff.

    A due refresh runs as ``tick_scheduler``'s deferred job, which publishes every stream at once; one the scheduler
    refuses stays due for a later tick.  Every failed refresh, WiFi down included, is an exception from
    ``_fetch_and_parse``.
    """

    def __init__(
        self,
        tick_scheduler: TickScheduler,
        interval_ms: int,
        log_tag: str,
        enabled: bool,
        stream_count: int = 1,
        get_ticks_ms=time.ticks_ms,  # () -> int
        backoff_base_ms: int = _DEFAULT_BACKOFF_BASE_MS,
        backoff_max_ms: int = _DEFAULT_BACKOFF_MAX_MS,
    ) -> None:
        self._tick_scheduler = tick_scheduler
        self._interval_ms = interval_ms
        self._log_tag = log_tag
        # Formatted here, as log_exception requires: formatting while handling a MemoryError can fail.
        self._err_tag = "[%s] err:" % log_tag
        self._enabled = enabled
        self._get_ticks_ms = get_ticks_ms
        self._backoff_base_ms = backoff_base_ms
        self._backoff_max_ms = backoff_max_ms

        self._events: tuple[list[Event], ...] = ([],) * stream_count

        # None latches a due fetch so long refusals can't age its deadline past half a ticks period.
        self._next_fetch_ms: int | None = get_ticks_ms()
        self._failures = 0

        self._refresh_ref = self._refresh

        self._tick_ref = self.tick
        tick_scheduler.register(self._tick_ref)

    def tick(self) -> None:
        if not self._enabled:
            return
        next_fetch_ms = self._next_fetch_ms
        if next_fetch_ms is not None and time.ticks_diff(self._get_ticks_ms(), next_fetch_ms) < 0:
            return
        self._next_fetch_ms = None
        self._tick_scheduler.try_defer(self._refresh_ref)

    def _refresh(self) -> None:
        try:
            events = self._fetch_and_parse()
        except Exception as exc:
            # The failure is committed before logging, without allocating, so a logger that raises can't leave the
            # refresh due on every tick.
            self._failures += 1
            delay_ms = self._backoff_delay()
            self._next_fetch_ms = time.ticks_add(self._get_ticks_ms(), delay_ms)
            log_exception(self._err_tag, exc)
            print("[%s] fail #%d, retry in %dms" % (self._log_tag, self._failures, delay_ms))
        else:
            self._events = events
            self._failures = 0
            self._next_fetch_ms = time.ticks_add(self._get_ticks_ms(), self._interval_ms)
            print("[%s] published %s events" % (self._log_tag, [len(e) for e in events]))

    def refresh_failed(self) -> bool:
        """Return whether the latest refresh failed: a success clears it, and a disabled service never fails."""
        return self._failures > 0

    def _backoff_delay(self) -> int:
        delay_ms = self._backoff_base_ms
        # Doubling a step at a time and stopping at the cap keeps it a small int, where one shift by the failure
        # count could need a big int.
        for _ in range(1, self._failures):
            if delay_ms >= self._backoff_max_ms:
                break
            delay_ms <<= 1
        return delay_ms if delay_ms < self._backoff_max_ms else self._backoff_max_ms

    def build_streams(self) -> list:  # -> list[(int) -> list[Event]]
        """Return a getter per event list ``_fetch_and_parse`` returns, in its order.

        A getter takes the UTC time, which it ignores, and returns that stream's latest published events.  The list is
        the service's own: callers must not change it, and a publish replaces it rather than changing it.
        """
        return [self._build_stream(i) for i in range(len(self._events))]

    def _build_stream(self, stream_index: int):  # -> (int) -> list[Event]
        # A helper, not a lambda in the comprehension: closures there would all see its last index.
        return lambda now_utc: self._events[stream_index]

    def _fetch_and_parse(self) -> tuple[list[Event], ...]:
        """Fetch and parse the latest events, one list per stream; subclasses must override.

        It runs as the tick scheduler's deferred job, so it may block.  The returned lists are published together; if
        it raises, nothing is published and the fetch is retried after a backoff.
        """
        raise NotImplementedError
