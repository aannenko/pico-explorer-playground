"""End-to-end test of the network substrate via the stub service.

Drives the full path a real network row uses: tick -> FetchMachine -> schedule
(fetch) -> harvest (parse+store) -> generation bump -> EventWindow refresh ->
what the renderer reads (get_visible / status).

Harvest model: a fetch's result lands in the FetchState during ``run_all()`` but
is published on the *next* ``tick()`` (the harvest), so published-state asserts
(generation / visible / FRESH / ERROR) come after an extra ``tick()``.
"""

import pytest

from scheduling.event_window import build_event_windows
from scheduling.stream import DISABLED, ERROR, FRESH, STALE, Stream
from _stub_service import StubService
from services._fetch_machine import FETCHING, INITIAL, FetchCoordinator
from services.http_client import HttpConnectError


class _FakeWifi:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected

    def is_connected(self) -> bool:
        return self.connected


class _FakeSchedule:
    """Deferred schedule: queues callbacks; ``run_all`` runs them on demand."""

    def __init__(self) -> None:
        self.queue: list[tuple] = []

    def __call__(self, callback, arg) -> None:
        self.queue.append((callback, arg))

    def run_all(self) -> None:
        pending, self.queue = self.queue, []
        for callback, arg in pending:
            callback(arg)


def _payload(*specs) -> dict:
    """Build a stub payload from (name, start, dur[, color]) tuples."""
    events = []
    for spec in specs:
        name, start, dur = spec[0], spec[1], spec[2]
        e = {"name": name, "start": start, "dur": dur}
        if len(spec) > 3:
            e["color"] = spec[3]
        events.append(e)
    return {"events": events}


class _Harness:
    def __init__(self, interval_ms: int = 1000, connected: bool = True, enabled: bool = True) -> None:
        self.clock_val = 0
        self.wifi = _FakeWifi(connected)
        self.schedule = _FakeSchedule()
        self.coord = FetchCoordinator()
        self.payload = _payload(("A", 0, 100))
        self.fetch_calls = 0
        self.raise_exc = None
        self.service = StubService(
            self._fetcher,
            self.wifi,
            self.coord,
            interval_ms,
            schedule=self.schedule,
            clock=lambda: self.clock_val,
            enabled=enabled,
        )
        stream = Stream(
            self.service.events_iter(),
            events_fn=self.service.events_iter,
            generation_fn=lambda: self.service.generation,
            status_fn=lambda: self.service.status,
        )
        self.window = build_event_windows(((1, 2),), [stream])[0]

    def _fetcher(self) -> dict:
        self.fetch_calls += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.payload

    def advance(self, ms: int) -> None:
        self.clock_val += ms

    def fetch_and_harvest(self) -> None:
        """One full cycle: dispatch (tick), run the deferred fetch, harvest (tick)."""
        self.service.tick()
        self.schedule.run_all()
        self.service.tick()

    def visible_names(self) -> list[str]:
        return [e.name for e, _ in self.window.get_visible(0, 10_000)]


def test_disabled_service_never_fetches_and_reports_disabled():
    h = _Harness(enabled=False)

    for _ in range(5):
        h.service.tick()

    assert h.fetch_calls == 0
    assert h.service.status == DISABLED
    assert h.window.status() == DISABLED
    assert h.visible_names() == []


def test_fetch_flows_through_to_visible_events():
    h = _Harness()

    h.service.tick()  # INITIAL -> FETCHING, fetch deferred
    assert h.fetch_calls == 0  # blocking work not run inline
    assert h.window.status() == STALE  # no data yet -> glyph

    h.schedule.run_all()  # _do_fetch: fetch + parse, result staged (not yet published)
    assert h.fetch_calls == 1
    assert h.service.generation == 0  # harvest hasn't run yet

    h.service.tick()  # harvest: store, generation 0 -> 1
    assert h.service.generation == 1
    assert h.visible_names() == ["A"]
    assert h.window.status() == FRESH  # fresh -> no glyph


def test_second_fetch_refreshes_the_window():
    h = _Harness(interval_ms=1000)
    h.fetch_and_harvest()
    assert h.visible_names() == ["A"]

    h.payload = _payload(("B", 0, 100), ("C", 200, 100))
    h.advance(1000)  # next interval due
    h.fetch_and_harvest()

    assert h.service.generation == 2
    assert h.visible_names() == ["B", "C"]


def test_wifi_down_holds_without_fetching():
    h = _Harness(connected=False)

    for _ in range(3):
        h.service.tick()

    assert h.fetch_calls == 0
    assert h.schedule.queue == []
    assert h.service.status == STALE
    assert h.visible_names() == []


def test_http_error_backs_off_and_keeps_prior_snapshot():
    h = _Harness(interval_ms=1000)
    h.fetch_and_harvest()  # first fetch ok -> ["A"]
    assert h.visible_names() == ["A"]

    h.raise_exc = HttpConnectError("down")
    h.advance(1000)
    h.fetch_and_harvest()  # fetch raises -> backoff, generation unchanged

    assert h.service._failures == 1  # one failure recorded -> backing off
    assert h.service.generation == 1  # no bump on failure
    assert h.visible_names() == ["A"]  # prior snapshot retained
    # A single failure with a still-recent success stays FRESH on purpose:
    # one transient blip shouldn't flip the row to a stale/error glyph.
    assert h.service.status == FRESH


def test_malformed_payload_backs_off_and_emits_nothing():
    h = _Harness()
    h.payload = {"unexpected": "shape"}  # missing "events" -> KeyError in parse

    h.fetch_and_harvest()

    assert h.fetch_calls == 1
    assert h.service._failures == 1  # parse failure counts as a fetch failure
    assert h.service.generation == 0  # parse failure -> no store
    assert h.visible_names() == []


def test_error_status_after_repeated_failures():
    h = _Harness(interval_ms=1000)
    h.raise_exc = HttpConnectError("down")

    # Default error threshold is 3 consecutive failures.  Each failure is
    # recorded on the harvest tick (inside fetch_and_harvest), so the loop
    # advances past the (capped) backoff and runs a full cycle each round.
    for _ in range(3):
        h.advance(700_000)
        h.fetch_and_harvest()

    assert h.service.status == ERROR
    assert h.window.status() == ERROR


def test_backoff_grows_exponentially_and_caps():
    h = _Harness()
    s = h.service
    s._backoff_base_ms = 100
    s._backoff_max_ms = 300

    s._failures = 1
    assert s._backoff_delay() == 100
    s._failures = 2
    assert s._backoff_delay() == 200
    s._failures = 3
    assert s._backoff_delay() == 300  # 400 capped to 300
    s._failures = 10
    assert s._backoff_delay() == 300


def test_status_goes_stale_after_cutoff():
    h = _Harness(interval_ms=1000)  # stale_after = 2 * interval = 2000
    h.fetch_and_harvest()  # success at clock 0
    assert h.service.status == FRESH

    h.advance(2000)  # boundary is inclusive
    assert h.service.status == FRESH

    h.advance(1)
    assert h.service.status == STALE


def test_store_exception_is_swallowed_but_success_recorded():
    h = _Harness()

    def boom(_events):
        raise RuntimeError("store blew up")

    h.service._store = boom
    h.fetch_and_harvest()

    # The store error is swallowed (health is updated *before* the store call),
    # so the fetch still counts as a success, but nothing gets published.
    assert h.service.status == FRESH
    assert h.service._failures == 0
    assert h.service.generation == 0  # store never completed its bump


def test_success_after_failure_resets_failures():
    h = _Harness(interval_ms=1000)
    h.raise_exc = HttpConnectError("down")
    h.fetch_and_harvest()  # one failure
    assert h.service._failures == 1

    h.raise_exc = None  # recovery
    h.advance(700_000)  # past the (capped) backoff so the retry is due
    h.fetch_and_harvest()  # success

    assert h.service._failures == 0  # a success clears the failure count
    assert h.service.status == FRESH


def test_not_due_does_not_fetch_before_interval():
    h = _Harness(interval_ms=1000)
    h.fetch_and_harvest()  # success at clock 0 -> next due at 1000
    assert h.fetch_calls == 1
    assert h.service.generation == 1

    h.advance(999)  # still before the interval elapses
    h.service.tick()

    assert h.fetch_calls == 1  # no second fetch yet
    assert h.service.generation == 1
    assert h.schedule.queue == []  # nothing dispatched


def test_only_one_stub_fetches_under_shared_coordinator():
    coord = FetchCoordinator()
    wifi = _FakeWifi(True)
    sched_a, sched_b = _FakeSchedule(), _FakeSchedule()
    a = StubService(lambda: _payload(("A", 0, 100)), wifi, coord, 1000, schedule=sched_a, clock=lambda: 0)
    b = StubService(lambda: _payload(("B", 0, 100)), wifi, coord, 1000, schedule=sched_b, clock=lambda: 0)

    a.tick()
    b.tick()

    assert a._fetch.stage == FETCHING
    assert b._fetch.stage == INITIAL  # held by the single-active invariant
