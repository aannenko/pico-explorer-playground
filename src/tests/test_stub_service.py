import pytest

from _stub_service import StubService
from conftest import make_timer_factory
import services._event_stream_service as event_stream_service
from services.http_client import HttpClient, HttpConnectError
from services.tick_scheduler import TickScheduler


class _FakeWifi:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected

    def is_connected(self) -> bool:
        return self.connected


class _FakeSchedule:
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
    def __init__(
        self, interval_ms: int = 1000, connected: bool = True, enabled: bool = True, start_ms: int = 0
    ) -> None:
        self.clock_val = start_ms
        self.wifi = _FakeWifi(connected)
        self.schedule = _FakeSchedule()
        self.http_client = HttpClient(self.wifi, self.schedule, timeout_sec=7)
        self.payload = _payload(("A", 0, 100))
        self.fetch_calls = 0
        self.raise_exc = None
        self.service = StubService(
            self._fetcher,
            self.http_client,
            interval_ms,
            get_ticks_ms=lambda: self.clock_val,
            enabled=enabled,
        )
        self.stream = self.service.build_streams()[0]

    def _fetcher(self) -> dict:
        self.fetch_calls += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.payload

    def advance(self, ms: int) -> None:
        self.clock_val += ms

    def fetch(self) -> None:
        self.service.tick()
        self.schedule.run_all()

    def visible_names(self) -> list[str]:
        return [e.label for e in self.stream(0)]


def test_disabled_service_never_fetches() -> None:
    h = _Harness(enabled=False)

    for _ in range(5):
        h.service.tick()

    assert h.fetch_calls == 0
    assert h.schedule.queue == []
    assert h.visible_names() == []


def test_fetch_publishes_in_callback_without_harvest_tick() -> None:
    h = _Harness()

    h.service.tick()
    assert h.fetch_calls == 0
    assert h.visible_names() == []
    assert len(h.schedule.queue) == 1

    h.schedule.run_all()
    assert h.fetch_calls == 1
    assert h.visible_names() == ["A"]


def test_second_fetch_replaces_snapshot_seen_by_existing_getter() -> None:
    h = _Harness(interval_ms=1000)
    h.fetch()
    previous = h.stream(0)

    h.payload = _payload(("B", 0, 100), ("C", 200, 100))
    h.advance(1000)
    h.fetch()

    assert h.visible_names() == ["B", "C"]
    assert [e.label for e in previous] == ["A"]
    assert h.stream(0) is not previous


def test_wifi_down_holds_without_fetching() -> None:
    h = _Harness(connected=False)

    for _ in range(3):
        h.service.tick()

    assert h.fetch_calls == 0
    assert h.schedule.queue == []
    assert h.visible_names() == []


@pytest.mark.parametrize("failure", ["fetch", "parse"], ids=["fetch-error", "parse-error"])
def test_failure_keeps_prior_snapshot_until_retry_deadline(failure: str) -> None:
    h = _Harness(interval_ms=1000)
    h.fetch()
    previous = h.stream(0)
    h.service._backoff_base_ms = 100
    h.service._backoff_max_ms = 300

    if failure == "fetch":
        h.raise_exc = HttpConnectError("down")
    else:
        h.payload = {"unexpected": "shape"}
    h.advance(1000)
    h.fetch()

    assert h.service._failures == 1
    assert h.stream(0) is previous
    assert h.visible_names() == ["A"]

    h.raise_exc = None
    h.payload = _payload(("B", 0, 100))
    h.advance(99)
    h.service.tick()
    assert h.schedule.queue == []
    assert h.fetch_calls == 2

    h.advance(1)
    h.fetch()
    assert h.fetch_calls == 3
    assert h.visible_names() == ["B"]
    assert h.service._failures == 0


def test_malformed_payload_backs_off_and_emits_nothing() -> None:
    h = _Harness()
    h.payload = {"unexpected": "shape"}

    h.fetch()

    assert h.fetch_calls == 1
    assert h.service._failures == 1
    assert h.visible_names() == []


def test_backoff_grows_exponentially_and_caps() -> None:
    h = _Harness()
    s = h.service
    s._backoff_base_ms = 100
    s._backoff_max_ms = 300

    h.raise_exc = HttpConnectError("down")

    for failure_count, delay_ms in enumerate((100, 200, 300, 300), start=1):
        h.fetch()
        assert s._failures == failure_count
        h.advance(delay_ms - 1)
        s.tick()
        assert h.schedule.queue == []
        assert h.fetch_calls == failure_count
        h.advance(1)

    s._failures = 30
    assert s._backoff_delay() == 300


def test_queue_full_is_logged_and_later_tick_retries(capsys) -> None:
    h = _Harness()
    h.schedule.raise_next = True

    h.service.tick()

    assert h.schedule.queue == []
    assert h.fetch_calls == 0
    out = capsys.readouterr().out
    assert "[stub] tick err:" in out
    assert "RuntimeError: schedule queue full" in out

    h.schedule.raise_next = False
    h.fetch()
    assert h.visible_names() == ["A"]
    assert h.fetch_calls == 1


def test_queue_full_service_does_not_skip_following_scheduler_subscriber(capsys) -> None:
    h = _Harness()
    h.schedule.raise_next = True
    timer_factory, _ = make_timer_factory()
    scheduler = TickScheduler(schedule=h.schedule, timer_factory=timer_factory)
    calls = []
    scheduler.register(h.service.tick)
    scheduler.register(lambda: calls.append("following"))

    scheduler._tick(0)

    assert calls == ["following"]
    assert h.schedule.queue == []
    assert h.fetch_calls == 0
    assert "RuntimeError: schedule queue full" in capsys.readouterr().out

    h.schedule.raise_next = False
    scheduler._tick(0)
    h.schedule.run_all()
    assert calls == ["following", "following"]
    assert h.visible_names() == ["A"]


def test_raising_success_print_preserves_publication_deadline_and_releases_gate(monkeypatch) -> None:
    h = _Harness()
    h.raise_exc = HttpConnectError("down")
    h.fetch()
    h.advance(5000)
    h.raise_exc = None
    h.payload = _payload(("B", 0, 100))
    peer = StubService(lambda: _payload(("C", 0, 100)), h.http_client, 1000, lambda: h.clock_val)

    def print_publication(message: str) -> None:
        assert h.visible_names() == ["B"]
        assert h.service._failures == 0
        assert h.service._next_fetch_ms == 6000
        h.service.tick()
        peer.tick()
        assert h.schedule.queue == []
        raise RuntimeError("publication log failed")

    with monkeypatch.context() as patch:
        patch.setattr(event_stream_service, "print", print_publication, raising=False)
        h.service.tick()
        with pytest.raises(RuntimeError, match="publication log failed"):
            h.schedule.run_all()

    assert h.visible_names() == ["B"]
    assert h.service._failures == 0
    assert h.service._next_fetch_ms == 6000
    peer.tick()
    h.schedule.run_all()
    assert [e.label for e in peer.build_streams()[0](0)] == ["C"]


def test_retry_deadline_precedes_raising_logger_and_gate_is_released(monkeypatch) -> None:
    h = _Harness()
    h.fetch()
    previous = h.stream(0)
    h.service._backoff_base_ms = 100
    h.advance(1000)
    h.raise_exc = HttpConnectError("down")
    peer = StubService(lambda: _payload(("B", 0, 100)), h.http_client, 1000, lambda: h.clock_val)
    logged = []

    def log_exception(tag: str, exc: Exception) -> None:
        logged.append((h.service._next_fetch_ms, exc))
        assert h.stream(0) is previous
        peer.tick()
        assert h.schedule.queue == []
        raise RuntimeError("logger failed")

    monkeypatch.setattr(event_stream_service, "log_exception", log_exception)
    h.service.tick()
    with pytest.raises(RuntimeError, match="logger failed"):
        h.schedule.run_all()

    assert logged == [(1100, h.raise_exc)]
    assert h.service._failures == 1
    assert h.visible_names() == ["A"]
    h.advance(99)
    h.service.tick()
    assert h.schedule.queue == []

    peer.tick()
    h.schedule.run_all()
    assert [e.label for e in peer.build_streams()[0](0)] == ["B"]


def test_refresh_interval_starts_at_callback_completion() -> None:
    h = _Harness(interval_ms=1000)
    h.service.tick()
    h.advance(250)
    h.schedule.run_all()
    assert h.fetch_calls == 1

    h.advance(999)
    h.service.tick()
    assert h.fetch_calls == 1
    assert h.schedule.queue == []

    h.advance(1)
    h.fetch()
    assert h.fetch_calls == 2


@pytest.mark.parametrize("refusal", ["offline", "busy"], ids=["offline", "busy"])
def test_due_fetch_survives_half_period_after_client_refusal(monkeypatch, refusal: str) -> None:
    ticks_period_ms = 1 << 30
    half_period_ms = ticks_period_ms // 2

    def ticks_add(value_ms: int, delta_ms: int) -> int:
        return (value_ms + delta_ms) % ticks_period_ms

    def ticks_diff(current_ms: int, previous_ms: int) -> int:
        return (current_ms - previous_ms + half_period_ms) % ticks_period_ms - half_period_ms

    monkeypatch.setattr(event_stream_service.time, "ticks_add", ticks_add)
    monkeypatch.setattr(event_stream_service.time, "ticks_diff", ticks_diff)
    h = _Harness(start_ms=ticks_period_ms - 500)
    h.fetch()
    h.payload = _payload(("B", 0, 100))
    h.clock_val = (h.clock_val + 1000) % ticks_period_ms
    if refusal == "offline":
        h.wifi.connected = False
    else:
        assert h.http_client.try_fetch(lambda: None) is True

    h.service.tick()
    assert h.fetch_calls == 1
    assert h.visible_names() == ["A"]
    assert len(h.schedule.queue) == (1 if refusal == "busy" else 0)

    h.clock_val = (h.clock_val + half_period_ms + 1) % ticks_period_ms
    if refusal == "offline":
        h.wifi.connected = True
    else:
        h.schedule.run_all()

    h.service.tick()

    assert len(h.schedule.queue) == 1
    h.schedule.run_all()
    assert h.fetch_calls == 2
    assert h.visible_names() == ["B"]


def test_shared_client_blocks_pending_running_and_reentrant_ticks_without_chaining() -> None:
    schedule = _FakeSchedule()
    http_client = HttpClient(_FakeWifi(), schedule, timeout_sec=7)
    calls = []

    def fetch_a() -> dict:
        calls.append("A")
        a.tick()
        b.tick()
        assert schedule.queue == []
        return _payload(("A", 0, 100))

    def fetch_b() -> dict:
        calls.append("B")
        return _payload(("B", 0, 100))

    a = StubService(fetch_a, http_client, 1000, lambda: 0)
    b = StubService(fetch_b, http_client, 1000, lambda: 0)

    a.tick()
    a.tick()
    b.tick()
    assert len(schedule.queue) == 1
    assert calls == []

    schedule.run_all()
    assert calls == ["A"]
    assert [e.label for e in a.build_streams()[0](0)] == ["A"]
    assert b.build_streams()[0](0) == []
    assert schedule.queue == []

    b.tick()
    schedule.run_all()
    assert calls == ["A", "B"]
    assert [e.label for e in b.build_streams()[0](0)] == ["B"]
