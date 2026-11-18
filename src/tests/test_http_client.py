import micropython
import pytest

import services.http_client as http_client
from services.http_client import (
    HttpConnectError,
    HttpClient,
    HttpError,
    HttpParseError,
    HttpProtocolError,
    HttpStatusError,
    HttpTimeoutError,
    get_lines,
)

_URL = "http://example.test/data"


def _lines(**kwargs) -> list[bytes]:
    received: list[bytes] = []
    get_lines(_URL, received.append, **kwargs)
    return received


def test_delivers_each_line_without_its_line_ending(fake_urequests):
    fake_urequests.chunks = [b"a,1\nb,2\r\nc,3\n"]

    assert _lines() == [b"a,1", b"b,2", b"c,3"]


def test_joins_lines_split_across_reads(fake_urequests):
    fake_urequests.chunks = [b"time,v\n17", b"94855600,", b"1\r", b"\n17948", b"59200,2\n"]

    assert _lines() == [b"time,v", b"1794855600,1", b"1794859200,2"]


def test_reads_bytearray_chunks_as_a_chunked_body_returns_them(fake_urequests):
    fake_urequests.chunks = [bytearray(b"a\nb"), bytearray(b"c\n")]

    assert _lines() == [b"a", b"bc"]


def test_delivers_a_final_line_without_a_newline(fake_urequests):
    fake_urequests.chunks = [b"a\nlast"]

    assert _lines() == [b"a", b"last"]


def test_delivers_blank_lines(fake_urequests):
    fake_urequests.chunks = [b"meta\n\ntime\n"]

    assert _lines() == [b"meta", b"", b"time"]


def test_empty_body_delivers_nothing(fake_urequests):
    assert _lines() == []


def test_reads_at_most_256_bytes_at_a_time(fake_urequests):
    fake_urequests.chunks = [b"x" * 300 + b"\n"]

    assert _lines() == [b"x" * 300]


@pytest.mark.parametrize(
    "chunks",
    [
        [b"x" * 9 + b"\nok\n"],  # a completed line
        [b"x" * 9, b"x\n"],  # a line still pending after a read
    ],
)
def test_a_line_over_the_limit_raises_parse_error_and_closes(fake_urequests, chunks):
    fake_urequests.chunks = chunks

    with pytest.raises(HttpParseError):
        _lines(max_line_bytes=8)

    assert fake_urequests.responses[-1].closed is True


def test_a_line_at_the_limit_is_delivered(fake_urequests):
    fake_urequests.chunks = [b"x" * 8 + b"\r\n"]

    assert _lines(max_line_bytes=8) == [b"x" * 8]


def test_body_past_the_deadline_raises_timeout(fake_urequests, fake_ticks):
    fake_urequests.chunks = [b"a\n", b"b\n"]
    received = []

    def on_line(line):
        received.append(line)
        fake_ticks[0] += 600

    with pytest.raises(HttpTimeoutError):
        get_lines(_URL, on_line, deadline_ms=500)

    assert received == [b"a"]
    assert fake_urequests.responses[-1].closed is True


def test_body_within_the_deadline_completes(fake_urequests, fake_ticks):
    fake_urequests.chunks = [b"a\n", b"b\n"]

    def on_line(line):
        fake_ticks[0] += 250

    get_lines(_URL, on_line, deadline_ms=500)


def test_what_on_line_raises_propagates_and_closes(fake_urequests):
    fake_urequests.chunks = [b"a\n"]

    def on_line(line):
        raise HttpParseError("bad row")

    with pytest.raises(HttpParseError, match="bad row"):
        get_lines(_URL, on_line)

    assert fake_urequests.responses[-1].closed is True


def test_connect_failure_raises_connect_error(fake_urequests):
    fake_urequests.raise_on_get = OSError(9999, "unreachable")

    with pytest.raises(HttpConnectError):
        _lines()


def test_oserror_without_args_is_connect_error(fake_urequests):
    fake_urequests.raise_on_get = OSError()

    with pytest.raises(HttpConnectError):
        _lines()


@pytest.mark.parametrize("code", [http_client._ETIMEDOUT, http_client._EAGAIN])
def test_timeout_errnos_raise_timeout(fake_urequests, code):
    fake_urequests.raise_on_get = OSError(code, "timed out")

    with pytest.raises(HttpTimeoutError):
        _lines()


@pytest.mark.parametrize("status, ok", [(199, False), (200, True), (299, True), (300, False), (404, False)])
def test_status_boundaries(fake_urequests, status, ok):
    fake_urequests.status_code = status
    fake_urequests.chunks = [b"a\n"]

    if ok:
        assert _lines() == [b"a"]
    else:
        with pytest.raises(HttpStatusError) as info:
            _lines()
        assert info.value.status == status
        assert fake_urequests.responses[-1].closed is True


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("Unsupported protocol: ftp"),
        ValueError("HTTP error: BadStatusLine:\nb''"),
        NotImplementedError("Redirect 305 not yet supported"),
    ],
)
def test_malformed_response_raises_protocol_error(fake_urequests, exc):
    fake_urequests.raise_on_get = exc

    with pytest.raises(HttpProtocolError):
        _lines()


def test_body_read_timeout_raises_timeout_after_the_lines_before_it(fake_urequests):
    fake_urequests.chunks = [b"a\n"]
    fake_urequests.raise_at_end = OSError(http_client._ETIMEDOUT, "read timeout")
    received = []

    with pytest.raises(HttpTimeoutError):
        get_lines(_URL, received.append)

    assert received == [b"a"]
    assert fake_urequests.responses[-1].closed is True


def test_body_cut_short_raises_protocol_error(fake_urequests):
    fake_urequests.chunks = [b"a\n"]
    fake_urequests.raise_at_end = ValueError("Connection closed before body complete")

    with pytest.raises(HttpProtocolError):
        _lines()

    assert fake_urequests.responses[-1].closed is True


def test_response_closed_on_success(fake_urequests):
    _lines()

    assert fake_urequests.responses[-1].closed is True


def test_connect_failure_creates_no_response_and_does_not_crash_on_close(fake_urequests):
    fake_urequests.raise_on_get = OSError(9999, "unreachable")

    with pytest.raises(HttpConnectError):
        _lines()

    assert fake_urequests.responses == []


def test_gc_collected_once_before_request(fake_urequests, monkeypatch):
    calls = []
    monkeypatch.setattr(http_client.gc, "collect", lambda: calls.append(1))

    _lines()

    assert len(calls) == 1


def test_timeout_passed_through(fake_urequests):
    _lines(timeout_sec=5)

    assert fake_urequests.calls[0] == (_URL, 5)


def test_default_timeout_is_3s(fake_urequests):
    _lines()

    assert fake_urequests.calls[0][1] == 3


def test_typed_exceptions_subclass_http_error():
    for exc_type in (
        HttpTimeoutError,
        HttpConnectError,
        HttpStatusError,
        HttpParseError,
        HttpProtocolError,
    ):
        assert issubclass(exc_type, HttpError)


def test_unclassified_failure_prints_heap_and_traceback_then_propagates(
    fake_urequests, monkeypatch, capsys
):
    error = MemoryError("memory allocation failed, allocating 2560 bytes")
    fake_urequests.raise_at_end = error
    heap_summaries = []
    monkeypatch.setattr(micropython, "mem_info", lambda: heap_summaries.append(1))

    with pytest.raises(MemoryError) as info:
        _lines()

    assert info.value is error
    assert heap_summaries == [1]
    out = capsys.readouterr().out
    assert out.startswith("[http] unclassified failure:")
    assert "MemoryError: memory allocation failed, allocating 2560 bytes" in out
    assert fake_urequests.responses[-1].closed is True


def test_classified_failure_prints_nothing(fake_urequests, capsys):
    fake_urequests.status_code = 500

    with pytest.raises(HttpStatusError):
        _lines()

    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "bounds, expected_bounds",
    [({}, (512, 10_000)), ({"max_line_bytes": 37, "deadline_ms": 850}, (37, 850))],
    ids=["default-bounds", "explicit-bounds"],
)
def test_client_forwards_timeout_and_streaming_bounds(bounds: dict, expected_bounds: tuple[int, int]) -> None:
    calls = []
    received = []
    on_line = received.append

    def http_get_lines(url: str, callback, timeout_sec: int, max_line_bytes: int, deadline_ms: int) -> None:
        calls.append((url, callback, timeout_sec, max_line_bytes, deadline_ms))
        callback(b"hour,value")

    client = HttpClient(None, None, timeout_sec=7, http_get_lines=http_get_lines)

    client.stream_lines(_URL, on_line, **bounds)

    assert calls == [(_URL, on_line, 7, *expected_bounds)]
    assert received == [b"hour,value"]


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


def test_offline_submission_leaves_no_job_and_reconnect_can_submit() -> None:
    wifi = _FakeWifi(connected=False)
    schedule = _FakeSchedule()
    client = HttpClient(wifi, schedule, timeout_sec=7)
    calls = []

    assert client.try_fetch(lambda: calls.append("offline")) is False
    assert schedule.queue == []

    wifi.connected = True
    assert client.try_fetch(lambda: calls.append("online")) is True
    assert calls == []
    assert len(schedule.queue) == 1

    schedule.run_all()
    assert calls == ["online"]


def test_pending_and_running_jobs_refuse_peers_without_chaining() -> None:
    schedule = _FakeSchedule()
    client = HttpClient(_FakeWifi(), schedule, timeout_sec=7)
    calls = []

    def second() -> None:
        calls.append("second")

    def first() -> None:
        calls.append("first")
        assert client.try_fetch(second) is False

    assert client.try_fetch(first) is True
    assert client.try_fetch(second) is False
    assert len(schedule.queue) == 1

    schedule.run_all()
    assert calls == ["first"]
    assert schedule.queue == []

    assert client.try_fetch(second) is True
    schedule.run_all()
    assert calls == ["first", "second"]


def test_slot_is_reserved_before_schedule_can_reenter() -> None:
    queue = []
    calls = []

    def peer() -> None:
        calls.append("peer")

    def schedule(callback, arg: int) -> None:
        assert client.try_fetch(peer) is False
        queue.append((callback, arg))

    client = HttpClient(_FakeWifi(), schedule, timeout_sec=7)

    assert client.try_fetch(lambda: calls.append("owner")) is True
    assert len(queue) == 1
    callback, arg = queue.pop()
    callback(arg)
    assert calls == ["owner"]
    assert client.try_fetch(peer) is True


def test_schedule_failure_reraises_and_rolls_back_for_later_submission() -> None:
    schedule = _FakeSchedule()
    schedule.raise_next = True
    client = HttpClient(_FakeWifi(), schedule, timeout_sec=7)
    calls = []

    with pytest.raises(RuntimeError, match="schedule queue full"):
        client.try_fetch(lambda: calls.append("rejected"))

    assert schedule.queue == []
    schedule.raise_next = False
    assert client.try_fetch(lambda: calls.append("retry")) is True
    schedule.run_all()
    assert calls == ["retry"]


def test_callback_exception_propagates_and_releases_for_later_submission() -> None:
    schedule = _FakeSchedule()
    client = HttpClient(_FakeWifi(), schedule, timeout_sec=7)
    calls = []
    error = RuntimeError("fetch failed")

    def fail() -> None:
        raise error

    assert client.try_fetch(fail) is True
    with pytest.raises(RuntimeError) as caught:
        schedule.run_all()
    assert caught.value is error

    assert client.try_fetch(lambda: calls.append("recovered")) is True
    schedule.run_all()
    assert calls == ["recovered"]


def test_scheduled_callback_is_cached_between_jobs() -> None:
    schedule = _FakeSchedule()
    client = HttpClient(_FakeWifi(), schedule, timeout_sec=7)
    calls = []

    client.try_fetch(lambda: calls.append("first"))
    first_callback = schedule.queue[0][0]
    schedule.run_all()
    client.try_fetch(lambda: calls.append("second"))
    assert schedule.queue[0][0] is first_callback
    schedule.run_all()
    assert calls == ["first", "second"]
