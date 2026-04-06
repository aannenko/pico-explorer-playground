import micropython

from machine import Timer
from displays.events import (
    Renderer,
    RING_SEGMENTS,
    TEXT_CENTER,
    TEXT_ABOVE_CENTER,
    TEXT_BELOW_CENTER,
)
from utilities.safe_timer import safe_init

from services.countdown_timer import (
    CountdownTimer,
    INITIAL,
    RUNNING,
    PAUSED,
    DONE,
)

_MAX_PRINTED_SEC = const(999 * 3600 + 59 * 60 + 59)  # 999:59:59

DURATIONS = (
    5 * 60,
    10 * 60,
    15 * 60,
    30 * 60,
    60 * 60,
    2 * 60 * 60,
    4 * 60 * 60,
    8 * 60 * 60,
)
LABELS = ("5 min", "10 min", "15 min", "30 min", "1 hour", "2 hours", "4 hours", "8 hours")

_DEFAULT_INDEX = const(5)  # "2 hours"


@micropython.native
def _fmt_time(sec: int) -> str:
    hours = sec // 3600
    if 0 <= sec <= _MAX_PRINTED_SEC:
        minutes = sec // 60 % 60
        seconds = sec % 60
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{hours} h"


class Display:
    def __init__(
        self,
        renderer: Renderer,
        countdown_timer: CountdownTimer,
        schedule=micropython.schedule,
        timer_factory=Timer,
    ) -> None:
        self._renderer: Renderer = renderer
        self._timer: CountdownTimer = countdown_timer
        self._schedule = schedule

        self._duration_index: int = _DEFAULT_INDEX
        self._timer.configure(LABELS[self._duration_index], DURATIONS[self._duration_index])

        self._update_each_second_ref = self._update_each_second
        self._schedule_update_each_second_ref = self._schedule_update_each_second
        self._clear_ring_segment_ref = self._clear_ring_segment
        self._schedule_clear_ring_segment_ref = self._schedule_clear_ring_segment

        self._seconds_timer = timer_factory(-1)
        self._ring_timer = timer_factory(-1)

        self._segments_cleared: int = 0
        self._active: bool = False

    def on_button_a(self) -> None:
        state = self._timer.state
        if state == INITIAL:
            self._timer.start()
            self._draw_running()
        elif state == RUNNING:
            self._timer.pause()
            self._draw_paused()
        elif state == PAUSED:
            self._timer.resume()
            self._draw_running()
        elif state == DONE:
            self._timer.reset()
            self._draw_idle()

    def on_button_b(self) -> None:
        state = self._timer.state
        if state == INITIAL:
            self._cycle_duration()
            self._renderer.text_write(TEXT_CENTER, self._timer.name)
            self._renderer.update()
        elif state in (RUNNING, PAUSED, DONE):
            self._timer.reset()
            self._draw_idle()

    def _cycle_duration(self) -> None:
        self._duration_index = (self._duration_index + 1) % len(DURATIONS)
        self._timer.configure(LABELS[self._duration_index], DURATIONS[self._duration_index])

    def _draw_idle(self) -> None:
        self._stop_display_timers()
        self._segments_cleared = 0
        self._renderer.reset()
        self._renderer.text_write(TEXT_CENTER, self._timer.name)
        self._renderer.update()

    def _restore_ring_progress(self) -> None:
        """Reset renderer and restore ring progress from elapsed time."""
        self._segments_cleared = 0
        self._renderer.reset()
        self._renderer.text_write(TEXT_CENTER, self._timer.name)

        timer = self._timer
        total = timer.total_sec
        expected_cleared = timer.elapsed_sec * RING_SEGMENTS // total if total > 0 else 0
        if expected_cleared > 0:
            self._renderer.ring_clear_segments(expected_cleared)
            self._segments_cleared = expected_cleared

    def _draw_running(self) -> None:
        self._restore_ring_progress()
        self._update_each_second(0)
        self._start_display_timers()

    def _draw_paused(self) -> None:
        self._stop_display_timers()
        self._renderer.text_write(TEXT_ABOVE_CENTER, "Paused")
        self._renderer.update()

    def _draw_paused_full(self) -> None:
        """Full redraw for PAUSED state — restores ring progress and remaining time."""
        self._stop_display_timers()
        self._restore_ring_progress()
        self._renderer.text_write(TEXT_BELOW_CENTER, f"-{_fmt_time(self._timer.remaining_sec)}")
        self._renderer.text_write(TEXT_ABOVE_CENTER, "Paused")
        self._renderer.update()

    def _draw_done(self) -> None:
        self._stop_display_timers()
        self._segments_cleared = RING_SEGMENTS
        self._renderer.reset()
        self._renderer.ring_clear_segments(RING_SEGMENTS)
        self._renderer.text_write(TEXT_CENTER, self._timer.name)
        self._renderer.text_write(TEXT_ABOVE_CENTER, "Done!")
        self._renderer.text_write(TEXT_BELOW_CENTER, "-00:00:00")
        self._renderer.update()

    def _start_display_timers(self) -> None:
        remaining = self._timer.remaining_sec
        remaining_segments = RING_SEGMENTS - self._segments_cleared

        if remaining_segments > 0 and remaining > 0:
            safe_init(
                self._ring_timer,
                mode=Timer.PERIODIC,
                period=remaining * 1000 // remaining_segments,
                callback=self._schedule_clear_ring_segment_ref,
            )

        safe_init(
            self._seconds_timer,
            mode=Timer.PERIODIC,
            period=1000,
            callback=self._schedule_update_each_second_ref,
        )

    def _stop_display_timers(self) -> None:
        self._seconds_timer.deinit()
        self._ring_timer.deinit()

    def _update_each_second(self, _: int) -> None:
        if not self._active:
            return
        timer = self._timer
        state = timer.state
        if state == DONE:
            self._draw_done()
            return
        if state != RUNNING:
            return

        renderer = self._renderer
        renderer.text_write(TEXT_ABOVE_CENTER, _fmt_time(timer.elapsed_sec))
        renderer.text_write(TEXT_BELOW_CENTER, f"-{_fmt_time(timer.remaining_sec)}")
        renderer.update()

    def _schedule_update_each_second(self, _: Timer) -> None:
        self._schedule(self._update_each_second_ref, 0)

    def _clear_ring_segment(self, _: int) -> None:
        if not self._active:
            return
        if self._timer.state != RUNNING:
            return
        self._segments_cleared += 1
        self._renderer.ring_clear_next_segment()
        self._renderer.update()

    def _schedule_clear_ring_segment(self, _: Timer) -> None:
        self._schedule(self._clear_ring_segment_ref, 0)

    def initialize(self) -> None:
        if self._active:
            return
        self._active = True

        state = self._timer.state
        if state == RUNNING:
            self._draw_running()
        elif state == PAUSED:
            self._draw_paused_full()
        elif state == DONE:
            self._draw_done()
        else:
            self._draw_idle()

    def deinitialize(self) -> None:
        if not self._active:
            return
        self._active = False
        self._stop_display_timers()
        self._segments_cleared = 0
