"""Tests for the shared HTTP client wrapper."""

import pytest

import services.http_client as http_client
from services.http_client import (
    HttpConnectError,
    HttpError,
    HttpParseError,
    HttpProtocolError,
    HttpStatusError,
    HttpTimeout,
    get_json,
)

_URL = "http://example.test/data"


def test_returns_parsed_dict_on_success(fake_urequests):
    fake_urequests.status_code = 200
    fake_urequests.json_data = {"ok": True, "n": 3}

    assert get_json(_URL) == {"ok": True, "n": 3}


def test_connect_failure_raises_connect_error(fake_urequests):
    fake_urequests.raise_on_get = OSError(9999, "unreachable")

    with pytest.raises(HttpConnectError):
        get_json(_URL)


def test_oserror_without_args_is_connect_error(fake_urequests):
    fake_urequests.raise_on_get = OSError()

    with pytest.raises(HttpConnectError):
        get_json(_URL)


def test_timeout_errno_raises_timeout(fake_urequests):
    fake_urequests.raise_on_get = OSError(http_client._ETIMEDOUT, "timed out")

    with pytest.raises(HttpTimeout):
        get_json(_URL)


def test_eagain_errno_raises_timeout(fake_urequests):
    fake_urequests.raise_on_get = OSError(http_client._EAGAIN, "again")

    with pytest.raises(HttpTimeout):
        get_json(_URL)


def test_non_2xx_raises_status_error_with_status(fake_urequests):
    fake_urequests.status_code = 404

    with pytest.raises(HttpStatusError) as info:
        get_json(_URL)

    assert info.value.status == 404


@pytest.mark.parametrize(
    "status, ok",
    [(200, True), (201, True), (299, True), (199, False), (300, False), (500, False)],
)
def test_status_boundaries(fake_urequests, status, ok):
    fake_urequests.status_code = status
    fake_urequests.json_data = {"v": 1}

    if ok:
        assert get_json(_URL) == {"v": 1}
    else:
        with pytest.raises(HttpStatusError):
            get_json(_URL)


def test_invalid_json_raises_parse_error(fake_urequests):
    fake_urequests.raise_on_json = ValueError("bad json")

    with pytest.raises(HttpParseError):
        get_json(_URL)


def test_non_object_json_raises_parse_error(fake_urequests):
    fake_urequests.json_data = [1, 2, 3]

    with pytest.raises(HttpParseError):
        get_json(_URL)


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
        get_json(_URL)


def test_body_read_oserror_classified_as_timeout(fake_urequests):
    fake_urequests.raise_on_json = OSError(http_client._ETIMEDOUT, "read timeout")

    with pytest.raises(HttpTimeout):
        get_json(_URL)

    assert fake_urequests.responses[-1].closed is True


def test_response_closed_on_success(fake_urequests):
    get_json(_URL)

    assert fake_urequests.responses[-1].closed is True


def test_response_closed_on_status_error(fake_urequests):
    fake_urequests.status_code = 500

    with pytest.raises(HttpStatusError):
        get_json(_URL)

    assert fake_urequests.responses[-1].closed is True


def test_response_closed_on_parse_error(fake_urequests):
    fake_urequests.raise_on_json = ValueError("bad json")

    with pytest.raises(HttpParseError):
        get_json(_URL)

    assert fake_urequests.responses[-1].closed is True


def test_connect_failure_creates_no_response_and_does_not_crash_on_close(fake_urequests):
    fake_urequests.raise_on_get = OSError(9999, "unreachable")

    with pytest.raises(HttpConnectError):
        get_json(_URL)

    assert fake_urequests.responses == []


def test_gc_collected_once_before_request(fake_urequests, monkeypatch):
    calls = []
    monkeypatch.setattr(http_client.gc, "collect", lambda: calls.append(1))

    get_json(_URL)

    assert len(calls) == 1


def test_headers_passed_through(fake_urequests):
    headers = {"X-Access-Token": "secret"}

    get_json(_URL, headers=headers)

    assert fake_urequests.calls[0][1] == headers


def test_headers_none_sent_as_empty_dict(fake_urequests):
    get_json(_URL)

    assert fake_urequests.calls[0][1] == {}


def test_timeout_passed_through(fake_urequests):
    get_json(_URL, timeout_s=5)

    assert fake_urequests.calls[0][2] == 5


def test_default_timeout_is_3s(fake_urequests):
    get_json(_URL)

    assert fake_urequests.calls[0][2] == 3


def test_typed_exceptions_subclass_http_error():
    for exc_type in (
        HttpTimeout,
        HttpConnectError,
        HttpStatusError,
        HttpParseError,
        HttpProtocolError,
    ):
        assert issubclass(exc_type, HttpError)
