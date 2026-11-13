import math
import time
from array import array

import micropython
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
from services.sample_history import MISSING, SampleHistory


_HISTORY_MS = const(24 * 3600 * 1000)
_GUTTER_PX = const(3)
# Every gap between neighbouring texts, icons and graphs, in a quadrant or the badge, and from a text or icon to the
# panel edge or the gutter.
_MARGIN_PX = const(8)
_ICON_SCALE = const(2)
# bitmap8's bottom cell row holds only descenders, which values, times and weekday names never use.
_DESCENDER_ROWS = const(1)
# Black space between the smallest disc that holds every badge line and the ring.
_BADGE_PADDING_PX = const(5)
# The badge is a 2-px DARK_GRAY ring with a 2-px black border outside it.
_BADGE_RING_PX = const(2)
_BADGE_BORDER_PX = const(2)
_GRAPH_PAD_PCT = const(8)
_TYPICAL_INDOOR_BAND_INDEX = const(1)
# A linear metric's history samples count fifths of its last displayed digit (0.02 °C, 0.2 hPa), finer than a
# graph's pixels.  Keep the count odd: then every display rounding boundary lies halfway between two samples, so a
# range end read back from them shows what its reading showed.  On a log scale, samples count hundred-thousandths
# of a natural log, which seldom changes a range end's last digit.
_SAMPLES_PER_DIGIT = const(5)
_LOG_UNITS = const(100000)

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
# A metric's band icons must share one size: its quadrant places and erases each one in the first one's box.
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


def _graph_bounds(lo: int, hi: int, min_span: int) -> tuple[int, int]:
    """Return the plotted bounds for samples spanning ``lo``..``hi``.

    A span under ``min_span`` widens about its middle to ``min_span``, so a steady reading plots as a level
    line rather than magnified noise; then each end gains ``_GRAPH_PAD_PCT`` % of the span, rounded down.
    ``min_span`` must be positive.
    """
    span = hi - lo
    if span < min_span:
        lo -= (min_span - span) // 2
        span = min_span
    pad = span * _GRAPH_PAD_PCT // 100
    return lo - pad, lo + span + pad


def _units(decimals: int, log_scale: bool) -> int:
    """Return how many sample steps make one unit of a metric shown with ``decimals`` places, or one natural log on a
    log scale."""
    if log_scale:
        return _LOG_UNITS
    return _SAMPLES_PER_DIGIT * 10**decimals


def _encode(value: float, decimals: int, log_scale: bool) -> int:
    """Return ``value``, a reading shown with ``decimals`` places, as a history sample: ``MISSING`` for NaN, and on a
    log scale for a non-positive value."""
    if log_scale:
        if not value > 0:
            return MISSING
        value = math.log(value)
    elif value != value:
        return MISSING
    return round(value * _units(decimals, log_scale))


def _decode(sample: int, decimals: int, log_scale: bool) -> float:
    """Return the reading ``sample`` stands for, which ``_encode`` made with the same ``decimals`` and ``log_scale``;
    ``sample`` must not be ``MISSING``."""
    value = sample / _units(decimals, log_scale)
    if log_scale:
        return math.exp(value)
    return value


def encode_reading(reading: tuple[float, float, float, float, str]) -> tuple[int, int, int, int]:
    """Return ``reading``'s metrics as the samples ``Display`` plots from its ``SampleHistory``."""
    return tuple(_encode(reading[i], _METRICS[i][2], _METRICS[i][-1]) for i in range(len(_METRICS)))


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
        self.icon_height = _ICON_SCALE * max(icon[1] for metric in _METRICS for icon in metric[1])

        # Offsets from a quadrant's gutter edge; the margins are measured to ink.  The graph takes the height left over.
        self.value_offset = _MARGIN_PX + self.icon_height + _MARGIN_PX
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
        block_height = 2 * label_ink_height + self.value_height + 2 * _MARGIN_PX + _DESCENDER_ROWS * label_scale
        weekday_y = y_center - block_height // 2
        time_y = weekday_y + label_ink_height + _MARGIN_PX
        date_y = time_y + self.value_height + _MARGIN_PX
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
    quadrant aligns them to the panel's right edge.  It plots the newest samples of ``samples``, its metric's
    ``SampleHistory`` array of ``encode_reading`` samples.  Raises ``RuntimeError`` if its elements overlap each
    other or the badge, or leave the quadrant, and ``ValueError`` if ``samples`` holds fewer samples than the
    graph has columns.
    """

    def __init__(
        self, geom: Geometry, metric_index: int, band_edges: tuple[float, float, float], samples: array
    ) -> None:
        (
            self._unit,
            self._icons,
            self._decimals,
            self._field,
            self._shade,
            min_span,
            self._log_scale,
        ) = _METRICS[metric_index]
        self._min_span = round(min_span * _units(self._decimals, self._log_scale))
        self._geom = geom
        self._gfx = geom.pico_graphics
        self._band_edges = band_edges
        self._samples = samples

        col = metric_index & 1
        row = metric_index >> 1
        x, width = geom.col_spans[col]
        y, height = geom.row_spans[row]
        self._x = x
        self._y = y
        self._width = width
        self._height = height
        if len(samples) < width:
            raise ValueError("sensors: the history holds fewer samples than a graph has columns")
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
        icon = self._icons[0]
        self._icon_width = icon[0] * _ICON_SCALE
        self._icon_height = icon[1] * _ICON_SCALE
        unit_width = self._unit[0] * geom.label_text_scale
        unit_height = self._unit[1] * geom.label_text_scale
        self._icon_x = _place(x, width, right, _MARGIN_PX, self._icon_width)
        self._icon_y = _place(
            y, height, top, _MARGIN_PX + (geom.icon_height - self._icon_height) // 2, self._icon_height
        )
        self._unit_x = _place(x, width, right, _MARGIN_PX + self._icon_width + _MARGIN_PX, unit_width)
        self._unit_y = self._icon_y + (self._icon_height - unit_height) // 2
        self._graph_y = _place(y, height, top, geom.graph_offset, geom.graph_height)
        _check_layout(
            (
                value_rect,
                range_rect,
                (self._icon_x, self._icon_y, self._icon_width, self._icon_height),
                (self._unit_x, self._unit_y, unit_width, unit_height),
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
        self._range_lo = None
        self._range_hi = None

    def show(self, value: float, history_changed: bool) -> bool:
        """Draw what changed for the live ``value``, and for the history if ``history_changed``; return whether
        anything was drawn.

        A NaN ``value`` means the sensor is warming up: the quadrant then shows a placeholder, keeps its icon,
        hides its graph and says so in its range.
        """
        valid = value == value
        drew = False
        if valid != self._valid:
            self._valid = valid
            drew = True
            if valid:
                # Backfill the newest sample once the value turns valid rather than at the next commit.
                # Entering the view also gets here and must keep a valid committed sample.
                samples = self._samples
                if samples[-1] == MISSING:
                    samples[-1] = _encode(value, self._decimals, self._log_scale)
                self._replace_graph()
            else:
                self._clear_graph()
                self._range_lo = None
                self._range_hi = None
                self._range_cell.write(_WARMING_TEXT, DARK_GRAY)
        elif valid and history_changed:
            self._replace_graph()
            drew = True

        if valid:
            icon = self._icons[_band_index(value, self._band_edges)]
            text = _format_value(value, self._decimals)
            pen = BLACK
        else:
            icon = self._icon if self._icon is not None else self._icons[_TYPICAL_INDOOR_BAND_INDEX]
            text = _PLACEHOLDER_TEXT
            pen = DARK_GRAY
        if icon is not self._icon:
            gfx = self._gfx
            gfx.set_pen(self._field)
            gfx.rectangle(self._icon_x, self._icon_y, self._icon_width, self._icon_height)
            icons_p4.draw_icon(gfx, icon, self._icon_x, self._icon_y, _ICON_SCALE)
            self._icon = icon
            drew = True
        if self._value_cell.write(text, pen):
            drew = True

        if valid:
            # Widen the range to take in the reading: a live reading can lead the history by a commit period.
            lo = self._range_lo
            hi = self._range_hi
            if lo is None or value < lo or value > hi:
                if lo is None or value < lo:
                    lo = value
                if hi is None or value > hi:
                    hi = value
                if self._write_range(lo, hi):
                    drew = True
        return drew

    def _write_range(self, lo: float, hi: float) -> bool:
        self._range_lo = lo
        self._range_hi = hi
        return self._range_cell.write(
            _format_value(lo, self._decimals) + _RANGE_SEPARATOR + _format_value(hi, self._decimals), DARK_GRAY
        )

    def _write_history_range(self, lo: int, hi: int) -> None:
        """Show the range of history samples ``lo``..``hi``, or a blank range when ``hi`` is ``MISSING``."""
        if hi == MISSING:
            self._range_lo = None
            self._range_hi = None
            self._range_cell.write("", DARK_GRAY)
        else:
            decimals = self._decimals
            log_scale = self._log_scale
            self._write_range(_decode(lo, decimals, log_scale), _decode(hi, decimals, log_scale))

    def _clear_graph(self) -> None:
        self._gfx.set_pen(self._field)
        self._gfx.rectangle(self._x, self._graph_y, self._width, self._geom.graph_height)

    # Viper: the per-column work is integer-only, so it runs as machine code and allocates nothing.
    @micropython.viper
    def _replace_graph(self):  # -> None
        """Plot the newest samples, one per column with the newest at the right edge, and show their range.

        A ``MISSING`` sample leaves its column empty and breaks the line.
        """
        self._clear_graph()
        samples = self._samples
        missing = int(MISSING)
        end = int(len(samples))
        first = end - int(self._width)
        lo = missing
        hi = missing
        for i in range(first, end):
            sample = int(samples[i])
            if sample != missing:
                if lo == missing or sample < lo:
                    lo = sample
                if sample > hi:
                    hi = sample
        self._write_history_range(lo, hi)
        if hi == missing:
            return

        bounds = _graph_bounds(lo, hi, self._min_span)
        lo = int(bounds[0])
        span = int(bounds[1]) - lo
        top_y = int(self._graph_y)
        bottom_y = top_y + int(self._geom.graph_height) - 1
        # Viper ints are 32-bit, so span * graph height must stay below 2**31 for the y products below.
        x = int(self._x) - first
        gfx = self._gfx
        # All fills, then the whole line, so each pen is set once.
        gfx.set_pen(self._shade)
        for i in range(first, end):
            sample = int(samples[i])
            if sample != missing:
                # The point sits (sample - lo) / span of the way up from bottom_y to top_y, rounded half up.
                y = bottom_y - ((sample - lo) * (bottom_y - top_y) + (span >> 1)) // span
                gfx.rectangle(x + i, y, 1, bottom_y - y + 1)
        gfx.set_pen(DARK_GRAY)
        prev_y = -1
        # Oldest first, so each column's line reaches back to the previous column's point.
        for i in range(first, end):
            sample = int(samples[i])
            if sample == missing:
                prev_y = -1
            else:
                y = bottom_y - ((sample - lo) * (bottom_y - top_y) + (span >> 1)) // span
                line_top_y = y
                line_bottom_y = y
                if prev_y >= 0:
                    if prev_y < y:
                        line_top_y = prev_y
                    else:
                        line_bottom_y = prev_y
                gfx.rectangle(x + i, line_top_y, 1, line_bottom_y - line_top_y + 1)
                prev_y = y


class Display(_Display):
    """Sensors view: each BME690 reading in a colour quadrant with its band icon, 24 h range and graph, around a
    date and time badge.

    ``history``'s sampler must return ``encode_reading`` of a reading.  ``band_edges`` holds each metric's three
    ascending band edges, in ``get_reading()`` order.  Raises ``RuntimeError`` if ``geometry`` puts a quadrant's
    elements over each other or the badge, or off the quadrant, and ``ValueError`` if ``history`` holds fewer than
    ``geometry.graph_columns`` samples per metric.
    """

    def __init__(
        self,
        geometry: Geometry,
        get_reading,  # () -> tuple[float, float, float, float, str]
        get_local_time,  # () -> int
        history: SampleHistory,
        band_edges: tuple[tuple[float, float, float], ...],
    ) -> None:
        gfx = geometry.pico_graphics
        self._geom = geometry
        self._gfx = gfx
        self._get_reading = get_reading
        self._get_local_time = get_local_time
        self._history = history
        self._quadrants = tuple(
            _Quadrant(geometry, i, band_edges[i], history.samples[i]) for i in range(len(_METRICS))
        )
        self._badge_cells = tuple(
            _TextCell(gfx, geometry.badge_rects[i], geometry.badge_scales[i], _ALIGN_CENTER, BLACK)
            for i in range(len(_BADGE_PENS))
        )
        self._active = False
        self._last_reading: tuple[float, float, float, float, str] | None = None
        self._commit_count = -1
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
        self._commit_count = -1
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
        commit_count = self._history.commit_count
        history_changed = commit_count != self._commit_count
        if history_changed or reading is not self._last_reading:
            self._last_reading = reading
            self._commit_count = commit_count
            quadrants = self._quadrants
            for i in range(len(quadrants)):
                if quadrants[i].show(reading[i], history_changed):
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
