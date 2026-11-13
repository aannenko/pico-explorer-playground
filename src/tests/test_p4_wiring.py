from __future__ import annotations

import math

from displays import sensors
from displays.palette import (
    DARK_GRAY,
    GREEN,
    GREEN_SHADE,
    ORANGE,
    ORANGE_SHADE,
    PINK,
    PINK_SHADE,
    SKY,
    SKY_SHADE,
)
from displays.shared import _icons_data as icons


def _ink(art: tuple[int, int, bytes]) -> list[tuple[int, int, int]]:
    """``(col, row, slot)`` of each pixel the blitter draws."""
    width, height, data = art
    pixels: list[tuple[int, int, int]] = []
    for i in range(width * height):
        byte = data[i >> 1]
        slot = byte >> 4 if i % 2 == 0 else byte & 0x0F
        if slot:
            pixels.append((i % width, i // width, slot))
    return pixels


def test_metrics_table() -> None:
    assert sensors._METRICS == (
        (
            icons.UNIT_CELSIUS,
            (icons.ICON_THERMO_BLUE, icons.ICON_THERMO_GREEN, icons.ICON_THERMO_ORANGE, icons.ICON_THERMO_RED),
            1,
            ORANGE,
            ORANGE_SHADE,
            4.0,
            False,
        ),
        (
            icons.UNIT_MBAR,
            (icons.ICON_GAUGE_MIN, icons.ICON_GAUGE_LOW, icons.ICON_GAUGE_HIGH, icons.ICON_GAUGE_MAX),
            0,
            PINK,
            PINK_SHADE,
            10.0,
            False,
        ),
        (
            icons.UNIT_PERCENT,
            (icons.ICON_DROP_LOW, icons.ICON_DROP_MED, icons.ICON_DROP_HIGH, icons.ICON_DROP_MAX),
            1,
            SKY,
            SKY_SHADE,
            20.0,
            False,
        ),
        (
            icons.UNIT_KOHM,
            (icons.ICON_MASK_RED, icons.ICON_MASK_ORANGE, icons.ICON_MASK_GREEN, icons.ICON_MASK_BLUE),
            1,
            GREEN,
            GREEN_SHADE,
            math.log(2),
            True,
        ),
    )


def _ink_box(art: tuple[int, int, bytes]) -> tuple[int, int, int, int]:
    """``(left, top, right, bottom)`` of the pixels the blitter draws."""
    cols = [col for col, _row, _slot in _ink(art)]
    rows = [row for _col, row, _slot in _ink(art)]
    return (min(cols), min(rows), max(cols), max(rows))


def test_band_icons_are_trimmed_to_their_ink_and_share_a_size_per_metric() -> None:
    for _unit, band_icons, *_rest in sensors._METRICS:
        assert len({icon[:2] for icon in band_icons}) == 1
        for icon in band_icons:
            assert _ink_box(icon) == (0, 0, icon[0] - 1, icon[1] - 1)


def test_units_are_dark_gray_art_trimmed_to_their_ink() -> None:
    for unit, *_rest in sensors._METRICS:
        assert _ink_box(unit) == (0, 0, unit[0] - 1, unit[1] - 1)
        assert {slot for _col, _row, slot in _ink(unit)} == {DARK_GRAY}
