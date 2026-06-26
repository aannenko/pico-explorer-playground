from __future__ import annotations

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


def test_decodes_nibbles_and_skips_transparent_zero() -> None:
    gfx = FakeGfx()
    icons_p4.draw_icon(gfx, _ICON_2x2, x=10, y=20, scale=1)
    # Only the two non-zero pixels are drawn (slot 0 is transparent).
    assert gfx.calls == [
        ("set_pen", 4), ("rectangle", 10, 20, 1, 1),
        ("set_pen", 5), ("rectangle", 11, 21, 1, 1),
    ]


def test_scale_expands_each_pixel_to_a_square() -> None:
    gfx = FakeGfx()
    icons_p4.draw_icon(gfx, _ICON_2x2, x=10, y=20, scale=3)
    assert gfx.calls == [
        ("set_pen", 4), ("rectangle", 10, 20, 3, 3),     # (0,0) -> col0,row0
        ("set_pen", 5), ("rectangle", 13, 23, 3, 3),     # (1,1) -> col1,row1
    ]


def test_transparent_override_skips_that_slot_not_zero() -> None:
    gfx = FakeGfx()
    # 1x2 icon: (0,0)=4, (1,0)=5  -> byte 0x45
    icon = (2, 1, bytes([0x45]))
    icons_p4.draw_icon(gfx, icon, x=0, y=0, scale=1, transparent=4)
    # slot 4 skipped, slot 5 drawn (and slot 0 would have been drawn if present).
    assert gfx.calls == [("set_pen", 5), ("rectangle", 1, 0, 1, 1)]


def test_zero_pixel_drawn_when_transparent_is_nonzero() -> None:
    gfx = FakeGfx()
    # (0,0)=0, (1,0)=5 -> byte 0x05; with transparent=4, slot 0 is opaque.
    icon = (2, 1, bytes([0x05]))
    icons_p4.draw_icon(gfx, icon, x=0, y=0, scale=1, transparent=4)
    assert gfx.calls == [
        ("set_pen", 0), ("rectangle", 0, 0, 1, 1),
        ("set_pen", 5), ("rectangle", 1, 0, 1, 1),
    ]


def test_real_icon_decodes_within_bounds_and_palette() -> None:
    gfx = FakeGfx()
    w, h, _blob = _icons_data.ICON_THERMO_RED
    assert (w, h) == (16, 16)
    icons_p4.draw_icon(gfx, _icons_data.ICON_THERMO_RED, x=0, y=0, scale=2)
    pens = [c[1] for c in gfx.calls if c[0] == "set_pen"]
    rects = [c for c in gfx.calls if c[0] == "rectangle"]
    assert pens, "expected at least one drawn pixel"
    for pen in pens:
        assert 0 < pen <= 15, "transparent (0) must never be drawn; pens are slots"
    for _name, x, y, rw, rh in rects:
        assert (rw, rh) == (2, 2)
        assert 0 <= x < w * 2 and 0 <= y < h * 2
