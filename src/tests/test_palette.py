from __future__ import annotations

import displays.palette as palette
from displays.palette import (
    BLACK,
    ICON_SLOTS,
    LABEL_FOR_SLOT,
    ORANGE,
    PALETTE_RGB,
    RPURPLE,
    BROWN,
    STREAM_COLORS,
    WHITE,
    program_palette,
)


class _FakePicoGraphics:
    """Records every ``update_pen(i, r, g, b)`` call."""

    def __init__(self) -> None:
        self.pens: list[tuple[int, int, int, int]] = []

    def update_pen(self, i: int, r: int, g: int, b: int) -> None:
        self.pens.append((i, r, g, b))


# ---------------------------------------------------------------------------
# Palette definition
# ---------------------------------------------------------------------------

def test_palette_rgb_has_16_valid_slots() -> None:
    assert len(PALETTE_RGB) == 16
    for idx, rgb in enumerate(PALETTE_RGB):
        assert len(rgb) == 3, f"slot {idx} must be an (r,g,b) triple"
        for ch in rgb:
            assert 0 <= ch <= 255, f"slot {idx} channel out of range"


def test_slot_constants_match_their_indices() -> None:
    assert palette.BLACK == 0
    assert palette.WHITE == 1
    assert palette.GRAY == 2
    assert palette.DKGRAY == 3
    assert palette.BLUE == 4
    assert palette.GREEN == 5
    assert palette.YELLOW == 6
    assert palette.RED == 7
    assert palette.SKY == 8
    assert palette.ORANGE == 9
    assert palette.RPURPLE == 10
    assert palette.BROWN == 11


def test_icon_slots_are_the_twelve_authored_and_distinct() -> None:
    # ICON_SLOTS excludes the 4 spares so the converter's exact-match map is
    # unambiguous (the spares duplicate BLACK).
    assert ICON_SLOTS == tuple(range(12))
    authored = [PALETTE_RGB[i] for i in ICON_SLOTS]
    assert len(set(authored)) == 12, "authored slot colours must be distinct"


def test_spare_slots_are_black() -> None:
    for i in range(12, 16):
        assert PALETTE_RGB[i] == (0, 0, 0)


# ---------------------------------------------------------------------------
# Auto-contrast lookup
# ---------------------------------------------------------------------------

def test_label_for_slot_is_black_or_white_per_slot() -> None:
    assert len(LABEL_FOR_SLOT) == 16
    for entry in LABEL_FOR_SLOT:
        assert entry in (BLACK, WHITE)


def test_label_for_slot_picks_readable_contrast() -> None:
    # Light backgrounds → black text; dark backgrounds → white text.
    assert LABEL_FOR_SLOT[palette.WHITE] == BLACK
    assert LABEL_FOR_SLOT[palette.YELLOW] == BLACK
    assert LABEL_FOR_SLOT[palette.SKY] == BLACK
    assert LABEL_FOR_SLOT[palette.BLACK] == WHITE
    assert LABEL_FOR_SLOT[palette.RED] == WHITE
    assert LABEL_FOR_SLOT[palette.BLUE] == WHITE
    assert LABEL_FOR_SLOT[palette.BROWN] == WHITE


# ---------------------------------------------------------------------------
# program_palette
# ---------------------------------------------------------------------------

def test_program_palette_writes_all_16_slots() -> None:
    gfx = _FakePicoGraphics()
    program_palette(gfx)
    assert len(gfx.pens) == 16
    for i in range(16):
        assert gfx.pens[i] == (i, *PALETTE_RGB[i])


# ---------------------------------------------------------------------------
# Stream colours
# ---------------------------------------------------------------------------

def test_stream_colors_are_valid_slots() -> None:
    assert len(STREAM_COLORS) == 9
    for idx, slot in enumerate(STREAM_COLORS):
        assert isinstance(slot, int)
        assert 0 <= slot <= 15, f"STREAM_COLORS[{idx}] out of slot range"


def test_stream_color_constants_match_positions() -> None:
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


def test_stream_colors_map_to_expected_slots() -> None:
    # work-week → ORANGE; severity ramp green/red; waste BIO → BROWN.
    assert STREAM_COLORS[palette.STREAM_AMBER] == ORANGE
    assert STREAM_COLORS[palette.STREAM_REDBROWN] == BROWN
    assert STREAM_COLORS[palette.STREAM_PINK] == RPURPLE
