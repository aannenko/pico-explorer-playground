"""Shared test helpers (fakes / stubs) for the host-side pytest suite.

Lives outside any ``test_*.py`` file so pytest doesn't collect it.  The
leading underscore also keeps it from clashing with the production
namespace if anyone ever puts ``src/tests/`` on the runtime path.

``src/tests/`` is on ``sys.path`` whenever pytest is collecting tests
from this directory (rootpath insertion), so ``from _fakes import ...``
works from any test file regardless of how pytest was invoked.
"""

from __future__ import annotations


class FakePicoGraphics:
    """In-memory ``PicoGraphics`` substitute that records every draw call.

    Sized to a 240×240 panel.  ``measure_text`` returns device-observed
    widths for the strings the layout / formatter actually touches
    (bitmap8, scale=3 — see ``files/brainstorm.md`` "Device-observed
    measure_text data points"); any other input falls back to a
    deterministic ``len * (scale*4 + 2)`` estimate so ad-hoc test inputs
    still yield stable layout calculations.
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
        if scale == 3:
            widths = {
                "8888": 57,
                "9999": 57,
                "1000": 54,
                "-999": 54,
                "99.9": 51,
                "-100": 51,
                "-88.8": 63,
                "-99.9": 63,
                "100.0": 63,
                "-100.0": 75,
            }
            if text in widths:
                return widths[text]
        return max(1, len(text) * (scale * 4 + 2))

    def create_pen(self, r: int, g: int, b: int) -> int:
        self.calls.append(("create_pen", (r, g, b), {}))
        return (r << 16) | (g << 8) | b
