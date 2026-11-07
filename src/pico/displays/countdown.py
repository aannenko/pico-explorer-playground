import micropython

from micropython import const
from displays.base import Display as _Display
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

DURATIONS_SEC = (
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

_DEFAULT_DURATION_SEC = const(2 * 60 * 60)


@micropython.native
def _format_hms(sec: int) -> str:
    hours = sec // 3600
    if 0 <= sec <= _MAX_PRINTED_SEC:
        minutes = sec // 60 % 60
        seconds = sec % 60
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{hours} h"


class Display(_Display):
    """Countdown view: a preset-duration timer shown as a draining ring."""

    def __init__(self, renderer: Renderer, countdown_timer: CountdownTimer) -> None:
        self._renderer = renderer
        self._countdown_timer = countdown_timer

        self._duration_index = DURATIONS_SEC.index(_DEFAULT_DURATION_SEC)
        self._countdown_timer.configure(LABELS[self._duration_index], DURATIONS_SEC[self._duration_index])

        self._active = False

    def on_button_a(self) -> None:
        state = self._countdown_timer.state
        if state == INITIAL:
            self._countdown_timer.start()
            self._draw_running()
        elif state == RUNNING:
            self._countdown_timer.pause()
            self._draw_paused()
        elif state == PAUSED:
            self._countdown_timer.resume()
            self._draw_running()
        elif state == DONE:
            self._countdown_timer.reset()
            self._draw_idle()

    def on_button_b(self) -> None:
        state = self._countdown_timer.state
        if state == INITIAL:
            self._cycle_duration()
            self._renderer.write_text(TEXT_CENTER, self._countdown_timer.label)
            self._renderer.update()
        elif state in (RUNNING, PAUSED, DONE):
            self._countdown_timer.reset()
            self._draw_idle()

    def _cycle_duration(self) -> None:
        self._duration_index = (self._duration_index + 1) % len(DURATIONS_SEC)
        self._countdown_timer.configure(LABELS[self._duration_index], DURATIONS_SEC[self._duration_index])

    def _draw_idle(self) -> None:
        self._renderer.reset()
        self._renderer.write_text(TEXT_CENTER, self._countdown_timer.label)
        self._renderer.update()

    def _restore_ring_progress(self) -> None:
        """Reset the renderer, clearing the screen, then redraw the timer's label and progress."""
        self._renderer.reset()
        self._renderer.write_text(TEXT_CENTER, self._countdown_timer.label)

        timer = self._countdown_timer
        total = timer.total_sec
        expected_cleared = timer.elapsed_sec * RING_SEGMENTS // total if total > 0 else 0
        if expected_cleared > 0:
            self._renderer.clear_ring_segments(expected_cleared)

    def _draw_running(self) -> None:
        self._restore_ring_progress()
        self._update_display()

    def _draw_paused(self) -> None:
        self._renderer.write_text(TEXT_ABOVE_CENTER, "Paused")
        self._renderer.update()

    def _draw_paused_full(self) -> None:
        self._restore_ring_progress()
        self._renderer.write_text(TEXT_BELOW_CENTER, f"-{_format_hms(self._countdown_timer.remaining_sec)}")
        self._renderer.write_text(TEXT_ABOVE_CENTER, "Paused")
        self._renderer.update()

    def _draw_done(self) -> None:
        self._renderer.reset()
        self._renderer.clear_ring_segments(RING_SEGMENTS)
        self._renderer.write_text(TEXT_CENTER, self._countdown_timer.label)
        self._renderer.write_text(TEXT_ABOVE_CENTER, "Done!")
        self._renderer.write_text(TEXT_BELOW_CENTER, "-00:00:00")
        self._renderer.update()

    def _update_display(self) -> None:
        timer = self._countdown_timer
        state = timer.state
        if state == DONE:
            if self._renderer.segments_cleared < RING_SEGMENTS:
                self._draw_done()
            return
        if state != RUNNING:
            return

        total = timer.total_sec
        elapsed = timer.elapsed_sec
        if total > 0:
            expected = elapsed * RING_SEGMENTS // total
            if expected > self._renderer.segments_cleared:
                self._renderer.clear_ring_segments(expected)

        self._renderer.write_text(TEXT_ABOVE_CENTER, _format_hms(elapsed))
        self._renderer.write_text(TEXT_BELOW_CENTER, f"-{_format_hms(timer.remaining_sec)}")
        self._renderer.update()

    def render(self) -> None:
        self._update_display()

    def initialize(self) -> None:
        if self._active:
            return
        self._active = True

        state = self._countdown_timer.state
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
