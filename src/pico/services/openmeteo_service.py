import time

from micropython import const

from displays.palette import STREAM_SEVERITY
from scheduling import event_runs
from scheduling.event import Event
from services._event_stream_service import EventStreamService
from services.http_client import HttpClient, HttpParseError
from services.tick_scheduler import TickScheduler

# HTTP (not HTTPS) on purpose: no TLS handshake and its large contiguous-heap block.
_FORECAST_URL = "http://api.open-meteo.com/v1/forecast"
_AIR_QUALITY_URL = "http://air-quality-api.open-meteo.com/v1/air-quality"

# The air-quality API answers a longer forecast with HTTP 400.
_AIR_QUALITY_MAX_FORECAST_HOURS = const(168)

_SEC_PER_HOUR = const(3600)
# The header row follows the location's column names, their values and a blank line.
_MAX_LINES_BEFORE_HEADER = const(3)

_FORECAST_METRICS = "precipitation_probability,precipitation,weathercode,uv_index"

# Precipitation, UV and AQI.
_STREAMS_BEFORE_POLLEN = const(3)

# Any amount, then the standard meteorological moderate and heavy rain rates (mm/h).
_PRECIP_THRESHOLDS_MM = (0.0, 2.5, 7.6)

# WMO weather interpretation codes (Open-Meteo ``weathercode``), as inclusive ranges.
_WMO_DRIZZLE_AND_RAIN_FIRST = const(51)  # freezing drizzle and freezing rain included
_WMO_DRIZZLE_AND_RAIN_LAST = const(67)
_WMO_SNOW_FIRST = const(71)  # snow grains included
_WMO_SNOW_LAST = const(77)
_WMO_RAIN_SHOWERS_FIRST = const(80)
_WMO_RAIN_SHOWERS_LAST = const(82)
_WMO_SNOW_SHOWERS_FIRST = const(85)
_WMO_SNOW_SHOWERS_LAST = const(86)
_WMO_THUNDERSTORM_FIRST = const(95)  # hail included
_WMO_THUNDERSTORM_LAST = const(99)


def _precip_label(wmo_code: float | None) -> str | None:
    """Return ``None`` for a missing or non-precipitation code: probability alone must not
    draw a precipitation bar.
    """
    if wmo_code is None:
        return None
    if (
        _WMO_DRIZZLE_AND_RAIN_FIRST <= wmo_code <= _WMO_DRIZZLE_AND_RAIN_LAST
        or _WMO_RAIN_SHOWERS_FIRST <= wmo_code <= _WMO_RAIN_SHOWERS_LAST
    ):
        return "RAIN"
    if (
        _WMO_SNOW_FIRST <= wmo_code <= _WMO_SNOW_LAST
        or _WMO_SNOW_SHOWERS_FIRST <= wmo_code <= _WMO_SNOW_SHOWERS_LAST
    ):
        return "SNOW"
    if _WMO_THUNDERSTORM_FIRST <= wmo_code <= _WMO_THUNDERSTORM_LAST:
        return "STORM"
    return None


class _WeatherHours:
    """The precipitation and UV events of a forecast, built an hour at a time."""

    def __init__(
        self,
        prob_threshold_pct: int,
        uv_thresholds: tuple[float, float, float],
        max_events: int,
        now_utc: int,
    ) -> None:
        self._prob_threshold_pct = prob_threshold_pct
        self._uv_thresholds = uv_thresholds
        self.precip = event_runs.RunBuilder(STREAM_SEVERITY, max_events, now_utc)
        self.uv = event_runs.RunBuilder(STREAM_SEVERITY, max_events, now_utc)

    def add_hour(self, utc_epoch: int, values: list[float | None]) -> None:
        """Add one hour's ``_FORECAST_METRICS`` values."""
        prob, amount_mm, wmo_code, uv_index = values
        kind = None if (prob is None or prob < self._prob_threshold_pct) else _precip_label(wmo_code)
        precip_level = 0
        if kind is not None:
            # The WMO code already says it precipitates, so a missing amount still warns.
            precip_level = event_runs.level(amount_mm if amount_mm is not None else 0.0, _PRECIP_THRESHOLDS_MM)
        self.precip.add(utc_epoch, kind, precip_level)
        self.uv.add(utc_epoch, "UV", event_runs.level(uv_index, self._uv_thresholds))


class _AirHours:
    """The AQI and per-species pollen events of an air-quality forecast, built an hour at a time.

    ``pollen`` holds a builder per species, in ``pollen_thresholds`` order, each measuring its counts against its own
    thresholds and labelling its events with the species' label.
    """

    def __init__(
        self,
        aqi_thresholds: tuple[float, float, float],
        pollen_thresholds: list[tuple[str, str, tuple[float, float, float]]],
        max_events: int,
        now_utc: int,
    ) -> None:
        self._aqi_thresholds = aqi_thresholds
        self._pollen_labels = tuple(label for _, label, _ in pollen_thresholds)
        self._species_thresholds = tuple(edges for _, _, edges in pollen_thresholds)
        self.aqi = event_runs.RunBuilder(STREAM_SEVERITY, max_events, now_utc)
        self.pollen = [event_runs.RunBuilder(STREAM_SEVERITY, max_events, now_utc) for _ in pollen_thresholds]

    def add_hour(self, utc_epoch: int, values: list[float | None]) -> None:
        """Add one hour's values: the AQI, then each species' count in ``pollen_thresholds`` order."""
        self.aqi.add(utc_epoch, "AQI", event_runs.level(values[0], self._aqi_thresholds))
        builders = self.pollen
        labels = self._pollen_labels
        thresholds = self._species_thresholds
        for i in range(len(builders)):
            builders[i].add(utc_epoch, labels[i], event_runs.level(values[i + 1], thresholds[i]))


def _parse_hourly_csv(
    lines,  # Iterable[bytes]
    metrics: str,
    row_count: int,
    on_hour,  # (int, list[int | float | None]) -> None
) -> None:
    """Parse Open-Meteo's hourly CSV body from ``lines``, passing each row to ``on_hour``, and read it to its end.

    ``on_hour(utc_epoch, values)`` gets each hour's UTC start, in ascending order, and its values in ``metrics``
    order: an int where the field has digits only, a float for any other number, ``None`` where one is missing.  A
    row's values list is new for each call.  Raises ``HttpParseError`` unless the header names ``time`` and then
    ``metrics`` in order, and the body holds ``row_count`` rows, an hour apart, of a number for each.
    """
    # One loop with locals rather than a reader fed a line at a time, whose method would allocate its frame on the heap
    # for every line.  Error texts of up to 10 bytes are interned once, where longer ones would each be a str on the
    # heap.
    names = bytes(metrics, "utf-8").split(b",")
    field_count = len(names) + 1
    lines_before_header = 0
    header_seen = False
    rows_seen = 0
    last_utc = 0
    for line in lines:
        if not header_seen:
            if line.startswith(b"time,"):
                _check_header(line, names)
                header_seen = True
                continue
            lines_before_header += 1
            if lines_before_header > _MAX_LINES_BEFORE_HEADER:
                raise HttpParseError("bad header")
            continue
        if not line:
            continue
        values = line.split(b",")
        if rows_seen == row_count or len(values) != field_count:
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
        if rows_seen and utc_epoch != last_utc + _SEC_PER_HOUR:
            raise HttpParseError("bad row")
        last_utc = utc_epoch
        rows_seen += 1
        on_hour(utc_epoch, values)
    if not header_seen or rows_seen != row_count:
        raise HttpParseError("rows short")


def _check_header(line: bytes, names: list[bytes]) -> None:
    columns = line.split(b",")
    if len(columns) != len(names) + 1:
        raise HttpParseError("bad header")
    for i in range(len(names)):
        column = columns[i + 1]
        name = names[i]
        # Open-Meteo names a column "<metric> (<unit>)".
        if column != name and not column.startswith(name + b" ("):
            raise HttpParseError("bad header")


class OpenMeteoService(EventStreamService):
    """Precipitation, UV and AQI streams, then a pollen stream per species in ``pollen_thresholds`` order, their
    events coloured by warning level, from one Open-Meteo forecast request and one air-quality request.

    The streams are published together: if either request fails, none is, and both are retried after a backoff.
    Warning: both requests run in one deferred job, which blocks rendering and button handling until both return.

    ``pollen_thresholds`` lists ``(species, label, levels)``: an Open-Meteo pollen name without its ``_pollen``
    suffix, the label of its events, and the ascending grains/m³ that start levels 1-3.  Each stream looks from
    ``past_hours`` back to ``forecast_hours`` ahead, but AQI and pollen at most 168 hours ahead, the air-quality API's
    limit.  Each stream keeps at most ``max_events`` events not over by the fetch, at ``get_utc_time``.  Stays disabled
    unless the coordinates are set: 0.0/0.0, a point at sea, means unset.
    """

    def __init__(
        self,
        latitude: float,
        longitude: float,
        prob_threshold_pct: int,
        uv_thresholds: tuple[float, float, float],
        aqi_thresholds: tuple[float, float, float],
        pollen_thresholds: list[tuple[str, str, tuple[float, float, float]]],
        http_client: HttpClient,
        tick_scheduler: TickScheduler,
        interval_ms: int,
        forecast_hours: int,
        past_hours: int,
        max_events: int,
        get_utc_time=time.time,  # () -> int
        get_ticks_ms=time.ticks_ms,  # () -> int
    ) -> None:
        self._http_client = http_client
        self._lat = latitude
        self._lon = longitude
        self._prob_threshold_pct = prob_threshold_pct
        self._uv_thresholds = uv_thresholds
        self._aqi_thresholds = aqi_thresholds
        self._pollen_thresholds = pollen_thresholds
        self._air_metrics = ",".join(["european_aqi"] + [species + "_pollen" for species, _, _ in pollen_thresholds])
        self._forecast_hours = forecast_hours
        self._past_hours = past_hours
        self._max_events = max_events
        self._get_utc_time = get_utc_time
        enabled = not (latitude == 0.0 and longitude == 0.0)
        super().__init__(
            tick_scheduler, interval_ms, "meteo", enabled, stream_count=_STREAMS_BEFORE_POLLEN + len(pollen_thresholds),
            get_ticks_ms=get_ticks_ms,
        )
        if enabled:
            print("[meteo] enabled: lat=%s lon=%s" % (latitude, longitude))
        else:
            print("[meteo] disabled: set LATITUDE/LONGITUDE in config.py")

    def _fetch_and_parse(self) -> tuple[list[Event], ...]:
        now_utc = self._get_utc_time()
        print("[meteo] fetching %s lat=%s lon=%s" % ("forecast", self._lat, self._lon))
        weather = _WeatherHours(self._prob_threshold_pct, self._uv_thresholds, self._max_events, now_utc)
        self._fetch_hourly(_FORECAST_URL, _FORECAST_METRICS, self._forecast_hours, weather.add_hour)
        precip = weather.precip.events()
        uv = weather.uv.events()
        # Drops the builders, so the collection before the air request can reclaim them; only their events are kept.
        del weather

        print("[meteo] fetching %s lat=%s lon=%s" % ("air", self._lat, self._lon))
        air = _AirHours(self._aqi_thresholds, self._pollen_thresholds, self._max_events, now_utc)
        self._fetch_hourly(
            _AIR_QUALITY_URL, self._air_metrics, min(self._forecast_hours, _AIR_QUALITY_MAX_FORECAST_HOURS),
            air.add_hour,
        )
        return (precip, uv, air.aqi.events()) + tuple([builder.events() for builder in air.pollen])

    def _fetch_hourly(
        self,
        base_url: str,
        metrics: str,
        forecast_hours: int,
        on_hour,  # (int, list[int | float | None]) -> None
    ) -> None:
        """Pass each hour of ``metrics`` at ``base_url``, from ``past_hours`` back to ``forecast_hours`` ahead, to
        ``on_hour``, as ``_parse_hourly_csv`` does.

        Raises what ``_parse_hourly_csv``, ``HttpClient.get`` and ``Response.lines`` raise.
        """
        # CSV, unlike JSON, parses a row at a time.  Rows are UTC Unix times: in a time zone, every row would take
        # the offset in force when it was requested, an hour out past a DST change.  The URL isn't kept in a local,
        # so it's garbage while the body streams.
        with self._http_client.get(
            "%s?format=csv&timeformat=unixtime&timezone=GMT&latitude=%s&longitude=%s&hourly=%s&past_hours=%s"
            "&forecast_hours=%s" % (base_url, self._lat, self._lon, metrics, self._past_hours, forecast_hours)
        ) as response:
            _parse_hourly_csv(response.lines(), metrics, self._past_hours + forecast_hours, on_hour)
