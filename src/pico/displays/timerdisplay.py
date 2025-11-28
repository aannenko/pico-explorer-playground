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
        self._update_time_ref = self._update_time
        self._schedule_update_time_ref = self._schedule_update_time

        self._clock_timer = Timer(-1)
        self._ring_timer = Timer(-1)

    def _update_ring(self, _: int) -> None:
        self._graphics.ring_clear_next_segment()
        self._display.update()

    def _schedule_update_ring(self, _: Timer) -> None:
        micropython.schedule(self._update_ring_ref, 0)

    def _update_time(self, _: int) -> None:
        _, _, _, hour, minute, second, _, _ = time.gmtime()
        self._graphics.text_write(
            TimerGraphics.TEXT_ABOVE_CENTER,
            f"{hour + self._timezone_offset_hours:02}:{minute:02}:{second:02}",
        )
        self._display.update()

    def _schedule_update_time(self, _: Timer) -> None:
        micropython.schedule(self._update_time_ref, 0)

    def initialize(self, events) -> None:
        self._clock_timer.init(
            mode=Timer.PERIODIC,
            period=1000,
            callback=self._schedule_update_time_ref,
        )

        for event in events:
            _, _, _, hour, minute, second, wday, _ = time.gmtime()
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

            self._graphics.reset()
            self._graphics.ring_clear_segments(
                Geometry.RING_SEGMENTS * elapsed_sec // event.duration_sec
            )
            self._graphics.text_write(TimerGraphics.TEXT_CENTER, event.name)
            self._graphics.text_write(TimerGraphics.TEXT_BELOW_CENTER, event.alt_text)
            self._display.update()

            remaining_sec = event.duration_sec - elapsed_sec
            if remaining_sec > 0:
                self._ring_timer.init(
                    mode=Timer.PERIODIC,
                    period=event.duration_sec * 1000 // Geometry.RING_SEGMENTS,
                    callback=self._schedule_update_ring_ref,
                )

                time.sleep(remaining_sec)
                self._ring_timer.deinit()

            self._graphics.ring_clear_next_segment()
            self._display.update()

    def deinitialize(self) -> None:
        self._clock_timer.deinit()
        self._ring_timer.deinit()
