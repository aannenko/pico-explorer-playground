"""Test-only reference network service exercising the fetch substrate.

Not wired into ``app.py``.  It is the minimal ``EventStreamService`` subclass —
the shape every real network service (weather / air / bus) follows: the base
drives the loop, all fallible work (the HTTP get + parse) lives in one
``_fetch_and_parse`` so failures back off, and the infallible store bumps a
generation the calendar polls to refresh.
"""

from scheduling.event import Event
from services._event_stream_service import EventStreamService


class StubService(EventStreamService):
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
        super().__init__(wifi, coordinator, schedule, interval_ms, "stub", enabled, clock=clock)

    def _fetch_and_parse(self) -> list[Event]:
        # Fallible: an HTTP error or a malformed payload raises here, so the
        # loop counts it as a failure and backs off.
        payload = self._fetcher()
        return [
            Event(e["name"], e["start"], e["dur"], color_index=e.get("color", 0))
            for e in payload["events"]
        ]
