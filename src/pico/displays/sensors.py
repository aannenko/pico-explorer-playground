import micropython

from displays.base import Display as _Display
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


class Renderer:
    def __init__(self, geometry: Geometry, colors: Colors) -> None:
        self._geom = geometry
        self._gfx = geometry.graphics
        self._colors = colors

        self._last_header = ""
        self._last_lines = ["", "", "", "", "", ""]

    def reset(self) -> None:
        self._last_header = ""
        self._last_lines = ["", "", "", "", "", ""]
        self._gfx.set_pen(self._colors.background)
        self._gfx.clear()

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

        # clear line rect
        self._gfx.set_pen(self._colors.background)
        self._gfx.rectangle(0, self._geom.line_y[line_idx], self._geom.width, self._geom.value_rect_height)

        if text:
            self._gfx.set_pen(pen)
            self._gfx.text(text, 0, self._geom.line_y[line_idx], scale=self._geom.text_scale)

        self._last_lines[line_idx] = text

    def value_write(self, line_idx: int, text: str) -> None:
        """Write a primary-value line (e.g. temperature) in the value-text color."""
        self.line_write(line_idx, text, pen=self._colors.value_text)

    def secondary_write(self, line_idx: int, text: str) -> None:
        """Write a secondary-value line in the subdued secondary-text color."""
        self.line_write(line_idx, text, pen=self._colors.secondary_text)

    def update(self) -> None:
        self._gfx.update()


class Display(_Display):
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

    def _update_display(self) -> None:
        self._renderer.header_write(format_header_time(self._time_service.now()))

        temp, press, hum, gas_r, status = self._bme690_reader.read()
        self._renderer.value_write(0, f"Temp: {temp:0.1f} C")
        self._renderer.secondary_write(1, f"Prsr: {press:0.0f} mb")
        self._renderer.secondary_write(2, f"Hum: {hum:0.2f} %")
        self._renderer.secondary_write(3, f"GasR: {gas_r:0.1f} kOhm")
        self._renderer.secondary_write(4, f"Stat: {status}")

        self._renderer.update()

    def render(self) -> None:
        self._update_display()

    def initialize(self) -> None:
        if self._active:
            return
        self._active = True
        self._renderer.reset()
        self._update_display()

    def deinitialize(self) -> None:
        if not self._active:
            return
        self._active = False
