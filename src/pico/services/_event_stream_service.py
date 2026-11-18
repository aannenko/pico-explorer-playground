import time

from micropython import const

from scheduling.event import Event
from services.http_client import HttpClient
from services.tick_scheduler import TickScheduler
from utilities.log import log_exception

_DEFAULT_BACKOFF_BASE_MS = const(5_000)
_DEFAULT_BACKOFF_MAX_MS = const(600_000)
_MAX_BACKOFF_SHIFT = const(20)


class EventStreamService:
    """Fetch/parse/publish loop for ``stream_count`` network-backed streams, with retry backoff.

    One scheduled fetch publishes every stream at once before releasing the shared HTTP client's fetch slot.
    """

    def __init__(
        self,
        http_client: HttpClient,
        interval_ms: int,
        log_tag: str,
        enabled: bool,
        stream_count: int = 1,
        get_ticks_ms=time.ticks_ms,  # () -> int
        tick_scheduler: TickScheduler | None = None,
        backoff_base_ms: int = _DEFAULT_BACKOFF_BASE_MS,
        backoff_max_ms: int = _DEFAULT_BACKOFF_MAX_MS,
    ) -> None:
        self._http_client = http_client
        self._interval_ms = interval_ms
        self._log_tag = log_tag
        self._tick_err_tag = "[%s] tick err:" % log_tag
        self._enabled = enabled
        self._get_ticks_ms = get_ticks_ms
        self._backoff_base_ms = backoff_base_ms
        self._backoff_max_ms = backoff_max_ms

        self._events: tuple[list[Event], ...] = ([],) * stream_count

        # None latches a due fetch so long refusals can't age its deadline past half a ticks period.
        self._next_fetch_ms: int | None = get_ticks_ms()
        self._failures = 0

        self._run_fetch_ref = self._run_fetch

        self._tick_ref = self.tick
        if tick_scheduler is not None:
            tick_scheduler.register(self._tick_ref)

    def tick(self) -> None:
        if not self._enabled:
            return
        try:
            next_fetch_ms = self._next_fetch_ms
            if next_fetch_ms is not None and time.ticks_diff(self._get_ticks_ms(), next_fetch_ms) < 0:
                return
            self._next_fetch_ms = None
            self._http_client.try_fetch(self._run_fetch_ref)
        except Exception as exc:
            log_exception(self._tick_err_tag, exc)

    def _run_fetch(self) -> None:
        try:
            events = self._fetch_and_parse()
        except Exception as exc:
            self._failures += 1
            delay = self._backoff_delay()
            self._next_fetch_ms = time.ticks_add(self._get_ticks_ms(), delay)
            log_exception(
                "[%s] err (fail #%d, retry in %dms):" % (self._log_tag, self._failures, delay),
                exc,
            )
        else:
            self._events = events
            self._failures = 0
            self._next_fetch_ms = time.ticks_add(self._get_ticks_ms(), self._interval_ms)
            print("[%s] published %s events" % (self._log_tag, [len(e) for e in events]))

    def _backoff_delay(self) -> int:
        shift = self._failures - 1
        if shift < 0:
            shift = 0
        if shift > _MAX_BACKOFF_SHIFT:
            return self._backoff_max_ms
        delay = self._backoff_base_ms << shift
        return delay if delay < self._backoff_max_ms else self._backoff_max_ms

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

        The returned lists are published together; if it raises, nothing is published and
        the fetch is retried after a backoff.
        """
        raise NotImplementedError
