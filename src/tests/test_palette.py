from __future__ import annotations

import displays.palette as palette
from displays.palette import SENSOR_BAND_RGB, STREAM_COLORS, build_sensor_band_pens, build_stream_pen_pairs


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


def test_stream_colors_are_rgb_triples_or_main_alt_pairs() -> None:
    for idx, entry in enumerate(STREAM_COLORS):
        if isinstance(entry[0], int):
            rgbs = (entry,)  # single solid RGB triple
        else:
            rgbs = entry  # (main_rgb, alt_rgb)
        for rgb in rgbs:
            assert len(rgb) == 3, f"entry {idx} must be an (r,g,b) triple"
            for ch in rgb:
                assert 0 <= ch <= 255, f"entry {idx} channel out of range"


def test_stream_color_constants_match_positions() -> None:
    # Named indices must line up with their palette slots.
    assert palette.STREAM_AMBER == 0
    assert palette.STREAM_SKY == 1
    assert palette.STREAM_YELLOW == 2
    assert palette.STREAM_PINK == 3
    assert palette.STREAM_TEAL == 4
    assert palette.STREAM_REDBROWN == 5
    assert palette.STREAM_GRAY == 6
    assert palette.STREAM_GREEN == 7
    assert palette.STREAM_RED == 8
    assert palette.STREAM_RED == len(STREAM_COLORS) - 1


def test_waste_default_indices_are_in_range() -> None:
    # The shipped WASTE_SCHEDULE references red-brown / gray / yellow / sky.
    for idx in (palette.STREAM_REDBROWN, palette.STREAM_GRAY,
                palette.STREAM_YELLOW, palette.STREAM_SKY):
        assert 0 <= idx < len(STREAM_COLORS)


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


# ---------------------------------------------------------------------------
# build_stream_pen_pairs
# ---------------------------------------------------------------------------

def test_build_stream_pen_pairs_expands_single_rgb_to_equal_pair() -> None:
    """A single RGB triple expands to (pen, pen) with one create_pen call."""
    gfx = _FakePicoGraphics()
    pairs = build_stream_pen_pairs(gfx, ((10, 20, 30),))

    expected = (10 << 16) | (20 << 8) | 30
    assert pairs == ((expected, expected),)
    assert gfx.calls == [(10, 20, 30)]  # one pen, reused for main and alt


def test_build_stream_pen_pairs_maps_main_alt_pair() -> None:
    """A (main_rgb, alt_rgb) pair maps each side to its own pen."""
    gfx = _FakePicoGraphics()
    pairs = build_stream_pen_pairs(gfx, (((1, 2, 3), (4, 5, 6)),))

    main = (1 << 16) | (2 << 8) | 3
    alt = (4 << 16) | (5 << 8) | 6
    assert pairs == ((main, alt),)


def test_build_stream_pen_pairs_handles_mixed_entries() -> None:
    """Singles and pairs may be mixed within one palette."""
    gfx = _FakePicoGraphics()
    pairs = build_stream_pen_pairs(gfx, ((1, 1, 1), ((2, 2, 2), (3, 3, 3))))

    solid = (1 << 16) | (1 << 8) | 1
    main = (2 << 16) | (2 << 8) | 2
    alt = (3 << 16) | (3 << 8) | 3
    assert pairs == ((solid, solid), (main, alt))


def test_build_stream_pen_pairs_returns_nested_tuples() -> None:
    gfx = _FakePicoGraphics()
    pairs = build_stream_pen_pairs(gfx, ((1, 2, 3),))

    assert isinstance(pairs, tuple)
    assert isinstance(pairs[0], tuple)
    assert len(pairs[0]) == 2
