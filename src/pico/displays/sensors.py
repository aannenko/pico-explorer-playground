import micropython

from displays.base import Display as _Display
from displays.shared import icons_symbols
from displays.shared.header import format_header_time
from picographics import PicoGraphics  # type: ignore
from services.pimoroni_bme690 import PimoroniBME690


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
        self.value_rect_width = self.width - self.value_x


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
        # Clear value-column rect only; left-column icon + unit are static.
        self._gfx.set_pen(self._colors.background)
        self._gfx.rectangle(g.value_x, g.line_y[line_idx], g.value_rect_width, g.value_rect_height)

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

    def update(self) -> None:
        self._gfx.update()


class Display(_Display):
    # Static per-row schema in display order: (unit_cell, icons_low_to_high).
    # Band thresholds arrive via ``__init__`` from ``config.SENSOR_*_BANDS``
    # and are merged into ``self._rows`` as ``(unit, bands, icons)`` triples.
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
        *,
        temp_bands: tuple[int, int, int],
        pressure_bands: tuple[int, int, int],
        humidity_bands: tuple[int, int, int],
        gas_bands: tuple[int, int, int],
    ) -> None:
        self._renderer = renderer
        self._time_service = time_service
        self._bme690_reader = bme690_reader
        self._active = False
        # Currently painted icon cell per row; ``None`` forces the first
        # ``_maybe_swap_icon`` to paint.  Populated by ``initialize``.
        self._row_icons: list[tuple[int, int] | None] = [None] * len(self.ROWS)
        self._last_rendered_reading: tuple | None = None

        # Validate at startup so a bad config raises here, not on the first
        # sensor read.
        bands_per_row = (temp_bands, pressure_bands, humidity_bands, gas_bands)
        self._rows = tuple(
            (unit_cell, self._validated_bands(i, bands_per_row[i]), icons)
            for i, (unit_cell, icons) in enumerate(self.ROWS)
        )

    @staticmethod
    def _validated_bands(row_index: int, bands) -> tuple[int, int, int]:
        """Return ``bands`` as a 3-tuple, or raise ``ValueError`` if the shape is wrong."""
        if len(bands) != 3:
            raise ValueError(
                "Display row {} requires 3 band thresholds, got {}".format(
                    row_index, len(bands)
                )
            )
        b0, b1, b2 = bands
        if not (b0 < b1 < b2):
            raise ValueError(
                "Display row {} bands must be strictly ascending, got {}".format(
                    row_index, bands
                )
            )
        return (b0, b1, b2)

    @staticmethod
    def _icon_for_value(
        value: float,
        bands: tuple[int, ...],
        icons: tuple[tuple[int, int], ...],
    ) -> tuple[int, int]:
        """Return the band's icon: the first ``icons[i]`` where ``value < bands[i]``.

        Falls through to ``icons[len(bands)]`` (the highest band) when
        ``value`` exceeds every threshold.
        """
        for i, threshold in enumerate(bands):
            if value < threshold:
                return icons[i]
        return icons[len(bands)]

    def _maybe_swap_icon(self, line_idx: int, new_cell: tuple[int, int]) -> None:
        if new_cell != self._row_icons[line_idx]:
            self._renderer.redraw_row_icon(line_idx, new_cell)
            self._row_icons[line_idx] = new_cell

    def _update_display(self) -> None:
        self._renderer.header_write(format_header_time(self._time_service.now()))

        reading = self._bme690_reader.read()
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
                _unit, bands, icons = self._rows[i]
                self._maybe_swap_icon(i, self._icon_for_value(value, bands, icons))

            self._renderer.value_write(0, f"{temp:0.1f}")
            self._renderer.value_write(1, f"{press:0.0f}")
            self._renderer.value_write(2, f"{hum:0.1f}")
            if status == "Stable":
                gas_r_text = str(round(gas_r)) if gas_r >= 100 else f"{gas_r:0.1f}"
                self._renderer.value_write(3, gas_r_text)
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
        for i, (unit_cell, _bands, icons) in enumerate(self._rows):
            default_icon = icons[1]
            self._renderer.draw_left_column(i, default_icon, unit_cell)
            self._row_icons[i] = default_icon
        # Force first _update_display to paint values even if the reader
        # returns the same tuple object as the last time we were active.
        self._last_rendered_reading = None
        self._update_display()

    def deinitialize(self) -> None:
        if not self._active:
            return
        self._active = False
