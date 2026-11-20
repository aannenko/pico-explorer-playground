from __future__ import annotations

import pytest

from displays.shared import _icons_data, icons_p4


class FakeGfx:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def set_pen(self, pen: int) -> None:
        self.calls.append(("set_pen", pen))

    def rectangle(self, x: int, y: int, w: int, h: int) -> None:
        self.calls.append(("rectangle", x, y, w, h))


# A 2x2 icon: nibbles (row-major, high nibble = left pixel)
#   (0,0)=4  (1,0)=0   ->  byte 0x40
#   (0,1)=0  (1,1)=5   ->  byte 0x05
_ICON_2x2 = (2, 2, bytes([0x40, 0x05]))


@pytest.mark.parametrize(
    "scale, calls",
    [
        (1, [("set_pen", 4), ("rectangle", 10, 20, 1, 1), ("set_pen", 5), ("rectangle", 11, 21, 1, 1)]),
        (
            3,
            [
                ("set_pen", 4), ("rectangle", 10, 20, 3, 3),     # (0,0) -> col0,row0
                ("set_pen", 5), ("rectangle", 13, 23, 3, 3),     # (1,1) -> col1,row1
            ],
        ),
    ],
)
def test_draws_each_non_zero_nibble_as_a_scale_px_square_in_its_slot(scale: int, calls: list[tuple]) -> None:
    gfx = FakeGfx()
    icons_p4.draw_icon(gfx, _ICON_2x2, x=10, y=20, scale=scale)
    assert gfx.calls == calls


@pytest.mark.parametrize(
    "icon, calls",
    [
        # 2x1 icon: (0,0)=4, (1,0)=5  -> byte 0x45
        pytest.param((2, 1, bytes([0x45])), [("set_pen", 5), ("rectangle", 1, 0, 1, 1)], id="that slot skipped"),
        # (0,0)=0, (1,0)=5 -> byte 0x05
        pytest.param(
            (2, 1, bytes([0x05])),
            [("set_pen", 0), ("rectangle", 0, 0, 1, 1), ("set_pen", 5), ("rectangle", 1, 0, 1, 1)],
            id="slot zero drawn",
        ),
    ],
)
def test_a_transparent_override_skips_that_slot_instead_of_zero(
    icon: tuple[int, int, bytes], calls: list[tuple]
) -> None:
    gfx = FakeGfx()
    icons_p4.draw_icon(gfx, icon, x=0, y=0, scale=1, transparent=4)
    assert gfx.calls == calls


def test_pixels_sharing_a_slot_set_its_pen_once_even_across_a_transparent_gap() -> None:
    gfx = FakeGfx()
    # 4x1 icon: 5, 5, 0, 5 -> bytes 0x55 0x05
    icons_p4.draw_icon(gfx, (4, 1, bytes([0x55, 0x05])), x=0, y=0, scale=1)
    assert gfx.calls == [
        ("set_pen", 5), ("rectangle", 0, 0, 1, 1), ("rectangle", 1, 0, 1, 1), ("rectangle", 3, 0, 1, 1),
    ]


@pytest.mark.parametrize(
    "icon, transparent, pen, calls",
    [
        pytest.param(
            _ICON_2x2, 0, 7, [("set_pen", 7), ("rectangle", 10, 20, 1, 1), ("rectangle", 11, 21, 1, 1)], id="a colour"
        ),
        # 2x1 icon: (0,0)=4, (1,0)=0 -> byte 0x40; slot 4 is transparent, so only slot 0's pixel takes the pen.
        pytest.param(
            (2, 1, bytes([0x40])), 4, 0, [("set_pen", 0), ("rectangle", 11, 20, 1, 1)],
            id="black, with slot 4 transparent",
        ),
    ],
)
def test_a_pen_draws_every_opaque_pixel_in_it_whatever_its_own_colour(
    icon: tuple[int, int, bytes], transparent: int, pen: int, calls: list[tuple]
) -> None:
    gfx = FakeGfx()
    icons_p4.draw_icon(gfx, icon, x=10, y=20, scale=1, transparent=transparent, pen=pen)
    assert gfx.calls == calls


def test_real_icon_decodes_within_bounds_and_palette() -> None:
    gfx = FakeGfx()
    w, h, _blob = _icons_data.ICON_THERMO_RED
    assert (w, h) == (10, 14)
    icons_p4.draw_icon(gfx, _icons_data.ICON_THERMO_RED, x=0, y=0, scale=2)
    pens = [c[1] for c in gfx.calls if c[0] == "set_pen"]
    rects = [c for c in gfx.calls if c[0] == "rectangle"]
    assert pens, "expected at least one drawn pixel"
    for pen in pens:
        assert 0 < pen <= 15, "transparent (0) must never be drawn; pens are slots"
    for _name, x, y, rw, rh in rects:
        assert (rw, rh) == (2, 2)
        assert 0 <= x < w * 2 and 0 <= y < h * 2
