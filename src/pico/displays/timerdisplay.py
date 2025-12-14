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
    ) -> None:
        self._display = display
        self._graphics = graphics
        self._timezone_offset_hours = timezone_offset_hours

        self._update_ring_ref = self._update_ring
        self._schedule_update_ring_ref = self._schedule_update_ring
        self._update_clock_ref = self._update_clock
        self._schedule_update_clock_ref = self._schedule_update_clock
        self._chain_event_ref = self._chain_event
        self._schedule_chain_event_ref = self._schedule_chain_event

        self._clock_timer = Timer(-1)
        self._ring_timer = Timer(-1)
        self._event_timer = Timer(-1)
        self._events = iter(())

    def _update_ring(self, _: int) -> None:
        self._graphics.ring_clear_next_segment()
        self._display.update()

    def _schedule_update_ring(self, _: Timer) -> None:
        micropython.schedule(self._update_ring_ref, 0)

    def _update_clock(self, _: int) -> None:
        _, _, _, hour, minute, second, _, _ = time.gmtime()
        local_hour = (hour + self._timezone_offset_hours) % 24
        self._graphics.text_write(
            TimerGraphics.TEXT_ABOVE_CENTER,
            f"{local_hour:02}:{minute:02}:{second:02}",
        )
        self._display.update()

    def _schedule_update_clock(self, _: Timer) -> None:
        micropython.schedule(self._update_clock_ref, 0)

    def _chain_event(self, _: int) -> None:
        # stop any previous periodic ring updates
        try:
            self._event_timer.deinit()
            self._ring_timer.deinit()
        except Exception:
            pass

        now = time.time()
        try:
            event = next(self._events)
            while event.start_timestamp + event.duration_sec <= now:
                event = next(self._events)
        except StopIteration:
            return  # iterator ended; nothing more to do

        # compute elapsed within current event (clamped)
        _, _, _, hour, minute, second, wday, _ = time.gmtime(now)
        _, _, _, start_hour, start_minute, start_second, start_wday, _ = (
            time.gmtime(event.start_timestamp)
        )
        elapsed_sec = (
            (hour * 3600 + minute * 60 + second)
            - (start_hour * 3600 + start_minute * 60 + start_second)
            + ((wday - start_wday) % 7) * 86400
        )

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
        micropython.schedule(self._chain_event_ref, 0)

    def initialize(self, events) -> None:
        self._events = events

        self._clock_timer.init(
            mode=Timer.PERIODIC,
            period=1000,
            callback=self._schedule_update_clock_ref,
        )

        micropython.schedule(self._chain_event_ref, 0)

    def deinitialize(self) -> None:
        self._clock_timer.deinit()
        self._event_timer.deinit()
        self._ring_timer.deinit()
