import micropython

from micropython import const

from displays.base import Display as _Display
from displays.shared import icons_symbols
from displays.shared.header import format_header_time
from picographics import PicoGraphics  # type: ignore
from services.pimoroni_bme690 import PimoroniBME690


_HISTORY_SECONDS = const(24 * 3600)   # 24 h of history per metric
_L_GAP = const(3)                     # px between value text and graph
_R_MARGIN = const(0)                  # px between graph right edge and screen edge
# Widest realistic value the formatter can emit: a sub-zero outdoor
# temperature with one decimal, e.g. "-88.8" (5 cells, 69 px at bitmap8
# scale 3).  Sized so every realistic reading fits without overdrawing
# the graph: e.g. "-12.3" (temp), "100.0" (humidity), "250.7" (gas).
_GRAPH_VALUE_SAMPLE = "-88.8"


def _largest_divisor_of(n: int, max_val: int) -> int:
    """Return the largest integer d in [1..max_val] that divides n.

    Used at boot to pick a graph width that splits 24 h of ticks into an
    integer ``ticks_per_commit``.  ``1`` always divides ``n``, so the loop
    terminates for any ``max_val >= 1``.
    """
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
        pico_graphics.set_font(font)  # must precede measure_text below
        self.text_scale = text_scale
        self.text_height = font_height * text_scale
        self.line_spacing = self.text_height // 2

        self.header_y = 0

        self.values_top_y = self.text_height + self.line_spacing

        # Precomputed y positions; 6 lines is more than enough for now.
        self.line_y = (
            self.values_top_y,
            self.values_top_y * 2,
            self.values_top_y * 3,
            self.values_top_y * 4,
            self.values_top_y * 5,
            self.values_top_y * 6,
        )

        self.header_rect = (0, 0, self.width, self.text_height)
        self.value_rect_height = self.text_height

        # Left-column layout: 32px icon (2x2 cells @scale=2) + 24px unit
        # (1 cell @text scale, inline with the glyph row).
        self.icon_scale = 2
        self.icon_cells = 2
        self.icon_size_px = 8 * self.icon_cells * self.icon_scale  # 32
        # Center vertically on the text row, then nudge up 2px for
        # optical balance against the glyph x-height.
        self.icon_y_offset = (self.icon_size_px - self.text_height) // 2 + 2  # 6

        self.unit_scale = text_scale
        self.unit_size_px = 8 * self.unit_scale  # 24

        self.icon_x = 0
        self.unit_x = self.icon_x + self.icon_size_px + 4   # 36
        self.value_x = self.unit_x + self.unit_size_px + 6  # 66

        # Graph layout — fully derived from the actual rendered width of a
        # 4-character value at the current font/scale.  No hardcoded value
        # column width.
        value_max_text_width = pico_graphics.measure_text(
            _GRAPH_VALUE_SAMPLE, scale=text_scale
        )
        self.graph_x = self.value_x + value_max_text_width + _L_GAP
        available = self.width - self.graph_x - _R_MARGIN
        if available < 1:
            raise RuntimeError(
                "sensors geometry: no room for graph (font/scale too large)"
            )
        # 24 h of scheduler ticks; for 500 ms ticks → 172800.
        total_ticks = _HISTORY_SECONDS * 1000 // tick_period_ms
        self.graph_width = _largest_divisor_of(total_ticks, available)
        self.ticks_per_commit = total_ticks // self.graph_width
        self.graph_height = self.text_height  # 24 px, matches row height

        # Value-cell clear width: covers the value text + the L-gap so
        # ``line_write`` never touches the graph rect.  Also stops just
        # before the graph rect on the right.
        self.value_clear_width = self.graph_x - self.value_x


class Renderer:
    def __init__(self, geometry: Geometry, colors: Colors) -> None:
        self._geom = geometry
        self._gfx = geometry.graphics
        self._colors = colors

        self._last_header = ""
        self._last_lines = ["", "", "", "", "", ""]

    def reset(self) -> None:
        self._last_header = ""
        for i in range(len(self._last_lines)):
            self._last_lines[i] = ""
        self._gfx.set_font(self._geom.font)
        self._gfx.set_pen(self._colors.background)
        self._gfx.clear()

    def draw_left_column(
        self,
        line_idx: int,
        icon_cell: tuple[int, int],
        unit_cell: tuple[int, int],
    ) -> None:
        """Paint icon (2x2 cells) + unit label (1 cell) in the left column.

        Called once per row on view entry; icons/units are static afterwards.
        Delegates to ``displays.shared.icons_symbols`` helpers, which pass
        ``transparent=0`` so the 1px black border around each icon never
        leaves a halo.
        """
        if line_idx < 0 or line_idx >= len(self._last_lines):
            return
        g = self._geom
        y = g.line_y[line_idx]
        icons_symbols.draw_icon(self._gfx, icon_cell, g.icon_x, y - g.icon_y_offset, g.icon_scale)
        icons_symbols.draw_sprite(self._gfx, unit_cell, g.unit_x, y, g.unit_scale)

    def header_write(self, text: str) -> None:
        if text == self._last_header:
            return
        self._last_header = text

        self._gfx.set_pen(self._colors.background)
        x, y, w, h = self._geom.header_rect
        self._gfx.rectangle(x, y, w, h)

        if not text:
            return

        self._gfx.set_pen(self._colors.header_text)
        self._gfx.text(text, 0, self._geom.header_y, scale=self._geom.text_scale)

    def line_write(self, line_idx: int, text: str, *, pen: int) -> None:
        if line_idx < 0 or line_idx >= len(self._last_lines):
            return
        if text == self._last_lines[line_idx]:
            return

        g = self._geom
        # Clear value-column rect only; left-column icon + unit are static,
        # and the graph rect (graph_x .. graph_x+graph_width) is never
        # touched by line_write — it has its own redraw path.
        self._gfx.set_pen(self._colors.background)
        self._gfx.rectangle(g.value_x, g.line_y[line_idx], g.value_clear_width, g.value_rect_height)

        if text:
            self._gfx.set_pen(pen)
            self._gfx.text(text, g.value_x, g.line_y[line_idx], scale=g.text_scale)

        self._last_lines[line_idx] = text

    def redraw_row_icon(self, line_idx: int, icon_cell: tuple[int, int]) -> None:
        """Replace the icon at ``line_idx`` with a different sprite cell."""
        if line_idx < 0 or line_idx >= len(self._last_lines):
            return
        g = self._geom
        icon_y = g.line_y[line_idx] - g.icon_y_offset
        self._gfx.set_pen(self._colors.background)
        self._gfx.rectangle(g.icon_x, icon_y, g.icon_size_px, g.icon_size_px)
        icons_symbols.draw_icon(self._gfx, icon_cell, g.icon_x, icon_y, g.icon_scale)

    def value_write(self, line_idx: int, text: str) -> None:
        self.line_write(line_idx, text, pen=self._colors.value_text)

    def secondary_write(self, line_idx: int, text: str) -> None:
        self.line_write(line_idx, text, pen=self._colors.secondary_text)

    def draw_graph_clear(self, line_idx: int) -> None:
        """Paint the row's graph rect with the background pen."""
        if line_idx < 0 or line_idx >= len(self._last_lines):
            return
        g = self._geom
        self._gfx.set_pen(self._colors.background)
        self._gfx.rectangle(g.graph_x, g.line_y[line_idx], g.graph_width, g.graph_height)

    @micropython.native
    def draw_graph_column(
        self,
        line_idx: int,
        col: int,
        pastel_pen: int,
        bright_pen,  # int | None
        value_y,     # int | None
    ) -> None:
        """Paint one 1×graph_height column: full-height pastel fill, plus an
        optional single bright pixel at ``value_y`` inside the column.

        ``col`` is the column index 0..graph_width-1 within the graph rect
        (caller maps history value_idx → col).  ``value_y`` is the y offset
        inside the row (0 = top, graph_height-1 = bottom); the bright pixel
        is only drawn when both ``bright_pen`` and ``value_y`` are not None.
        """
        if line_idx < 0 or line_idx >= len(self._last_lines):
            return
        g = self._geom
        x = g.graph_x + col
        y = g.line_y[line_idx]
        self._gfx.set_pen(pastel_pen)
        self._gfx.rectangle(x, y, 1, g.graph_height)
        if bright_pen is not None and value_y is not None:
            self._gfx.set_pen(bright_pen)
            self._gfx.pixel(x, y + value_y)

    def update(self) -> None:
        self._gfx.update()


class Display(_Display):
    # Static per-row schema in display order: (unit_cell, icons_low_to_high).
    # Band thresholds arrive via ``__init__`` from ``config.SENSOR_*_BANDS``
    # and are merged into ``self._rows`` as ``(unit, edges, icons)`` triples.
    # ``edges`` is a 5-tuple ``(cap_min, t1, t2, t3, cap_max)``; the inner
    # three drive icon classification, the outer two bound the history
    # graph's Y axis.
    # ``icons[1]`` (MID_LOW) is what ``initialize`` paints by default so a
    # centered indoor reading needs no first swap.
    ROWS = (
        (
            icons_symbols.UNIT_DEG_C,
            (
                icons_symbols.ICON_THERMO_BLUE,
                icons_symbols.ICON_THERMO_GREEN,
                icons_symbols.ICON_THERMO_YELLOW,
                icons_symbols.ICON_THERMO_RED,
            ),
        ),
        (
            icons_symbols.UNIT_MB,
            (
                icons_symbols.ICON_GAUGE_LOW,
                icons_symbols.ICON_GAUGE_MID_LOW,
                icons_symbols.ICON_GAUGE_MID_HIGH,
                icons_symbols.ICON_GAUGE_HIGH,
            ),
        ),
        (
            icons_symbols.UNIT_PCT,
            (
                icons_symbols.ICON_DROP_LOW,
                icons_symbols.ICON_DROP_MID_LOW,
                icons_symbols.ICON_DROP_MID_HIGH,
                icons_symbols.ICON_DROP_HIGH,
            ),
        ),
        (
            icons_symbols.UNIT_KOHM,
            (
                icons_symbols.ICON_GAS_LOW,
                icons_symbols.ICON_GAS_MID_LOW,
                icons_symbols.ICON_GAS_MID_HIGH,
                icons_symbols.ICON_GAS_HIGH,
            ),
        ),
    )

    # Row index gated on heater status (see ``_update_display``).
    _GAS_ROW = 3

    def __init__(
        self,
        renderer: Renderer,
        bme690_reader: PimoroniBME690,
        time_service,
        history,
        band_pens,
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
        self._band_pens = band_pens
        self._graph_height = graph_height
        self._active = False
        # Currently painted icon cell per row; ``None`` forces the first
        # ``_maybe_swap_icon`` to paint.  Populated by ``initialize``.
        self._row_icons: list[tuple[int, int] | None] = [None] * len(self.ROWS)
        self._last_rendered_reading: tuple | None = None
        # Graph redraw triggers: track the last commit_count we drew for, and
        # the last gas heater stable-state we rendered.  ``-1`` / ``None``
        # values force a redraw on first ``_update_display`` after init.
        self._last_commit: int = -1
        self._gas_was_stable = None  # bool | None — None means "force redraw"

        # Validate at startup so a bad config raises here, not on the first
        # sensor read.
        bands_per_row = (temp_bands, pressure_bands, humidity_bands, gas_bands)
        self._rows = tuple(
            (unit_cell, self._validated_bands(i, bands_per_row[i]), icons)
            for i, (unit_cell, icons) in enumerate(self.ROWS)
        )

    @staticmethod
    def _validated_bands(row_index: int, bands) -> tuple:
        """Return ``bands`` as a 5-tuple, or raise ``ValueError`` on bad shape.

        Accepts a tuple/list of 5 strictly ascending numeric edges
        ``(cap_min, t1, t2, t3, cap_max)``.  Rejects any other length, any
        non-ascending or duplicated sequence.
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
        """Return band 0..3 for ``value`` against the 3 inner edges of ``edges``.

        ``edges`` is the full 5-tuple; only ``edges[1:4]`` is used for
        classification (the outer two bound the graph Y axis, not the bands).
        Matches the pre-graph behavior: ``value < threshold`` walks low→high.
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
    def _y_for(value: float, edges: tuple, graph_height: int):  # -> int | None
        """Map ``value`` to a row-local y in 0..graph_height-1.

        ``cap_max`` (edges[-1]) → ``y=0`` (top), ``cap_min`` (edges[0]) →
        ``y=graph_height-1`` (bottom).  Both caps inclusive.  Returns
        ``None`` for values outside the cap range — the caller draws the
        column pastel-only (no bright pixel).  NaN handling lives at the
        caller (``_redraw_graphs``), not here; this stays pure math.
        """
        cap_min = edges[0]
        cap_max = edges[-1]
        if value < cap_min or value > cap_max:
            return None
        # Linear map: at cap_max → 0, at cap_min → graph_height-1.
        return round((cap_max - value) * (graph_height - 1) / (cap_max - cap_min))

    @staticmethod
    def _fit_chars(value: float, decimals: int) -> str:
        """Format ``value`` for the sensor value cell.

        Rule: keep ``decimals`` decimals iff the rounded value is in
        ``(-100, 100)``; otherwise drop to the integer form.  Integer
        outputs are clamped to ``"9999"`` / ``"-999"`` to guarantee the
        rendered width never exceeds the 63 px budget set by
        ``_GRAPH_VALUE_SAMPLE = "-88.8"`` (``PicoGraphics.text()`` doesn't
        clip, so an overflow would overdraw the history graph).

        Realistic readings (BME690 in the project's typical setup) all fit:
          - temp:     ``"22.4"``, ``"-9.9"``, ``"-12.3"``, ``"-99.9"``, ``"100"``
          - humidity: ``"50.5"``, ``"99.9"``, ``"100"`` (decimal drops at >= 100)
          - pressure: ``"1013"`` (no decimal requested)
          - gas:      ``"75.3"``, ``"99.9"``, ``"100"``, ``"251"``, ``"1000"``

        The rounded-value check (``round(value, decimals)``) handles the
        boundary edge: ``-99.99`` formats to ``"-100.0"`` (6 cells, 75 px
        on-device) which would overdraw; rounded to ``-100.0`` it leaves
        the in-range window and takes the integer branch instead → ``"-100"``.
        """
        if decimals > 0 and -100 < round(value, decimals) < 100:
            return "{:.{}f}".format(value, decimals)
        i = round(value)
        if i > 9999:
            return "9999"
        if i < -999:
            return "-999"
        return str(i)

    def _maybe_swap_icon(self, line_idx: int, new_cell: tuple[int, int]) -> None:
        if new_cell != self._row_icons[line_idx]:
            self._renderer.redraw_row_icon(line_idx, new_cell)
            self._row_icons[line_idx] = new_cell

    @micropython.native
    def _redraw_graphs(self, gas_stable_now: bool) -> None:
        """Repaint all 4 history graphs based on current ``self._history`` state.

        Triggered by a commit_count bump or a gas heater stable-state change.
        Gas row has special handling: while heater is unstable, the entire
        graph region is owned by the wide ``"warming..."`` text and we do
        not paint there; on the Stable→Warming transition we clear it once
        to wipe any prior column content.
        """
        history = self._history
        renderer = self._renderer
        band_pens = self._band_pens
        capacity = history.capacity
        gas_row = self._GAS_ROW

        for metric_idx in range(len(self._rows)):
            _unit, edges, _icons = self._rows[metric_idx]

            if metric_idx == gas_row:
                if not gas_stable_now:
                    # While unstable: only act on the Stable→Warming transition
                    # (was_stable is True).  Other transitions and steady-state
                    # warming leave the row alone — the "warming..." text owns
                    # those pixels.
                    if self._gas_was_stable is True:
                        renderer.draw_graph_clear(gas_row)
                    continue
                # gas_stable_now is True → fall through to the normal redraw.

            renderer.draw_graph_clear(metric_idx)
            graph_height = self._graph_height
            pens_row = band_pens[metric_idx]
            for i in range(history.filled(metric_idx)):
                value = history.value_at(metric_idx, i)
                if value != value:  # NaN — leave the column as cleared background
                    continue
                band = self._band_index(value, edges)
                pastel_pen, bright_pen = pens_row[band]
                y = self._y_for(value, edges, graph_height)
                col = capacity - 1 - i
                renderer.draw_graph_column(
                    metric_idx,
                    col,
                    pastel_pen,
                    bright_pen if y is not None else None,
                    y,
                )

    def _update_display(self) -> None:
        self._renderer.header_write(format_header_time(self._time_service.now()))

        reading = self._bme690_reader.read()

        # Graph-redraw check lives BEFORE the reading-identity guard so a
        # history commit observed on a "reading unchanged" tick still fires.
        gas_stable_now = (reading[4] == "Stable")
        commit_now = self._history.commit_count
        if (
            commit_now != self._last_commit
            or gas_stable_now != self._gas_was_stable
        ):
            self._redraw_graphs(gas_stable_now)
            self._last_commit = commit_now
            self._gas_was_stable = gas_stable_now

        # PimoroniBME690 replaces _last_reading with a fresh tuple on each
        # sensor read (~5 s); until then read() returns the same object.
        # Identity-compare to skip the four f-string formats per tick.
        if reading is not self._last_rendered_reading:
            self._last_rendered_reading = reading
            temp, press, hum, gas_r, status = reading

            # Gas row only follows the reading when the heater is stable.
            for i, value in enumerate((temp, press, hum, gas_r)):
                if i == self._GAS_ROW and status != "Stable":
                    continue
                _unit, edges, icons = self._rows[i]
                self._maybe_swap_icon(i, icons[self._band_index(value, edges)])

            self._renderer.value_write(0, self._fit_chars(temp, 1))
            self._renderer.value_write(1, self._fit_chars(press, 0))
            self._renderer.value_write(2, self._fit_chars(hum, 1))
            if status == "Stable":
                self._renderer.value_write(3, self._fit_chars(gas_r, 1))
            else:
                # "warming..." is intentionally wider than the value cell; it
                # spills into the gas-row graph rect and the gas-row state
                # machine in _redraw_graphs ensures we don't paint over it.
                self._renderer.value_write(3, "warming...")

        self._renderer.update()

    def render(self) -> None:
        self._update_display()

    def initialize(self) -> None:
        if self._active:
            return
        self._active = True
        self._renderer.reset()
        for i, (unit_cell, _bands, icons) in enumerate(self._rows):
            default_icon = icons[1]
            self._renderer.draw_left_column(i, default_icon, unit_cell)
            self._row_icons[i] = default_icon
        # Force first _update_display to paint values even if the reader
        # returns the same tuple object as the last time we were active.
        self._last_rendered_reading = None
        # Force a graph redraw on re-entry (the screen was cleared by reset()).
        self._last_commit = -1
        self._gas_was_stable = None
        self._update_display()

    def deinitialize(self) -> None:
        if not self._active:
            return
        self._active = False
