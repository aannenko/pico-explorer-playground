"""Cheap host-side wiring checks for the P4 sensors display.

``sensors.Display.ROWS`` is the single source that colocates each band's
``(icon, fill)``.  These tests catch metric/band remap typos and a metric-order
swap without a device: every icon/unit must resolve to a real generated blob of
the right size, and the band pens derived from ROWS must be valid slots in the
right order.
"""

from __future__ import annotations

from displays import sensors
from displays.palette import BLUE, GREEN, LABEL_FOR_SLOT, ORANGE, RED, RPURPLE, SKY, YELLOW
from displays.sensors import build_sensor_band_pens
from displays.shared import _icons_data


def _is_icon_tuple(obj) -> bool:
    return (
        isinstance(obj, tuple)
        and len(obj) == 3
        and isinstance(obj[0], int)
        and isinstance(obj[1], int)
        and isinstance(obj[2], (bytes, bytearray))
    )


_DATA_ICONS = [
    v for k, v in vars(_icons_data).items()
    if not k.startswith("_") and _is_icon_tuple(v)
]


def test_rows_have_four_cells_with_real_blobs_and_valid_fills() -> None:
    for unit, cells in sensors.Display.ROWS:
        assert _is_icon_tuple(unit)
        assert unit in _DATA_ICONS, "ROWS unit is not a generated icon blob"
        assert len(cells) == 4, "each metric row must have 4 band cells"
        for icon, fill in cells:
            assert _is_icon_tuple(icon)
            assert icon in _DATA_ICONS, "ROWS icon is not a generated icon blob"
            assert 0 <= fill <= 15, "fill must be a valid palette slot"


def test_row_icon_and_unit_dimensions() -> None:
    for unit, cells in sensors.Display.ROWS:
        assert (unit[0], unit[1]) == (8, 8), "units are 8x8"
        for icon, _fill in cells:
            assert (icon[0], icon[1]) == (16, 16), "metric icons are 16x16"


def test_band_pen_fields_are_valid_slots() -> None:
    pens = build_sensor_band_pens()
    assert len(pens) == 4
    for row in pens:
        assert len(row) == 4
        for fill, marker in row:
            assert 0 <= fill <= 15
            assert 0 <= marker <= 15


def test_band_pen_marker_is_auto_contrast_of_fill() -> None:
    pens = build_sensor_band_pens()
    for row in pens:
        for fill, marker in row:
            assert marker == LABEL_FOR_SLOT[fill]


def test_band_pen_metric_order_guard() -> None:
    # Guards the ROWS metric order (temp / PRESSURE / HUMIDITY / gas): if
    # pressure↔humidity ever swap, these break loudly.
    pens = build_sensor_band_pens()
    assert pens[1][0][0] == RPURPLE, "pressure band-0 fill must be RPURPLE"
    assert pens[2][0][0] == YELLOW, "humidity band-0 fill must be YELLOW"


def test_rows_match_expected_band_order() -> None:
    # Pins the full ROWS table (unit + per-band (icon, fill)) — a metric swap or
    # band/colour reorder breaks this loudly.
    d = _icons_data
    expected = (
        (d.UNIT_CELSIUS, (
            (d.ICON_THERMO_BLUE, SKY), (d.ICON_THERMO_GREEN, GREEN),
            (d.ICON_THERMO_ORANGE, ORANGE), (d.ICON_THERMO_RED, RED),
        )),
        (d.UNIT_MBAR, (
            (d.ICON_GAUGE_MIN, RPURPLE), (d.ICON_GAUGE_LOW, GREEN),
            (d.ICON_GAUGE_HIGH, YELLOW), (d.ICON_GAUGE_MAX, ORANGE),
        )),
        (d.UNIT_PERCENT, (
            (d.ICON_DROP_LOW, YELLOW), (d.ICON_DROP_MED, GREEN),
            (d.ICON_DROP_HIGH, SKY), (d.ICON_DROP_MAX, BLUE),
        )),
        (d.UNIT_KOHM, (
            (d.ICON_MASK_RED, RED), (d.ICON_MASK_ORANGE, ORANGE),
            (d.ICON_MASK_GREEN, GREEN), (d.ICON_MASK_BLUE, SKY),
        )),
    )
    assert sensors.Display.ROWS == expected
