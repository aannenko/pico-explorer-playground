import micropython
import pytest

from _stub_service import StubService
from conftest import make_timer_factory
import services._event_stream_service as event_stream_service
from services.http_client import HttpConnectError
from services.tick_scheduler import TickScheduler


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


def _scheduler() -> TickScheduler:
    timer_factory, _ = make_timer_factory()
    return TickScheduler(schedule=lambda callback, arg: None, timer_factory=timer_factory)


class _Harness:
    """A stub service on a real ``TickScheduler``, whose ticks the test runs; ``fetch_ms`` is how long a fetch takes."""

    def __init__(self, interval_ms: int = 1000, enabled: bool = True, start_ms: int = 0) -> None:
        self.clock_val = start_ms
        self.scheduler = _scheduler()
        self.payload = _payload(("A", 0, 100))
        self.fetch_calls = 0
        self.fetch_ms = 0
        self.raise_exc = None
        self.service = StubService(
            self._fetcher,
            self.scheduler,
            interval_ms,
            get_ticks_ms=lambda: self.clock_val,
            enabled=enabled,
        )
        self.stream = self.service.build_streams()[0]

    def _fetcher(self) -> dict:
        self.fetch_calls += 1
        self.clock_val += self.fetch_ms
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.payload

    def advance(self, ms: int) -> None:
        self.clock_val += ms

    def tick(self) -> None:
        self.scheduler._tick(0)

    def visible_names(self) -> list[str]:
        return [e.label for e in self.stream(0)]


def test_a_disabled_service_never_fetches_or_reports_a_failed_refresh() -> None:
    h = _Harness(enabled=False)
    h.raise_exc = HttpConnectError("offline")

    for _ in range(5):
        h.tick()

    assert h.fetch_calls == 0
    assert h.visible_names() == []
    assert h.service.refresh_failed() is False


def test_a_due_refresh_publishes_after_the_tick_s_other_subscribers() -> None:
    h = _Harness()
    seen_by_render = []
    h.scheduler.register(lambda: seen_by_render.append((h.fetch_calls, h.visible_names())))

    h.tick()

    assert seen_by_render == [(0, [])]
    assert h.fetch_calls == 1
    assert h.visible_names() == ["A"]


def test_second_fetch_replaces_snapshot_seen_by_existing_getter() -> None:
    h = _Harness(interval_ms=1000)
    h.tick()
    previous = h.stream(0)

    h.payload = _payload(("B", 0, 100), ("C", 200, 100))
    h.advance(1000)
    h.tick()

    assert h.visible_names() == ["B", "C"]
    assert [e.label for e in previous] == ["A"]
    assert h.stream(0) is not previous


@pytest.mark.parametrize("failure", ["fetch", "parse"], ids=["fetch-error", "parse-error"])
def test_a_failure_keeps_the_prior_snapshot_and_is_reported_until_a_retry_succeeds(failure: str) -> None:
    h = _Harness(interval_ms=1000)
    h.tick()
    assert h.service.refresh_failed() is False
    previous = h.stream(0)
    h.service._backoff_base_ms = 100
    h.service._backoff_max_ms = 300

    if failure == "fetch":
        h.raise_exc = HttpConnectError("down")
    else:
        h.payload = {"unexpected": "shape"}
    h.advance(1000)
    h.tick()

    assert h.service._failures == 1
    assert h.service.refresh_failed() is True
    assert h.stream(0) is previous
    assert h.visible_names() == ["A"]

    h.raise_exc = None
    h.payload = _payload(("B", 0, 100))
    h.advance(99)
    h.tick()
    assert h.fetch_calls == 2
    assert h.service.refresh_failed() is True

    h.advance(1)
    h.tick()
    assert h.fetch_calls == 3
    assert h.visible_names() == ["B"]
    assert h.service._failures == 0
    assert h.service.refresh_failed() is False


def test_backoff_grows_exponentially_and_caps() -> None:
    h = _Harness()
    s = h.service
    s._backoff_base_ms = 100
    s._backoff_max_ms = 300

    h.raise_exc = HttpConnectError("down")

    for failure_count, delay_ms in enumerate((100, 200, 300, 300), start=1):
        h.tick()
        assert s._failures == failure_count
        h.advance(delay_ms - 1)
        h.tick()
        assert h.fetch_calls == failure_count
        h.advance(1)

    s._failures = 30
    assert s._backoff_delay() == 300


def test_a_memory_error_is_logged_with_heap_info_once_its_failure_is_committed(monkeypatch, capsys) -> None:
    h = _Harness()
    h.raise_exc = MemoryError("memory allocation failed, allocating 2560 bytes")
    retry_at_heap_summary = []
    monkeypatch.setattr(micropython, "mem_info", lambda: retry_at_heap_summary.append(h.service._next_fetch_ms))

    h.tick()

    assert retry_at_heap_summary == [5000]
    assert h.service.refresh_failed() is True
    out = capsys.readouterr().out
    assert out.startswith("[stub] err:\n")
    assert "MemoryError: memory allocation failed, allocating 2560 bytes" in out
    assert "[stub] fail #1, retry in 5000ms" in out


def test_raising_success_print_preserves_publication_deadline_and_frees_the_slot(monkeypatch, capsys) -> None:
    h = _Harness()
    h.raise_exc = HttpConnectError("down")
    h.tick()
    h.advance(5000)
    h.raise_exc = None
    h.payload = _payload(("B", 0, 100))
    peer = StubService(lambda: _payload(("C", 0, 100)), h.scheduler, 1000, lambda: h.clock_val)

    def print_publication(message: str) -> None:
        assert h.visible_names() == ["B"]
        assert h.service._failures == 0
        assert h.service._next_fetch_ms == 6000
        raise RuntimeError("publication log failed")

    with monkeypatch.context() as patch:
        patch.setattr(event_stream_service, "print", print_publication, raising=False)
        h.tick()

    assert "RuntimeError: publication log failed" in capsys.readouterr().out
    assert h.visible_names() == ["B"]
    assert h.service._failures == 0
    assert h.service._next_fetch_ms == 6000
    h.tick()
    assert [e.label for e in peer.build_streams()[0](0)] == ["C"]


def test_retry_deadline_precedes_raising_logger_and_the_slot_is_freed(monkeypatch) -> None:
    h = _Harness()
    h.tick()
    previous = h.stream(0)
    h.service._backoff_base_ms = 100
    h.advance(1000)
    h.raise_exc = HttpConnectError("down")
    peer = StubService(lambda: _payload(("B", 0, 100)), h.scheduler, 1000, lambda: h.clock_val)
    logged = []

    def log_exception(tag: str, exc: Exception) -> None:
        logged.append((h.service._next_fetch_ms, exc))
        assert h.stream(0) is previous
        raise RuntimeError("logger failed")

    monkeypatch.setattr(event_stream_service, "log_exception", log_exception)
    h.tick()

    assert logged == [(1100, h.raise_exc)]
    assert h.service._failures == 1
    assert h.visible_names() == ["A"]
    h.advance(99)
    h.tick()
    assert h.fetch_calls == 2
    assert [e.label for e in peer.build_streams()[0](0)] == ["B"]


def test_refresh_interval_starts_when_the_job_completes() -> None:
    h = _Harness(interval_ms=1000)
    h.fetch_ms = 250
    h.tick()
    assert h.fetch_calls == 1

    h.fetch_ms = 0
    h.advance(999)
    h.tick()
    assert h.fetch_calls == 1

    h.advance(1)
    h.tick()
    assert h.fetch_calls == 2


def test_due_fetch_survives_half_period_after_a_refusal(monkeypatch) -> None:
    ticks_period_ms = 1 << 30
    half_period_ms = ticks_period_ms // 2

    def ticks_add(value_ms: int, delta_ms: int) -> int:
        return (value_ms + delta_ms) % ticks_period_ms

    def ticks_diff(current_ms: int, previous_ms: int) -> int:
        return (current_ms - previous_ms + half_period_ms) % ticks_period_ms - half_period_ms

    monkeypatch.setattr(event_stream_service.time, "ticks_add", ticks_add)
    monkeypatch.setattr(event_stream_service.time, "ticks_diff", ticks_diff)
    h = _Harness(start_ms=ticks_period_ms - 500)
    h.tick()
    h.payload = _payload(("B", 0, 100))
    h.clock_val = (h.clock_val + 1000) % ticks_period_ms
    assert h.scheduler.try_defer(lambda: None) is True

    h.service.tick()
    assert h.fetch_calls == 1
    assert h.service.refresh_failed() is False

    h.clock_val = (h.clock_val + half_period_ms + 1) % ticks_period_ms
    h.tick()
    assert h.fetch_calls == 1
    assert h.visible_names() == ["A"]

    h.tick()
    assert h.fetch_calls == 2
    assert h.visible_names() == ["B"]


def test_a_shared_scheduler_refuses_pending_running_and_reentrant_refreshes_without_chaining() -> None:
    scheduler = _scheduler()
    calls = []

    def fetch_a() -> dict:
        calls.append("A")
        a.tick()
        b.tick()
        return _payload(("A", 0, 100))

    def fetch_b() -> dict:
        calls.append("B")
        return _payload(("B", 0, 100))

    a = StubService(fetch_a, scheduler, 1000, lambda: 0)
    b = StubService(fetch_b, scheduler, 1000, lambda: 0)
    scheduler.register(lambda: calls.append("render"))

    a.tick()
    a.tick()
    b.tick()
    assert calls == []
    assert scheduler._job is a._refresh_ref

    scheduler._tick(0)
    assert calls == ["render", "A"]
    assert [e.label for e in a.build_streams()[0](0)] == ["A"]
    assert b.build_streams()[0](0) == []

    scheduler._tick(0)
    assert calls == ["render", "A", "render", "B"]
    assert [e.label for e in b.build_streams()[0](0)] == ["B"]
