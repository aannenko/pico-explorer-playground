import micropython
import time

from micropython import const
from picographics import PicoGraphics  # type: ignore

from displays.base import Display as _Display
from displays.palette import LABEL_FOR_SLOT
from displays.shared.header import format_header_time, header_fits
from scheduling.event_window import EventWindow
from scheduling.stream import FRESH

WINDOW_PAST_SEC = const(30 * 60)
WINDOW_FUTURE_SEC = const(90 * 60)
WINDOW_TOTAL_SEC = const(WINDOW_PAST_SEC + WINDOW_FUTURE_SEC)

_MAX_STREAMS = const(5)
_HEADER_MARGIN = const(6)
_AXIS_MARGIN = const(3)
_BAR_TEXT_MARGIN = const(2)
_BAR_SEAM_PX = const(1)
_MIN_LABEL_PX = const(14)

_SEC_PER_HOUR = const(3600)
_SEC_PER_QUARTER = const(900)
_TICK_MARK_HEIGHT = const(4)
_STATUS_GLYPH_PX = const(4)


def _fmt_remaining(sec: int) -> str:
    h = sec // 3600
    m = sec % 3600 // 60
    return f"-{h:02}:{m:02}"


class Colors:
    """Pens for the Calendar view, except event bars and their labels."""

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
    """Pixel layout of the Calendar view: a header, ``_MAX_STREAMS`` rows and a time axis.

    Raises ``RuntimeError`` if the header doesn't fit the panel width.
    """

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

        self.header_font = header_font
        self.header_text_scale = header_text_scale
        self.header_height = header_font_height * header_text_scale
        self.header_y = 0

        if not header_fits(pico_graphics, header_font, header_text_scale, self.width):
            raise RuntimeError(
                "calendar geometry: no room for header (font/scale too large)"
            )

        self.bar_font = bar_font
        self.bar_text_scale = bar_text_scale
        self.bar_text_height = bar_font_height * bar_text_scale

        self.axis_height = bar_font_height * bar_text_scale
        self.axis_y = self.height - self.axis_height

        body_top = self.header_height + _HEADER_MARGIN
        body_bottom = self.axis_y - _AXIS_MARGIN
        body_height = body_bottom - body_top

        cell_height = body_height // _MAX_STREAMS
        gap = max(3, cell_height // 5)
        bar_height = cell_height - gap

        self.num_rows = _MAX_STREAMS
        self.row_y: list[int] = []
        self.row_height = bar_height
        self.gap_y: list[int] = []
        self.gap_height = gap

        for i in range(_MAX_STREAMS):
            row_top = body_top + i * cell_height
            self.row_y.append(row_top)
            self.gap_y.append(row_top + bar_height)

        self.now_x = self.width // 4


class Renderer:
    """Times are local epoch seconds."""

    def __init__(self, geometry: Geometry, colors: Colors) -> None:
        self._geom = geometry
        self._gfx = geometry.graphics
        self._colors = colors
        self._last_header = ""

    def reset(self) -> None:
        """Clear the screen to empty rows and forget the drawn header."""
        self._last_header = ""
        gfx = self._gfx
        geom = self._geom

        gfx.set_pen(self._colors.background)
        gfx.clear()

        gfx.set_pen(self._colors.empty_row)
        for row_idx in range(geom.num_rows):
            gfx.rectangle(0, geom.row_y[row_idx], geom.width, geom.row_height)

    def header_write(self, text: str) -> None:
        """Draw ``text`` in the header strip unless it is already shown."""
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
        now = window_start + WINDOW_PAST_SEC

        gfx.set_font(geom.bar_font)

        for row_idx in range(len(streams)):
            row_top = geom.row_y[row_idx]
            bar_h = geom.row_height

            gfx.set_pen(self._colors.empty_row)
            gfx.rectangle(0, row_top, width, bar_h)

            stream = streams[row_idx]
            visible = stream.get_visible(window_start, window_end)
            n_visible = len(visible)

            for i in range(n_visible):
                event, pen = visible[i]
                ev_start = event.start_timestamp
                ev_end = ev_start + event.wall_clock_duration_sec

                # Prevent overlapping bars from stacking; this also hides the
                # remaining time of a clipped bar.
                if i + 1 < n_visible:
                    next_start = visible[i + 1][0].start_timestamp
                    if next_start < ev_end:
                        ev_end = next_start

                x0 = max(0, (ev_start - window_start) * width // WINDOW_TOTAL_SEC)
                x1 = min(width, (ev_end - window_start) * width // WINDOW_TOTAL_SEC)

                if x1 <= x0:
                    continue

                gfx.set_pen(pen)
                gfx.rectangle(x0, row_top, x1 - x0, bar_h)

                # Seams keep adjacent bars distinct, same colour or not.
                gfx.set_pen(self._colors.empty_row)
                if x0 - _BAR_SEAM_PX >= 0:
                    gfx.rectangle(x0 - _BAR_SEAM_PX, row_top, _BAR_SEAM_PX, bar_h)
                gfx.rectangle(x1 - _BAR_SEAM_PX, row_top, _BAR_SEAM_PX, bar_h)

                bar_px = x1 - x0
                text_y = row_top + (bar_h - geom.bar_text_height) // 2 + 2
                label_right = x0
                usable_px = bar_px - 2 * _BAR_TEXT_MARGIN

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
                        gfx.set_pen(LABEL_FOR_SLOT[pen])
                        gfx.text(label, x0 + _BAR_TEXT_MARGIN, text_y, scale=geom.bar_text_scale)
                        label_right = x0 + _BAR_TEXT_MARGIN + text_w

                if ev_end > window_end:
                    remaining = ev_end - now
                    if remaining > 0:
                        rem_text = _fmt_remaining(remaining)
                        rem_w = gfx.measure_text(rem_text, scale=geom.bar_text_scale)
                        rem_x = x1 - rem_w - _BAR_TEXT_MARGIN
                        if rem_x > label_right + 1:
                            gfx.set_pen(LABEL_FOR_SLOT[pen])
                            gfx.text(rem_text, rem_x, text_y, scale=geom.bar_text_scale)

            status = stream.status()
            if status is not None and status != FRESH:
                gfx.set_pen(self._colors.now_line)
                gfx.rectangle(width - _STATUS_GLYPH_PX, row_top, _STATUS_GLYPH_PX, _STATUS_GLYPH_PX)

    @micropython.native
    def draw_time_axis(self, window_start: int, window_end: int) -> None:
        """Redraw the time axis: quarter-hour ticks and hour labels."""
        geom = self._geom
        gfx = self._gfx
        width = geom.width

        baseline_y = geom.gap_y[geom.num_rows - 1] + geom.gap_height - 1
        tick_bottom = baseline_y + _TICK_MARK_HEIGHT

        gfx.set_pen(self._colors.background)
        gfx.rectangle(0, baseline_y + 1, width, geom.axis_y + geom.axis_height - baseline_y - 1)

        gfx.set_font(geom.bar_font)

        first_q = (window_start // _SEC_PER_QUARTER) * _SEC_PER_QUARTER
        if first_q < window_start:
            first_q += _SEC_PER_QUARTER

        t = first_q
        while t < window_end:
            x = (t - window_start) * width // WINDOW_TOTAL_SEC

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
        """Draw the parts that never move: the now-line and the axis baseline."""
        geom = self._geom
        gfx = self._gfx

        gfx.set_pen(self._colors.now_line)
        x = geom.now_x

        for i in range(geom.num_rows):
            gap_top = geom.gap_y[i]
            gfx.line(x, gap_top, x, gap_top + geom.gap_height - 1)

        baseline_y = geom.gap_y[geom.num_rows - 1] + geom.gap_height - 1
        gfx.line(0, baseline_y, geom.width - 1, baseline_y)

    def update(self) -> None:
        """Push the framebuffer to the panel."""
        self._gfx.update()


class Display(_Display):
    """Calendar view: a timeline of event rows that scrolls with the clock.

    ``streams`` must hold at most ``_MAX_STREAMS`` rows, and ``get_time`` must
    return local epoch seconds.
    """

    refresh_period_ms = 60_000

    def __init__(
        self,
        renderer: Renderer,
        streams: list[EventWindow],
        get_time,  # () -> int
    ) -> None:
        self._renderer = renderer
        self._streams = streams
        self._get_time = get_time
        self._active = False

    def _redraw(self) -> None:
        now = self._get_time()
        window_start = now - WINDOW_PAST_SEC
        window_end = now + WINDOW_FUTURE_SEC

        self._renderer.header_write(format_header_time(now))
        self._renderer.draw_rows(self._streams, window_start, window_end)
        self._renderer.draw_time_axis(window_start, window_end)
        self._renderer.update()

    def render(self) -> None:
        self._redraw()

    def initialize(self) -> None:
        if self._active:
            return
        self._active = True
        self._renderer.reset()
        self._renderer.draw_static_overlay()
        self._redraw()

    def deinitialize(self) -> None:
        if not self._active:
            return
        self._active = False
