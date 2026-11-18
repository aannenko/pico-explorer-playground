import time

from micropython import const

from scheduling.event import Event
from services.fetch_machine import FetchCoordinator, FetchMachine, FetchState
from services.tick_scheduler import TickScheduler
from utilities.log import log_exception

_DEFAULT_BACKOFF_BASE_MS = const(5_000)
_DEFAULT_BACKOFF_MAX_MS = const(600_000)
_MAX_BACKOFF_SHIFT = const(20)


class EventStreamService:
    """Fetch/parse/publish loop for ``stream_count`` network-backed streams, with retry backoff.

    One fetch publishes every stream at once.

    A ``FetchState`` lives only from ``FetchMachine.start`` to harvest, so no
    attempt's state stays pinned during the long idle between fetches.
    """

    def __init__(
        self,
        wifi,  # has is_connected() -> bool
        coordinator: FetchCoordinator,
        schedule,  # (callback, arg) -> None
        interval_ms: int,
        log_tag: str,
        enabled: bool,
        stream_count: int = 1,
        get_ticks_ms=time.ticks_ms,  # () -> int
        tick_scheduler: TickScheduler | None = None,
        backoff_base_ms: int = _DEFAULT_BACKOFF_BASE_MS,
        backoff_max_ms: int = _DEFAULT_BACKOFF_MAX_MS,
    ) -> None:
        self._wifi = wifi
        self._coordinator = coordinator
        self._schedule = schedule
        self._interval_ms = interval_ms
        self._log_tag = log_tag
        self._tick_err_tag = "[%s] tick err:" % log_tag
        self._store_err_tag = "[%s] store err:" % log_tag
        self._enabled = enabled
        self._get_ticks_ms = get_ticks_ms
        self._backoff_base_ms = backoff_base_ms
        self._backoff_max_ms = backoff_max_ms

        self._events: tuple[list[Event], ...] = ([],) * stream_count
        self._generation = 0

        self._next_fetch_ms = get_ticks_ms()
        self._failures = 0

        self._fetch_state: FetchState | None = None
        self._fetcher_ref = self._fetch_and_parse

        self._tick_ref = self.tick
        if tick_scheduler is not None:
            tick_scheduler.register(self._tick_ref)

    def tick(self) -> None:
        if not self._enabled:
            return
        try:
            self._advance()
        except Exception as exc:
            log_exception(self._tick_err_tag, exc)

    def _advance(self) -> None:
        if self._fetch_state is None:
            if time.ticks_diff(self._get_ticks_ms(), self._next_fetch_ms) < 0:
                return
            self._fetch_state = FetchMachine.start(
                self._fetcher_ref, self._wifi, self._schedule, self._coordinator
            )
        FetchMachine.tick(self._fetch_state)
        if FetchMachine.is_done(self._fetch_state):
            state = self._fetch_state
            self._fetch_state = None  # drop before harvest so a raising harvest can't repeat
            self._harvest(state)

    def _harvest(self, state: FetchState) -> None:
        now_ms = self._get_ticks_ms()
        if state.error is None:
            self._failures = 0
            self._next_fetch_ms = time.ticks_add(now_ms, self._interval_ms)
            try:
                self._store(state.result)
            except Exception as exc:
                log_exception(self._store_err_tag, exc)
        else:
            self._failures += 1
            delay = self._backoff_delay()
            print(
                "[%s] err (fail #%d, retry in %dms):" % (self._log_tag, self._failures, delay),
                state.error,
            )
            self._next_fetch_ms = time.ticks_add(now_ms, delay)

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

    def _store(self, events: tuple[list[Event], ...]) -> None:
        self._events = events
        self._generation += 1
        print("[%s] published %s events (gen %d)" % (self._log_tag, [len(e) for e in events], self._generation))

    def _fetch_and_parse(self) -> tuple[list[Event], ...]:
        """Fetch and parse the latest events, one list per stream; subclasses must override.

        The returned lists are published together; if it raises, nothing is published and
        the fetch is retried after a backoff.
        """
        raise NotImplementedError
