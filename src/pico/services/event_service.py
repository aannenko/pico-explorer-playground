from services.tick_scheduler import TickScheduler
from services.time_service import TimeService


class EventService:
    """Long-lived service that wraps an event iterator and auto-advances.

    Boundary detection uses local-epoch (now() + wall-clock duration_sec).
    Countdown uses UTC (utc_now() + real_duration_sec) for smooth seconds.
    """

    def __init__(
        self,
        events_iter,
        time_service: TimeService,  # TimeService
        tick_scheduler: TickScheduler
    ) -> None:
        self._events = events_iter
        self._time_service = time_service

        self._current_event = None  # Event | None
        self._pending_event = None  # Event | None
        self._event_end: int = 0  # local-epoch end (for boundary detection)
        self._event_start_utc: int = 0  # UTC start (for countdown)
        self._real_total: int = 0  # real seconds (for countdown)

        self._advance()

        if tick_scheduler is not None:
            tick_scheduler.register(self._tick)

    @property
    def current_event(self):  # -> Event | None
        return self._current_event

    @property
    def name(self) -> str:
        event = self._current_event
        return event.name if event is not None else ""

    @property
    def elapsed_sec(self) -> int:
        if self._current_event is None:
            return 0
        return max(0, self._time_service.utc_now() - self._event_start_utc)

    @property
    def remaining_sec(self) -> int:
        if self._current_event is None:
            return 0
        return max(0, self._real_total - self.elapsed_sec)

    @property
    def total_sec(self) -> int:
        if self._current_event is None:
            return 0
        return self._real_total

    def _tick(self) -> None:
        now = self._time_service.now()
        if self._current_event is not None and now >= self._event_end:
            self._advance()
        elif self._pending_event is not None and now >= self._pending_event.start_timestamp:
            self._advance()

    def _advance(self) -> None:
        now = self._time_service.now()

        event = self._pending_event
        self._pending_event = None

        try:
            if event is None:
                event = next(self._events)
            while event.duration_sec <= 0 or event.start_timestamp + event.duration_sec <= now:
                event = next(self._events)
        except StopIteration:
            self._current_event = None
            self._event_end = 0
            self._event_start_utc = 0
            self._real_total = 0
            return

        # Future event — store it and wait
        if event.start_timestamp > now:
            self._pending_event = event
            self._current_event = None
            self._event_end = 0
            self._event_start_utc = 0
            self._real_total = 0
            return

        # Active event
        self._current_event = event
        self._event_end = event.start_timestamp + event.duration_sec
        self._event_start_utc = self._time_service.to_utc(event.start_timestamp)
        self._real_total = event.real_duration_sec
