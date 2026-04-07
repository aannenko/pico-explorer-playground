import time


class EventService:
    """Long-lived service that wraps an event iterator and auto-advances."""

    def __init__(self, events_iter, get_time=time.time, tick_scheduler=None) -> None:
        self._events = events_iter
        self._get_time = get_time

        self._current_event = None  # Event | None
        self._pending_event = None  # Event | None
        self._event_start: int = 0
        self._event_end: int = 0

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
        return max(0, self._get_time() - self._event_start)

    @property
    def remaining_sec(self) -> int:
        if self._current_event is None:
            return 0
        return max(0, self._event_end - self._get_time())

    @property
    def total_sec(self) -> int:
        if self._current_event is None:
            return 0
        return self._current_event.duration_sec

    def _tick(self) -> None:
        now = self._get_time()
        if self._current_event is not None and now >= self._event_end:
            self._advance()
        elif self._pending_event is not None and now >= self._pending_event.start_timestamp:
            self._advance()

    def _advance(self) -> None:
        now = self._get_time()

        event = self._pending_event
        self._pending_event = None

        try:
            if event is None:
                event = next(self._events)
            while event.duration_sec <= 0 or event.start_timestamp + event.duration_sec <= now:
                event = next(self._events)
        except StopIteration:
            self._current_event = None
            self._event_start = 0
            self._event_end = 0
            return

        # Future event — store it and wait
        if event.start_timestamp > now:
            self._pending_event = event
            self._current_event = None
            self._event_start = 0
            self._event_end = 0
            return

        # Active event
        self._current_event = event
        self._event_start = event.start_timestamp
        self._event_end = event.start_timestamp + event.duration_sec
