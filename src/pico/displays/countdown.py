import micropython
import time

from micropython import const
from displays.ring import (
    Renderer,
    RING_SEGMENTS,
    TEXT_CENTER,
    TEXT_ABOVE_CENTER,
    TEXT_BELOW_CENTER,
)
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
    def __init__(self, renderer: Renderer, countdown_timer: CountdownTimer) -> None:
        self._renderer = renderer
        self._timer = countdown_timer

        self._duration_index: int = _DEFAULT_INDEX
        self._timer.configure(LABELS[self._duration_index], DURATIONS[self._duration_index])

        self._segments_cleared: int = 0
        self._last_tick: int = 0
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
        self._update_display()

    def _draw_paused(self) -> None:
        self._renderer.text_write(TEXT_ABOVE_CENTER, "Paused")
        self._renderer.update()

    def _draw_paused_full(self) -> None:
        """Full redraw for PAUSED state — restores ring progress and remaining time."""
        self._restore_ring_progress()
        self._renderer.text_write(TEXT_BELOW_CENTER, f"-{_fmt_time(self._timer.remaining_sec)}")
        self._renderer.text_write(TEXT_ABOVE_CENTER, "Paused")
        self._renderer.update()

    def _draw_done(self) -> None:
        self._segments_cleared = RING_SEGMENTS
        self._renderer.reset()
        self._renderer.ring_clear_segments(RING_SEGMENTS)
        self._renderer.text_write(TEXT_CENTER, self._timer.name)
        self._renderer.text_write(TEXT_ABOVE_CENTER, "Done!")
        self._renderer.text_write(TEXT_BELOW_CENTER, "-00:00:00")
        self._renderer.update()

    def _update_display(self) -> None:
        timer = self._timer
        state = timer.state
        if state == DONE:
            if self._segments_cleared < RING_SEGMENTS:
                self._draw_done()
            return
        if state != RUNNING:
            return

        total = timer.total_sec
        elapsed = timer.elapsed_sec
        if total > 0:
            expected = elapsed * RING_SEGMENTS // total
            if expected > self._segments_cleared:
                self._renderer.ring_clear_segments(expected)
                self._segments_cleared = expected

        self._renderer.text_write(TEXT_ABOVE_CENTER, _fmt_time(elapsed))
        self._renderer.text_write(TEXT_BELOW_CENTER, f"-{_fmt_time(timer.remaining_sec)}")
        self._renderer.update()

    def tick(self) -> None:
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_tick) < 1000:
            return
        self._last_tick = now
        self._update_display()

    def initialize(self) -> None:
        if self._active:
            return
        self._active = True
        self._last_tick = time.ticks_ms()

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
        self._segments_cleared = 0
