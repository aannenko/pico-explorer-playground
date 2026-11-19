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
)

_URL = "http://example.test/data"


class _FakeWifi:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected

    def is_connected(self) -> bool:
        return self.connected


def _client(connected: bool = True) -> HttpClient:
    return HttpClient(_FakeWifi(connected), timeout_sec=7)


def _lines(deadline_ms: int = 10_000, **line_bounds) -> list[bytes]:
    with _client().get(_URL, deadline_ms=deadline_ms) as response:
        return list(response.lines(**line_bounds))


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
    assert set(fake_urequests.responses[-1].raw.read_sizes) == {256}


def test_the_default_bounds_take_512_byte_lines_and_10_seconds(fake_urequests, fake_ticks):
    fake_urequests.chunks = [b"x" * 512 + b"\n", b"y" * 513 + b"\n"]
    received = []

    with pytest.raises(HttpParseError):
        with _client().get(_URL) as response:
            for line in response.lines():
                received.append(line)
    assert received == [b"x" * 512]

    fake_urequests.chunks = [b"a\n", b"b\n", b"c\n"]
    received = []
    with pytest.raises(HttpTimeoutError):
        with _client().get(_URL) as response:
            for line in response.lines():
                received.append(line)
                fake_ticks[0] += 6_000
    assert received == [b"a", b"b"]


@pytest.mark.parametrize(
    "chunks",
    [
        [b"x" * 9 + b"\nok\n"],  # a completed line
        [b"x" * 10, b"x\n"],  # a line still pending after a read
        [b"x" * 9],  # the final line
    ],
)
def test_a_line_over_the_limit_raises_parse_error_and_closes(fake_urequests, chunks):
    fake_urequests.chunks = chunks

    with pytest.raises(HttpParseError):
        _lines(max_line_bytes=8)

    assert fake_urequests.responses[-1].closed is True


@pytest.mark.parametrize("chunk", [b"x" * 9, b"x" * 10], ids=["one-byte-over-not-cr", "two-bytes-over"])
def test_a_pending_line_over_the_limit_raises_before_the_next_read(fake_urequests, chunk):
    fake_urequests.chunks = [chunk]
    fake_urequests.raise_at_end = ValueError("Connection closed before body complete")

    with pytest.raises(HttpParseError):
        _lines(max_line_bytes=8)


@pytest.mark.parametrize(
    "chunks",
    [[b"x" * 8 + b"\r\n"], [b"x" * 8 + b"\r", b"\nok\n"]],
    ids=["one-read", "crlf-split-across-reads"],
)
def test_a_line_at_the_limit_is_delivered(fake_urequests, chunks):
    fake_urequests.chunks = chunks

    assert _lines(max_line_bytes=8)[0] == b"x" * 8


def test_body_past_the_deadline_raises_timeout(fake_urequests, fake_ticks):
    fake_urequests.chunks = [b"a\n", b"b\n"]
    received = []

    with pytest.raises(HttpTimeoutError):
        with _client().get(_URL, deadline_ms=500) as response:
            for line in response.lines():
                received.append(line)
                fake_ticks[0] += 600

    assert received == [b"a"]
    assert fake_urequests.responses[-1].closed is True


def test_body_within_the_deadline_completes(fake_urequests, fake_ticks):
    fake_urequests.chunks = [b"a\n", b"b\n"]
    received = []

    with _client().get(_URL, deadline_ms=500) as response:
        for line in response.lines():
            received.append(line)
            fake_ticks[0] += 250

    assert received == [b"a", b"b"]


def test_an_exception_in_the_block_closes_the_response_and_propagates(fake_urequests):
    fake_urequests.chunks = [b"a\n"]

    with pytest.raises(HttpParseError, match="bad row"):
        with _client().get(_URL) as response:
            lines = response.lines()
            for _ in lines:
                raise HttpParseError("bad row")

    # The generator stays referenced, so CPython's finaliser can't be what closed the response.
    assert lines is not None
    assert fake_urequests.responses[-1].closed is True


def test_leaving_the_block_early_closes_the_response(fake_urequests):
    fake_urequests.chunks = [b"a\nb\nc\n"]

    with _client().get(_URL) as response:
        lines = response.lines()
        assert next(lines) == b"a"

    assert lines is not None
    assert fake_urequests.responses[-1].closed is True


def test_closing_twice_closes_once(fake_urequests):
    response = _client().get(_URL)
    body = fake_urequests.responses[-1].raw
    closes = []
    body.close = lambda: closes.append(1)

    response.close()
    response.close()

    assert closes == [1]


def test_response_closed_on_success(fake_urequests):
    _lines()

    assert fake_urequests.responses[-1].closed is True


def test_offline_raises_before_collecting_or_connecting(fake_urequests, monkeypatch):
    collections = []
    monkeypatch.setattr(http_client.gc, "collect", lambda: collections.append(1))

    with pytest.raises(HttpConnectError, match="offline"):
        _client(connected=False).get(_URL)

    assert collections == []
    assert fake_urequests.calls == []


def test_connect_failure_raises_connect_error(fake_urequests):
    fake_urequests.raise_on_get = OSError(9999, "unreachable")

    with pytest.raises(HttpConnectError):
        _client().get(_URL)

    assert fake_urequests.responses == []


def test_oserror_without_args_is_connect_error(fake_urequests):
    fake_urequests.raise_on_get = OSError()

    with pytest.raises(HttpConnectError):
        _client().get(_URL)


@pytest.mark.parametrize("code", [http_client._ETIMEDOUT, http_client._EAGAIN])
def test_timeout_errnos_raise_timeout(fake_urequests, code):
    fake_urequests.raise_on_get = OSError(code, "timed out")

    with pytest.raises(HttpTimeoutError):
        _client().get(_URL)


@pytest.mark.parametrize("status, ok", [(199, False), (200, True), (299, True), (300, False), (404, False)])
def test_status_boundaries(fake_urequests, status, ok):
    fake_urequests.status_code = status
    fake_urequests.chunks = [b"a\n"]

    if ok:
        assert _lines() == [b"a"]
    else:
        with pytest.raises(HttpStatusError) as info:
            _client().get(_URL)
        assert info.value.status == status
        assert fake_urequests.responses[-1].closed is True


def test_a_failure_building_the_response_closes_it(fake_urequests, monkeypatch):
    error = MemoryError("memory allocation failed, allocating 32 bytes")

    def raise_memory_error(body, deadline_ms: int):
        raise error

    monkeypatch.setattr(http_client, "Response", raise_memory_error)

    with pytest.raises(MemoryError) as info:
        _client().get(_URL)

    assert info.value is error
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
        _client().get(_URL)


def test_body_read_timeout_raises_timeout_after_the_lines_before_it(fake_urequests):
    fake_urequests.chunks = [b"a\n"]
    fake_urequests.raise_at_end = OSError(http_client._ETIMEDOUT, "read timeout")
    received = []

    with pytest.raises(HttpTimeoutError):
        with _client().get(_URL) as response:
            for line in response.lines():
                received.append(line)

    assert received == [b"a"]
    assert fake_urequests.responses[-1].closed is True


def test_body_cut_short_raises_protocol_error(fake_urequests):
    fake_urequests.chunks = [b"a\n"]
    fake_urequests.raise_at_end = ValueError("Connection closed before body complete")

    with pytest.raises(HttpProtocolError):
        _lines()

    assert fake_urequests.responses[-1].closed is True


def test_gc_collected_once_before_request(fake_urequests, monkeypatch):
    calls = []
    monkeypatch.setattr(http_client.gc, "collect", lambda: calls.append(len(fake_urequests.calls)))

    _lines()

    assert calls == [0]


def test_the_client_timeout_reaches_the_request(fake_urequests):
    _lines()

    assert fake_urequests.calls == [(_URL, 7)]


def test_typed_exceptions_subclass_http_error():
    for exc_type in (
        HttpTimeoutError,
        HttpConnectError,
        HttpStatusError,
        HttpParseError,
        HttpProtocolError,
    ):
        assert issubclass(exc_type, HttpError)
