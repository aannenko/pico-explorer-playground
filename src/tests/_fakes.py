"""Shared test helpers (fakes / stubs) for the host-side pytest suite.

Lives outside any ``test_*.py`` file so pytest doesn't collect it.  The
leading underscore also keeps it from clashing with the production
namespace if anyone ever puts ``src/tests/`` on the runtime path.

``src/tests/`` is on ``sys.path`` whenever pytest is collecting tests
from this directory (rootpath insertion), so ``from _fakes import ...``
works from any test file regardless of how pytest was invoked.
"""

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

    def get_bounds(self) -> tuple[int, int]:
        return (240, 240)

    def measure_text(self, text: str, scale: int) -> int:
        return bitmap8_width(text, scale)

    def create_pen(self, r: int, g: int, b: int) -> int:
        self.calls.append(("create_pen", (r, g, b), {}))
        return (r << 16) | (g << 8) | b
