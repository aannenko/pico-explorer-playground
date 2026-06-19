"""Precipitation forecast calendar stream (Open-Meteo).

Long-lived service: a ``FetchState`` polls Open-Meteo every 30 min, parses
the hourly forecast into per-run ``Event`` bars (background = intensity
green/yellow/red, label = type RAIN/SNOW/STORM) and bumps a generation the
calendar watches.  Disabled until real coordinates are configured.
"""

import time

from micropython import const

from displays.palette import STREAM_GREEN, STREAM_YELLOW, STREAM_RED
from scheduling.event import Event
from scheduling.stream import DISABLED
from services import http_client
from services._fetch_state import FetchState

# Plain HTTP (not HTTPS) on purpose: the data is public and keyless, and the
# RP2040's TLS handshake needs a large contiguous heap block that isn't
# reliably available after the framebuffer + WiFi stack (raises ENOMEM).
_FORECAST_URL = "http://api.open-meteo.com/v1/forecast"
_HOURLY = "precipitation_probability,precipitation,weathercode,uv_index"
_REFRESH_MS = const(30 * 60 * 1000)
_SEC_PER_HOUR = const(3600)

# Standard meteorological light / moderate / heavy rain-rate edges (mm/h).
_MODERATE_MM = 2.5
_HEAVY_MM = 7.6


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


def _intensity_index(mm: float) -> int:
    """Map an hourly precipitation amount to a global palette index."""
    if mm < _MODERATE_MM:
        return STREAM_GREEN
    if mm < _HEAVY_MM:
        return STREAM_YELLOW
    return STREAM_RED


def _parse_iso_local(text: str) -> int:
    """Parse a naive-local ``"YYYY-MM-DDTHH:MM"`` string to a local epoch.

    Open-Meteo with ``timezone=auto`` returns already-local times, so
    ``mktime`` of the components yields the local epoch directly (no DST math).
    """
    year = int(text[0:4])
    month = int(text[5:7])
    day = int(text[8:10])
    hour = int(text[11:13])
    minute = int(text[14:16])
    return time.mktime((year, month, day, hour, minute, 0, 0, 0))


def _build_events(payload: dict, threshold: int) -> list[Event]:
    """Turn an Open-Meteo forecast payload into merged precipitation bars.

    Emits one bar per contiguous run of hours sharing the same ``(type,
    intensity)``; hours below ``threshold`` probability — or whose
    weathercode isn't precipitation — split runs and emit nothing.  Raises
    on a malformed payload (missing keys, mismatched array lengths) so the
    caller's fetch state machine counts it as a failure and keeps the last
    good snapshot.
    """
    hourly = payload["hourly"]
    times = hourly["time"]
    probs = hourly["precipitation_probability"]
    amounts = hourly["precipitation"]
    codes = hourly["weathercode"]

    n = len(times)
    if not (len(probs) == n and len(amounts) == n and len(codes) == n):
        raise ValueError("Open-Meteo hourly arrays have mismatched lengths")

    events: list[Event] = []
    run = None  # [type, color_index, start_ts, end_ts]

    for i in range(n):
        prob = probs[i]
        kind = None if (prob is None or prob < threshold) else _weather_type(codes[i])
        if kind is None:
            # Below threshold, or not a precipitation code: end any open run.
            if run is not None:
                events.append(_event_from_run(run))
                run = None
            continue

        start_ts = _parse_iso_local(times[i])
        mm = amounts[i] if amounts[i] is not None else 0.0
        color_index = _intensity_index(mm)

        if run is not None and run[0] == kind and run[1] == color_index and run[3] == start_ts:
            run[3] = start_ts + _SEC_PER_HOUR
        else:
            if run is not None:
                events.append(_event_from_run(run))
            run = [kind, color_index, start_ts, start_ts + _SEC_PER_HOUR]

    if run is not None:
        events.append(_event_from_run(run))
    return events


def _event_from_run(run: list) -> Event:
    kind, color_index, start_ts, end_ts = run
    return Event(kind, start_ts, end_ts - start_ts, color_index=color_index)


class PrecipService:
    """Drives precip fetch/parse/publish; the calendar reads it passively."""

    def __init__(
        self,
        latitude: float,
        longitude: float,
        prob_threshold: int,
        wifi,  # has is_connected() -> bool
        coordinator,  # FetchCoordinator
        schedule,  # (callback, arg) -> None
        clock=time.ticks_ms,  # () -> int
        http_get=http_client.get_json,  # (url, timeout_s) -> dict
        timeout_s: int = 3,
        interval_ms: int = _REFRESH_MS,
        tick_scheduler=None,
    ) -> None:
        self._lat = latitude
        self._lon = longitude
        self._threshold = prob_threshold
        self._http_get = http_get
        self._timeout_s = timeout_s
        # Coordinates left at 0.0/0.0 mean "unconfigured": stay disabled
        # rather than silently fetch Gulf-of-Guinea weather.
        self._enabled = not (latitude == 0.0 and longitude == 0.0)

        self._events: list[Event] = []
        self._payload: dict | None = None
        self._generation: int = 0
        self._fetch = FetchState(
            self._fetch_and_parse,
            self._store,
            wifi,
            coordinator,
            interval_ms,
            schedule=schedule,
            clock=clock,
            name="precip",
        )
        self._tick_ref = self.tick
        if tick_scheduler is not None:
            tick_scheduler.register(self._tick_ref)

        if self._enabled:
            print("[precip] enabled: lat=%s lon=%s" % (latitude, longitude))
        else:
            print("[precip] disabled: set LATITUDE/LONGITUDE in config.py")

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

    @property
    def payload(self) -> dict | None:
        # Latest raw forecast; the advisory service reads its UV channel.
        return self._payload

    def _url(self) -> str:
        return (
            _FORECAST_URL
            + "?latitude=" + str(self._lat)
            + "&longitude=" + str(self._lon)
            + "&hourly=" + _HOURLY
            + "&timezone=auto&forecast_days=2"
        )

    def _fetch_and_parse(self) -> tuple:
        # Fallible: HTTP error or malformed payload raises -> state machine
        # backs off without publishing.
        url = self._url()
        print("[precip] fetching", url)
        payload = self._http_get(url, timeout_s=self._timeout_s)
        return (payload, _build_events(payload, self._threshold))

    def _store(self, result: tuple) -> None:
        # Infallible: publish the parsed snapshot and bump the generation.
        self._payload, self._events = result
        self._generation += 1
        print("[precip] published %d events (gen %d)" % (len(self._events), self._generation))
