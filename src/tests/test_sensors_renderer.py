from __future__ import annotations

from dataclasses import dataclass

from displays.sensors import Colors, Renderer


class FakePicoGraphics:
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


@dataclass
class FakeGeometry:
    graphics: FakePicoGraphics
    font: str = "bitmap8"
    text_scale: int = 2
    width: int = 240
    header_y: int = 0
    header_rect: tuple[int, int, int, int] = (0, 0, 240, 16)
    value_rect_height: int = 16
    line_y: tuple[int, ...] = (24, 48, 72, 96, 120, 144)


def _mk() -> tuple[Renderer, FakePicoGraphics, FakeGeometry]:
    gfx = FakePicoGraphics()
    geom = FakeGeometry(graphics=gfx)
    colors = Colors(background=1, header_text=2, value_text=3, secondary_text=4)
    return Renderer(geom, colors), gfx, geom


def test_reset_applies_font_then_clears_background() -> None:
    r, gfx, _ = _mk()

    r.reset()

    assert gfx.calls == [
        ("set_font", ("bitmap8",), {}),
        ("set_pen", (1,), {}),
        ("clear", (), {}),
    ]


def test_reset_clears_dirty_tracking_so_next_writes_are_drawn() -> None:
    r, gfx, _ = _mk()

    # Prime the dirty-state cache, then reset, then redraw the same content.
    r.header_write("hello")
    r.value_write(0, "v")
    r.reset()
    gfx.calls.clear()

    r.header_write("hello")
    r.value_write(0, "v")

    # Both writes should hit the GFX again (cache was cleared by reset).
    assert any(c[0] == "text" and c[1][0] == "hello" for c in gfx.calls)
    assert any(c[0] == "text" and c[1][0] == "v" for c in gfx.calls)


def test_header_write_skips_when_unchanged() -> None:
    r, gfx, _ = _mk()

    r.header_write("same")
    gfx.calls.clear()

    r.header_write("same")

    assert gfx.calls == []


def test_value_write_uses_value_text_pen_and_renders() -> None:
    r, gfx, geom = _mk()

    r.value_write(0, "23.4")

    assert ("set_pen", (3,), {}) in gfx.calls  # value_text
    assert ("text", ("23.4", 0, geom.line_y[0]), {"scale": geom.text_scale}) in gfx.calls


def test_secondary_write_uses_secondary_pen() -> None:
    r, gfx, _ = _mk()

    r.secondary_write(1, "42")

    assert ("set_pen", (4,), {}) in gfx.calls  # secondary_text


def test_line_write_out_of_range_is_noop() -> None:
    r, gfx, _ = _mk()

    r.line_write(99, "ignored", pen=3)
    r.line_write(-1, "ignored", pen=3)

    assert gfx.calls == []
