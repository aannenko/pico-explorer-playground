import micropython
import time

from micropython import const

from displays.base import Display as _Display
from displays.palette import (
    BLUE,
    GREEN,
    LABEL_FOR_SLOT,
    ORANGE,
    RED,
    RPURPLE,
    SKY,
    YELLOW,
)
from displays.shared import _icons_data, icons_p4
from displays.shared.header import format_header_time, header_fits
from picographics import PicoGraphics  # type: ignore
from services.pimoroni_bme690 import PimoroniBME690


_HISTORY_MS = const(24 * 3600 * 1000)
_L_GAP = const(3)  # px between value text and graph
_R_MARGIN = const(0)  # px between graph right edge and screen edge
_ICON_SCALE = const(2)
# bitmap8 glyph ink sits high in its cell, so a box-centred icon reads low
# against digits.
_ICON_INK_LIFT_PX = const(2)
# Its width is the budget every value string must fit: 63 px at bitmap8 scale 3.
# "-99.9", the widest _fit_chars emits, also measures 63; its integer limits "9999"
# and "-999" measure 57 and 54.
_WIDEST_GRAPH_VALUE = "-88.8"


def _largest_divisor_of(n: int, max_val: int) -> int:
    """Return the largest ``d`` in 1..``max_val`` that divides ``n``."""
    if max_val < 1:
        raise ValueError("max_val must be >= 1")
    if max_val > n:
        max_val = n
    d = max_val
    while d > 1:
        if n % d == 0:
            return d
        d -= 1
    return 1


class Colors:
    """Pens for the Sensors view's background and text."""

    def __init__(
        self,
        background: int,
        header_text: int,
        value_text: int,
        secondary_text: int,
    ) -> None:
        self.background = background
        self.header_text = header_text
        self.value_text = value_text
        self.secondary_text = secondary_text


class Geometry:
    """Pixel layout of the Sensors view, plus scheduler ticks per graph column.

    Raises ``RuntimeError`` if the font and scale leave no room for the header or graph.
    """

    @micropython.native
    def __init__(
        self,
        pico_graphics: PicoGraphics,
        font: str,
        font_height: int,
        text_scale: int,
        tick_period_ms: int,
    ) -> None:
        self.graphics = pico_graphics

        self.width, self.height = pico_graphics.get_bounds()

        self.font = font
        pico_graphics.set_font(font)
        self.text_scale = text_scale
        self.text_height = font_height * text_scale
        self.line_spacing = self.text_height // 2

        self.header_y = 0

        self.values_top_y = self.text_height + self.line_spacing

        self.line_y = (
            self.values_top_y,
            self.values_top_y * 2,
            self.values_top_y * 3,
            self.values_top_y * 4,
            self.values_top_y * 5,
            self.values_top_y * 6,
        )

        self.header_rect = (0, 0, self.width, self.text_height)

        if not header_fits(pico_graphics, font, text_scale, self.width):
            raise RuntimeError(
                "sensors geometry: no room for header (font/scale too large)"
            )

        self.value_rect_height = self.text_height

        icon_px, unit_px = left_column_native_px()

        self.icon_scale = _ICON_SCALE
        # Doubles as the icon height, so band icons must be square.
        self.icon_size_px = icon_px * _ICON_SCALE
        self.icon_y_offset = (self.icon_size_px - self.text_height) // 2 + _ICON_INK_LIFT_PX

        self.unit_scale = text_scale
        self.unit_size_px = unit_px * self.unit_scale

        self.icon_x = 0
        self.unit_x = self.icon_x + self.icon_size_px + 4
        self.value_x = self.unit_x + self.unit_size_px + 6

        value_max_text_width = pico_graphics.measure_text(
            _WIDEST_GRAPH_VALUE, scale=text_scale
        )
        self.graph_x = self.value_x + value_max_text_width + _L_GAP
        available = self.width - self.graph_x - _R_MARGIN
        if available < 1:
            raise RuntimeError(
                "sensors geometry: no room for graph (font/scale too large)"
            )
        total_ticks = _HISTORY_MS // tick_period_ms
        # A divisor, so the columns span exactly 24 h of ticks.
        self.graph_width = _largest_divisor_of(total_ticks, available)
        self.ticks_per_commit = total_ticks // self.graph_width
        self.graph_height = self.text_height

        # Stops at graph_x so clearing a value never erases the graph.
        self.value_clear_width = self.graph_x - self.value_x


class Renderer:
    """Line-based drawing: each line holds an icon, a unit, a value and a history graph."""

    def __init__(self, geometry: Geometry, colors: Colors) -> None:
        self._geom = geometry
        self._gfx = geometry.graphics
        self._colors = colors

        self._last_header = ""
        self._last_lines = ["", "", "", "", "", ""]
        self._update_needed = False

    def reset(self) -> None:
        """Clear the screen and forget the drawn header and lines."""
        self._last_header = ""
        for i in range(len(self._last_lines)):
            self._last_lines[i] = ""
        self._gfx.set_font(self._geom.font)
        self._gfx.set_pen(self._colors.background)
        self._gfx.clear()
        self._update_needed = True

    def draw_left_column(
        self,
        line_idx: int,
        icon: tuple,
        unit: tuple,
    ) -> None:
        """Draw a line's ``icon`` and ``unit``; their area must already be clear."""
        if line_idx < 0 or line_idx >= len(self._last_lines):
            return
        self._update_needed = True
        g = self._geom
        y = g.line_y[line_idx]
        icons_p4.draw_icon(self._gfx, icon, g.icon_x, y - g.icon_y_offset, g.icon_scale)
        icons_p4.draw_icon(self._gfx, unit, g.unit_x, y, g.unit_scale)

    def header_write(self, text: str) -> None:
        """Draw ``text`` in the header strip unless it is already shown."""
        if text == self._last_header:
            return
        self._last_header = text
        self._update_needed = True

        self._gfx.set_pen(self._colors.background)
        x, y, w, h = self._geom.header_rect
        self._gfx.rectangle(x, y, w, h)

        if not text:
            return

        self._gfx.set_pen(self._colors.header_text)
        self._gfx.text(text, 0, self._geom.header_y, scale=self._geom.text_scale)

    def line_write(self, line_idx: int, text: str, *, pen: int) -> None:
        """Draw ``text`` in a line's value cell unless it is already shown."""
        if line_idx < 0 or line_idx >= len(self._last_lines):
            return
        if text == self._last_lines[line_idx]:
            return

        self._update_needed = True
        g = self._geom
        self._gfx.set_pen(self._colors.background)
        self._gfx.rectangle(g.value_x, g.line_y[line_idx], g.value_clear_width, g.value_rect_height)

        if text:
            self._gfx.set_pen(pen)
            self._gfx.text(text, g.value_x, g.line_y[line_idx], scale=g.text_scale)

        self._last_lines[line_idx] = text

    def redraw_row_icon(self, line_idx: int, icon: tuple) -> None:
        """Replace a line's icon, erasing the old one."""
        if line_idx < 0 or line_idx >= len(self._last_lines):
            return
        self._update_needed = True
        g = self._geom
        icon_y = g.line_y[line_idx] - g.icon_y_offset
        self._gfx.set_pen(self._colors.background)
        self._gfx.rectangle(g.icon_x, icon_y, g.icon_size_px, g.icon_size_px)
        icons_p4.draw_icon(self._gfx, icon, g.icon_x, icon_y, g.icon_scale)

    def value_write(self, line_idx: int, text: str) -> None:
        self.line_write(line_idx, text, pen=self._colors.value_text)

    def secondary_write(self, line_idx: int, text: str) -> None:
        """Draw ``text`` in a line's value cell as secondary text."""
        self.line_write(line_idx, text, pen=self._colors.secondary_text)

    def draw_graph_clear(self, line_idx: int) -> None:
        if line_idx < 0 or line_idx >= len(self._last_lines):
            return
        self._update_needed = True
        g = self._geom
        self._gfx.set_pen(self._colors.background)
        self._gfx.rectangle(g.graph_x, g.line_y[line_idx], g.graph_width, g.graph_height)

    @micropython.native
    def draw_graph_column(
        self,
        line_idx: int,
        col: int,
        fill_pen: int,
        marker_pen: int | None,
        value_y: int | None,
    ) -> None:
        """Draw one full-height graph column, optionally with a marker pixel.

        ``col`` is graph-local (0..graph_width-1) and ``value_y`` row-local (0 is top);
        the marker is drawn only when ``marker_pen`` and ``value_y`` are both set.
        """
        if line_idx < 0 or line_idx >= len(self._last_lines):
            return
        self._update_needed = True
        g = self._geom
        x = g.graph_x + col
        y = g.line_y[line_idx]
        self._gfx.set_pen(fill_pen)
        self._gfx.rectangle(x, y, 1, g.graph_height)
        if marker_pen is not None and value_y is not None:
            self._gfx.set_pen(marker_pen)
            self._gfx.pixel(x, y + value_y)

    def update(self) -> None:
        """Push the framebuffer to the panel if drawn to since the last push."""
        if not self._update_needed:
            return
        self._update_needed = False
        self._gfx.update()


class Display(_Display):
    """Sensors view: live BME690 readings with band icons and 24 h history graphs."""

    # (unit, cells) per row, in ``PimoroniBME690.read()`` order; cells are four
    # low-to-high (icon, fill_slot) bands, colocated so a band's icon and graph fill
    # can't drift apart.
    ROWS = (
        (
            _icons_data.UNIT_CELSIUS,
            (
                (_icons_data.ICON_THERMO_BLUE, SKY),
                (_icons_data.ICON_THERMO_GREEN, GREEN),
                (_icons_data.ICON_THERMO_ORANGE, ORANGE),
                (_icons_data.ICON_THERMO_RED, RED),
            ),
        ),
        (
            _icons_data.UNIT_MBAR,
            (
                (_icons_data.ICON_GAUGE_MIN, RPURPLE),
                (_icons_data.ICON_GAUGE_LOW, GREEN),
                (_icons_data.ICON_GAUGE_HIGH, YELLOW),
                (_icons_data.ICON_GAUGE_MAX, ORANGE),
            ),
        ),
        (
            _icons_data.UNIT_PERCENT,
            (
                (_icons_data.ICON_DROP_LOW, YELLOW),
                (_icons_data.ICON_DROP_MED, GREEN),
                (_icons_data.ICON_DROP_HIGH, SKY),
                (_icons_data.ICON_DROP_MAX, BLUE),
            ),
        ),
        (
            _icons_data.UNIT_KOHM,
            (
                (_icons_data.ICON_MASK_RED, RED),
                (_icons_data.ICON_MASK_ORANGE, ORANGE),
                (_icons_data.ICON_MASK_GREEN, GREEN),
                (_icons_data.ICON_MASK_BLUE, SKY),
            ),
        ),
    )

    _GAS_ROW = 3

    def __init__(
        self,
        renderer: Renderer,
        bme690_reader: PimoroniBME690,
        time_service,
        history,
        graph_height: int,
        *,
        temp_bands: tuple,
        pressure_bands: tuple,
        humidity_bands: tuple,
        gas_bands: tuple,
    ) -> None:
        self._renderer = renderer
        self._time_service = time_service
        self._bme690_reader = bme690_reader
        self._history = history
        self._band_pens = build_sensor_band_pens()
        self._graph_height = graph_height
        self._active = False
        self._row_icons: list[tuple | None] = [None] * len(self.ROWS)
        self._last_rendered_reading: tuple | None = None
        self._last_commit = -1
        self._gas_was_stable: bool | None = None
        self._last_header_minute = -1
        self._next_header_check_ms = 0

        bands_per_row = (temp_bands, pressure_bands, humidity_bands, gas_bands)
        self._rows = tuple(
            (unit, self._validated_bands(i, bands_per_row[i]), cells)
            for i, (unit, cells) in enumerate(self.ROWS)
        )

    @staticmethod
    def _validated_bands(row_index: int, bands) -> tuple:
        """Return ``bands`` as a tuple of edges ``(cap_min, t1, t2, t3, cap_max)``.

        Raises ``ValueError`` unless ``bands`` holds 5 strictly ascending edges.
        """
        if len(bands) != 5:
            raise ValueError(
                "Display row {} requires 5 band edges (cap_min, t1, t2, t3, cap_max), got {}".format(
                    row_index, len(bands)
                )
            )
        b0, b1, b2, b3, b4 = bands
        if not (b0 < b1 < b2 < b3 < b4):
            raise ValueError(
                "Display row {} band edges must be strictly ascending, got {}".format(
                    row_index, bands
                )
            )
        return (b0, b1, b2, b3, b4)

    @staticmethod
    def _band_index(value: float, edges: tuple) -> int:
        """Return ``value``'s band, 0..3, as split by the three inner edges of ``edges``.

        A value on an edge falls in the band above it.  The outer edges bound the graph,
        not the bands.
        """
        if value < edges[1]:
            return 0
        if value < edges[2]:
            return 1
        if value < edges[3]:
            return 2
        return 3

    @staticmethod
    @micropython.native
    def _y_for(value: float, edges: tuple, graph_height: int) -> int | None:
        """Map ``value`` to the row-local y of its marker pixel.

        ``cap_max`` (``edges[-1]``) maps to y 0 (top) and ``cap_min`` (``edges[0]``)
        to ``graph_height - 1`` (bottom), both inclusive; outside them it returns
        ``None``.  ``value`` must not be NaN.
        """
        cap_min = edges[0]
        cap_max = edges[-1]
        if value < cap_min or value > cap_max:
            return None
        return round((cap_max - value) * (graph_height - 1) / (cap_max - cap_min))

    @staticmethod
    def _fit_chars(value: float, decimals: int) -> str:
        """Format ``value`` for the sensor value cell.

        Shows ``decimals`` places while the rounded value is within (-100, 100), else
        the nearest integer, clamped to -999..9999.

        ``decimals`` must be at most 1, or an in-range value can exceed the
        ``_WIDEST_GRAPH_VALUE`` budget: ``PicoGraphics.text()`` doesn't clip
        to the value cell, so an overflow would overdraw the history graph.
        """
        # Range-check the rounded value: -99.99 formats as "-100.0", which overdraws.
        if decimals > 0 and -100 < round(value, decimals) < 100:
            return "{:.{}f}".format(value, decimals)
        i = round(value)
        if i > 9999:
            return "9999"
        if i < -999:
            return "-999"
        return str(i)

    def _maybe_swap_icon(self, line_idx: int, new_icon: tuple) -> None:
        if new_icon != self._row_icons[line_idx]:
            self._renderer.redraw_row_icon(line_idx, new_icon)
            self._row_icons[line_idx] = new_icon

    @micropython.native
    def _redraw_graphs(self, gas_stable_now: bool) -> None:
        """While gas warms up, its wide status text owns the graph pixels; do not
        paint columns over it.
        """
        history = self._history
        renderer = self._renderer
        band_pens = self._band_pens
        capacity = history.capacity
        gas_row = self._GAS_ROW

        for metric_idx in range(len(self._rows)):
            _unit, edges, _cells = self._rows[metric_idx]

            if metric_idx == gas_row:
                if not gas_stable_now:
                    if self._gas_was_stable is True:
                        renderer.draw_graph_clear(gas_row)
                    continue

            renderer.draw_graph_clear(metric_idx)
            graph_height = self._graph_height
            pens_row = band_pens[metric_idx]
            for i in range(history.filled(metric_idx)):
                value = history.value_at(metric_idx, i)
                if value != value:  # NaN
                    continue
                band = self._band_index(value, edges)
                fill_pen, marker_pen = pens_row[band]
                y = self._y_for(value, edges, graph_height)
                col = capacity - 1 - i
                renderer.draw_graph_column(
                    metric_idx,
                    col,
                    fill_pen,
                    marker_pen if y is not None else None,
                    y,
                )

    def _update_display(self) -> None:
        # The wall-clock read allocates, so do it only once a minute boundary is due.
        now_ms = time.ticks_ms()
        if time.ticks_diff(now_ms, self._next_header_check_ms) >= 0:
            now = self._time_service.now()
            minute = now // 60
            if minute != self._last_header_minute:
                self._last_header_minute = minute
                self._renderer.header_write(format_header_time(now))
            # No slack: an early read just recomputes a ~1 s deadline, while slack
            # can delay catching the minute rollover by a render.
            self._next_header_check_ms = time.ticks_add(now_ms, (60 - now % 60) * 1000)

        reading = self._bme690_reader.read()

        # Graph-redraw check lives BEFORE the reading-identity guard so a
        # history commit observed on a "reading unchanged" tick still fires.
        gas_stable_now = (reading[4] == "Stable")
        # Backfill the newest gas sample once valid rather than at the next commit;
        # must precede the redraw block, which updates _gas_was_stable.
        if gas_stable_now and self._gas_was_stable is not True:
            self._history.update_latest(self._GAS_ROW, reading[3])
        commit_now = self._history.commit_count
        if (
            commit_now != self._last_commit
            or gas_stable_now != self._gas_was_stable
        ):
            self._redraw_graphs(gas_stable_now)
            self._last_commit = commit_now
            self._gas_was_stable = gas_stable_now

        if reading is not self._last_rendered_reading:
            self._last_rendered_reading = reading
            temp, press, hum, gas_r, status = reading

            # Direct indexing avoids a temporary tuple and enumerate object.
            for i in range(len(self._rows)):
                if i == self._GAS_ROW and status != "Stable":
                    continue
                _unit, edges, cells = self._rows[i]
                self._maybe_swap_icon(i, cells[self._band_index(reading[i], edges)][0])

            self._renderer.value_write(0, self._fit_chars(temp, 1))  # "22.4", "-99.9", "100"
            self._renderer.value_write(1, self._fit_chars(press, 0))  # "1013"
            self._renderer.value_write(2, self._fit_chars(hum, 1))  # "50.5", "100"
            if status == "Stable":
                self._renderer.value_write(3, self._fit_chars(gas_r, 1))  # "75.3", "251", "1000"
            else:
                self._renderer.value_write(3, "warming...")

        self._renderer.update()

    def render(self) -> None:
        self._update_display()

    def initialize(self) -> None:
        if self._active:
            return
        self._active = True
        self._renderer.reset()
        for i, (unit, _edges, cells) in enumerate(self._rows):
            # Band 1 by default, so a typical indoor reading needs no first swap.
            default_icon = cells[1][0]
            self._renderer.draw_left_column(i, default_icon, unit)
            self._row_icons[i] = default_icon
        # A cleared screen still needs repainting when the reading object is unchanged.
        self._last_rendered_reading = None
        self._last_commit = -1
        self._gas_was_stable = None
        self._last_header_minute = -1
        self._next_header_check_ms = time.ticks_ms()
        self._update_display()

    def deinitialize(self) -> None:
        if not self._active:
            return
        self._active = False


def build_sensor_band_pens():
    """Return each band's ``(fill, marker)`` pens, indexed ``pens[metric_idx][band_idx]``.

    The marker is the fill's auto-contrast, precomputed so the render loop does no
    palette lookups.
    """
    return tuple(
        tuple((fill, LABEL_FOR_SLOT[fill]) for _icon, fill in cells)
        for _unit, cells in Display.ROWS
    )


def left_column_native_px() -> tuple[int, int]:
    """Return the ``(icon, unit)`` native pixel widths the left column must fit.

    Derived from the art so no size constant can drift from it.
    """
    icon_px = 0
    unit_px = 0
    for unit, cells in Display.ROWS:
        if unit[0] > unit_px:
            unit_px = unit[0]
        for icon, _fill in cells:
            if icon[0] > icon_px:
                icon_px = icon[0]
    return icon_px, unit_px
