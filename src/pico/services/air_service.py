import time

from displays.palette import STREAM_SEVERITY
from scheduling import event_runs
from scheduling.event import Event
from services import http_client, openmeteo_client
from services._event_stream_service import EventStreamService
from services.fetch_machine import FetchCoordinator
from services.tick_scheduler import TickScheduler


class _AirHours:
    """The AQI and pollen events of an air-quality forecast, built an hour at a time.

    An hour's pollen warning is the species with the highest level, each measured against its own thresholds, so raw
    counts aren't compared: a tie goes to the species listed first.
    """

    def __init__(
        self,
        aqi_thresholds: tuple[float, float, float],
        pollen_thresholds: list[tuple[str, tuple[float, float, float]]],
        utc_offset_sec,  # (int) -> int
        max_events: int,
        now_utc: int,
    ) -> None:
        self._aqi_thresholds = aqi_thresholds
        self._pollen_labels = tuple(species.upper() for species, _ in pollen_thresholds)
        self._species_thresholds = tuple(edges for _, edges in pollen_thresholds)
        self.aqi = event_runs.RunBuilder(STREAM_SEVERITY, utc_offset_sec, max_events, now_utc)
        self.pollen = event_runs.RunBuilder(STREAM_SEVERITY, utc_offset_sec, max_events, now_utc)

    def add_hour(self, utc_epoch: int, values: list[float | None]) -> None:
        """Add one hour's values: the AQI, then each species' count in ``pollen_thresholds`` order."""
        self.aqi.add(utc_epoch, "AQI", event_runs.level(values[0], self._aqi_thresholds))
        # Inline, rather than a helper taking values[1:], as that slice and a returned tuple would cost two
        # allocations a row.
        thresholds = self._species_thresholds
        best_level = 0
        best_index = 0
        for i in range(len(thresholds)):
            species_level = event_runs.level(values[i + 1], thresholds[i])
            if species_level > best_level:
                best_level = species_level
                best_index = i
        self.pollen.add(utc_epoch, self._pollen_labels[best_index] if best_level else None, best_level)


class AirService(EventStreamService):
    """European AQI and pollen streams over one Open-Meteo air-quality fetch, coloured by warning level.

    ``pollen_thresholds`` lists ``(species, levels)``: an Open-Meteo pollen name without its ``_pollen``
    suffix, and the ascending grains/m³ that start levels 1-3.  Event times are local, by ``utc_offset_sec``; each
    stream keeps at most ``max_events`` events not over by the fetch, at ``get_utc_time``.

    Stays disabled unless ``openmeteo_client.is_location_set(latitude, longitude)``.
    """

    def __init__(
        self,
        latitude: float,
        longitude: float,
        aqi_thresholds: tuple[float, float, float],
        pollen_thresholds: list[tuple[str, tuple[float, float, float]]],
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
        self._aqi_thresholds = aqi_thresholds
        self._pollen_thresholds = pollen_thresholds
        self._http_get_lines = http_get_lines
        self._timeout_sec = timeout_sec
        self._forecast_hours = forecast_hours
        self._past_hours = past_hours
        self._utc_offset_sec = utc_offset_sec
        self._max_events = max_events
        self._get_utc_time = get_utc_time
        self._metrics = ",".join(["european_aqi"] + [species + "_pollen" for species, _ in pollen_thresholds])
        enabled = openmeteo_client.is_location_set(latitude, longitude)
        super().__init__(
            wifi, coordinator, schedule, interval_ms, "air", enabled, stream_count=2,
            get_ticks_ms=get_ticks_ms, tick_scheduler=tick_scheduler,
        )
        if enabled:
            print("[air] enabled: lat=%s lon=%s" % (latitude, longitude))
        else:
            print("[air] disabled: set LATITUDE/LONGITUDE in config.py")

    def _fetch_and_parse(self) -> tuple[list[Event], list[Event]]:
        print("[air] fetching lat=%s lon=%s" % (self._lat, self._lon))
        hours = _AirHours(
            self._aqi_thresholds, self._pollen_thresholds, self._utc_offset_sec, self._max_events,
            self._get_utc_time(),
        )
        openmeteo_client.fetch_air_quality(
            self._http_get_lines, self._lat, self._lon, self._metrics, self._timeout_sec,
            self._forecast_hours, self._past_hours, hours.add_hour,
        )
        return hours.aqi.events(), hours.pollen.events()
