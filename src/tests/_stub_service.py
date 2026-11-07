from scheduling.event import Event
from services._event_stream_service import EventStreamService
from services.fetch_machine import FetchCoordinator


class StubService(EventStreamService):
    def __init__(
        self,
        fetcher,  # () -> dict; the "HTTP get_json" layer (may raise)
        wifi,  # has is_connected() -> bool
        coordinator: FetchCoordinator,
        interval_ms: int,
        schedule,  # (callback, arg) -> None
        get_ticks_ms,  # () -> int
        enabled: bool = True,
    ) -> None:
        self._fetcher = fetcher
        super().__init__(wifi, coordinator, schedule, interval_ms, "stub", enabled, get_ticks_ms=get_ticks_ms)

    def _fetch_and_parse(self) -> list[Event]:
        # Fallible: an HTTP error or a malformed payload raises here, so the
        # loop counts it as a failure and backs off.
        payload = self._fetcher()
        return [
            Event(e["name"], e["start"], e["dur"], color_index=e.get("color", 0))
            for e in payload["events"]
        ]
