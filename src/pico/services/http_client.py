import gc

from utilities.log import log_exception

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
    pass


class HttpTimeout(HttpError):
    pass


class HttpConnectError(HttpError):
    """Any non-timeout socket failure: DNS, a refused connection or a failed read."""


class HttpStatusError(HttpError):
    """Any non-2xx status."""

    def __init__(self, status: int) -> None:
        super().__init__("HTTP status {}".format(status))
        self.status = status


class HttpParseError(HttpError):
    """The body isn't valid JSON, or isn't a JSON object."""


class HttpProtocolError(HttpError):
    """The reply isn't a usable HTTP response, e.g. from a captive portal."""


def _classify_oserror(exc: OSError) -> HttpError:
    code = exc.args[0] if exc.args else None
    if code == _ETIMEDOUT or code == _EAGAIN:
        return HttpTimeout(str(exc))
    return HttpConnectError(str(exc))


def get_json(url: str, headers: dict | None = None, timeout_s: int = 3) -> dict:
    """GET ``url`` and return the parsed JSON body as a dict.

    Raises an ``HttpError`` subclass for transport, status, protocol and JSON
    failures; anything else (e.g. ``MemoryError``) is logged and re-raised.
    """
    try:
        return _get_json(url, headers, timeout_s)
    except HttpError:
        raise
    except Exception as exc:
        log_exception("[http] unclassified failure:", exc)
        raise


def _get_json(url: str, headers: dict | None, timeout_s: int) -> dict:
    gc.collect()  # reduces fragmented-heap allocation failures
    response = None
    try:
        try:
            response = _requests.get(url, headers=headers or {}, timeout=timeout_s)
        except OSError as exc:
            raise _classify_oserror(exc)
        except (ValueError, NotImplementedError) as exc:
            # urequests raises these for a bad status line or an unsupported scheme,
            # chunked transfer encoding or redirect status.
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
