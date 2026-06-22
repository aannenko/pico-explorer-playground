"""Shared lifecycle for the network-backed calendar streams.

A subclass supplies only ``_fetch_and_parse`` (fallible: HTTP + parse, may raise
so the loop backs off) and its own config.  This base owns the long-lived
concerns that every network row shares: *when* to fetch (interval + exponential
backoff), the health/freshness the calendar polls (``status`` / ``generation``),
publishing the parsed snapshot (``_store``), and registering with the
``TickScheduler``.

The per-fetch *mechanics* live in ``FetchMachine``; the transient ``FetchState``
it drives exists only while a fetch attempt is active (from start through harvest
— including the brief hold in ``INITIAL`` while it waits on Wi-Fi or the gate) and
is dropped (GC'd) once harvested, so nothing fetch-related is pinned during the
long idle between fetches.  Disabled services never fetch and report ``DISABLED``.
"""

import time

from micropython import const

from scheduling.event import Event
from scheduling.stream import DISABLED, ERROR, FRESH, STALE
from services._fetch_machine import FetchMachine

_DEFAULT_BACKOFF_BASE_MS = const(5_000)
_DEFAULT_BACKOFF_MAX_MS = const(600_000)
_DEFAULT_ERROR_AFTER = const(3)
_MAX_BACKOFF_SHIFT = const(20)


class EventStreamService:
    """Drives one stream's fetch/parse/publish loop; the calendar reads it passively."""

    def __init__(
        self,
        wifi,  # has is_connected() -> bool
        coordinator,  # FetchCoordinator
        schedule,  # (callback, arg) -> None
        interval_ms: int,
        name: str,  # log tag, e.g. "weather" / "air"
        enabled: bool,
        clock=time.ticks_ms,  # () -> int
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
        self._name = name
        self._enabled = enabled
        self._clock = clock
        self._backoff_base_ms = backoff_base_ms
        self._backoff_max_ms = backoff_max_ms
        self._stale_after_ms = stale_after_ms if stale_after_ms is not None else 2 * interval_ms
        self._error_after_failures = error_after_failures

        self._events: list[Event] = []
        self._generation: int = 0

        # Persistent health, consulted by ``status`` between fetches.
        self._next_due: int = clock()  # due immediately at boot
        self._failures: int = 0
        self._last_success: int | None = None

        # Transient: a ``FetchState`` only while a fetch is in flight, else None.
        self._fetch = None  # FetchState | None
        self._fetcher_ref = self._fetch_and_parse  # cache the subclass bound method

        self._tick_ref = self.tick
        if tick_scheduler is not None:
            tick_scheduler.register(self._tick_ref)

    def tick(self) -> None:
        if not self._enabled:
            return
        try:
            self._advance()
        except Exception as exc:
            print("[%s] tick err:" % self._name, exc)

    def _advance(self) -> None:
        if self._fetch is None:
            if time.ticks_diff(self._clock(), self._next_due) < 0:
                return  # not due yet
            self._fetch = FetchMachine.start(
                self._fetcher_ref, self._wifi, self._schedule, self._coordinator
            )
        FetchMachine.tick(self._fetch)
        if FetchMachine.is_done(self._fetch):
            state = self._fetch
            self._fetch = None  # drop before harvest so a store error can't re-harvest
            self._harvest(state)

    def _harvest(self, state) -> None:
        now = self._clock()
        if state.error is None:
            self._failures = 0
            self._last_success = now
            self._next_due = time.ticks_add(now, self._interval_ms)
            try:
                self._store(state.result)
            except Exception as exc:
                print("[%s] store err:" % self._name, exc)
        else:
            self._failures += 1
            delay = self._backoff_delay()
            print(
                "[%s] err (fail #%d, retry in %dms):" % (self._name, self._failures, delay),
                state.error,
            )
            self._next_due = time.ticks_add(now, delay)

    def _backoff_delay(self) -> int:
        shift = self._failures - 1
        if shift < 0:
            shift = 0
        if shift > _MAX_BACKOFF_SHIFT:
            return self._backoff_max_ms
        delay = self._backoff_base_ms << shift
        return delay if delay < self._backoff_max_ms else self._backoff_max_ms

    def events_iter(self):  # -> Iterator[Event]
        return iter(self._events)

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def status(self) -> int:
        if not self._enabled:
            return DISABLED
        if self._failures >= self._error_after_failures:
            return ERROR
        if self._last_success is None:
            return STALE
        if time.ticks_diff(self._clock(), self._last_success) <= self._stale_after_ms:
            return FRESH
        return STALE

    def _store(self, events: list[Event]) -> None:
        # Infallible: publish the parsed snapshot and bump the generation the
        # calendar polls to refresh its window.
        self._events = events
        self._generation += 1
        print("[%s] published %d events (gen %d)" % (self._name, len(self._events), self._generation))

    def _fetch_and_parse(self) -> list[Event]:
        # Fallible: a subclass fetches + parses here; raising backs the loop off
        # without publishing.  Subclasses must override.
        raise NotImplementedError
