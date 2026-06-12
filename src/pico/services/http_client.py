import gc

try:
    import urequests as _requests
except ImportError:
    import requests as _requests

try:
    import errno as _errno
    _ETIMEDOUT = getattr(_errno, "ETIMEDOUT", 110)
    _EAGAIN = getattr(_errno, "EAGAIN", 11)
except ImportError:
    _ETIMEDOUT = 110
    _EAGAIN = 11


class HttpError(Exception):
    """Base for every http_client failure; callers catch this to classify retry."""


class HttpTimeout(HttpError):
    """Socket timed out while connecting or reading."""


class HttpConnectError(HttpError):
    """DNS, connection-refused, or other socket setup failure."""


class HttpStatusError(HttpError):
    """Server replied with a non-2xx status."""

    def __init__(self, status: int) -> None:
        super().__init__("HTTP status {}".format(status))
        self.status = status


class HttpParseError(HttpError):
    """Response body was not valid JSON, or not a JSON object."""


class HttpProtocolError(HttpError):
    """Reply was not a usable HTTP response (bad status line, unsupported
    scheme / transfer-encoding / redirect) — e.g. a captive portal."""


def _classify_oserror(exc: OSError) -> HttpError:
    code = exc.args[0] if exc.args else None
    if code == _ETIMEDOUT or code == _EAGAIN:
        return HttpTimeout(str(exc))
    return HttpConnectError(str(exc))


def get_json(url: str, headers: dict | None = None, timeout_s: int = 10) -> dict:
    """GET ``url`` and return the parsed JSON body as a dict.

    Raises an ``HttpError`` subclass on any failure; never returns None.
    Collects garbage first to reduce fragmented-heap allocation failures,
    and always closes the response.
    """
    gc.collect()
    response = None
    try:
        try:
            response = _requests.get(url, headers=headers or {}, timeout=timeout_s)
        except OSError as exc:
            raise _classify_oserror(exc)
        except (ValueError, NotImplementedError) as exc:
            raise HttpProtocolError(str(exc))

        status = response.status_code
        if status < 200 or status > 299:
            raise HttpStatusError(status)

        try:
            result = response.json()
        except ValueError:
            raise HttpParseError("invalid JSON body")
        except OSError as exc:
            raise _classify_oserror(exc)

        if not isinstance(result, dict):
            raise HttpParseError("JSON body is not an object")
        return result
    finally:
        if response is not None:
            response.close()
