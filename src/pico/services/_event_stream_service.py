"""Shared base for the network-backed calendar streams (weather, air).

``WeatherService`` and ``AirService`` differ only in *what* they fetch and how
they classify it into bars; their lifecycle is identical — own a ``FetchState``,
publish a ``list[Event]`` the calendar reads passively, and expose the same
``tick`` / ``status`` / ``generation`` / ``events_iter`` surface.  This base
owns that identical wiring (the ``0.0/0.0`` → disabled gate, ``FetchState``
construction, ``_tick_ref`` caching + scheduler registration, and the
``_store`` snapshot publish); subclasses supply only ``_fetch_and_parse`` plus
their own config.

No allocation/perf change vs. the hand-rolled copies: both objects are built
once at boot, and ``tick`` still just delegates to ``FetchState.tick`` — there
is no new per-tick or per-frame allocation.
"""

import time

from scheduling.event import Event
from scheduling.stream import DISABLED
from services import http_client
from services._fetch_state import FetchState


class EventStreamService:
    """Drives one stream's fetch/parse/publish; the calendar reads it passively.

    Subclasses must implement ``_fetch_and_parse`` (fallible: may raise so the
    state machine backs off) and set any service-specific config *before*
    calling ``super().__init__``.
    """

    def __init__(
        self,
        latitude: float,
        longitude: float,
        wifi,  # has is_connected() -> bool
        coordinator,  # FetchCoordinator
        schedule,  # (callback, arg) -> None
        interval_ms: int,
        forecast_hours: int,
        past_hours: int,
        name: str,  # log tag, e.g. "weather" / "air"
        clock=time.ticks_ms,  # () -> int
        http_get=http_client.get_json,  # (url, timeout_s) -> dict
        timeout_s: int = 3,
        tick_scheduler=None,
    ) -> None:
        self._lat = latitude
        self._lon = longitude
        self._http_get = http_get
        self._timeout_s = timeout_s
        self._forecast_hours = forecast_hours
        self._past_hours = past_hours
        self._name = name
        # Coordinates left at 0.0/0.0 mean "unconfigured": stay disabled rather
        # than silently fetch Gulf-of-Guinea data.
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
            name=name,
        )
        self._tick_ref = self.tick
        if tick_scheduler is not None:
            tick_scheduler.register(self._tick_ref)

        if self._enabled:
            print("[%s] enabled: lat=%s lon=%s" % (name, latitude, longitude))
        else:
            print("[%s] disabled: set LATITUDE/LONGITUDE in config.py" % name)

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
        # backs off without publishing.  Subclasses override.
        raise NotImplementedError

    def _store(self, events: list[Event]) -> None:
        # Infallible: publish the parsed snapshot and bump the generation.
        self._events = events
        self._generation += 1
        print("[%s] published %d events (gen %d)" % (self._name, len(self._events), self._generation))
