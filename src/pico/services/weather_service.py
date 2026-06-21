"""Weather forecast calendar stream (Open-Meteo): precipitation + UV.

Long-lived service: a ``FetchState`` polls Open-Meteo every 30 min and emits
one row mixing two temporally anti-correlated metrics — precipitation
(background = intensity green/yellow/red, label RAIN/SNOW/STORM) and the UV
index (label UV).  They rarely coincide (heavy precip ⟺ cloud ⟺ low UV), so
sharing a row keeps it dense.  On the rare overlap, precip wins ties and
heavier precip, but a *severe* UV warning still shows through light precip.
Disabled until real coordinates are configured.
"""

import time

from displays.palette import STREAM_GREEN, STREAM_YELLOW, STREAM_RED
from scheduling import event_runs
from scheduling.event import Event
from scheduling.stream import DISABLED
from services import http_client, openmeteo_client
from services._fetch_state import FetchState

_METRICS = "precipitation_probability,precipitation,weathercode,uv_index"

# Standard meteorological light / moderate / heavy rain-rate edges (mm/h).
_MODERATE_MM = 2.5
_HEAVY_MM = 7.6

# UV severity level (1 warning / 2 severe) -> global palette index.
_UV_LEVEL_COLOR = (None, STREAM_YELLOW, STREAM_RED)


def _weather_type(code: int) -> str | None:
    """Map a WMO weather code to a precip label, or None if not precipitation.

    Drizzle / rain / freezing rain / rain showers -> RAIN, snow (incl.
    showers) -> SNOW, thunderstorm -> STORM.  Clear / cloud / fog codes
    return None so the hour is skipped even if its probability cleared the
    gate (a "precip" bar over a clear sky would be misleading).
    """
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "RAIN"
    if 71 <= code <= 77 or code == 85 or code == 86:
        return "SNOW"
    if 95 <= code <= 99:
        return "STORM"
    return None


def _intensity(mm: float) -> tuple[int, int]:
    """Map an hourly precipitation amount to ``(priority_rank, color_index)``.

    Rank 1/2/3 (light/moderate/heavy) ranks precip against UV on the rare
    same-hour overlap; the color is the global palette index.
    """
    if mm < _MODERATE_MM:
        return (1, STREAM_GREEN)
    if mm < _HEAVY_MM:
        return (2, STREAM_YELLOW)
    return (3, STREAM_RED)


def _uv_column(payload: dict, n: int) -> list:
    """Read the hourly ``uv_index`` array defensively (length ``n``).

    UV shares the forecast payload, but precip must render even if UV is
    absent or malformed, so any problem degrades to ``None`` rather than
    failing the fetch: a missing key / non-list / wrong-length array yields an
    all-``None`` column, and a stray non-numeric element yields ``None`` for
    just that hour.
    """
    try:
        uv = payload["hourly"]["uv_index"]
    except (KeyError, TypeError):
        return [None] * n
    if not isinstance(uv, list) or len(uv) != n:
        return [None] * n
    return [v if isinstance(v, (int, float)) else None for v in uv]


def _build_events(payload: dict, prob_threshold: int, uv_thresholds: tuple[int, int]) -> list[Event]:
    """Turn an Open-Meteo forecast payload into merged weather bars.

    Each hour picks the higher-priority of its precipitation and UV
    candidates (precip listed first → wins ties; severe UV still beats light
    precip), and contiguous equal winners merge into one bar.  Raises on a
    malformed payload (missing precip keys, mismatched array lengths) so the
    caller's fetch state machine backs off and keeps the last good snapshot;
    a malformed UV array only suppresses UV (see ``_uv_column``).
    """
    times, probs, amounts, codes = openmeteo_client.extract_hourly(
        payload, ("time", "precipitation_probability", "precipitation", "weathercode")
    )
    uv = _uv_column(payload, len(times))
    uv_warn, uv_severe = uv_thresholds

    emitted = []  # (epoch, label, color_index) per winning hour
    for i in range(len(times)):
        candidates = []
        prob = probs[i]
        kind = None if (prob is None or prob < prob_threshold) else _weather_type(codes[i])
        if kind is not None:
            mm = amounts[i] if amounts[i] is not None else 0.0
            rank, color = _intensity(mm)
            candidates.append((rank, kind, color))
        uv_lvl = event_runs._level(uv[i], uv_warn, uv_severe)
        if uv_lvl:
            candidates.append((uv_lvl, "UV", _UV_LEVEL_COLOR[uv_lvl]))

        win = event_runs.best_by_priority(candidates)
        if win is not None:
            emitted.append((openmeteo_client.parse_iso_local(times[i]), win[0], win[1]))

    return event_runs.merge_runs(emitted)


class WeatherService:
    """Drives weather fetch/parse/publish; the calendar reads it passively."""

    def __init__(
        self,
        latitude: float,
        longitude: float,
        prob_threshold: int,
        uv_thresholds: tuple[int, int],
        wifi,  # has is_connected() -> bool
        coordinator,  # FetchCoordinator
        schedule,  # (callback, arg) -> None
        interval_ms: int,
        forecast_hours: int,
        past_hours: int,
        clock=time.ticks_ms,  # () -> int
        http_get=http_client.get_json,  # (url, timeout_s) -> dict
        timeout_s: int = 3,
        tick_scheduler=None,
    ) -> None:
        self._lat = latitude
        self._lon = longitude
        self._threshold = prob_threshold
        self._uv_thr = uv_thresholds
        self._http_get = http_get
        self._timeout_s = timeout_s
        self._forecast_hours = forecast_hours
        self._past_hours = past_hours
        # Coordinates left at 0.0/0.0 mean "unconfigured": stay disabled
        # rather than silently fetch Gulf-of-Guinea weather.
        self._enabled = not (latitude == 0.0 and longitude == 0.0)

        self._events: list[Event] = []
        self._generation: int = 0
        self._fetch = FetchState(
            self._fetch_and_parse,
            self._store,
            wifi,
            coordinator,
            interval_ms,
            schedule=schedule,
            clock=clock,
            name="weather",
        )
        self._tick_ref = self.tick
        if tick_scheduler is not None:
            tick_scheduler.register(self._tick_ref)

        if self._enabled:
            print("[weather] enabled: lat=%s lon=%s" % (latitude, longitude))
        else:
            print("[weather] disabled: set LATITUDE/LONGITUDE in config.py")

    def tick(self) -> None:
        if self._enabled:
            self._fetch.tick()

    def events_iter(self):  # -> Iterator[Event]
        return iter(self._events)

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def status(self) -> int:
        return self._fetch.status if self._enabled else DISABLED

    def _fetch_and_parse(self) -> list[Event]:
        # Fallible: HTTP error or malformed payload raises -> state machine
        # backs off without publishing.
        print("[weather] fetching lat=%s lon=%s" % (self._lat, self._lon))
        payload = openmeteo_client.fetch_forecast(
            self._http_get, self._lat, self._lon, _METRICS, self._timeout_s,
            self._forecast_hours, self._past_hours,
        )
        return _build_events(payload, self._threshold, self._uv_thr)

    def _store(self, events: list[Event]) -> None:
        # Infallible: publish the parsed snapshot and bump the generation.
        self._events = events
        self._generation += 1
        print("[weather] published %d events (gen %d)" % (len(self._events), self._generation))
