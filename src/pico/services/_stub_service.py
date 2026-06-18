"""Test-only reference network service exercising the fetch substrate.

Not wired into ``app.py``.  It shows the shape every real network service
(precip / advisory / bus) follows: a ``FetchState`` drives the loop, all
fallible work (HTTP + parse) lives in one fetcher so failures back off,
and an infallible store bumps a generation the calendar polls to refresh.
"""

from scheduling.event import Event
from scheduling.stream import DISABLED
from services._fetch_state import FetchState


class StubService:
    def __init__(
        self,
        fetcher,  # () -> dict; the "HTTP get_json" layer (may raise)
        wifi,  # has is_connected() -> bool
        coordinator,  # FetchCoordinator
        interval_ms: int,
        schedule,  # (callback, arg) -> None
        clock,  # () -> int
        enabled: bool = True,
    ) -> None:
        self._fetcher = fetcher
        self._enabled = enabled
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
        )

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
        # Fallible: an HTTP error or a malformed payload raises here, so the
        # state machine counts it as a failure and backs off.
        payload = self._fetcher()
        return [
            Event(e["name"], e["start"], e["dur"], color_index=e.get("color", 0))
            for e in payload["events"]
        ]

    def _store(self, events: list[Event]) -> None:
        # Infallible: the snapshot is already parsed; just publish it.
        self._events = events
        self._generation += 1
