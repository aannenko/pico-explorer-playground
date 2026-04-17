import micropython
import time

from micropython import const
from picographics import PicoGraphics  # type: ignore

from displays.base import Display as _Display, RefreshGate
from displays.shared.header import format_header_time
from scheduling.event_window import EventWindow

_WINDOW_PAST_SEC = const(30 * 60)      # 30 minutes of past
_WINDOW_FUTURE_SEC = const(90 * 60)    # 90 minutes of future
_WINDOW_TOTAL_SEC = const(_WINDOW_PAST_SEC + _WINDOW_FUTURE_SEC)  # 7200s

_MAX_STREAMS = const(5)
_HEADER_MARGIN = const(6)
_AXIS_MARGIN = const(3)
_BAR_TEXT_MARGIN = const(2)
_MIN_LABEL_PX = const(14)  # don't render label if bar is narrower

_SEC_PER_HOUR = const(3600)
_SEC_PER_QUARTER = const(900)
_TICK_MARK_HEIGHT = const(4)


def _fmt_remaining(sec: int) -> str:
    h = sec // 3600
    m = sec % 3600 // 60
    return f"-{h:02}:{m:02}"

# Predefined stream color pairs (color_a, color_b) as RGB tuples.
# Based on the Okabe-Ito palette, brightened for black-text contrast.
# Color-blind safe: avoids red-green confusion; distinguishable under
# protanopia and deuteranopia.  Within-stream pairs use analogous hue shift.
STREAM_COLORS: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = [
    ((240, 180, 50), (255, 210, 90)),    # orange / amber
    ((100, 190, 245), (150, 210, 255)),  # sky blue / light blue
    ((180, 200, 50), (210, 240, 130)),   # yellow / chartreuse
    ((230, 150, 190), (245, 185, 215)),  # pink / light pink
    ((80, 200, 160), (130, 240, 230)),   # teal / aqua
]


class Colors:
    def __init__(
        self,
        background: int,
        header_text: int,
        axis_text: int,
        empty_row: int,
        now_line: int,
    ) -> None:
        self.background = background
        self.header_text = header_text
        self.axis_text = axis_text
        self.empty_row = empty_row
        self.now_line = now_line


class Geometry:
    def __init__(
        self,
        pico_graphics: PicoGraphics,
        header_font: str,
        header_font_height: int,
        header_text_scale: int,
        bar_font: str,
        bar_font_height: int,
        bar_text_scale: int,
    ) -> None:
        self.graphics = pico_graphics
        self.width, self.height = pico_graphics.get_bounds()

        # Header geometry
        self.header_font = header_font
        self.header_text_scale = header_text_scale
        self.header_height = header_font_height * header_text_scale
        self.header_y = 0

        # Bar label geometry
        self.bar_font = bar_font
        self.bar_text_scale = bar_text_scale
        self.bar_text_height = bar_font_height * bar_text_scale

        # Time axis geometry (reuses bar font)
        self.axis_height = bar_font_height * bar_text_scale
        self.axis_y = self.height - self.axis_height

        # Event rows — always laid out for _MAX_STREAMS rows
        body_top = self.header_height + _HEADER_MARGIN
        body_bottom = self.axis_y - _AXIS_MARGIN
        body_height = body_bottom - body_top

        cell_height = body_height // _MAX_STREAMS
        gap = max(3, cell_height // 5)
        bar_height = cell_height - gap

        self.num_rows = _MAX_STREAMS
        self.row_y: list[int] = []
        self.row_height: int = bar_height
        self.gap_y: list[int] = []
        self.gap_height: int = gap

        for i in range(_MAX_STREAMS):
            row_top = body_top + i * cell_height
            self.row_y.append(row_top)
            self.gap_y.append(row_top + bar_height)

        # "Now" line x position (25% from left)
        self.now_x = self.width // 4


class Renderer:
    def __init__(self, geometry: Geometry, colors: Colors) -> None:
        self._geom = geometry
        self._gfx = geometry.graphics
        self._colors = colors
        self._last_header = ""

    def reset(self) -> None:
        self._last_header = ""
        gfx = self._gfx
        geom = self._geom

        gfx.set_pen(self._colors.background)
        gfx.clear()

        gfx.set_pen(self._colors.empty_row)
        for row_idx in range(geom.num_rows):
            gfx.rectangle(0, geom.row_y[row_idx], geom.width, geom.row_height)

    def header_write(self, text: str) -> None:
        if text == self._last_header:
            return
        self._last_header = text

        geom = self._geom
        gfx = self._gfx

        gfx.set_pen(self._colors.background)
        gfx.rectangle(0, 0, geom.width, geom.header_height)

        if text:
            gfx.set_font(geom.header_font)
            gfx.set_pen(self._colors.header_text)
            gfx.text(text, 0, geom.header_y, scale=geom.header_text_scale)

    @micropython.native
    def draw_rows(
        self,
        streams: list[EventWindow],
        window_start: int,
        window_end: int,
    ) -> None:
        geom = self._geom
        gfx = self._gfx
        width = geom.width
        now = window_start + _WINDOW_PAST_SEC

        gfx.set_font(geom.bar_font)

        for row_idx in range(len(streams)):
            row_top = geom.row_y[row_idx]
            bar_h = geom.row_height

            gfx.set_pen(self._colors.empty_row)
            gfx.rectangle(0, row_top, width, bar_h)

            stream = streams[row_idx]
            visible = stream.get_visible(window_start, window_end)

            for event, use_alt in visible:
                ev_start = event.start_timestamp
                ev_end = ev_start + event.wall_clock_duration_sec

                # Clip to window
                x0 = max(0, (ev_start - window_start) * width // _WINDOW_TOTAL_SEC)
                x1 = min(width, (ev_end - window_start) * width // _WINDOW_TOTAL_SEC)

                if x1 <= x0:
                    continue

                color = stream.color_b if use_alt else stream.color_a
                gfx.set_pen(color)
                gfx.rectangle(x0, row_top, x1 - x0, bar_h)

                bar_px = x1 - x0
                text_y = row_top + (bar_h - geom.bar_text_height) // 2
                label_right = x0
                usable_px = bar_px - 2 * _BAR_TEXT_MARGIN

                # Left-aligned name label
                if usable_px >= _MIN_LABEL_PX and event.name:
                    label = event.name.upper()
                    text_w = gfx.measure_text(label, scale=geom.bar_text_scale)

                    # Binary search for longest fitting prefix
                    if text_w > usable_px:
                        lo, hi = 1, len(label) - 1
                        while lo < hi:
                            mid = (lo + hi + 1) // 2
                            if gfx.measure_text(label[:mid], scale=geom.bar_text_scale) <= usable_px:
                                lo = mid
                            else:
                                hi = mid - 1
                        label = label[:lo]
                        text_w = gfx.measure_text(label, scale=geom.bar_text_scale)

                    if text_w <= usable_px:
                        gfx.set_pen(self._colors.background)
                        gfx.text(label, x0 + _BAR_TEXT_MARGIN, text_y, scale=geom.bar_text_scale)
                        label_right = x0 + _BAR_TEXT_MARGIN + text_w

                # Right-aligned remaining time when event end is beyond window
                if ev_end > window_end:
                    remaining = ev_end - now
                    if remaining > 0:
                        rem_text = _fmt_remaining(remaining)
                        rem_w = gfx.measure_text(rem_text, scale=geom.bar_text_scale)
                        rem_x = x1 - rem_w - _BAR_TEXT_MARGIN
                        if rem_x > label_right + 1:
                            gfx.set_pen(self._colors.background)
                            gfx.text(rem_text, rem_x, text_y, scale=geom.bar_text_scale)

    @micropython.native
    def draw_time_axis(self, window_start: int, window_end: int) -> None:
        geom = self._geom
        gfx = self._gfx
        width = geom.width

        baseline_y = geom.gap_y[geom.num_rows - 1] + geom.gap_height - 1
        tick_bottom = baseline_y + _TICK_MARK_HEIGHT

        # Clear axis label area + tick mark band
        gfx.set_pen(self._colors.background)
        gfx.rectangle(0, baseline_y + 1, width, geom.axis_y + geom.axis_height - baseline_y - 1)

        gfx.set_font(geom.bar_font)

        # Iterate every 15 minutes; draw tick mark at each, hour label at full hours
        first_q = (window_start // _SEC_PER_QUARTER) * _SEC_PER_QUARTER
        if first_q < window_start:
            first_q += _SEC_PER_QUARTER

        t = first_q
        while t < window_end:
            x = (t - window_start) * width // _WINDOW_TOTAL_SEC

            if 0 <= x < width:
                gfx.set_pen(self._colors.now_line)
                gfx.line(x, baseline_y, x, tick_bottom)

                if t % _SEC_PER_HOUR == 0:
                    hour = time.gmtime(t)[3]
                    label = str(hour)
                    gfx.set_pen(self._colors.axis_text)
                    text_w = gfx.measure_text(label, scale=geom.bar_text_scale)
                    label_x = x - text_w // 2
                    if 0 <= label_x and label_x + text_w <= width:
                        gfx.text(label, label_x, geom.axis_y, scale=geom.bar_text_scale)

            t += _SEC_PER_QUARTER

    def draw_static_overlay(self) -> None:
        geom = self._geom
        gfx = self._gfx

        gfx.set_pen(self._colors.now_line)
        x = geom.now_x

        for i in range(geom.num_rows):
            gap_top = geom.gap_y[i]
            gfx.line(x, gap_top, x, gap_top + geom.gap_height - 1)

        # Horizontal baseline at the bottom of the last gap
        baseline_y = geom.gap_y[geom.num_rows - 1] + geom.gap_height - 1
        gfx.line(0, baseline_y, geom.width - 1, baseline_y)

    def update(self) -> None:
        self._gfx.update()


class Display(_Display):
    def __init__(
        self,
        renderer: Renderer,
        streams: list[EventWindow],
        get_time,  # () -> int
    ) -> None:
        self._renderer = renderer
        self._streams = streams
        self._get_time = get_time
        self._gate = RefreshGate(60_000)
        self._active: bool = False

    def _redraw(self) -> None:
        now = self._get_time()
        window_start = now - _WINDOW_PAST_SEC
        window_end = now + _WINDOW_FUTURE_SEC

        self._renderer.header_write(format_header_time(now))
        self._renderer.draw_rows(self._streams, window_start, window_end)
        self._renderer.draw_time_axis(window_start, window_end)
        self._renderer.update()

    def tick(self) -> None:
        if not self._gate.ready():
            return
        self._redraw()

    def initialize(self) -> None:
        if self._active:
            return
        self._active = True
        self._gate.reset()
        self._renderer.reset()
        self._renderer.draw_static_overlay()
        self._redraw()

    def deinitialize(self) -> None:
        if not self._active:
            return
        self._active = False
