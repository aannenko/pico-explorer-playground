import micropython
import time

from graphics.geometry import Geometry
from graphics.timergraphics import TimerGraphics
from machine import Timer
from picographics import PicoGraphics


class TimerDisplay:
    def __init__(
        self,
        display: PicoGraphics,
        graphics: TimerGraphics,
        timezone_offset_hours: int,
        get_time=time.time,
        gmtime=time.gmtime,
        schedule=micropython.schedule,
        timer_factory=Timer,
    ) -> None:
        self._display = display
        self._graphics = graphics
        self._timezone_offset_hours = timezone_offset_hours

        # method references for use with micropython.schedule
        self._update_ring_ref = self._update_ring
        self._schedule_update_ring_ref = self._schedule_update_ring
        self._update_clock_ref = self._update_clock
        self._schedule_update_clock_ref = self._schedule_update_clock
        self._chain_event_ref = self._chain_event
        self._schedule_chain_event_ref = self._schedule_chain_event

        # dependencies for easier testing
        self._schedule = schedule
        self._get_time = get_time
        self._gmtime = gmtime
        self._timer_factory = timer_factory

        # deinitialize() will reset these
        self._clock_timer = self._timer_factory(-1)
        self._ring_timer = self._timer_factory(-1)
        self._event_timer = self._timer_factory(-1)
        self._events = iter(())
        self._event_end_timestamp = 0
        self._active = False

    def _update_ring(self, _: int) -> None:
        self._graphics.ring_clear_next_segment()
        self._display.update()

    def _schedule_update_ring(self, _: Timer) -> None:
        self._schedule(self._update_ring_ref, 0)

    def _update_clock(self, _: int) -> None:
        now = self._get_time()
        tm = self._gmtime(now)
        hour, minute, second = tm[3], tm[4], tm[5]
        local_hour = (hour + self._timezone_offset_hours) % 24
        self._graphics.text_write(
            TimerGraphics.TEXT_ABOVE_CENTER,
            f"{local_hour:02}:{minute:02}:{second:02}",
        )

        rem_total_sec = self._event_end_timestamp - now
        if 0 <= rem_total_sec <= 604800:
            rem_hours = rem_total_sec // 3600
            rem_minutes = rem_total_sec // 60 % 60
            rem_seconds = rem_total_sec % 60
            self._graphics.text_write(
                TimerGraphics.TEXT_BELOW_CENTER,
                f"-{rem_hours:02}:{rem_minutes:02}:{rem_seconds:02}",
            )

        self._display.update()

    def _schedule_update_clock(self, _: Timer) -> None:
        self._schedule(self._update_clock_ref, 0)

    def _chain_event(self, _: int) -> None:
        # stop any previous periodic updates
        try:
            self._event_timer.deinit()
            self._ring_timer.deinit()
        except Exception:
            pass

        now = self._get_time()
        try:
            event = next(self._events)
            while (
                event.duration_sec <= 0
                or event.start_timestamp + event.duration_sec <= now
            ):
                event = next(self._events)
        except StopIteration:
            return  # iterator ended; nothing more to do

        if event.start_timestamp > now:
            # event is in the future; schedule next check at its start
            self._event_timer.init(
                mode=Timer.ONE_SHOT,
                period=(event.start_timestamp - now) * 1000,
                callback=self._schedule_chain_event_ref,
            )
            return

        self._event_end_timestamp = event.start_timestamp + event.duration_sec

        # compute elapsed within current event (clamped)
        elapsed_sec = now - event.start_timestamp
        if elapsed_sec < 0:
            elapsed_sec = 0
        elif elapsed_sec > event.duration_sec:
            elapsed_sec = event.duration_sec

        # draw event state
        self._graphics.reset()
        self._graphics.ring_clear_segments(
            Geometry.RING_SEGMENTS * elapsed_sec // event.duration_sec
        )
        self._graphics.text_write(TimerGraphics.TEXT_CENTER, event.name)
        self._display.update()

        # schedule: ring ticking + next event start
        remaining_sec = event.duration_sec - elapsed_sec
        if remaining_sec > 0:
            self._ring_timer.init(
                mode=Timer.PERIODIC,
                period=event.duration_sec * 1000 // Geometry.RING_SEGMENTS,
                callback=self._schedule_update_ring_ref,
            )
            self._event_timer.init(
                mode=Timer.ONE_SHOT,
                period=remaining_sec * 1000,
                callback=self._schedule_chain_event_ref,
            )
        else:
            # already past the end of the event; schedule next event "soon"
            self._event_timer.init(
                mode=Timer.ONE_SHOT,
                period=10,
                callback=self._schedule_chain_event_ref,
            )

    def _schedule_chain_event(self, _: Timer) -> None:
        self._schedule(self._chain_event_ref, 0)

    def initialize(self, events) -> None:
        if self._active:
            return
        self._active = True
        self._events = events
        self._chain_event(0)
        self._clock_timer.init(
            mode=Timer.PERIODIC,
            period=1000,
            callback=self._schedule_update_clock_ref,
        )

    def deinitialize(self) -> None:
        if not self._active:
            return
        self._active = False
        self._clock_timer.deinit()
        self._event_timer.deinit()
        self._ring_timer.deinit()
        self._events = iter(())
        self._event_end_timestamp = 0
