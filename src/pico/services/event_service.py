import micropython
import time

from machine import Timer
from utilities.safe_timer import safe_init


class EventService:
    """Long-lived service that wraps an event iterator and auto-advances."""

    def __init__(
        self,
        events_iter,
        get_time=time.time,
        schedule=micropython.schedule,
        timer_factory=Timer,
    ) -> None:
        self._events = events_iter
        self._get_time = get_time
        self._schedule = schedule

        self._current_event = None  # Event | None
        self._pending_event = None  # Event | None
        self._event_start: int = 0
        self._event_end: int = 0

        self._advance_ref = self._advance
        self._schedule_advance_ref = self._schedule_advance
        self._event_timer = timer_factory(-1)

        self._advance()

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

    def _advance(self, _: int = 0) -> None:
        self._event_timer.deinit()
        now = self._get_time()

        # Use pending future event if available, otherwise consume from iterator
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

        # Future event — store it and wait for its start
        if event.start_timestamp > now:
            self._pending_event = event
            self._current_event = None
            self._event_start = 0
            self._event_end = 0
            safe_init(
                self._event_timer,
                mode=Timer.ONE_SHOT,
                period=(event.start_timestamp - now) * 1000,
                callback=self._schedule_advance_ref,
            )
            return

        # Active event — schedule advance at expiry
        self._current_event = event
        self._event_start = event.start_timestamp
        self._event_end = event.start_timestamp + event.duration_sec
        remaining_ms = (self._event_end - now) * 1000
        if remaining_ms > 0:
            safe_init(
                self._event_timer,
                mode=Timer.ONE_SHOT,
                period=remaining_ms,
                callback=self._schedule_advance_ref,
            )

    def _schedule_advance(self, _: Timer) -> None:
        self._schedule(self._advance_ref, 0)
