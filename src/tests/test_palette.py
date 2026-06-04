from __future__ import annotations

from displays.palette import SENSOR_BAND_RGB, build_sensor_band_pens


class _FakePicoGraphics:
    """Records every ``create_pen(r, g, b)`` and returns a deterministic int."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int]] = []

    def create_pen(self, r: int, g: int, b: int) -> int:
        self.calls.append((r, g, b))
        # Use a deterministic-but-distinct value so tests can check
        # which RGB triple a pen came from.
        return (r << 16) | (g << 8) | b


def test_sensor_band_rgb_shape() -> None:
    """SENSOR_BAND_RGB must be 4 rows × 4 bands × (pastel, bright) × 3 RGB."""
    assert len(SENSOR_BAND_RGB) == 4
    for row_idx, row in enumerate(SENSOR_BAND_RGB):
        assert len(row) == 4, f"row {row_idx} must hold 4 bands"
        for band_idx, band in enumerate(row):
            assert len(band) == 2, f"row {row_idx} band {band_idx} must hold (pastel, bright)"
            pastel, bright = band
            assert len(pastel) == 3, f"pastel for row {row_idx} band {band_idx} must be (r,g,b)"
            assert len(bright) == 3, f"bright for row {row_idx} band {band_idx} must be (r,g,b)"
            for ch in (*pastel, *bright):
                assert 0 <= ch <= 255, f"channel out of range in row {row_idx} band {band_idx}"


def test_build_sensor_band_pens_shape() -> None:
    """build_sensor_band_pens returns the same 4×4×2 nesting, with pen ints."""
    gfx = _FakePicoGraphics()
    pens = build_sensor_band_pens(gfx)

    assert len(pens) == 4
    for row_idx, row in enumerate(pens):
        assert len(row) == 4, f"row {row_idx} must hold 4 bands"
        for band_idx, band in enumerate(row):
            assert len(band) == 2, f"row {row_idx} band {band_idx} must be (pastel_pen, bright_pen)"
            for pen in band:
                assert isinstance(pen, int)


def test_build_sensor_band_pens_uses_create_pen_with_rgb_table_values() -> None:
    """Each (pastel_pen, bright_pen) must come from create_pen called with
    the matching SENSOR_BAND_RGB triple."""
    gfx = _FakePicoGraphics()
    pens = build_sensor_band_pens(gfx)

    for row_idx, row in enumerate(SENSOR_BAND_RGB):
        for band_idx, (pastel_rgb, bright_rgb) in enumerate(row):
            pastel_pen, bright_pen = pens[row_idx][band_idx]
            # Deterministic encoding from the fake gfx.
            assert pastel_pen == (pastel_rgb[0] << 16) | (pastel_rgb[1] << 8) | pastel_rgb[2]
            assert bright_pen == (bright_rgb[0] << 16) | (bright_rgb[1] << 8) | bright_rgb[2]


def test_build_sensor_band_pens_calls_create_pen_for_every_entry() -> None:
    """4 rows × 4 bands × 2 entries = 32 create_pen calls."""
    gfx = _FakePicoGraphics()
    build_sensor_band_pens(gfx)
    assert len(gfx.calls) == 32


def test_pens_indexable_as_metric_then_band() -> None:
    """Validate the documented access pattern: pens[metric_idx][band_idx] →
    (pastel_pen, bright_pen)."""
    gfx = _FakePicoGraphics()
    pens = build_sensor_band_pens(gfx)
    # Spot-check: temperature (row 0) hot-band (3) → bright should encode
    # SENSOR_BAND_RGB[0][3][1].
    expected_bright_rgb = SENSOR_BAND_RGB[0][3][1]
    expected_bright_pen = (
        (expected_bright_rgb[0] << 16)
        | (expected_bright_rgb[1] << 8)
        | expected_bright_rgb[2]
    )
    _pastel, bright = pens[0][3]
    assert bright == expected_bright_pen
