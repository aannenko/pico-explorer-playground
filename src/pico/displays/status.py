from picographics import PicoGraphics  # type: ignore


class StatusDisplay:
    def __init__(
        self,
        pico_graphics: PicoGraphics,
        font: str,
        font_height: int,
        text_scale: int,
        background: int,
        foreground: int,
        subtext_color: int,
    ) -> None:
        self._gfx = pico_graphics
        self._font = font
        self._font_height = font_height
        self._text_scale = text_scale
        self._background = background
        self._foreground = foreground
        self._subtext_color = subtext_color

        self._width, h = pico_graphics.get_bounds()
        self._text_y = (h // 2) - (font_height * text_scale)
        self._subtext_y = (h // 2) + 5

    def show(self, text: str, subtext: str = "") -> None:
        self._gfx.set_font(self._font)

        self._gfx.set_pen(self._background)
        self._gfx.clear()

        self._gfx.set_pen(self._foreground)
        text_x = (
            self._width - self._gfx.measure_text(text, scale=self._text_scale)
        ) // 2
        self._gfx.text(text, text_x, self._text_y, scale=self._text_scale)

        if subtext:
            self._gfx.set_pen(self._subtext_color)
            subtext_x = (
                self._width - self._gfx.measure_text(subtext, scale=self._text_scale)
            ) // 2
            self._gfx.text(subtext, subtext_x, self._subtext_y, scale=self._text_scale)

        self._gfx.update()
