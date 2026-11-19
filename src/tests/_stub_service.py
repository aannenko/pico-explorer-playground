from scheduling.event import create_event, Event
from services._event_stream_service import EventStreamService
from services.tick_scheduler import TickScheduler


class StubService(EventStreamService):
    def __init__(
        self,
        fetcher,  # () -> dict
        tick_scheduler: TickScheduler,
        interval_ms: int,
        get_ticks_ms,  # () -> int
        enabled: bool = True,
    ) -> None:
        self._fetcher = fetcher
        super().__init__(tick_scheduler, interval_ms, "stub", enabled, get_ticks_ms=get_ticks_ms)

    def _fetch_and_parse(self) -> tuple[list[Event]]:
        payload = self._fetcher()
        return ([
            create_event(e["name"], e["start"], e["dur"], color_index=e.get("color", 0))
            for e in payload["events"]
        ],)
