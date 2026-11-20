from __future__ import annotations

import math
from array import array

import pytest

import displays.ring as ring
from displays.ring import Geometry, RING_SEGMENTS


class FakeDisplay:
    def __init__(self, width: int, height: int) -> None:
        self._bounds = (width, height)

    def get_bounds(self) -> tuple[int, int]:
        return self._bounds


def test_geometry_sets_expected_dimensions_and_ring_values() -> None:
    display = FakeDisplay(240, 240)
    g = Geometry(display, font="bitmap6", font_height=6, text_scale=3)

    assert g.width == 240
    assert g.height == 240
    assert g.x_center == 120
    assert g.y_center == 120

    assert g.ring_thickness == 8  # min(240,240)//30
    assert g.outer_circle_r == min(g.x_center, g.y_center) - ring._RING_OUTER_MARGIN_PX
    assert g.inner_circle_r == g.outer_circle_r - g.ring_thickness
    assert g.outer_poly_r == g.outer_circle_r + 2
    assert g.inner_poly_r == g.inner_circle_r - 1


def test_geometry_center_rounds_up_for_odd_dimensions() -> None:
    display = FakeDisplay(241, 239)
    g = Geometry(display, font="bitmap6", font_height=6, text_scale=3)

    assert g.x_center == 121
    assert g.y_center == 120


def test_geometry_text_rects_are_even_and_centered() -> None:
    display = FakeDisplay(240, 240)
    g = Geometry(display, font="bitmap6", font_height=6, text_scale=3)

    assert g.text_scale == 3
    assert g.text_height == 6 * g.text_scale

    assert g.max_text_center_width % 2 == 0
    assert g.max_text_above_center_width % 2 == 0

    assert g.text_center_rect_x == (g.width - g.max_text_center_width) // 2
    assert g.text_above_center_rect_x == (g.width - g.max_text_above_center_width) // 2

    assert 0 <= g.max_text_center_width <= g.width
    assert 0 <= g.max_text_above_center_width <= g.width


@pytest.mark.parametrize(
    "width, height, coordinate_bound, typecode, item_bytes",
    [(240, 240, 240, "B", 1), (240, 270, 255, "B", 1), (270, 240, 255, "B", 1),
     (240, 272, 256, "H", 2), (272, 240, 256, "H", 2), (480, 320, 400, "H", 2)],
    ids=["default-panel", "tall-byte-limit", "wide-byte-limit", "tall-short-limit", "wide-short-limit", "wide-panel"],
)
def test_geometry_storage_boundary_and_binary_initializers_preserve_coordinates(
    monkeypatch, width: int, height: int, coordinate_bound: int, typecode: str, item_bytes: int
) -> None:
    initializers = []

    def make_array(code: str, initializer: bytes) -> array:
        initializers.append((code, initializer))
        return array(code, initializer)

    monkeypatch.setattr(ring, "array", make_array)

    geom = Geometry(FakeDisplay(width, height), font="bitmap6", font_height=6, text_scale=3)

    assert len(initializers) == 4
    for code, initializer in initializers:
        assert code == typecode
        assert isinstance(initializer, bytes)
        assert initializer == bytes(120 * item_bytes)

    x_center, y_center = (width + 1) // 2, (height + 1) // 2
    outer_r = min(x_center, y_center)
    inner_r = outer_r - 3 - min(width, height) // 30
    expected = [[], [], [], []]
    for index in range(120):
        angle = math.radians(index * 3 - 90)
        expected[0].append(int(x_center + outer_r * math.cos(angle)))
        expected[1].append(int(y_center + outer_r * math.sin(angle)))
        expected[2].append(int(x_center + inner_r * math.cos(angle)))
        expected[3].append(int(y_center + inner_r * math.sin(angle)))
    vertices = (geom.x_outer_vertices, geom.y_outer_vertices, geom.x_inner_vertices, geom.y_inner_vertices)
    for actual, old_coordinates in zip(vertices, expected):
        assert actual.typecode == typecode
        assert actual.itemsize == item_bytes
        assert len(actual) == RING_SEGMENTS == 120
        assert list(actual) == old_coordinates
    assert max(max(axis) for axis in vertices) == coordinate_bound
