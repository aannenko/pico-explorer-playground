from __future__ import annotations

import pytest

import displays.calendar as calendar
from scheduling.event import Event
from scheduling.event_window import EventWindow

from conftest import RecordingRenderer


# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------

class FakeRenderer(RecordingRenderer):
    pass


def _make_event(name: str, start: int, duration: int) -> Event:
    return Event(name=name, start_timestamp=start, wall_clock_duration_sec=duration)


def _make_stream(*specs, color_a: int = 1, color_b: int = 2) -> EventWindow:
    return EventWindow(
        iter([_make_event(n, s, d) for n, s, d in specs]),
        color_a=color_a,
        color_b=color_b,
    )


def _mk_display(streams=None, now: int = 0):
    """Build a calendar.Display with a FakeRenderer and a fixed-now clock."""
    renderer = FakeRenderer()
    d = calendar.Display(
        renderer=renderer,
        streams=streams if streams is not None else [],
        get_time=lambda: now,
    )
    return d, renderer


@pytest.fixture(autouse=True)
def _patch_header(monkeypatch):
    """Patch `format_header_time` to a deterministic stand-in for every test."""
    monkeypatch.setattr(calendar, "format_header_time", lambda t: f"HDR:{t}")


# ---------------------------------------------------------------------------
# Display lifecycle
# ---------------------------------------------------------------------------

class TestDisplayLifecycle:
    def test_initialize_renders_and_calls_update(self):
        stream = _make_stream(("work", 0, 100_000))
        d, renderer = _mk_display(streams=[stream], now=50_000)

        d.initialize()

        assert d._active is True
        call_names = [c[0] for c in renderer.calls]
        assert "reset" in call_names
        assert "draw_static_overlay" in call_names
        assert "header_write" in call_names
        assert "draw_rows" in call_names
        assert "draw_time_axis" in call_names
        assert "draw_now_line" not in call_names
        assert renderer.update_calls == 1

    def test_initialize_is_idempotent(self):
        d, renderer = _mk_display()

        d.initialize()
        renderer.calls.clear()
        renderer.update_calls = 0

        d.initialize()

        assert renderer.calls == []
        assert renderer.update_calls == 0

    def test_deinitialize_sets_inactive(self):
        d, _ = _mk_display()

        d.initialize()
        d.deinitialize()

        assert d._active is False

    def test_deinitialize_is_idempotent(self):
        d, _ = _mk_display()

        d.deinitialize()
        assert d._active is False


# ---------------------------------------------------------------------------
# render()
# ---------------------------------------------------------------------------

class TestRender:
    def test_render_redraws(self):
        d, renderer = _mk_display(now=100_000)

        d.initialize()
        renderer.calls.clear()
        renderer.update_calls = 0

        d.render()

        assert renderer.update_calls == 1
        assert ("header_write", ("HDR:100000",), {}) in renderer.calls


# ---------------------------------------------------------------------------
# Window calculation
# ---------------------------------------------------------------------------

class TestWindowCalculation:
    def test_window_passes_correct_range(self):
        now_val = 100_000
        d, renderer = _mk_display(
            streams=[_make_stream(("work", 0, 200_000))],
            now=now_val,
        )

        d.initialize()

        # Find the draw_rows call and check the window
        draw_rows_calls = [c for c in renderer.calls if c[0] == "draw_rows"]
        assert len(draw_rows_calls) == 1

        _, (streams, window_start, window_end), _ = draw_rows_calls[0]
        assert window_start == now_val - 1800  # 30 min past
        assert window_end == now_val + 5400    # 90 min future


# ---------------------------------------------------------------------------
# Header formatting
# ---------------------------------------------------------------------------

class TestHeaderFormatting:
    def test_header_uses_format_header_time(self, monkeypatch):
        captured = []
        monkeypatch.setattr(
            calendar, "format_header_time", lambda t: (captured.append(t), f"T:{t}")[1]
        )

        now_val = 42_000
        d, renderer = _mk_display(now=now_val)

        d.initialize()

        assert captured == [now_val]
        header_calls = [c for c in renderer.calls if c[0] == "header_write"]
        assert header_calls[0][1] == (f"T:{now_val}",)


# ---------------------------------------------------------------------------
# Shared header module
# ---------------------------------------------------------------------------

class TestSharedHeader:
    def test_format_header_time(self, monkeypatch):
        from displays.shared.header import format_header_time

        # Use a known epoch: 2026-04-10 17:56 UTC
        # gmtime of that epoch gives the components.
        import time
        epoch = time.mktime((2026, 4, 10, 17, 56, 0, 0, 0))

        result = format_header_time(epoch)

        assert result == "2026-04-10 17:56"

    def test_format_header_time_midnight(self, monkeypatch):
        from displays.shared.header import format_header_time

        import time
        epoch = time.mktime((2026, 1, 1, 0, 0, 0, 0, 0))

        result = format_header_time(epoch)

        assert result == "2026-01-01 00:00"


# ---------------------------------------------------------------------------
# _fmt_remaining helper
# ---------------------------------------------------------------------------

class TestFmtRemaining:
    def test_zero(self):
        assert calendar._fmt_remaining(0) == "-00:00"

    def test_minutes_only(self):
        assert calendar._fmt_remaining(30 * 60) == "-00:30"

    def test_hours_and_minutes(self):
        assert calendar._fmt_remaining(2 * 3600 + 15 * 60) == "-02:15"

    def test_large_hours(self):
        assert calendar._fmt_remaining(25 * 3600) == "-25:00"

    def test_seconds_are_truncated(self):
        assert calendar._fmt_remaining(3661) == "-01:01"


# ---------------------------------------------------------------------------
# Remaining time rendering in draw_rows
# ---------------------------------------------------------------------------

class FakeGfx:
    """Minimal PicoGraphics fake for Renderer-level tests."""
    def __init__(self, width: int = 240, height: int = 240) -> None:
        self._bounds = (width, height)
        self.text_calls: list[tuple[str, int, int, int]] = []
        self.line_calls: list[tuple[int, int, int, int]] = []

    def get_bounds(self) -> tuple[int, int]:
        return self._bounds

    def set_font(self, font: str) -> None:
        pass

    def set_pen(self, pen: int) -> None:
        pass

    def clear(self) -> None:
        pass

    def rectangle(self, x: int, y: int, w: int, h: int) -> None:
        pass

    def line(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self.line_calls.append((x1, y1, x2, y2))

    def measure_text(self, text: str, *, scale: int) -> int:
        return len(text) * 6 * scale

    def text(self, text: str, x: int, y: int, *, scale: int) -> None:
        self.text_calls.append((text, x, y, scale))

    def update(self) -> None:
        pass


def _make_renderer(gfx: FakeGfx | None = None) -> tuple[calendar.Renderer, FakeGfx]:
    if gfx is None:
        gfx = FakeGfx()
    geom = calendar.Geometry(
        pico_graphics=gfx,
        header_font="bitmap6",
        header_font_height=6,
        header_text_scale=3,
        bar_font="bitmap6",
        bar_font_height=6,
        bar_text_scale=2,
    )
    colors = calendar.Colors(
        background=0,
        header_text=1,
        axis_text=2,
        empty_row=3,
        now_line=4,
    )
    return calendar.Renderer(geom, colors), gfx


class TestRemainingTime:
    def test_remaining_shown_when_event_extends_beyond_window(self):
        renderer, gfx = _make_renderer()
        now = 100_000
        window_start = now - 1800
        window_end = now + 5400

        # Event: started 10 min ago, lasts 3 hours (end well beyond window)
        ev_duration = 3 * 3600
        stream = _make_stream(("work", now - 600, ev_duration), color_a=10, color_b=11)
        stream.get_visible(window_start, window_end)  # prime the buffer

        renderer.draw_rows([stream], window_start, window_end)

        # Should find a text call with the remaining time format.
        # Event started 10 min ago, lasts 3 h → remaining = 2 h 50 min.
        expected_text = "-02:50"
        rem_texts = [t for t, *_ in gfx.text_calls if t == expected_text]
        assert len(rem_texts) == 1

    def test_remaining_not_shown_when_event_ends_within_window(self):
        renderer, gfx = _make_renderer()
        now = 100_000
        window_start = now - 1800
        window_end = now + 5400

        # Event: started 10 min ago, lasts 30 min (ends within window)
        stream = _make_stream(("short", now - 600, 1800), color_a=10, color_b=11)
        stream.get_visible(window_start, window_end)

        renderer.draw_rows([stream], window_start, window_end)

        # No remaining-time text (only the name label if any)
        rem_texts = [t for t, *_ in gfx.text_calls if t.startswith("-")]
        assert len(rem_texts) == 0

    def test_remaining_not_shown_when_bar_too_narrow_for_both(self):
        renderer, gfx = _make_renderer()
        now = 100_000
        window_start = now - 1800
        window_end = now + 5400

        # Event with a very long name starting near the right edge of the window,
        # extending beyond — bar is wide but label fills it
        stream = _make_stream(
            ("AVERYLONGEVENTNAME", now + 4800, 7200),
            color_a=10, color_b=11,
        )
        stream.get_visible(window_start, window_end)

        renderer.draw_rows([stream], window_start, window_end)

        # The bar for this event starts at ~92% of the width (4800/7200 offset)
        # and extends to the right edge — very narrow visible portion.
        # Remaining text should NOT appear if it would overlap the label.
        rem_texts = [t for t, *_ in gfx.text_calls if t.startswith("-")]
        # Either no remaining text, or if bar is wide enough, it appears.
        # With bar starting at ~92% of 240px = ~220px, only ~20px visible.
        # "-02:50" at scale 2 = 6*6*2 = 72px — won't fit.
        assert len(rem_texts) == 0


# ---------------------------------------------------------------------------
# Tick marks (15-minute markers below baseline)
# ---------------------------------------------------------------------------

class TestTickMarks:
    def test_draws_vertical_lines_every_15_minutes(self):
        renderer, gfx = _make_renderer()
        geom = renderer._geom

        # Window: 2 hours starting at an exact quarter-hour boundary
        window_start = 7200  # 02:00:00
        window_end = window_start + 7200  # 04:00:00

        renderer.draw_time_axis(window_start, window_end)

        baseline_y = geom.gap_y[geom.num_rows - 1] + geom.gap_height - 1
        tick_bottom = baseline_y + 4  # _TICK_MARK_HEIGHT

        # 2h window at quarter-aligned start → marks at 0:00, 0:15, ..., 1:45 = 8 marks
        tick_lines = [c for c in gfx.line_calls if c[1] == baseline_y and c[3] == tick_bottom]
        assert len(tick_lines) == 8

    def test_tick_marks_at_correct_x_positions(self):
        renderer, gfx = _make_renderer()
        geom = renderer._geom

        # Start mid-quarter so first mark is at 900s
        window_start = 100
        window_end = window_start + 7200

        renderer.draw_time_axis(window_start, window_end)

        baseline_y = geom.gap_y[geom.num_rows - 1] + geom.gap_height - 1
        tick_bottom = baseline_y + 4

        tick_lines = [c for c in gfx.line_calls if c[1] == baseline_y and c[3] == tick_bottom]

        # First mark at 900s → x = (900 - 100) * 240 // 7200 = 800 * 240 // 7200 = 26
        assert tick_lines[0][0] == (900 - window_start) * 240 // 7200
        # Second mark at 1800s → x = (1800 - 100) * 240 // 7200 = 1700 * 240 // 7200 = 56
        assert tick_lines[1][0] == (1800 - window_start) * 240 // 7200
