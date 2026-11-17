"""Open-Meteo access for hourly forecast and air-quality data."""

from micropython import const

from services.http_client import HttpParseError

# HTTP (not HTTPS) on purpose: no TLS handshake and its large contiguous-heap block.
_FORECAST_URL = "http://api.open-meteo.com/v1/forecast"
_AIR_QUALITY_URL = "http://air-quality-api.open-meteo.com/v1/air-quality"

# The air-quality API answers a longer forecast with HTTP 400.
AIR_QUALITY_MAX_FORECAST_HOURS = const(168)

_SEC_PER_HOUR = const(3600)
# The header row follows the location's column names, their values and a blank line.
_MAX_LINES_BEFORE_HEADER = const(3)


def _build_url(
    base: str, lat: float, lon: float, metrics: str, forecast_hours: int, past_hours: int
) -> str:
    # CSV, unlike JSON, parses a row at a time.  Rows are UTC Unix times: in a time zone, every row would take
    # the offset in force when it was requested, an hour out past a DST change.
    return (
        "%s?format=csv&timeformat=unixtime&timezone=GMT&latitude=%s&longitude=%s&hourly=%s"
        "&past_hours=%s&forecast_hours=%s" % (base, lat, lon, metrics, past_hours, forecast_hours)
    )


def is_location_set(latitude: float, longitude: float) -> bool:
    """Return whether the coordinates are set: 0.0/0.0, a point at sea, means unset."""
    return not (latitude == 0.0 and longitude == 0.0)


def fetch_forecast(
    http_get_lines,  # (url, on_line, timeout_sec) -> None
    lat: float,
    lon: float,
    metrics: str,
    timeout_sec: int,
    forecast_hours: int,
    past_hours: int,
    on_hour,  # (int, list[int | float | None]) -> None
) -> None:
    """Pass each hour of the forecast ``metrics``, from ``past_hours`` back to ``forecast_hours`` ahead, to
    ``on_hour``.

    ``metrics`` lists Open-Meteo hourly variables, comma-separated.  ``on_hour(utc_epoch, values)`` gets each hour's
    UTC start, in ascending order, and its values in ``metrics`` order: an int where the body has digits only, a
    float for any other number, ``None`` where one is missing.  Raises ``HttpParseError`` unless the body holds
    exactly those hours, and whatever ``http_get_lines`` raises.
    """
    _fetch_hourly(http_get_lines, _FORECAST_URL, lat, lon, metrics, timeout_sec, forecast_hours, past_hours, on_hour)


def fetch_air_quality(
    http_get_lines,  # (url, on_line, timeout_sec) -> None
    lat: float,
    lon: float,
    metrics: str,
    timeout_sec: int,
    forecast_hours: int,
    past_hours: int,
    on_hour,  # (int, list[int | float | None]) -> None
) -> None:
    """As ``fetch_forecast``, for air-quality ``metrics``; ``forecast_hours`` is capped at
    ``AIR_QUALITY_MAX_FORECAST_HOURS``."""
    if forecast_hours > AIR_QUALITY_MAX_FORECAST_HOURS:
        forecast_hours = AIR_QUALITY_MAX_FORECAST_HOURS
    _fetch_hourly(
        http_get_lines, _AIR_QUALITY_URL, lat, lon, metrics, timeout_sec, forecast_hours, past_hours, on_hour
    )


def _fetch_hourly(
    http_get_lines, base: str, lat: float, lon: float, metrics: str, timeout_sec: int, forecast_hours: int,
    past_hours: int, on_hour,
) -> None:
    reader = _HourlyCsv(metrics, past_hours + forecast_hours, on_hour)
    http_get_lines(
        _build_url(base, lat, lon, metrics, forecast_hours, past_hours), reader.feed, timeout_sec=timeout_sec
    )
    reader.finish()


class _HourlyCsv:
    """Parser for Open-Meteo's hourly CSV body, fed a line at a time, that passes each row to ``on_hour``.

    Raises ``HttpParseError`` unless the header names ``time`` and then ``metrics`` in order, and the body holds
    ``row_count`` rows, an hour apart, of a number for each.  A row's values list is new for each call.
    """

    def __init__(
        self,
        metrics: str,
        row_count: int,
        on_hour,  # (int, list[int | float | None]) -> None
    ) -> None:
        self._names = bytes(metrics, "utf-8").split(b",")
        self._row_count = row_count
        self._on_hour = on_hour
        self._lines_before_header = 0
        self._header_seen = False
        self._rows_seen = 0
        self._last_utc = 0

    def feed(self, line: bytes) -> None:
        # Error texts of up to 10 bytes are interned once, where longer ones would each be a str on the heap.
        if not self._header_seen:
            if line.startswith(b"time,"):
                self._check_header(line)
                self._header_seen = True
                return
            self._lines_before_header += 1
            if self._lines_before_header > _MAX_LINES_BEFORE_HEADER:
                raise HttpParseError("bad header")
            return
        if not line:
            return
        values = line.split(b",")
        if self._rows_seen == self._row_count or len(values) != len(self._names) + 1:
            raise HttpParseError("bad row")
        # The values replace their fields in the split list, rather than filling a second list.
        try:
            utc_epoch = int(values.pop(0))
            for i in range(len(values)):
                field = values[i]
                if not field or field == b"NaN":
                    values[i] = None
                # Open-Meteo writes most zeros so: the shared 0.0 saves boxing a float for each.
                elif field == b"0.0" or field == b"0.00":
                    values[i] = 0.0
                # A whole number, such as a percentage, a WMO code or the AQI, becomes a small int: no float to box.
                elif field.isdigit():
                    values[i] = int(field)
                else:
                    values[i] = float(field)
        except ValueError:
            raise HttpParseError("bad row")
        if self._rows_seen and utc_epoch != self._last_utc + _SEC_PER_HOUR:
            raise HttpParseError("bad row")
        self._last_utc = utc_epoch
        self._rows_seen += 1
        self._on_hour(utc_epoch, values)

    def finish(self) -> None:
        """Raise ``HttpParseError`` unless every row has been fed."""
        if not self._header_seen or self._rows_seen != self._row_count:
            raise HttpParseError("rows short")

    def _check_header(self, line: bytes) -> None:
        columns = line.split(b",")
        names = self._names
        if len(columns) != len(names) + 1:
            raise HttpParseError("bad header")
        for i in range(len(names)):
            column = columns[i + 1]
            name = names[i]
            # Open-Meteo names a column "<metric> (<unit>)".
            if column != name and not column.startswith(name + b" ("):
                raise HttpParseError("bad header")
