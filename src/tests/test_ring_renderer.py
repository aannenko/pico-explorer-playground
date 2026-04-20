from __future__ import annotations

from dataclasses import dataclass

import pytest

from displays.ring import Colors, Renderer, TEXT_ABOVE_CENTER, TEXT_BELOW_CENTER, TEXT_CENTER, RING_SEGMENTS


class FakePicoGraphics:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def set_pen(self, pen: int) -> None:
        self.calls.append(("set_pen", (pen,), {}))

    def set_font(self, font: str) -> None:
        self.calls.append(("set_font", (font,), {}))

    def circle(self, x: int, y: int, r: int) -> None:
        self.calls.append(("circle", (x, y, r), {}))

    def polygon(self, points: list[tuple[int, int]]) -> None:
        # Copy points to avoid later mutation affecting assertions.
        self.calls.append(("polygon", (list(points),), {}))

    def rectangle(self, x: int, y: int, w: int, h: int) -> None:
        self.calls.append(("rectangle", (x, y, w, h), {}))

    def measure_text(self, text: str, *, scale: int) -> int:
        self.calls.append(("measure_text", (text,), {"scale": scale}))
        # Deterministic width model suitable for layout assertions.
        return len(text) * 10 * scale

    def text(self, text: str, x: int, y: int, *, scale: int) -> None:
        self.calls.append(("text", (text, x, y), {"scale": scale}))

    def clear(self) -> None:
        self.calls.append(("clear", (), {}))

    def update(self) -> None:
        self.calls.append(("update", (), {}))


@dataclass
class FakeGeometry:
    graphics: FakePicoGraphics

    # Ring geometry
    x_center: int = 50
    y_center: int = 40
    outer_circle_r: int = 30
    inner_circle_r: int = 25

    x_outer_vertices: list[int] = None  # type: ignore[assignment]
    y_outer_vertices: list[int] = None  # type: ignore[assignment]
    x_inner_vertices: list[int] = None  # type: ignore[assignment]
    y_inner_vertices: list[int] = None  # type: ignore[assignment]

    # Text geometry
    width: int = 100
    font: str = "bitmap6"
    text_scale: int = 1
    text_height: int = 6

    max_text_center_width: int = 80
    text_center_rect_x: int = 10
    text_center_y: int = 20

    max_text_above_center_width: int = 60
    text_above_center_rect_x: int = 20
    text_above_center_y: int = 10

    text_below_center_y: int = 30

    def __post_init__(self) -> None:
        if self.x_outer_vertices is None:
            self.x_outer_vertices = [100 + i for i in range(120)]
        if self.y_outer_vertices is None:
            self.y_outer_vertices = [200 + i for i in range(120)]
        if self.x_inner_vertices is None:
            self.x_inner_vertices = [300 + i for i in range(120)]
        if self.y_inner_vertices is None:
            self.y_inner_vertices = [400 + i for i in range(120)]


def _mk_timergraphics() -> tuple[Renderer, FakePicoGraphics, FakeGeometry]:
    display = FakePicoGraphics()
    geom = FakeGeometry(graphics=display)
    colors = Colors(background=1, ring=2, primary_text=3, secondary_text=4)
    return Renderer(geom, colors), display, geom

def test_reset_draws_ring_and_clears_state() -> None:
    tg, display, geom = _mk_timergraphics()

    tg.text_write(TEXT_CENTER, "X")
    tg.ring_clear_segments(2)
    display.calls.clear()

    tg.reset()

    assert display.calls == [
        ("set_font", ("bitmap6",), {}),
        ("set_pen", (1,), {}),
        ("clear", (), {}),
        ("set_pen", (2,), {}),
        ("circle", (geom.x_center, geom.y_center, geom.outer_circle_r), {}),
        ("set_pen", (1,), {}),
        ("circle", (geom.x_center, geom.y_center, geom.inner_circle_r), {}),
    ]


def test_ring_clear_segments_noop_when_not_advancing() -> None:
    tg, display, _geom = _mk_timergraphics()

    tg.ring_clear_segments(2)
    display.calls.clear()

    tg.ring_clear_segments(2)

    assert display.calls == []


def test_ring_clear_segments_draws_polygon_for_increment() -> None:
    tg, display, geom = _mk_timergraphics()

    tg.ring_clear_segments(2)

    # First call sets pen to background, then draws a polygon.
    assert display.calls[0] == ("set_pen", (1,), {})

    method, args, kwargs = display.calls[1]
    assert method == "polygon"
    assert kwargs == {}

    (points,) = args
    # For count=2 from 0 cleared: (count+1)*2 = 6 points
    assert len(points) == 6

    # Expected order: outer[0], outer[1], outer[2], inner[2], inner[1], inner[0]
    assert points[0] == (geom.x_outer_vertices[0], geom.y_outer_vertices[0])
    assert points[1] == (geom.x_outer_vertices[1], geom.y_outer_vertices[1])
    assert points[2] == (geom.x_outer_vertices[2], geom.y_outer_vertices[2])
    assert points[3] == (geom.x_inner_vertices[2], geom.y_inner_vertices[2])
    assert points[4] == (geom.x_inner_vertices[1], geom.y_inner_vertices[1])
    assert points[5] == (geom.x_inner_vertices[0], geom.y_inner_vertices[0])


def test_text_write_centers_and_uses_primary_color_for_center() -> None:
    tg, display, geom = _mk_timergraphics()

    tg.text_write(TEXT_CENTER, "Hi")

    # measure_text should be called before text placement
    assert ("measure_text", ("Hi",), {"scale": geom.text_scale}) in display.calls

    # pen should be set to primary before drawing center text
    assert ("set_pen", (3,), {}) in display.calls

    expected_width = 2 * 10 * geom.text_scale
    expected_x = (geom.width - expected_width) // 2

    assert ("text", ("Hi", expected_x, geom.text_center_y), {"scale": geom.text_scale}) in display.calls


def test_text_write_noop_if_same_text() -> None:
    tg, display, _geom = _mk_timergraphics()

    tg.text_write(TEXT_ABOVE_CENTER, "A")
    display.calls.clear()

    tg.text_write(TEXT_ABOVE_CENTER, "A")

    assert display.calls == []


def test_text_clear_draws_background_rectangle_only_when_needed() -> None:
    tg, display, geom = _mk_timergraphics()

    # Clearing when empty is a noop.
    tg.text_clear(TEXT_BELOW_CENTER)
    assert display.calls == []

    tg.text_write(TEXT_BELOW_CENTER, "B")
    display.calls.clear()

    tg.text_clear(TEXT_BELOW_CENTER)

    assert display.calls[0] == ("set_pen", (1,), {})
    assert display.calls[1] == (
        "rectangle",
        (geom.text_above_center_rect_x, geom.text_below_center_y, geom.max_text_above_center_width, geom.text_height),
        {},
    )


def test_ring_clear_segments_full_clear_rewrites_existing_text() -> None:
    tg, display, geom = _mk_timergraphics()

    tg.text_write(TEXT_CENTER, "C")
    tg.text_write(TEXT_ABOVE_CENTER, "A")
    tg.text_write(TEXT_BELOW_CENTER, "B")
    display.calls.clear()

    tg.ring_clear_segments(RING_SEGMENTS)

    # Full clear draws outer circle with background.
    assert display.calls[0] == ("set_pen", (1,), {})
    assert display.calls[1] == ("circle", (geom.x_center, geom.y_center, geom.outer_circle_r), {})

    # And then re-writes backed up texts (at least one text() call per non-empty string).
    text_calls = [c for c in display.calls if c[0] == "text"]
    assert len(text_calls) == 3


@pytest.mark.parametrize("position", [999, -1])
def test_invalid_text_position_is_ignored(position: int) -> None:
    tg, display, _geom = _mk_timergraphics()

    tg.text_write(position, "X")
    tg.text_clear(position)

    assert display.calls == []
