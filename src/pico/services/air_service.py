"""Outdoor air-quality calendar stream (Open-Meteo): AQI + pollen.

Long-lived ``EventStreamService`` subclass: polls the air-quality API every 30 min and
combines each hour's AQI and pollen into a single worst-of-N severity, emitting
one bar per contiguous run of equal (metric, severity).  Disabled until real
coordinates are configured.
"""

import time

from displays.palette import STREAM_YELLOW, STREAM_RED
from scheduling import event_runs
from scheduling.event import Event
from services import http_client, openmeteo_client
from services._event_stream_service import EventStreamService

# Severity level (1 warning / 2 severe) -> global palette index.
_LEVEL_COLOR = (None, STREAM_YELLOW, STREAM_RED)


def _pollen_winner(labels, values, warn, severe):  # -> (level, label)
    """Pick the dominant pollen for one hour.

    Highest severity wins; ties broken by the highest raw count (not list
    order).  Returns ``(0, None)`` when every species is below warning.
    """
    best_level = 0
    best_label = None
    best_value = -1.0
    for i in range(len(values)):
        v = values[i]
        if v is None:
            continue
        lvl = event_runs._level(v, warn, severe)
        if lvl == 0:
            continue  # below warning: never a winner
        if lvl > best_level or (lvl == best_level and v > best_value):
            best_level = lvl
            best_label = labels[i]
            best_value = v
    return best_level, best_label


def _build_events(aq_payload, species, aqi_thr, pollen_thr) -> list[Event]:
    """Merge an air-quality payload into air bars.

    Each hour picks the worse of AQI and pollen (AQI wins ties); contiguous
    equal winners merge into one bar.  Raises on a malformed payload (missing
    keys or mismatched array lengths) so the caller's fetch state machine backs
    off and keeps the last good snapshot.
    """
    pollen_keys = tuple(s + "_pollen" for s in species)
    arrays = openmeteo_client.extract_hourly(aq_payload, ("time", "european_aqi") + pollen_keys)
    times = arrays[0]
    aqi_arr = arrays[1]
    pollen_arrs = arrays[2:]
    pollen_labels = tuple(s.upper() for s in species)
    aqi_warn, aqi_severe = aqi_thr

    emitted = []  # (epoch, label, color_index) per winning hour
    for i in range(len(times)):
        candidates = []
        aqi_lvl = event_runs._level(aqi_arr[i], aqi_warn, aqi_severe)
        if aqi_lvl:
            candidates.append((aqi_lvl, "AQI", _LEVEL_COLOR[aqi_lvl]))
        pol_lvl, pol_label = _pollen_winner(
            pollen_labels, [arr[i] for arr in pollen_arrs], pollen_thr[0], pollen_thr[1]
        )
        if pol_lvl:
            candidates.append((pol_lvl, pol_label, _LEVEL_COLOR[pol_lvl]))

        win = event_runs.best_by_priority(candidates)
        if win is not None:
            emitted.append((openmeteo_client.parse_iso_local(times[i]), win[0], win[1]))

    return event_runs.merge_runs(emitted)


class AirService(EventStreamService):
    """Air row (European AQI + pollen) over one Open-Meteo air-quality fetch."""

    def __init__(
        self,
        latitude: float,
        longitude: float,
        species,  # list[str] of pollen names
        aqi_thresholds: tuple[int, int],
        pollen_thresholds: tuple[int, int],
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
        self._species = tuple(species)
        self._aqi_thr = aqi_thresholds
        self._pollen_thr = pollen_thresholds
        self._http_get = http_get
        self._timeout_s = timeout_s
        self._forecast_hours = forecast_hours
        self._past_hours = past_hours
        # Empty POLLEN_SPECIES is a valid (AQI-only) config, so build the metrics
        # string from a field list to avoid a trailing comma the API rejects.
        self._metrics = ",".join(["european_aqi"] + [s + "_pollen" for s in self._species])
        # Coordinates left at 0.0/0.0 mean "unconfigured": stay disabled rather
        # than silently fetch Gulf-of-Guinea air quality.
        enabled = not (latitude == 0.0 and longitude == 0.0)
        super().__init__(
            wifi, coordinator, schedule, interval_ms, "air", enabled,
            clock=clock, tick_scheduler=tick_scheduler,
        )
        if enabled:
            print("[air] enabled: lat=%s lon=%s" % (latitude, longitude))
        else:
            print("[air] disabled: set LATITUDE/LONGITUDE in config.py")

    def _fetch_and_parse(self) -> list[Event]:
        # Fallible: HTTP error or malformed payload raises -> the loop backs off.
        print("[air] fetching lat=%s lon=%s" % (self._lat, self._lon))
        payload = openmeteo_client.fetch_air_quality(
            self._http_get, self._lat, self._lon, self._metrics, self._timeout_s,
            self._forecast_hours, self._past_hours,
        )
        return _build_events(payload, self._species, self._aqi_thr, self._pollen_thr)
