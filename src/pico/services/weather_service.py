import time

from micropython import const

from displays.palette import STREAM_SEVERITY
from scheduling import event_runs
from scheduling.event import Event
from services import http_client, openmeteo_client
from services._event_stream_service import EventStreamService
from services.fetch_machine import FetchCoordinator
from services.tick_scheduler import TickScheduler

_METRICS = "precipitation_probability,precipitation,weathercode,uv_index"

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
        utc_offset_sec,  # (int) -> int
        max_events: int,
        now_utc: int,
    ) -> None:
        self._prob_threshold_pct = prob_threshold_pct
        self._uv_thresholds = uv_thresholds
        self.precip = event_runs.RunBuilder(STREAM_SEVERITY, utc_offset_sec, max_events, now_utc)
        self.uv = event_runs.RunBuilder(STREAM_SEVERITY, utc_offset_sec, max_events, now_utc)

    def add_hour(self, utc_epoch: int, values: list[float | None]) -> None:
        """Add one hour's ``_METRICS`` values."""
        prob, amount_mm, wmo_code, uv_index = values
        kind = None if (prob is None or prob < self._prob_threshold_pct) else _precip_label(wmo_code)
        precip_level = 0
        if kind is not None:
            # The WMO code already says it precipitates, so a missing amount still warns.
            precip_level = event_runs.level(amount_mm if amount_mm is not None else 0.0, _PRECIP_THRESHOLDS_MM)
        self.precip.add(utc_epoch, kind, precip_level)
        self.uv.add(utc_epoch, "UV", event_runs.level(uv_index, self._uv_thresholds))


class WeatherService(EventStreamService):
    """Precipitation and UV streams over one Open-Meteo forecast fetch, coloured by warning level.

    Event times are local, by ``utc_offset_sec``; each stream keeps at most ``max_events`` events not over by the
    fetch, at ``get_utc_time``.  Stays disabled unless ``openmeteo_client.is_location_set(latitude, longitude)``.
    """

    def __init__(
        self,
        latitude: float,
        longitude: float,
        prob_threshold_pct: int,
        uv_thresholds: tuple[float, float, float],
        wifi,  # has is_connected() -> bool
        coordinator: FetchCoordinator,
        schedule,  # (callback, arg) -> None
        interval_ms: int,
        forecast_hours: int,
        past_hours: int,
        utc_offset_sec,  # (int) -> int
        max_events: int,
        get_utc_time=time.time,  # () -> int
        get_ticks_ms=time.ticks_ms,  # () -> int
        http_get_lines=http_client.get_lines,  # (url, on_line, timeout_sec) -> None
        timeout_sec: int = 3,
        tick_scheduler: TickScheduler | None = None,
    ) -> None:
        self._lat = latitude
        self._lon = longitude
        self._prob_threshold_pct = prob_threshold_pct
        self._uv_thresholds = uv_thresholds
        self._http_get_lines = http_get_lines
        self._timeout_sec = timeout_sec
        self._forecast_hours = forecast_hours
        self._past_hours = past_hours
        self._utc_offset_sec = utc_offset_sec
        self._max_events = max_events
        self._get_utc_time = get_utc_time
        enabled = openmeteo_client.is_location_set(latitude, longitude)
        super().__init__(
            wifi, coordinator, schedule, interval_ms, "weather", enabled, stream_count=2,
            get_ticks_ms=get_ticks_ms, tick_scheduler=tick_scheduler,
        )
        if enabled:
            print("[weather] enabled: lat=%s lon=%s" % (latitude, longitude))
        else:
            print("[weather] disabled: set LATITUDE/LONGITUDE in config.py")

    def _fetch_and_parse(self) -> tuple[list[Event], list[Event]]:
        print("[weather] fetching lat=%s lon=%s" % (self._lat, self._lon))
        hours = _WeatherHours(
            self._prob_threshold_pct, self._uv_thresholds, self._utc_offset_sec, self._max_events,
            self._get_utc_time(),
        )
        openmeteo_client.fetch_forecast(
            self._http_get_lines, self._lat, self._lon, _METRICS, self._timeout_sec,
            self._forecast_hours, self._past_hours, hours.add_hour,
        )
        return hours.precip.events(), hours.uv.events()
