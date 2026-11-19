import gc
import time

from micropython import const

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


def _trim_line(line: bytes, max_line_bytes: int) -> bytes:
    """Return ``line`` without a trailing ``\\r``; raise ``HttpParseError`` if the rest is over ``max_line_bytes``."""
    if line.endswith(b"\r"):
        line = line[:-1]
    if len(line) > max_line_bytes:
        raise HttpParseError("line too long")
    return line


class Response:
    """An open response body, read once; use it in a ``with`` block, which closes it however the block ends.

    Holds only the body stream, not ``requests``' response, so its parsed headers can be collected while the body
    streams.
    """

    def __init__(self, body, deadline_ms: int) -> None:  # body: has readinto(buf) -> int and close()
        self._body = body
        self._deadline_ms = deadline_ms

    def __enter__(self):  # -> Response
        return self

    def __exit__(self, exc_type: type | None, exc: BaseException | None, tb) -> None:  # tb: traceback | None
        self.close()

    def close(self) -> None:
        """Close the socket; closing again does nothing."""
        body = self._body
        if body is not None:
            self._body = None
            body.close()

    def lines(self, max_line_bytes: int = _MAX_LINE_BYTES):  # -> Iterator[bytes]
        """Yield each line of the body as bytes without its ``\\n`` or ``\\r\\n``, the last one even without either.

        Holds at most one read of up to 256 bytes and one line, so the body's size doesn't matter.  The deadline,
        counted from the first read, is checked between reads: a peer that trickles bytes can stretch one read well
        beyond it.  Raises ``HttpParseError`` for a line longer than ``max_line_bytes``, ``HttpTimeoutError`` past the
        deadline, and an ``HttpError`` subclass for a failed read.
        """
        # Warning: close() closes the socket, not a finally here: MicroPython never finalises a generator that stops
        # before its end, so such a finally would leave the socket open whenever a caller stops early.
        body = self._body
        # A chunked or sized body is a BodyStream, which has no readline(), so lines are split here.  Reading into
        # one buffer saves the n-byte bytearray and its slice that each BodyStream.read(n) allocates.
        buf = bytearray(_READ_BYTES)
        view = memoryview(buf)
        start_ms = time.ticks_ms()
        pending = b""
        while True:
            if time.ticks_diff(time.ticks_ms(), start_ms) > self._deadline_ms:
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
                yield _trim_line(line, max_line_bytes)
            # One byte over the limit is allowed only as the \r of a \r\n that the next read completes.
            if len(pending) > max_line_bytes and (len(pending) > max_line_bytes + 1 or not pending.endswith(b"\r")):
                raise HttpParseError("line too long")
        if pending:
            yield _trim_line(pending, max_line_bytes)


class HttpClient:
    """Plain-HTTP GETs whose bodies stream through a ``Response``, with one socket timeout.

    Warning: a request blocks the main thread, freezing rendering and button handling until it returns, so make it
    from a deferred job (``TickScheduler.try_defer``).
    """

    def __init__(
        self,
        wifi,  # has is_connected() -> bool
        timeout_sec: int,
    ) -> None:
        self._wifi = wifi
        self._timeout_sec = timeout_sec

    def get(self, url: str, deadline_ms: int = _DEADLINE_MS) -> Response:
        """GET ``url`` and return its body once the status is 2xx.

        ``timeout_sec`` bounds each socket operation but not the DNS lookup, and ``deadline_ms`` the body's reads, as
        ``Response.lines`` says.  Raises ``HttpConnectError`` while WiFi is down, before any lookup or socket, and
        otherwise an ``HttpError`` subclass for a transport, status or protocol failure.  Whatever this raises once
        ``requests`` has returned a response, it closes it first.
        """
        if not self._wifi.is_connected():
            raise HttpConnectError("offline")
        gc.collect()  # reduces fragmented-heap allocation failures
        try:
            # requests closes its socket itself only on OSError, leaving any other failure before it returns to the
            # socket's finaliser at a later collection; a redirect also drops the timeout.
            response = _requests.get(url, timeout=self._timeout_sec)
        except OSError as exc:
            raise _classify_oserror(exc)
        except (ValueError, NotImplementedError) as exc:
            # requests raises these for a bad status line, an unsupported scheme or a redirect it can't follow.
            raise HttpProtocolError(str(exc))
        try:
            status = response.status_code
            if status < 200 or status > 299:
                raise HttpStatusError(status)
            return Response(response.raw, deadline_ms)
        except BaseException:
            response.close()
            raise
