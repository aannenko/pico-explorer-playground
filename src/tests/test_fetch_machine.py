"""Tests for the stateless fetch machine + the single-in-flight gate.

Scheduling / backoff / freshness now live on ``EventStreamService`` and are
covered end-to-end in ``test_stub_service.py``; this file covers only the
``FetchMachine`` transition mechanics and the ``FetchCoordinator`` gate.
"""

import pytest

from services._fetch_machine import (
    DONE,
    FAILED,
    FETCHING,
    INITIAL,
    FetchCoordinator,
    FetchMachine,
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


def _start(wifi=None, coord=None, schedule=None, fetcher=None):
    """Build a fresh FetchState plus its collaborators (all fakes by default)."""
    wifi = wifi or _FakeWifi()
    coord = coord or FetchCoordinator()
    schedule = schedule or _FakeSchedule()
    fetcher = fetcher or _FakeFetcher()
    state = FetchMachine.start(fetcher, wifi, schedule, coord)
    return state, wifi, coord, schedule, fetcher


# ── FetchCoordinator (busy-flag gate) ────────────────────────────────


def test_coordinator_acquire_release_cycle():
    c = FetchCoordinator()
    assert c.busy is False
    assert c.try_acquire() is True
    assert c.busy is True
    assert c.try_acquire() is False  # already held
    c.release()
    assert c.busy is False
    assert c.try_acquire() is True  # reusable after release


# ── start ────────────────────────────────────────────────────────────


def test_start_returns_initial_state():
    state, _, _, _, _ = _start()
    assert isinstance(state, FetchState)
    assert state.stage == INITIAL
    assert state.result is None
    assert state.error is None
    assert FetchMachine.is_done(state) is False


# ── tick: dispatch gating ────────────────────────────────────────────


def test_tick_dispatches_when_connected_and_gate_free():
    state, _, coord, sched, fetcher = _start()

    FetchMachine.tick(state)

    assert state.stage == FETCHING
    assert coord.busy is True        # gate acquired
    assert len(sched.queue) == 1     # _do_fetch scheduled
    assert fetcher.calls == 0        # blocking work deferred to the callback


def test_tick_holds_initial_while_wifi_down():
    wifi = _FakeWifi(connected=False)
    state, _, coord, sched, fetcher = _start(wifi=wifi)

    for _ in range(5):
        FetchMachine.tick(state)

    assert state.stage == INITIAL
    assert coord.busy is False       # never acquired the gate
    assert sched.queue == []
    assert fetcher.calls == 0


def test_tick_fetches_once_wifi_returns():
    wifi = _FakeWifi(connected=False)
    state, _, _, _, _ = _start(wifi=wifi)

    FetchMachine.tick(state)
    assert state.stage == INITIAL

    wifi.connected = True
    FetchMachine.tick(state)
    assert state.stage == FETCHING


def test_tick_holds_initial_when_gate_busy():
    coord = FetchCoordinator()
    coord.try_acquire()  # a peer fetch holds the gate
    state, _, _, sched, fetcher = _start(coord=coord)

    FetchMachine.tick(state)

    assert state.stage == INITIAL    # blocked by the single-active invariant
    assert sched.queue == []
    assert fetcher.calls == 0


def test_tick_is_idempotent_while_fetching():
    state, _, _, sched, _ = _start()

    FetchMachine.tick(state)
    FetchMachine.tick(state)
    FetchMachine.tick(state)

    assert state.stage == FETCHING
    assert len(sched.queue) == 1     # not re-scheduled


def test_schedule_failure_rolls_back_to_initial_and_releases():
    sched = _FakeSchedule()
    sched.raise_next = True
    state, _, coord, _, _ = _start(schedule=sched)

    FetchMachine.tick(state)

    assert state.stage == INITIAL    # rolled back so the next tick can retry
    assert coord.busy is False       # gate released


# ── _do_fetch: outcome ───────────────────────────────────────────────


def test_do_fetch_success_sets_done_and_releases():
    state, _, coord, sched, fetcher = _start()

    FetchMachine.tick(state)
    sched.run_all()

    assert state.stage == DONE
    assert state.result is fetcher.result
    assert state.error is None
    assert coord.busy is False       # gate released on success
    assert FetchMachine.is_done(state) is True


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
def test_do_fetch_failure_sets_failed_and_releases(exc):
    fetcher = _FakeFetcher()
    fetcher.exc = exc
    state, _, coord, sched, _ = _start(fetcher=fetcher)

    FetchMachine.tick(state)
    sched.run_all()

    assert state.stage == FAILED
    assert state.error is exc
    assert state.result is None
    assert coord.busy is False       # gate released even on failure
    assert FetchMachine.is_done(state) is True
