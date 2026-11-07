import time

from micropython import const

from scheduling.event import Event
from scheduling.stream import DISABLED, ERROR, FRESH, STALE
from services._fetch_machine import FetchCoordinator, FetchMachine, FetchState
from utilities.log import log_exception

_DEFAULT_BACKOFF_BASE_MS = const(5_000)
_DEFAULT_BACKOFF_MAX_MS = const(600_000)
_DEFAULT_ERROR_AFTER = const(3)
_MAX_BACKOFF_SHIFT = const(20)


class EventStreamService:
    """Fetch/parse/publish loop for one network-backed stream, with retry backoff.

    ``stale_after_ms`` defaults to twice ``interval_ms``.

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
        get_ticks_ms=time.ticks_ms,  # () -> int
        tick_scheduler=None,
        backoff_base_ms: int = _DEFAULT_BACKOFF_BASE_MS,
        backoff_max_ms: int = _DEFAULT_BACKOFF_MAX_MS,
        stale_after_ms: int | None = None,
        error_after_failures: int = _DEFAULT_ERROR_AFTER,
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
        self._stale_after_ms = stale_after_ms if stale_after_ms is not None else 2 * interval_ms
        self._error_after_failures = error_after_failures

        self._events: list[Event] = []
        self._generation = 0

        self._next_fetch_ms = get_ticks_ms()
        self._failures = 0
        self._last_success_ms: int | None = None

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

    def _harvest(self, state) -> None:
        now_ms = self._get_ticks_ms()
        if state.error is None:
            self._failures = 0
            self._last_success_ms = now_ms
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

    def events_iter(self):  # -> Iterator[Event]
        """Return an iterator over the latest published events."""
        return iter(self._events)

    @property
    def generation(self) -> int:
        """Number of event snapshots published so far."""
        return self._generation

    @property
    def status(self) -> int:
        """Freshness code: FRESH, STALE, ERROR or DISABLED.

        ERROR after ``error_after_failures`` failed fetches in a row; otherwise FRESH
        within ``stale_after_ms`` of the last success, and STALE if there is none or
        it is older.
        """
        if not self._enabled:
            return DISABLED
        if self._failures >= self._error_after_failures:
            return ERROR
        if self._last_success_ms is None:
            return STALE
        if time.ticks_diff(self._get_ticks_ms(), self._last_success_ms) <= self._stale_after_ms:
            return FRESH
        return STALE

    def _store(self, events: list[Event]) -> None:
        self._events = events
        self._generation += 1
        print("[%s] published %d events (gen %d)" % (self._log_tag, len(self._events), self._generation))

    def _fetch_and_parse(self) -> list[Event]:
        """Fetch and parse the latest events; subclasses must override.

        The returned list is published; if it raises, nothing is published and
        the fetch is retried after a backoff.
        """
        raise NotImplementedError
