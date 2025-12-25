from __future__ import annotations

from array import array

from displays.timer import Geometry


class FakeDisplay:
    def __init__(self, width: int, height: int) -> None:
        self._bounds = (width, height)
        self.font_calls: list[str] = []

    def get_bounds(self) -> tuple[int, int]:
        return self._bounds

    def set_font(self, font: str) -> None:
        self.font_calls.append(font)


def test_geometry_sets_expected_dimensions_and_ring_values() -> None:
    display = FakeDisplay(240, 240)
    g = Geometry(display)

    assert g.width == 240
    assert g.height == 240
    assert g.x_center == 120
    assert g.y_center == 120

    assert g.ring_thickness == 8  # min(240,240)//30
    assert g.outer_circle_r == 118  # min(120,120)-2
    assert g.inner_circle_r == 110
    assert g.outer_poly_r == 120
    assert g.inner_poly_r == 109

    assert display.font_calls == [g.FONT]


def test_geometry_center_rounds_up_for_odd_dimensions() -> None:
    display = FakeDisplay(241, 239)
    g = Geometry(display)

    assert g.x_center == 121
    assert g.y_center == 120


def test_geometry_precomputes_vertex_arrays() -> None:
    display = FakeDisplay(240, 240)
    g = Geometry(display)

    assert isinstance(g.x_outer_vertices, array)
    assert isinstance(g.y_outer_vertices, array)
    assert isinstance(g.x_inner_vertices, array)
    assert isinstance(g.y_inner_vertices, array)

    assert g.x_outer_vertices.typecode == "H"
    assert g.y_outer_vertices.typecode == "H"
    assert g.x_inner_vertices.typecode == "H"
    assert g.y_inner_vertices.typecode == "H"

    assert len(g.x_outer_vertices) == g.RING_SEGMENTS
    assert len(g.y_outer_vertices) == g.RING_SEGMENTS
    assert len(g.x_inner_vertices) == g.RING_SEGMENTS
    assert len(g.y_inner_vertices) == g.RING_SEGMENTS

    # Segment 0 is at angle -90°, so x should be centered and y should be above center.
    # Note: Geometry uses float32 intermediates; allow a small integer rounding tolerance.
    assert abs(g.x_outer_vertices[0] - g.x_center) <= 1
    assert abs(g.y_outer_vertices[0] - (g.y_center - g.outer_poly_r)) <= 1


def test_geometry_text_rects_are_even_and_centered() -> None:
    display = FakeDisplay(240, 240)
    g = Geometry(display)

    assert g.text_scale == 3  # 240//80
    assert g.text_height == g.FONT_HEIGHT * g.text_scale

    assert g.max_text_center_width % 2 == 0
    assert g.max_text_above_center_width % 2 == 0

    assert g.text_center_rect_x == (g.width - g.max_text_center_width) // 2
    assert g.text_above_center_rect_x == (g.width - g.max_text_above_center_width) // 2

    assert 0 <= g.max_text_center_width <= g.width
    assert 0 <= g.max_text_above_center_width <= g.width
