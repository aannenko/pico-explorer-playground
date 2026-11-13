from __future__ import annotations


# bitmap8 advance widths for printable ASCII, index = ``ord(c) - 32``.  Read off
# the device with ``measure_text(chr(c), scale=1)``, which returns a single
# glyph's raw width because the inter-glyph spacing term vanishes at n=1.
# The font is proportional, not monospaced: 'I'/'l'/'1' are 3 px, 'M'/'W'/'m'/'w'
# are 5, ':' is 1.
_BITMAP8_WIDTHS = (
    "31354441333323244344444444123334444444444344454444445445"
    "444242334444444443443544444444454443134"
)


def bitmap8_width(text: str, scale: int) -> int:
    """Firmware-accurate ``measure_text`` for the bitmap8 font.

    PicoGraphics measures ``scale * (sum(glyph_widths) + len(text) - 1)``.
    Shared by every host fake so layout assertions agree with the device
    instead of with a per-file approximation.
    """
    if not text:
        return 0
    total = 0
    for ch in text:
        idx = ord(ch) - 32
        if not 0 <= idx < len(_BITMAP8_WIDTHS):
            raise ValueError(
                "no bitmap8 width for %r - the table covers printable ASCII "
                "only; measure it on-device to extend it" % ch
            )
        total += int(_BITMAP8_WIDTHS[idx])
    return scale * (total + len(text) - 1)


def circle_pixels(x_center: int, y_center: int, radius: int) -> set[tuple[int, int]]:
    """The pixels ``PicoGraphics.circle()`` fills, ported from pimoroni-pico's ``pico_graphics.cpp``."""
    pixels: set[tuple[int, int]] = set()

    def span(x: int, y: int, length: int) -> None:
        pixels.update((x + i, y) for i in range(length))

    ox, oy, err = radius, 0, -radius
    while ox >= oy:
        last_oy = oy
        err += oy
        oy += 1
        err += oy
        span(x_center - ox, y_center + last_oy, ox * 2 + 1)
        if last_oy != 0:
            span(x_center - ox, y_center - last_oy, ox * 2 + 1)
        if err >= 0 and ox != last_oy:
            span(x_center - last_oy, y_center + ox, last_oy * 2 + 1)
            if ox != 0:
                span(x_center - last_oy, y_center - ox, last_oy * 2 + 1)
            err -= ox
            ox -= 1
            err -= ox
    return pixels


class FakePicoGraphics:
    """In-memory ``PicoGraphics`` substitute that records every draw call.

    Sized to a 240×240 panel.  ``measure_text`` reproduces the firmware's
    own formula, ``scale * (sum(glyph_widths) + len(text) - 1)``, against a
    glyph table measured on the device — so it is exact for any string at
    any scale rather than approximating.  It deliberately raises on
    non-ASCII instead of guessing: a silently wrong width is what a layout
    test is least able to catch.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def set_pen(self, pen: int) -> None:
        self.calls.append(("set_pen", (pen,), {}))

    def set_font(self, font: str) -> None:
        self.calls.append(("set_font", (font,), {}))

    def rectangle(self, x: int, y: int, w: int, h: int) -> None:
        self.calls.append(("rectangle", (x, y, w, h), {}))

    def text(self, text: str, x: int, y: int, *, scale: int) -> None:
        self.calls.append(("text", (text, x, y), {"scale": scale}))

    def clear(self) -> None:
        self.calls.append(("clear", (), {}))

    def update(self) -> None:
        self.calls.append(("update", (), {}))

    def load_spritesheet(self, path: str) -> None:
        self.calls.append(("load_spritesheet", (path,), {}))

    def sprite(self, sx, sy, x, y, scale=1, transparent=-1) -> None:
        self.calls.append(("sprite", (sx, sy, x, y, scale, transparent), {}))

    def pixel(self, x: int, y: int) -> None:
        self.calls.append(("pixel", (x, y), {}))

    def circle(self, x: int, y: int, r: int) -> None:
        self.calls.append(("circle", (x, y, r), {}))

    def get_bounds(self) -> tuple[int, int]:
        return (240, 240)

    def measure_text(self, text: str, scale: int) -> int:
        return bitmap8_width(text, scale)

    def create_pen(self, r: int, g: int, b: int) -> int:
        self.calls.append(("create_pen", (r, g, b), {}))
        return (r << 16) | (g << 8) | b
