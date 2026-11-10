import time

from micropython import const

from displays.palette import STREAM_GREEN, STREAM_YELLOW, STREAM_RED
from scheduling import event_runs
from scheduling.event import Event
from services import http_client, openmeteo_client
from services._event_stream_service import EventStreamService
from services.fetch_machine import FetchCoordinator
from services.tick_scheduler import TickScheduler

_METRICS = "precipitation_probability,precipitation,weathercode,uv_index"

# Standard meteorological light / moderate / heavy rain-rate edges (mm/h).
_MODERATE_MM = 2.5
_HEAVY_MM = 7.6

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

_UV_LEVEL_COLOR = (None, STREAM_YELLOW, STREAM_RED)


def _precip_label(wmo_code: int) -> str | None:
    """Return ``None`` for non-precipitation codes: probability alone must not
    draw a precipitation bar.
    """
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


def _precip_rank_and_color(precip_mm: float) -> tuple[int, int]:
    """Ranks 1/2/3 mean light/moderate/heavy."""
    if precip_mm < _MODERATE_MM:
        return (1, STREAM_GREEN)
    if precip_mm < _HEAVY_MM:
        return (2, STREAM_YELLOW)
    return (3, STREAM_RED)


def _uv_column(payload: dict, n: int) -> list[float | None]:
    """Return the payload's ``n`` hourly UV index values.

    Precip must render even if UV is absent or malformed, so any problem
    degrades to ``None`` rather than failing the fetch: a missing key, non-list
    or wrong-length array gives an all-``None`` column, and a non-numeric
    element gives ``None`` for that hour.
    """
    try:
        uv = payload["hourly"]["uv_index"]
    except (KeyError, TypeError):
        return [None] * n
    if not isinstance(uv, list) or len(uv) != n:
        return [None] * n
    return [v if isinstance(v, (int, float)) else None for v in uv]


def _build_events(payload: dict, prob_threshold_pct: int, uv_thresholds: tuple[int, int]) -> list[Event]:
    """Return the weather bars from a forecast payload.

    Precipitation wins equal-priority ties; severe UV beats light precipitation.
    """
    times, probs, amounts, codes = openmeteo_client.extract_hourly(
        payload, ("time", "precipitation_probability", "precipitation", "weathercode")
    )
    uv = _uv_column(payload, len(times))
    uv_warn, uv_severe = uv_thresholds

    emitted: list[tuple[int, str, int]] = []
    for i in range(len(times)):
        candidates = []
        prob = probs[i]
        kind = None if (prob is None or prob < prob_threshold_pct) else _precip_label(codes[i])
        if kind is not None:
            precip_mm = amounts[i] if amounts[i] is not None else 0.0
            rank, color = _precip_rank_and_color(precip_mm)
            candidates.append((rank, kind, color))
        uv_lvl = event_runs.level(uv[i], uv_warn, uv_severe)
        if uv_lvl:
            candidates.append((uv_lvl, "UV", _UV_LEVEL_COLOR[uv_lvl]))

        win = event_runs.best_by_priority(candidates)
        if win is not None:
            emitted.append((openmeteo_client.parse_iso_local(times[i]), win[0], win[1]))

    return event_runs.merge_runs(emitted)


class WeatherService(EventStreamService):
    """Weather row (precipitation + UV) over one Open-Meteo forecast fetch.

    Precipitation and UV rarely coincide, so sharing a row keeps it dense.

    Stays disabled unless ``openmeteo_client.is_location_set(latitude, longitude)``.
    """

    def __init__(
        self,
        latitude: float,
        longitude: float,
        prob_threshold_pct: int,
        uv_thresholds: tuple[int, int],
        wifi,  # has is_connected() -> bool
        coordinator: FetchCoordinator,
        schedule,  # (callback, arg) -> None
        interval_ms: int,
        forecast_hours: int,
        past_hours: int,
        get_ticks_ms=time.ticks_ms,  # () -> int
        http_get=http_client.get_json,  # (url, timeout_sec) -> dict
        timeout_sec: int = 3,
        tick_scheduler: TickScheduler | None = None,
    ) -> None:
        self._lat = latitude
        self._lon = longitude
        self._prob_threshold_pct = prob_threshold_pct
        self._uv_thresholds = uv_thresholds
        self._http_get = http_get
        self._timeout_sec = timeout_sec
        self._forecast_hours = forecast_hours
        self._past_hours = past_hours
        enabled = openmeteo_client.is_location_set(latitude, longitude)
        super().__init__(
            wifi, coordinator, schedule, interval_ms, "weather", enabled,
            get_ticks_ms=get_ticks_ms, tick_scheduler=tick_scheduler,
        )
        if enabled:
            print("[weather] enabled: lat=%s lon=%s" % (latitude, longitude))
        else:
            print("[weather] disabled: set LATITUDE/LONGITUDE in config.py")

    def _fetch_and_parse(self) -> list[Event]:
        print("[weather] fetching lat=%s lon=%s" % (self._lat, self._lon))
        payload = openmeteo_client.fetch_forecast(
            self._http_get, self._lat, self._lon, _METRICS, self._timeout_sec,
            self._forecast_hours, self._past_hours,
        )
        return _build_events(payload, self._prob_threshold_pct, self._uv_thresholds)
