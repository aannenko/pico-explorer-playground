"""Tests for the shared fetch state machine."""

import pytest

from services._fetch_state import (
    BACKOFF,
    DUE,
    ERROR,
    FETCHING,
    FRESH,
    IDLE,
    STALE,
    FetchCoordinator,
    FetchState,
)
from services.http_client import (
    HttpConnectError,
    HttpParseError,
    HttpProtocolError,
    HttpStatusError,
    HttpTimeout,
)


class _FakeWifi:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected

    def is_connected(self) -> bool:
        return self.connected


class _FakeSchedule:
    """Deferred schedule: queues callbacks; ``run_all`` runs them on demand."""

    def __init__(self) -> None:
        self.queue: list[tuple] = []
        self.raise_next = False

    def __call__(self, callback, arg) -> None:
        if self.raise_next:
            raise RuntimeError("schedule queue full")
        self.queue.append((callback, arg))

    def run_all(self) -> None:
        pending, self.queue = self.queue, []
        for callback, arg in pending:
            callback(arg)


class _FakeFetcher:
    def __init__(self) -> None:
        self.result = {"ok": 1}
        self.exc: Exception | None = None
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.result


def _raising(_result) -> None:
    raise RuntimeError("on_success boom")


class _Harness:
    def __init__(
        self,
        interval_ms: int = 1000,
        connected: bool = True,
        coordinator: FetchCoordinator | None = None,
        on_success=None,
        **kwargs,
    ) -> None:
        self.clock_val = 0
        self.wifi = _FakeWifi(connected)
        self.schedule = _FakeSchedule()
        self.fetcher = _FakeFetcher()
        self.successes: list = []
        self.coord = coordinator or FetchCoordinator()
        self.fs = FetchState(
            self.fetcher,
            on_success or self.successes.append,
            self.wifi,
            self.coord,
            interval_ms,
            schedule=self.schedule,
            clock=lambda: self.clock_val,
            **kwargs,
        )

    def advance(self, ms: int) -> None:
        self.clock_val += ms


# ── Due gating ───────────────────────────────────────────────────────


def test_starts_due_and_schedules_fetch_when_connected():
    h = _Harness()

    h.fs.tick()

    assert h.fs.state == FETCHING
    assert h.coord.active is h.fs
    assert len(h.schedule.queue) == 1
    assert h.fetcher.calls == 0  # blocking work deferred to scheduled callback


def test_not_due_stays_idle():
    h = _Harness(interval_ms=1000)
    h.fs.tick()
    h.schedule.run_all()  # success at clock 0 → next_due = 1000

    h.advance(999)
    h.fs.tick()

    assert h.fs.state == IDLE
    assert h.fetcher.calls == 1


def test_becomes_due_after_interval():
    h = _Harness(interval_ms=1000)
    h.fs.tick()
    h.schedule.run_all()

    h.advance(1000)
    h.fs.tick()

    assert h.fs.state == FETCHING
    assert h.fetcher.calls == 1  # still deferred until run_all


# ── WiFi gate ────────────────────────────────────────────────────────


def test_wifi_down_holds_in_due_without_fetching():
    h = _Harness(connected=False)

    for _ in range(5):
        h.fs.tick()

    assert h.fs.state == DUE
    assert h.fetcher.calls == 0
    assert h.schedule.queue == []
    assert h.coord.active is None  # did not acquire the coordinator
    assert h.fs._failures == 0  # WiFi-down is not a failure → no backoff


def test_fetches_once_wifi_returns():
    h = _Harness(connected=False)
    h.fs.tick()
    assert h.fs.state == DUE

    h.wifi.connected = True
    h.fs.tick()

    assert h.fs.state == FETCHING


# ── Single-active invariant ──────────────────────────────────────────


def test_only_one_service_fetches_at_a_time():
    coord = FetchCoordinator()
    a = _Harness(coordinator=coord)
    b = _Harness(coordinator=coord)

    a.fs.tick()
    b.fs.tick()

    assert a.fs.state == FETCHING
    assert b.fs.state == DUE
    assert coord.active is a.fs
    assert b.fetcher.calls == 0

    a.schedule.run_all()
    assert a.fs.state == IDLE
    assert coord.active is None

    b.fs.tick()
    assert b.fs.state == FETCHING


# ── FETCHING persistence ─────────────────────────────────────────────


def test_fetching_persists_until_scheduled_callback_runs():
    h = _Harness()
    h.fs.tick()

    h.fs.tick()
    h.fs.tick()

    assert h.fs.state == FETCHING
    assert len(h.schedule.queue) == 1  # not re-scheduled
    assert h.fetcher.calls == 0


# ── Success path ─────────────────────────────────────────────────────


def test_success_invokes_callback_and_returns_to_idle():
    h = _Harness(interval_ms=1000)
    h.fs.tick()
    h.advance(50)
    h.schedule.run_all()

    assert h.successes == [h.fetcher.result]
    assert h.fs.state == IDLE
    assert h.fs.status == FRESH
    assert h.coord.active is None
    assert h.fetcher.calls == 1


def test_on_success_exception_is_swallowed():
    h = _Harness(on_success=_raising)
    h.fs.tick()
    h.schedule.run_all()

    assert h.fs.state == IDLE
    assert h.fs.status == FRESH  # success still recorded
    assert h.coord.active is None  # coordinator released


# ── Failure / backoff ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "exc",
    [
        HttpTimeout("t"),
        HttpConnectError("c"),
        HttpStatusError(500),
        HttpParseError("p"),
        HttpProtocolError("x"),
    ],
)
def test_any_fetch_error_enters_backoff(exc):
    h = _Harness()
    h.fetcher.exc = exc
    h.fs.tick()
    h.schedule.run_all()

    assert h.fs.state == BACKOFF
    assert h.fs._failures == 1
    assert h.coord.active is None  # released even on failure


def test_backoff_delays_then_retries():
    h = _Harness(backoff_base_ms=100)
    h.fetcher.exc = HttpTimeout("t")
    h.fs.tick()
    h.schedule.run_all()  # fail at clock 0 → next_due = 100
    assert h.fs.state == BACKOFF

    h.advance(99)
    h.fs.tick()
    assert h.fs.state == BACKOFF  # still before next_due

    h.advance(1)
    h.fs.tick()
    assert h.fs.state == FETCHING  # backoff elapsed → retry


def test_backoff_grows_exponentially_and_caps():
    h = _Harness(backoff_base_ms=100, backoff_max_ms=300, error_after_failures=99)

    h.fs._failures = 1
    assert h.fs._backoff_delay() == 100
    h.fs._failures = 2
    assert h.fs._backoff_delay() == 200
    h.fs._failures = 3
    assert h.fs._backoff_delay() == 300  # 400 capped to 300
    h.fs._failures = 10
    assert h.fs._backoff_delay() == 300


def test_success_after_failure_resets_failures():
    h = _Harness(backoff_base_ms=0)
    h.fetcher.exc = HttpTimeout("t")
    h.fs.tick()
    h.schedule.run_all()
    assert h.fs._failures == 1

    h.fetcher.exc = None
    h.fs.tick()  # BACKOFF (next_due=0) → DUE → FETCHING
    h.schedule.run_all()

    assert h.fs._failures == 0
    assert h.fs.status == FRESH


def test_schedule_queue_full_releases_coordinator():
    h = _Harness()
    h.schedule.raise_next = True

    h.fs.tick()

    assert h.fs.state == DUE
    assert h.coord.active is None  # rolled back so next tick can retry


# ── Status model ─────────────────────────────────────────────────────


def test_status_stale_before_first_success():
    h = _Harness()
    assert h.fs.status == STALE


def test_status_fresh_then_stale_after_cutoff():
    h = _Harness(interval_ms=1000)  # stale_after = 2000
    h.fs.tick()
    h.schedule.run_all()  # success at clock 0
    assert h.fs.status == FRESH

    h.advance(2000)
    assert h.fs.status == FRESH  # boundary is inclusive

    h.advance(1)
    assert h.fs.status == STALE


def test_status_error_after_threshold_failures():
    h = _Harness(backoff_base_ms=0, error_after_failures=2)
    h.fetcher.exc = HttpConnectError("c")

    h.fs.tick()
    h.schedule.run_all()  # fail 1
    assert h.fs.status != ERROR

    h.fs.tick()  # next_due=0 → retry
    h.schedule.run_all()  # fail 2
    assert h.fs.status == ERROR


def test_coordinator_release_only_by_owner():
    coord = FetchCoordinator()
    a = object()
    b = object()
    assert coord.try_acquire(a) is True
    assert coord.try_acquire(b) is False

    coord.release(b)  # non-owner must not release
    assert coord.active is a

    coord.release(a)
    assert coord.active is None
