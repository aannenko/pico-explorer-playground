import math
import time

from micropython import const
from picographics import PicoGraphics  # type: ignore

from displays.base import Display as _Display
from displays.palette import (
    BLACK,
    DARK_GRAY,
    GRAY,
    GREEN,
    GREEN_SHADE,
    ORANGE,
    ORANGE_SHADE,
    PINK,
    PINK_SHADE,
    SKY,
    SKY_SHADE,
    WHITE,
)
from displays.shared import _icons_data, icons_p4
from services.ring_history import RingHistory


_HISTORY_MS = const(24 * 3600 * 1000)
_GUTTER_PX = const(3)
# Between stacked elements, and from the outermost ones to the panel edge or the gutter.
_MARGIN_PX = const(4)
_ICON_ART_PX = const(16)
_ICON_SCALE = const(2)
# Blank art rows above and below every band icon's ink, so margins can be measured to the ink.
_ICON_INK_INSET_ROWS = const(1)
_UNIT_ART_PX = const(8)
# Unit ink sits high in its cell, as bitmap8's does, so a unit centred on its icon's box reads high.
_UNIT_DROP_PX = const(2)
# bitmap8's bottom cell row holds only descenders, which values, times and weekday names never use.
_DESCENDER_ROWS = const(1)
_BADGE_LINE_GAP_PX = const(4)
# Black space between the smallest disc that holds every badge line and the ring.
_BADGE_PADDING_PX = const(2)
# The badge is a 2-px DARK_GRAY ring with a 2-px black border outside it.
_BADGE_RING_PX = const(2)
_BADGE_BORDER_PX = const(2)
_GRAPH_PAD_PCT = const(8)
_TYPICAL_INDOOR_BAND_INDEX = const(1)

# _TextCell alignments: how many halves of the spare width go left of the text.
_ALIGN_LEFT = const(0)
_ALIGN_CENTER = const(1)
_ALIGN_RIGHT = const(2)

# Its width is the budget every value string must fit: 63 px at bitmap8 scale 3.
# "-99.9", the widest _format_value emits, also measures 63; its integer limits "9999"
# and "-999" measure 57 and 54.
_WIDEST_VALUE_TEXT = "-88.8"
# bitmap8 draws '1' narrower than every other digit.
_WIDEST_TIME_TEXT = "00:00"
_WIDEST_MDAY_TEXT = "20"
_RANGE_SEPARATOR = ".."
_PLACEHOLDER_TEXT = "--"
_WARMING_TEXT = "warming..."
# Three characters per name, sliced out rather than kept as 19 short literals that would each take a qstr slot.
_WEEKDAY_NAMES = "MonTueWedThuFriSatSun"
_MONTH_NAMES = "JanFebMarAprMayJunJulAugSepOctNovDec"
# Weekday, time and date, top to bottom.
_BADGE_PENS = (GRAY, WHITE, GRAY)

# Per metric in ``PimoroniBME690.read()`` order, which also places the quadrants left to right, then top to
# bottom: (unit, band icons from low to high, decimals, field pen, graph fill pen, minimum graph span, log scale).
# On a log scale the span is a natural-log ratio: the gas graph spans at least a doubling.
_METRICS = (
    (
        _icons_data.UNIT_CELSIUS,
        (
            _icons_data.ICON_THERMO_BLUE,
            _icons_data.ICON_THERMO_GREEN,
            _icons_data.ICON_THERMO_ORANGE,
            _icons_data.ICON_THERMO_RED,
        ),
        1,
        ORANGE,
        ORANGE_SHADE,
        4.0,
        False,
    ),
    (
        _icons_data.UNIT_MBAR,
        (
            _icons_data.ICON_GAUGE_MIN,
            _icons_data.ICON_GAUGE_LOW,
            _icons_data.ICON_GAUGE_HIGH,
            _icons_data.ICON_GAUGE_MAX,
        ),
        0,
        PINK,
        PINK_SHADE,
        10.0,
        False,
    ),
    (
        _icons_data.UNIT_PERCENT,
        (
            _icons_data.ICON_DROP_LOW,
            _icons_data.ICON_DROP_MED,
            _icons_data.ICON_DROP_HIGH,
            _icons_data.ICON_DROP_MAX,
        ),
        1,
        SKY,
        SKY_SHADE,
        20.0,
        False,
    ),
    (
        _icons_data.UNIT_KOHM,
        (
            _icons_data.ICON_MASK_RED,
            _icons_data.ICON_MASK_ORANGE,
            _icons_data.ICON_MASK_GREEN,
            _icons_data.ICON_MASK_BLUE,
        ),
        1,
        GREEN,
        GREEN_SHADE,
        math.log(2),
        True,
    ),
)


def _format_value(value: float, decimals: int) -> str:
    """Show ``decimals`` places while the rounded value is within (-100, 100), else
    the nearest integer, clamped to -999..9999.

    ``decimals`` must be at most 1, or an in-range value can exceed the
    ``_WIDEST_VALUE_TEXT`` budget: ``PicoGraphics.text()`` doesn't clip
    to the value cell, so an overflow would overdraw its neighbours.
    """
    # Range-check the rounded value: -99.99 formats as "-100.0", which overflows.
    if decimals > 0 and -100 < round(value, decimals) < 100:
        return "{:.{}f}".format(value, decimals)
    i = round(value)
    if i > 9999:
        return "9999"
    if i < -999:
        return "-999"
    return str(i)


def _band_index(value: float, edges: tuple[float, float, float]) -> int:
    """Return ``value``'s band, 0..3, as split by ``edges``; a value on an edge falls in the band above it."""
    if value < edges[0]:
        return 0
    if value < edges[1]:
        return 1
    if value < edges[2]:
        return 2
    return 3


def _graph_bounds(lo: float, hi: float, min_span: float) -> tuple[float, float]:
    """Return the plotted bounds for samples spanning ``lo``..``hi``.

    A span under ``min_span`` widens about its middle to ``min_span``, so a steady reading plots as a level
    line rather than magnified noise; then each end gains ``_GRAPH_PAD_PCT`` % of the span.
    """
    span = hi - lo
    if span < min_span:
        lo -= (min_span - span) / 2
        span = min_span
    pad = span * _GRAPH_PAD_PCT / 100
    return lo - pad, lo + span + pad


def _format_badge(local_epoch: int) -> tuple[str, str, str]:
    """Return the badge's weekday, time and date for ``local_epoch``, e.g. ``("Mon", "13:08", "2 Nov")``."""
    fields = time.gmtime(local_epoch)
    month, mday, hour, minute = fields[1:5]
    weekday_start = 3 * fields[6]
    month_start = 3 * (month - 1)
    return (
        _WEEKDAY_NAMES[weekday_start:weekday_start + 3],
        f"{hour:02}:{minute:02}",
        str(mday) + " " + _MONTH_NAMES[month_start:month_start + 3],
    )


def _split(size: int) -> tuple[tuple[int, int], tuple[int, int]]:
    """Return the ``(start, length)`` spans either side of the central gutter; the first takes the odd pixel."""
    first = (size - _GUTTER_PX + 1) // 2
    return ((0, first), (first + _GUTTER_PX, size - first - _GUTTER_PX))


def _place(start: int, length: int, from_end: bool, offset: int, size: int) -> int:
    """Return where a ``size``-px element starts that lies ``offset`` px in from its span's start, or end."""
    if from_end:
        return start + length - offset - size
    return start + offset


class Geometry:
    """Pixel layout shared by the Sensors view's quadrants and badge, and the shape of their history.

    The panel splits into four quadrants around a date and time badge.  Each graph column shows one history
    sample: ``graph_columns`` is the widest graph's count, and ``ticks_per_commit`` makes the narrowest graph's
    columns stand for at least 24 h.  Raises ``RuntimeError`` if the font and scales leave no room for a graph.
    """

    def __init__(
        self,
        pico_graphics: PicoGraphics,
        font: str,
        font_height: int,
        value_text_scale: int,
        label_text_scale: int,
        tick_period_ms: int,
    ) -> None:
        self.pico_graphics = pico_graphics
        self.font = font
        self.value_text_scale = value_text_scale
        self.label_text_scale = label_text_scale
        width, height = pico_graphics.get_bounds()
        pico_graphics.set_font(font)
        self.col_spans = _split(width)
        self.row_spans = _split(height)

        ink_rows = font_height - _DESCENDER_ROWS
        self.value_width = pico_graphics.measure_text(_WIDEST_VALUE_TEXT, scale=value_text_scale)
        self.value_height = ink_rows * value_text_scale
        self.range_width = max(
            pico_graphics.measure_text(
                _WIDEST_VALUE_TEXT + _RANGE_SEPARATOR + _WIDEST_VALUE_TEXT, scale=label_text_scale
            ),
            pico_graphics.measure_text(_WARMING_TEXT, scale=label_text_scale),
        )
        self.label_ink_height = ink_rows * label_text_scale
        # The whole cell, since "warming..." descends.
        self.range_height = font_height * label_text_scale
        self.icon_size = _ICON_ART_PX * _ICON_SCALE
        self.unit_size = _UNIT_ART_PX * label_text_scale

        # Offsets from a quadrant's gutter edge; the margins are measured to ink.
        icon_inset = _ICON_INK_INSET_ROWS * _ICON_SCALE
        self.icon_offset = _MARGIN_PX - icon_inset
        self.value_offset = _MARGIN_PX + self.icon_size - 2 * icon_inset + _MARGIN_PX
        self.range_offset = self.value_offset + self.value_height + _MARGIN_PX
        self.graph_offset = self.range_offset + self.label_ink_height + _MARGIN_PX
        self.graph_height = min(self.row_spans[0][1], self.row_spans[1][1]) - self.graph_offset
        if self.graph_height < 1:
            raise RuntimeError("sensors geometry: no room for graph (font/scale too large)")

        self.graph_columns = max(self.col_spans[0][1], self.col_spans[1][1])
        narrowest = min(self.col_spans[0][1], self.col_spans[1][1])
        self.ticks_per_commit = -(-(_HISTORY_MS // tick_period_ms) // narrowest)

        self._place_badge(font_height, width // 2, height // 2)

    def _place_badge(self, font_height: int, x_center: int, y_center: int) -> None:
        self.x_center = x_center
        self.y_center = y_center
        measure_text = self.pico_graphics.measure_text
        label_scale = self.label_text_scale
        weekday_width = 0
        for i in range(0, len(_WEEKDAY_NAMES), 3):
            weekday_width = max(weekday_width, measure_text(_WEEKDAY_NAMES[i:i + 3], scale=label_scale))
        date_width = 0
        for i in range(0, len(_MONTH_NAMES), 3):
            date_width = max(
                date_width, measure_text(_WIDEST_MDAY_TEXT + " " + _MONTH_NAMES[i:i + 3], scale=label_scale)
            )
        time_width = measure_text(_WIDEST_TIME_TEXT, scale=self.value_text_scale)

        label_ink_height = self.label_ink_height
        # Centres the lines' ink plus the date's descenders.
        block_height = (
            2 * label_ink_height + self.value_height + 2 * _BADGE_LINE_GAP_PX + _DESCENDER_ROWS * label_scale
        )
        weekday_y = y_center - block_height // 2
        time_y = weekday_y + label_ink_height + _BADGE_LINE_GAP_PX
        date_y = time_y + self.value_height + _BADGE_LINE_GAP_PX
        # Each line's text is centred in the rectangle its widest text needs; only the date descends.
        self.badge_rects = (
            (x_center - weekday_width // 2, weekday_y, weekday_width, label_ink_height),
            (x_center - time_width // 2, time_y, time_width, self.value_height),
            (x_center - date_width // 2, date_y, date_width, font_height * label_scale),
        )
        self.badge_scales = (label_scale, self.value_text_scale, label_scale)

        # The smallest circle() holding every rectangle plus a 1-px margin, so erasing one never touches the ring.
        # PicoGraphics' circle(r) fills exactly the pixels with dx * dx + dy * dy < r * (r + 1), for any r >= 1.
        reach_sq = 0
        for x, y, w, h in self.badge_rects:
            dx = max(x_center - x + 1, x + w - x_center)
            dy = max(y_center - y + 1, y + h - y_center)
            reach_sq = max(reach_sq, dx * dx + dy * dy)
        inner_r = 0
        while inner_r * (inner_r + 1) <= reach_sq:
            inner_r += 1
        self.badge_r = inner_r + _BADGE_PADDING_PX + _BADGE_RING_PX + _BADGE_BORDER_PX


def _check_layout(
    rects: tuple[tuple[int, int, int, int], ...], bounds: tuple[int, int, int, int], geom: Geometry
) -> None:
    """Raise ``RuntimeError`` unless ``rects`` lie inside ``bounds``, clear of the badge and of each other.

    Rectangles are ``(x, y, width, height)``.  Each is erased and redrawn on its own, so an overlap would
    corrupt its neighbour.
    """
    x0, y0, width, height = bounds
    # PicoGraphics' circle() reaches up to half a pixel past its radius.
    clear_r = geom.badge_r + 1
    for i in range(len(rects)):
        x, y, w, h = rects[i]
        dx = max(x - geom.x_center, geom.x_center - (x + w - 1), 0)
        dy = max(y - geom.y_center, geom.y_center - (y + h - 1), 0)
        fits = (
            x0 <= x
            and x + w <= x0 + width
            and y0 <= y
            and y + h <= y0 + height
            and dx * dx + dy * dy > clear_r * clear_r
        )
        for j in range(i):
            other_x, other_y, other_w, other_h = rects[j]
            if x < other_x + other_w and other_x < x + w and y < other_y + other_h and other_y < y + h:
                fits = False
        if not fits:
            raise RuntimeError(
                "sensors geometry: a quadrant's elements overlap or leave it (font/scale too large)"
            )


class _TextCell:
    """A text slot that erases its rectangle to ``background`` and redraws only when its text changes.

    ``rect`` is ``(x, y, width, height)``.  Only the text is remembered, so a new pen alone doesn't redraw.
    Text wider than the rectangle overdraws its neighbours: ``PicoGraphics.text()`` doesn't clip.
    """

    def __init__(
        self,
        gfx: PicoGraphics,
        rect: tuple[int, int, int, int],
        scale: int,
        align: int,
        background: int,
    ) -> None:
        self._gfx = gfx
        self._x, self._y, self._width, self._height = rect
        self._scale = scale
        self._align = align
        self._background = background
        self._text: str | None = None

    def forget(self) -> None:
        """Make the next ``write`` draw; call after the screen is cleared."""
        self._text = None

    def write(self, text: str, pen: int) -> bool:
        """Show ``text`` in ``pen`` unless it is already shown; return whether anything was drawn."""
        if text == self._text:
            return False
        self._text = text
        gfx = self._gfx
        gfx.set_pen(self._background)
        gfx.rectangle(self._x, self._y, self._width, self._height)
        if text:
            x = self._x
            if self._align != _ALIGN_LEFT:
                spare = self._width - gfx.measure_text(text, scale=self._scale)
                x += spare * self._align // 2
            gfx.set_pen(pen)
            gfx.text(text, x, self._y, scale=self._scale)
        return True


class _Quadrant:
    """One metric's quadrant: field, band icon, unit, value, range and graph, and what it last drew.

    From the gutter outward it stacks the icon and unit, the value, the range and the graph; a right-hand
    quadrant aligns them to the panel's right edge.  Raises ``RuntimeError`` if they overlap each other or the
    badge, or leave the quadrant.
    """

    def __init__(self, geom: Geometry, metric_index: int, band_edges: tuple[float, float, float]) -> None:
        (
            self._unit,
            self._icons,
            self._decimals,
            self._field,
            self._shade,
            self._min_span,
            self._log_scale,
        ) = _METRICS[metric_index]
        self._geom = geom
        self._gfx = geom.pico_graphics
        self._metric_index = metric_index
        self._band_edges = band_edges

        col = metric_index & 1
        row = metric_index >> 1
        x, width = geom.col_spans[col]
        y, height = geom.row_spans[row]
        self._x = x
        self._y = y
        self._width = width
        self._height = height
        right = col == 1
        # Offsets run from the gutter, which is a top quadrant's bottom edge.
        top = row == 0
        value_rect = (
            _place(x, width, right, _MARGIN_PX, geom.value_width),
            _place(y, height, top, geom.value_offset, geom.value_height),
            geom.value_width,
            geom.value_height,
        )
        range_rect = (
            _place(x, width, right, _MARGIN_PX, geom.range_width),
            _place(y, height, top, geom.range_offset, geom.label_ink_height),
            geom.range_width,
            geom.range_height,
        )
        self._icon_x = _place(x, width, right, _MARGIN_PX, geom.icon_size)
        self._icon_y = _place(y, height, top, geom.icon_offset, geom.icon_size)
        self._unit_x = _place(x, width, right, _MARGIN_PX + geom.icon_size + _MARGIN_PX, geom.unit_size)
        self._unit_y = self._icon_y + (geom.icon_size - geom.unit_size) // 2 + _UNIT_DROP_PX
        self._graph_y = _place(y, height, top, geom.graph_offset, geom.graph_height)
        _check_layout(
            (
                value_rect,
                range_rect,
                (self._icon_x, self._icon_y, geom.icon_size, geom.icon_size),
                (self._unit_x, self._unit_y, geom.unit_size, geom.unit_size),
                (x, self._graph_y, width, geom.graph_height),
            ),
            (x, y, width, height),
            geom,
        )

        align = _ALIGN_RIGHT if right else _ALIGN_LEFT
        self._value_cell = _TextCell(self._gfx, value_rect, geom.value_text_scale, align, self._field)
        self._range_cell = _TextCell(self._gfx, range_rect, geom.label_text_scale, align, self._field)
        self._icon: tuple[int, int, bytes] | None = None
        self._valid: bool | None = None
        self._commit_count = -1
        self._range_lo: float | None = None
        self._range_hi: float | None = None

    def draw_static(self) -> None:
        """Paint the field and unit, and forget everything else drawn; call after the screen is cleared."""
        gfx = self._gfx
        gfx.set_pen(self._field)
        gfx.rectangle(self._x, self._y, self._width, self._height)
        icons_p4.draw_icon(gfx, self._unit, self._unit_x, self._unit_y, self._geom.label_text_scale)
        self._value_cell.forget()
        self._range_cell.forget()
        self._icon = None
        self._valid = None
        self._commit_count = -1
        self._range_lo = None
        self._range_hi = None

    def update(self, value: float, history: RingHistory, commit_count: int, reading_changed: bool) -> bool:
        """Draw what changed for the live ``value`` and the history; return whether anything was drawn.

        A NaN ``value`` means the sensor is warming up: the quadrant then shows a placeholder, keeps its icon,
        hides its graph and says so in its range.  ``commit_count`` is ``history.commit_count``, and
        ``reading_changed`` must be true whenever ``value`` may differ from the previous call's.
        """
        valid = value == value
        drew = False
        if valid:
            if self._valid is not True:
                # Backfill the newest sample once the value turns valid rather than at the next commit.
                # Entering the view also gets here and must keep a valid committed sample.
                newest = history.value_at(self._metric_index, 0)
                if newest != newest:  # NaN
                    history.update_latest(self._metric_index, value)
                self._replace_graph(history)
                drew = True
            elif commit_count != self._commit_count:
                self._replace_graph(history)
                drew = True
        elif self._valid is not False:
            self._clear_graph()
            self._range_lo = None
            self._range_hi = None
            self._range_cell.write(_WARMING_TEXT, DARK_GRAY)
            drew = True
        self._valid = valid
        self._commit_count = commit_count
        if reading_changed and self._write_reading(value):
            drew = True
        return drew

    def _write_reading(self, value: float) -> bool:
        valid = value == value
        if valid:
            icon = self._icons[_band_index(value, self._band_edges)]
            text = _format_value(value, self._decimals)
            pen = BLACK
        else:
            icon = self._icon if self._icon is not None else self._icons[_TYPICAL_INDOOR_BAND_INDEX]
            text = _PLACEHOLDER_TEXT
            pen = DARK_GRAY
        drew = False
        if icon is not self._icon:
            gfx = self._gfx
            size = self._geom.icon_size
            gfx.set_pen(self._field)
            gfx.rectangle(self._icon_x, self._icon_y, size, size)
            icons_p4.draw_icon(gfx, icon, self._icon_x, self._icon_y, _ICON_SCALE)
            self._icon = icon
            drew = True
        if self._value_cell.write(text, pen):
            drew = True
        if valid and self._widen_range(value):
            drew = True
        return drew

    def _widen_range(self, value: float) -> bool:
        """Widen the range to take in ``value``: a live reading can lead the history by a commit period."""
        lo = self._range_lo
        hi = self._range_hi
        if lo is not None and lo <= value <= hi:
            return False
        if lo is None or value < lo:
            lo = value
        if hi is None or value > hi:
            hi = value
        return self._write_range(lo, hi)

    def _write_range(self, lo: float, hi: float) -> bool:
        self._range_lo = lo
        self._range_hi = hi
        return self._range_cell.write(
            _format_value(lo, self._decimals) + _RANGE_SEPARATOR + _format_value(hi, self._decimals), DARK_GRAY
        )

    def _clear_graph(self) -> None:
        self._gfx.set_pen(self._field)
        self._gfx.rectangle(self._x, self._graph_y, self._width, self._geom.graph_height)

    def _replace_graph(self, history: RingHistory) -> None:
        """Plot the newest samples, one per column with the newest at the right edge, and show their range.

        A NaN sample, or a non-positive one on a log scale, leaves its column empty and breaks the line.
        """
        self._clear_graph()
        index = self._metric_index
        log_scale = self._log_scale
        count = min(history.sample_count, self._width)
        lo: float | None = None
        hi: float | None = None
        for age in range(count):
            value = history.value_at(index, age)
            if value != value or (log_scale and value <= 0):
                continue
            if lo is None or value < lo:
                lo = value
            if hi is None or value > hi:
                hi = value
        if lo is None:
            self._range_lo = None
            self._range_hi = None
            self._range_cell.write("", DARK_GRAY)
            return
        self._write_range(lo, hi)

        if log_scale:
            lo = math.log(lo)
            hi = math.log(hi)
        lo, hi = _graph_bounds(lo, hi, self._min_span)
        top_y = self._graph_y
        bottom_y = top_y + self._geom.graph_height - 1
        px_per_unit = (bottom_y - top_y) / (hi - lo)
        right_x = self._x + self._width - 1
        gfx = self._gfx
        prev_y = -1
        # Oldest first, so each column's line reaches back to the previous column's point.
        for age in range(count - 1, -1, -1):
            value = history.value_at(index, age)
            if value != value or (log_scale and value <= 0):
                prev_y = -1
                continue
            if log_scale:
                value = math.log(value)
            y = top_y + round((hi - value) * px_per_unit)
            x = right_x - age
            gfx.set_pen(self._shade)
            gfx.rectangle(x, y, 1, bottom_y - y + 1)
            line_top_y = y
            line_bottom_y = y
            if prev_y >= 0:
                line_top_y = min(y, prev_y)
                line_bottom_y = max(y, prev_y)
            gfx.set_pen(DARK_GRAY)
            gfx.rectangle(x, line_top_y, 1, line_bottom_y - line_top_y + 1)
            prev_y = y


class Display(_Display):
    """Sensors view: each BME690 reading in a colour quadrant with its band icon, 24 h range and graph, around a
    date and time badge.

    ``band_edges`` holds each metric's three ascending band edges, in ``get_reading()`` order.  Raises
    ``RuntimeError`` if ``geometry`` puts a quadrant's elements over each other or the badge, or off the quadrant.
    """

    def __init__(
        self,
        geometry: Geometry,
        get_reading,  # () -> tuple[float, float, float, float, str]
        get_local_time,  # () -> int
        history: RingHistory,
        band_edges: tuple[tuple[float, float, float], ...],
    ) -> None:
        gfx = geometry.pico_graphics
        self._geom = geometry
        self._gfx = gfx
        self._get_reading = get_reading
        self._get_local_time = get_local_time
        self._history = history
        self._quadrants = tuple(_Quadrant(geometry, i, band_edges[i]) for i in range(len(_METRICS)))
        self._badge_cells = tuple(
            _TextCell(gfx, geometry.badge_rects[i], geometry.badge_scales[i], _ALIGN_CENTER, BLACK)
            for i in range(len(_BADGE_PENS))
        )
        self._active = False
        self._last_reading: tuple[float, float, float, float, str] | None = None
        self._next_clock_check_ms = 0

    def initialize(self) -> None:
        if self._active:
            return
        self._active = True
        gfx = self._gfx
        geom = self._geom
        gfx.set_font(geom.font)
        gfx.set_pen(BLACK)
        gfx.clear()
        for quadrant in self._quadrants:
            quadrant.draw_static()
        r = geom.badge_r
        gfx.set_pen(BLACK)
        gfx.circle(geom.x_center, geom.y_center, r)
        r -= _BADGE_BORDER_PX
        gfx.set_pen(DARK_GRAY)
        gfx.circle(geom.x_center, geom.y_center, r)
        gfx.set_pen(BLACK)
        gfx.circle(geom.x_center, geom.y_center, r - _BADGE_RING_PX)
        for cell in self._badge_cells:
            cell.forget()
        self._last_reading = None
        self._next_clock_check_ms = time.ticks_ms()
        self._draw_changes()
        gfx.update()

    def deinitialize(self) -> None:
        self._active = False

    def render(self) -> None:
        if self._draw_changes():
            self._gfx.update()

    def _draw_changes(self) -> bool:
        """Draw what changed since the last call; return whether anything was drawn."""
        drew = self._write_clock()
        reading = self._get_reading()
        reading_changed = reading is not self._last_reading
        self._last_reading = reading
        history = self._history
        commit_count = history.commit_count
        quadrants = self._quadrants
        for i in range(len(quadrants)):
            if quadrants[i].update(reading[i], history, commit_count, reading_changed):
                drew = True
        return drew

    def _write_clock(self) -> bool:
        # The wall-clock read allocates, so do it only once a minute boundary is due.
        now_ms = time.ticks_ms()
        if time.ticks_diff(now_ms, self._next_clock_check_ms) < 0:
            return False
        now = self._get_local_time()
        # No slack: an early read just recomputes a ~1 s deadline, while slack
        # can delay catching the minute rollover by a render.
        self._next_clock_check_ms = time.ticks_add(now_ms, (60 - now % 60) * 1000)
        texts = _format_badge(now)
        drew = False
        cells = self._badge_cells
        for i in range(len(cells)):
            if cells[i].write(texts[i], _BADGE_PENS[i]):
                drew = True
        return drew
