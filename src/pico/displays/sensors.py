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

        # Precompute y positions for up to 6 lines.
        # (More than enough for now; avoids dynamic list allocations in updates.)
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

        # Left-column layout.
        # Icon: 2x2 sprite cells at scale=2 -> 32x32 px footprint (28px visible
        # content inside 1px black margin, rendered transparent).
        # Unit: 1x1 sprite cell at scale=3 -> 24x24 px, aligns with bitmap8 x3 text.
        self.icon_scale = 2
        self.icon_cells = 2  # 2x2 cells per icon
        self.icon_size_px = 8 * self.icon_cells * self.icon_scale  # 32
        # Center the 32px icon vertically on the 24px text row, then nudge up
        # by 2px for a slightly better optical balance against the glyph
        # x-height.
        self.icon_y_offset = (self.icon_size_px - self.text_height) // 2 + 2  # 6

        self.unit_scale = text_scale  # match text scale so unit glyphs sit inline
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
    # Rows in display order: (icon_cell, unit_cell).
    # Row 0's icon is swapped dynamically in ``_update_display`` per temperature.
    ROWS = (
        (icons_symbols.ICON_THERMO_GREEN, icons_symbols.UNIT_DEG_C),
        (icons_symbols.ICON_GAUGE,        icons_symbols.UNIT_MB),
        (icons_symbols.ICON_WATERDROP,    icons_symbols.UNIT_PCT),
        (icons_symbols.ICON_GAS,          icons_symbols.UNIT_KOHM),
    )

    # Temperature band thresholds (°C). Below `_COLD` → blue; [_COLD, _WARM)
    # → green; [_WARM, _HOT) → yellow; >= `_HOT` → red.
    _THERMO_COLD = 12
    _THERMO_WARM = 24
    _THERMO_HOT = 28

    def __init__(
        self,
        renderer: Renderer,
        bme690_reader: PimoroniBME690,
        time_service,
    ) -> None:
        self._renderer = renderer
        self._time_service = time_service
        self._bme690_reader = bme690_reader
        self._active = False
        self._thermo_cell: tuple[int, int] | None = None

    @classmethod
    def _thermo_cell_for(cls, temp: float) -> tuple[int, int]:
        if temp < cls._THERMO_COLD:
            return icons_symbols.ICON_THERMO_BLUE
        if temp < cls._THERMO_WARM:
            return icons_symbols.ICON_THERMO_GREEN
        if temp < cls._THERMO_HOT:
            return icons_symbols.ICON_THERMO_YELLOW
        return icons_symbols.ICON_THERMO_RED

    def _update_display(self) -> None:
        self._renderer.header_write(format_header_time(self._time_service.now()))

        temp, press, hum, gas_r, status = self._bme690_reader.read()

        new_thermo = self._thermo_cell_for(temp)
        if new_thermo != self._thermo_cell:
            self._renderer.redraw_row_icon(0, new_thermo)
            self._thermo_cell = new_thermo

        self._renderer.value_write(0, f"{temp:0.1f}")
        self._renderer.value_write(1, f"{press:0.0f}")
        self._renderer.value_write(2, f"{hum:0.1f}")
        # Gas row fuses the heater status: show kOhm value only when stable,
        # otherwise replace the number with a short "warming..." text.
        if status == "Stable":
            self._renderer.value_write(3, f"{gas_r:0.1f}")
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
        for i, (icon_cell, unit_cell) in enumerate(self.ROWS):
            self._renderer.draw_left_column(i, icon_cell, unit_cell)
        # ROWS[0] paints the green thermometer; track it so _update_display
        # only repaints when the band actually changes.
        self._thermo_cell = self.ROWS[0][0]
        self._update_display()

    def deinitialize(self) -> None:
        if not self._active:
            return
        self._active = False
