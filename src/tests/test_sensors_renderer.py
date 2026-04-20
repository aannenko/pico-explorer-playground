from __future__ import annotations

from dataclasses import dataclass, field

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

    def load_spritesheet(self, path: str) -> None:
        self.calls.append(("load_spritesheet", (path,), {}))

    def sprite(self, sx, sy, x, y, scale=1, transparent=-1) -> None:
        self.calls.append(("sprite", (sx, sy, x, y, scale, transparent), {}))


@dataclass
class FakeGeometry:
    graphics: FakePicoGraphics
    font: str = "bitmap8"
    text_scale: int = 3
    width: int = 240
    header_y: int = 0
    header_rect: tuple[int, int, int, int] = (0, 0, 240, 24)
    text_height: int = 24
    value_rect_height: int = 24
    line_y: tuple[int, ...] = (32, 64, 96, 128, 160, 192)
    icon_x: int = 0
    icon_scale: int = 2
    icon_cells: int = 2
    icon_size_px: int = 32
    icon_y_offset: int = 6
    unit_x: int = 36
    unit_scale: int = 3
    unit_size_px: int = 24
    value_x: int = 66
    value_rect_width: int = 174


def _mk() -> tuple[Renderer, FakePicoGraphics, FakeGeometry]:
    gfx = FakePicoGraphics()
    geom = FakeGeometry(graphics=gfx)
    colors = Colors(
        background=1,
        header_text=2,
        value_text=3,
        secondary_text=4,
    )
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


def test_value_write_uses_value_text_pen_and_renders_in_value_column() -> None:
    r, gfx, geom = _mk()

    r.value_write(0, "23.4")

    assert ("set_pen", (3,), {}) in gfx.calls  # value_text
    assert ("text", ("23.4", geom.value_x, geom.line_y[0]), {"scale": geom.text_scale}) in gfx.calls


def test_secondary_write_uses_secondary_pen() -> None:
    r, gfx, _ = _mk()

    r.secondary_write(1, "42")

    assert ("set_pen", (4,), {}) in gfx.calls  # secondary_text


def test_line_write_out_of_range_is_noop() -> None:
    r, gfx, _ = _mk()

    r.line_write(99, "ignored", pen=3)
    r.line_write(-1, "ignored", pen=3)

    assert gfx.calls == []


def test_line_write_clears_only_value_column_not_icons() -> None:
    r, gfx, geom = _mk()

    r.line_write(2, "99", pen=3)

    # Clearing rect should be confined to the value column — icons stay.
    assert ("rectangle", (geom.value_x, geom.line_y[2], geom.value_rect_width, geom.value_rect_height), {}) in gfx.calls
    # No full-width clear of the left column.
    for name, args, _kw in gfx.calls:
        if name == "rectangle":
            x, _y, w, _h = args
            assert (x, w) != (0, geom.width)


def test_draw_left_column_draws_four_icon_cells_and_one_unit_cell() -> None:
    r, gfx, geom = _mk()

    # Arbitrary icon (sx=2, sy=0) and unit (sx=3, sy=15).
    r.draw_left_column(1, (2, 0), (3, 15))

    step = 8 * geom.icon_scale
    icon_y = geom.line_y[1] - geom.icon_y_offset
    # Four 8x8 cells forming the 2x2 icon, at icon_scale with transparent=0.
    assert ("sprite", (2, 0, geom.icon_x,        icon_y,        geom.icon_scale, 0), {}) in gfx.calls
    assert ("sprite", (3, 0, geom.icon_x + step, icon_y,        geom.icon_scale, 0), {}) in gfx.calls
    assert ("sprite", (2, 1, geom.icon_x,        icon_y + step, geom.icon_scale, 0), {}) in gfx.calls
    assert ("sprite", (3, 1, geom.icon_x + step, icon_y + step, geom.icon_scale, 0), {}) in gfx.calls
    # Single unit-label cell at text scale aligned to text baseline.
    assert ("sprite", (3, 15, geom.unit_x, geom.line_y[1], geom.unit_scale, 0), {}) in gfx.calls


def test_draw_left_column_out_of_range_is_noop() -> None:
    r, gfx, _ = _mk()

    r.draw_left_column(99, (0, 0), (0, 15))
    r.draw_left_column(-1, (0, 0), (0, 15))

    assert gfx.calls == []


def test_redraw_row_icon_clears_icon_rect_then_draws_new_icon() -> None:
    r, gfx, geom = _mk()

    r.redraw_row_icon(0, (4, 0))

    icon_y = geom.line_y[0] - geom.icon_y_offset
    # Background-pen set, then icon-footprint rect cleared, then 4 sprite cells drawn.
    assert ("set_pen", (1,), {}) in gfx.calls  # background pen
    assert (
        "rectangle",
        (geom.icon_x, icon_y, geom.icon_size_px, geom.icon_size_px),
        {},
    ) in gfx.calls
    # All four 2x2 sprite cells drawn at icon_scale with transparent=0.
    step = 8 * geom.icon_scale
    assert ("sprite", (4, 0, geom.icon_x,        icon_y,        geom.icon_scale, 0), {}) in gfx.calls
    assert ("sprite", (5, 0, geom.icon_x + step, icon_y,        geom.icon_scale, 0), {}) in gfx.calls
    assert ("sprite", (4, 1, geom.icon_x,        icon_y + step, geom.icon_scale, 0), {}) in gfx.calls
    assert ("sprite", (5, 1, geom.icon_x + step, icon_y + step, geom.icon_scale, 0), {}) in gfx.calls
    # Value-column rect must NOT be cleared — only the icon footprint.
    assert not any(
        c[0] == "rectangle" and c[1] == (geom.value_x, geom.line_y[0], geom.value_rect_width, geom.value_rect_height)
        for c in gfx.calls
    )


def test_redraw_row_icon_out_of_range_is_noop() -> None:
    r, gfx, _ = _mk()

    r.redraw_row_icon(99, (0, 0))
    r.redraw_row_icon(-1, (0, 0))

    assert gfx.calls == []
