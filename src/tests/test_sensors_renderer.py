from __future__ import annotations

from dataclasses import dataclass

from displays.sensors import Colors, Renderer

from _fakes import FakePicoGraphics


@dataclass
class FakeGeometry:
    graphics: FakePicoGraphics
    font: str = "bitmap8"
    text_scale: int = 3
    width: int = 240
    height: int = 240
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
    # New layout fields (R2.6 / R2.7).  Defaults mirror the real Geometry
    # against the device-observed bitmap8/scale=3 measurements: with
    # ``_GRAPH_VALUE_SAMPLE = "-88.8"`` measuring 63 px, L_GAP=3 and
    # R_MARGIN=0 → graph_x=132, available=108, graph_width=108,
    # value_clear_width=66, ticks_per_commit=1600.
    value_clear_width: int = 66
    graph_x: int = 132
    graph_width: int = 108
    graph_height: int = 24
    ticks_per_commit: int = 1600


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

    # Clearing rect should be confined to the value column — icons stay,
    # and the graph region (x >= graph_x) is never touched.
    assert ("rectangle", (geom.value_x, geom.line_y[2], geom.value_clear_width, geom.value_rect_height), {}) in gfx.calls
    # No full-width clear of the left column.
    for name, args, _kw in gfx.calls:
        if name == "rectangle":
            x, _y, w, _h = args
            assert (x, w) != (0, geom.width)
            # Regression for R2.1/R2.6: clear must not extend into the graph rect.
            assert x + w <= geom.graph_x, (
                "line_write rectangle (x={}, w={}) extended past graph_x={}".format(
                    x, w, geom.graph_x
                )
            )


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
        c[0] == "rectangle" and c[1] == (geom.value_x, geom.line_y[0], geom.value_clear_width, geom.value_rect_height)
        for c in gfx.calls
    )


def test_redraw_row_icon_out_of_range_is_noop() -> None:
    r, gfx, _ = _mk()

    r.redraw_row_icon(99, (0, 0))
    r.redraw_row_icon(-1, (0, 0))

    assert gfx.calls == []


# ─────────────────────────────────────────────────────────────────────
# Graph rendering: draw_graph_clear / draw_graph_column
# ─────────────────────────────────────────────────────────────────────


def test_draw_graph_clear_paints_full_graph_rect_with_background_pen() -> None:
    r, gfx, geom = _mk()
    r.draw_graph_clear(0)

    # Background pen set, then the row's graph rect cleared (graph_x, line_y,
    # graph_width, graph_height).
    assert ("set_pen", (1,), {}) in gfx.calls  # background
    assert (
        "rectangle",
        (geom.graph_x, geom.line_y[0], geom.graph_width, geom.graph_height),
        {},
    ) in gfx.calls


def test_draw_graph_clear_out_of_range_is_noop() -> None:
    r, gfx, _ = _mk()
    r.draw_graph_clear(99)
    r.draw_graph_clear(-1)
    assert gfx.calls == []


def test_draw_graph_column_with_value_draws_pastel_rect_and_bright_pixel() -> None:
    r, gfx, geom = _mk()

    r.draw_graph_column(line_idx=1, col=5, pastel_pen=10, bright_pen=20, value_y=7)

    x = geom.graph_x + 5
    y = geom.line_y[1]
    assert ("set_pen", (10,), {}) in gfx.calls
    assert ("rectangle", (x, y, 1, geom.graph_height), {}) in gfx.calls
    assert ("set_pen", (20,), {}) in gfx.calls
    assert ("pixel", (x, y + 7), {}) in gfx.calls


def test_draw_graph_column_skips_bright_when_value_y_is_none() -> None:
    """Out-of-cap: pastel column only, no pixel call."""
    r, gfx, geom = _mk()

    r.draw_graph_column(line_idx=2, col=0, pastel_pen=10, bright_pen=20, value_y=None)

    assert ("set_pen", (10,), {}) in gfx.calls
    assert ("rectangle", (geom.graph_x + 0, geom.line_y[2], 1, geom.graph_height), {}) in gfx.calls
    # No bright pen set, no pixel.
    assert ("set_pen", (20,), {}) not in gfx.calls
    assert not any(c[0] == "pixel" for c in gfx.calls)


def test_draw_graph_column_skips_bright_when_pen_is_none() -> None:
    """``bright_pen=None`` also suppresses the pixel call (parity with value_y=None)."""
    r, gfx, _ = _mk()

    r.draw_graph_column(line_idx=0, col=10, pastel_pen=5, bright_pen=None, value_y=7)
    assert not any(c[0] == "pixel" for c in gfx.calls)


def test_draw_graph_column_out_of_range_is_noop() -> None:
    r, gfx, _ = _mk()

    r.draw_graph_column(99, 0, 1, 2, 3)
    r.draw_graph_column(-1, 0, 1, 2, 3)
    assert gfx.calls == []


# ─────────────────────────────────────────────────────────────────────
# Real Geometry: layout invariants against the actual constructor.
# ─────────────────────────────────────────────────────────────────────


def test_real_geometry_layout_invariants() -> None:
    """Construct the real ``Geometry`` against ``FakePicoGraphics`` and assert
    derived layout invariants hold without hardcoding magic numbers."""
    from displays.sensors import Geometry, _HISTORY_SECONDS, _R_MARGIN

    gfx = FakePicoGraphics()
    geom = Geometry(
        pico_graphics=gfx,
        font="bitmap8",
        font_height=8,
        text_scale=3,
        tick_period_ms=500,
    )

    # Graph must fit on screen.
    assert geom.graph_x + geom.graph_width + _R_MARGIN <= geom.width
    # ticks_per_commit × graph_width covers exactly 24 h of ticks.
    total_ticks = _HISTORY_SECONDS * 1000 // 500
    assert geom.ticks_per_commit * geom.graph_width == total_ticks
    # value_clear_width covers value text + L-gap (stops just before graph_x).
    assert geom.value_clear_width == geom.graph_x - geom.value_x
    # graph_width divides total_ticks exactly.
    assert total_ticks % geom.graph_width == 0
    assert geom.graph_width >= 1
    # graph_height matches the row height.
    assert geom.graph_height == geom.text_height
    # With the device-observed measure_text("-88.8",3)=63, derivation lands
    # on a 108-column graph (largest divisor of 172800 ≤ 108 available).
    # Would shift to a different divisor if the font/scale or value sample
    # changed — sanity check, not a hardcode.
    assert geom.graph_width == 108
    assert geom.ticks_per_commit == 1600


def test_real_geometry_raises_when_font_too_large() -> None:
    """If the value column eats all the screen, geometry must raise at boot
    rather than silently producing a zero-width graph."""
    from displays.sensors import Geometry

    class _TinyScreen(FakePicoGraphics):
        def get_bounds(self):
            return (100, 100)

        def measure_text(self, text, scale):
            return 90  # eats more than the 100-wide screen

    gfx = _TinyScreen()
    import pytest

    with pytest.raises(RuntimeError, match="no room for graph"):
        Geometry(
            pico_graphics=gfx,
            font="bitmap8",
            font_height=8,
            text_scale=3,
            tick_period_ms=500,
        )
