"""Shared multi-tick fetch state machine for network-backed services.

A ``FetchState`` rides ``TickScheduler`` (one tiny step per tick) and runs the
blocking work (DNS + TLS + JSON parse) inside a ``micropython.schedule``
callback so a tick never blocks the UI.  All services share one
``FetchCoordinator`` so only a single fetch is ever in flight.
"""

import time

import micropython
from micropython import const

from scheduling.stream import DISABLED, ERROR, FRESH, STALE

# Machine states.
IDLE = const(0)
DUE = const(1)
FETCHING = const(2)
BACKOFF = const(3)

# Freshness codes (FRESH/STALE/ERROR/DISABLED) are re-exported from
# scheduling.stream above so the renderer and the state machine share one
# definition.  DISABLED is set by a service with nothing to fetch (e.g.
# missing config); the machine never sets it.

_DEFAULT_BACKOFF_BASE_MS = const(5_000)
_DEFAULT_BACKOFF_MAX_MS = const(600_000)
_DEFAULT_ERROR_AFTER = const(3)
_MAX_BACKOFF_SHIFT = const(20)


class FetchCoordinator:
    """Enforces the single-in-flight-fetch invariant across all services."""

    def __init__(self) -> None:
        self._active = None

    @property
    def active(self):  # owner | None
        return self._active

    def try_acquire(self, owner) -> bool:
        if self._active is None or self._active is owner:
            self._active = owner
            return True
        return False

    def release(self, owner) -> None:
        if self._active is owner:
            self._active = None


class FetchState:
    """Drives one service's fetch loop; advance once per scheduler tick."""

    def __init__(
        self,
        fetcher,  # () -> result; may raise (e.g. HttpError)
        on_success,  # (result) -> None
        wifi,  # has is_connected() -> bool
        coordinator: FetchCoordinator,
        interval_ms: int,
        schedule=micropython.schedule,  # (callback, arg) -> None
        clock=time.ticks_ms,  # () -> int
        backoff_base_ms: int = _DEFAULT_BACKOFF_BASE_MS,
        backoff_max_ms: int = _DEFAULT_BACKOFF_MAX_MS,
        stale_after_ms: int | None = None,
        error_after_failures: int = _DEFAULT_ERROR_AFTER,
        name: str = "fetch",  # log label, to tell services apart
    ) -> None:
        self._fetcher = fetcher
        self._on_success = on_success
        self._wifi = wifi
        self._coordinator = coordinator
        self._interval_ms = interval_ms
        self._schedule = schedule
        self._clock = clock
        self._backoff_base_ms = backoff_base_ms
        self._backoff_max_ms = backoff_max_ms
        self._stale_after_ms = stale_after_ms if stale_after_ms is not None else 2 * interval_ms
        self._error_after_failures = error_after_failures
        self._name = name

        self._state: int = IDLE
        self._next_due: int = clock()  # due immediately at boot
        self._last_success: int | None = None
        self._failures: int = 0
        self._do_fetch_ref = self._do_fetch

    @property
    def state(self) -> int:
        return self._state

    @property
    def status(self) -> int:
        if self._failures >= self._error_after_failures:
            return ERROR
        if self._last_success is None:
            return STALE
        if time.ticks_diff(self._clock(), self._last_success) <= self._stale_after_ms:
            return FRESH
        return STALE

    def tick(self) -> None:
        try:
            self._advance()
        except Exception as exc:
            print("[%s] tick err:" % self._name, exc)

    def _advance(self) -> None:
        now = self._clock()

        if self._state == IDLE or self._state == BACKOFF:
            if time.ticks_diff(now, self._next_due) < 0:
                return
            self._state = DUE

        if self._state == DUE:
            if not self._wifi.is_connected():
                return  # hold in DUE; re-poll cheaply next tick
            if not self._coordinator.try_acquire(self):
                return  # another fetch in flight; stay DUE
            self._state = FETCHING
            try:
                self._schedule(self._do_fetch_ref, 0)
            except Exception:
                self._coordinator.release(self)
                self._state = DUE

    def _do_fetch(self, _arg) -> None:
        # Runs off the tick via schedule(); the blocking work lives here.
        try:
            result = self._fetcher()
        except Exception as exc:
            self._on_failure(exc)
        else:
            self._on_ok(result)
        finally:
            self._coordinator.release(self)

    def _on_ok(self, result) -> None:
        self._failures = 0
        self._last_success = self._clock()
        self._next_due = time.ticks_add(self._last_success, self._interval_ms)
        self._state = IDLE
        try:
            self._on_success(result)
        except Exception as exc:
            print("[%s] on_success err:" % self._name, exc)

    def _on_failure(self, exc) -> None:
        self._failures += 1
        delay = self._backoff_delay()
        print("[%s] err (fail #%d, retry in %dms):" % (self._name, self._failures, delay), exc)
        self._next_due = time.ticks_add(self._clock(), delay)
        self._state = BACKOFF

    def _backoff_delay(self) -> int:
        shift = self._failures - 1
        if shift < 0:
            shift = 0
        if shift > _MAX_BACKOFF_SHIFT:
            return self._backoff_max_ms
        delay = self._backoff_base_ms << shift
        return delay if delay < self._backoff_max_ms else self._backoff_max_ms
