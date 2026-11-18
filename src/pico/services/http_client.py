import gc
import time

from micropython import const

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

_READ_BYTES = const(256)
# The air-quality CSV header is 158 B with five pollen species, and about 27 B longer per extra species.
_MAX_LINE_BYTES = const(512)
_DEADLINE_MS = const(10_000)


class HttpError(Exception):
    pass


class HttpTimeoutError(HttpError):
    pass


class HttpConnectError(HttpError):
    """Any non-timeout socket failure: DNS, a refused connection or a failed read."""


class HttpStatusError(HttpError):
    """Any non-2xx status."""

    def __init__(self, status: int) -> None:
        super().__init__("HTTP status {}".format(status))
        self.status = status


class HttpParseError(HttpError):
    """The body isn't what the caller expects, e.g. a line is too long."""


class HttpProtocolError(HttpError):
    """The reply isn't a usable HTTP response, e.g. from a captive portal or cut short."""


def _classify_oserror(exc: OSError) -> HttpError:
    code = exc.args[0] if exc.args else None
    if code == _ETIMEDOUT or code == _EAGAIN:
        return HttpTimeoutError(str(exc))
    return HttpConnectError(str(exc))


def get_lines(
    url: str,
    on_line,  # (bytes) -> None
    timeout_sec: int = 3,
    max_line_bytes: int = _MAX_LINE_BYTES,
    deadline_ms: int = _DEADLINE_MS,
) -> None:
    """GET ``url`` and pass each line of its body to ``on_line``, as bytes without its ``\\n`` or ``\\r\\n``.

    Streams the body, holding at most one read and one line, so its size doesn't matter.  ``timeout_sec`` bounds
    each socket operation, and ``deadline_ms`` the body, checked between reads of up to 256 bytes: a peer that
    trickles bytes can stretch one read well beyond it.  Raises an ``HttpError`` subclass for transport, status and
    protocol failures, ``HttpParseError`` for a line longer than ``max_line_bytes`` and ``HttpTimeoutError`` past the
    deadline; whatever ``on_line`` raises propagates, and anything else (e.g. ``MemoryError``) is logged and
    re-raised.
    """
    try:
        _get_lines(url, on_line, timeout_sec, max_line_bytes, deadline_ms)
    except HttpError:
        raise
    except Exception as exc:
        log_exception("[http] unclassified failure:", exc)
        raise


def _get_lines(url: str, on_line, timeout_sec: int, max_line_bytes: int, deadline_ms: int) -> None:
    gc.collect()  # reduces fragmented-heap allocation failures
    response = None
    try:
        try:
            response = _requests.get(url, timeout=timeout_sec)
        except OSError as exc:
            raise _classify_oserror(exc)
        except (ValueError, NotImplementedError) as exc:
            # requests raises these for a bad status line, an unsupported scheme or a redirect it can't follow.
            raise HttpProtocolError(str(exc))

        status = response.status_code
        if status < 200 or status > 299:
            raise HttpStatusError(status)

        # A chunked or sized body is a BodyStream, which has no readline(), so lines are split here.  Reading into
        # one buffer saves the n-byte bytearray and its slice that each BodyStream.read(n) allocates.
        body = response.raw
        buf = bytearray(_READ_BYTES)
        view = memoryview(buf)
        start_ms = time.ticks_ms()
        pending = b""
        while True:
            if time.ticks_diff(time.ticks_ms(), start_ms) > deadline_ms:
                raise HttpTimeoutError("body read deadline")
            try:
                got = body.readinto(buf)
            except OSError as exc:
                raise _classify_oserror(exc)
            except ValueError as exc:
                # A BodyStream raises this for a body cut short.
                raise HttpProtocolError(str(exc))
            if not got:
                break
            # The concatenation copies, so the next read can reuse buf.
            lines = (pending + view[:got]).split(b"\n")
            pending = lines.pop()
            for line in lines:
                _deliver(line, on_line, max_line_bytes)
            if len(pending) > max_line_bytes:
                raise HttpParseError("line too long")
        if pending:
            _deliver(pending, on_line, max_line_bytes)
    finally:
        if response is not None:
            response.close()


def _deliver(line: bytes, on_line, max_line_bytes: int) -> None:
    if line.endswith(b"\r"):
        line = line[:-1]
    if len(line) > max_line_bytes:
        raise HttpParseError("line too long")
    on_line(line)


class HttpClient:
    """Run one complete fetch job at a time on the main thread, and stream HTTP lines with one socket timeout.

    Share one client across sources and submit from periodic ticks.  Busy or offline submissions aren't queued: retry
    on later ticks so competing fetches leave an opportunity for rendering between them.
    """

    def __init__(
        self,
        wifi,  # has is_connected() -> bool
        schedule,  # (callback, arg) -> None
        timeout_sec: int,
        http_get_lines=get_lines,  # (url, on_line, timeout_sec, max_line_bytes, deadline_ms) -> None
    ) -> None:
        self._wifi = wifi
        self._schedule = schedule
        self._timeout_sec = timeout_sec
        self._http_get_lines = http_get_lines
        self._fetcher = None  # Callable[[], None] | None
        self._run_ref = self._run

    def try_fetch(self, fetcher) -> bool:  # fetcher: () -> None
        """Queue ``fetcher`` if WiFi is up and no job is queued or running; return whether accepted.

        Scheduling errors propagate after releasing the slot.
        """
        if self._fetcher is not None or not self._wifi.is_connected():
            return False
        self._fetcher = fetcher
        try:
            self._schedule(self._run_ref, 0)
        except Exception:
            self._fetcher = None
            raise
        return True

    def _run(self, _: int) -> None:
        try:
            fetcher = self._fetcher
            assert fetcher is not None
            fetcher()
        finally:
            self._fetcher = None

    def stream_lines(
        self,
        url: str,
        on_line,  # (bytes) -> None
        max_line_bytes: int = _MAX_LINE_BYTES,
        deadline_ms: int = _DEADLINE_MS,
    ) -> None:
        """Pass lines to ``on_line`` as ``get_lines`` does, with the client's socket timeout.

        Blocks the main thread, so call it from a submitted fetch job.
        """
        self._http_get_lines(
            url, on_line, timeout_sec=self._timeout_sec, max_line_bytes=max_line_bytes, deadline_ms=deadline_ms
        )
