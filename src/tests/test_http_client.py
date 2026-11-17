"""Tests for the shared HTTP client wrapper."""

import micropython
import pytest

import services.http_client as http_client
from services.http_client import (
    HttpConnectError,
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
