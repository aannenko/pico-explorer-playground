"""Shared sprite-sheet helpers for icons and unit labels.

Asset: ``icons_symbols.rgb332`` — 128x128 RGB332, a 16x16 grid of 8x8 cells.

Layout:
  top row (sy=0..1):  16x16 icons (2x2 cells each), 1px black margin for
                      halo-free rendering against any background
  bottom row (sy=15): 8x8 single-cell unit labels (2-symbol combos matched to
                      the bitmap8 font metrics so they align inline with text)

All draw helpers pass ``transparent=0`` (RGB332 black) so the black padding
and the black cell margins never leave a halo.

Keep this module free of display-specific geometry — each display computes its
own (x, y) and scale and passes them in.
"""

import gc

SPRITESHEET_PATH = "icons_symbols.rgb332"

# Sprite cell coordinates (sx, sy) into the 16x16 cell grid.
# Icons are 2x2 cells; the constant points to the top-left cell.
ICON_THERMO_BLUE = (0, 0)
ICON_THERMO_GREEN = (2, 0)
ICON_THERMO_YELLOW = (4, 0)
ICON_THERMO_RED = (6, 0)
ICON_WATERDROP = (8, 0)
ICON_GAUGE = (10, 0)
ICON_GAS = (12, 0)

# Unit labels are single 8x8 cells along the bottom row.
UNIT_KOHM = (0, 15)
UNIT_MB = (1, 15)
UNIT_DEG_C = (2, 15)
UNIT_PCT = (3, 15)

# Native cell size in the sheet.
CELL_PX = 8


def load(gfx) -> None:
    """Load the icons+units spritesheet into ``gfx``.

    Runs ``gc.collect()`` first: the spritesheet is a 16 KiB contiguous
    allocation, and by the time a display initializes the heap is usually
    fragmented enough to refuse it without a collection.
    """
    gc.collect()
    gfx.load_spritesheet(SPRITESHEET_PATH)


def draw_icon(gfx, cell, x: int, y: int, scale: int = 2) -> None:
    """Draw an icon (2x2 cells) at (x, y) on-screen.

    ``cell`` is the ``(sx, sy)`` top-left cell of the icon in the sheet. The
    on-screen footprint is ``ICON_CELLS * CELL_PX * scale`` on each side.
    """
    sx, sy = cell
    step = CELL_PX * scale
    gfx.sprite(sx, sy, x, y, scale, 0)
    gfx.sprite(sx + 1, sy, x + step, y, scale, 0)
    gfx.sprite(sx, sy + 1, x, y + step, scale, 0)
    gfx.sprite(sx + 1, sy + 1, x + step, y + step, scale, 0)


def draw_sprite(gfx, cell, x: int, y: int, scale: int = 3) -> None:
    """Draw a single 8x8px unit-label cell at (x, y) on-screen.

    The unit glyphs are copies of bitmap8 letterforms, so drawing at the text
    scale and at the same ``y`` as ``gfx.text(..., y, scale=scale)`` produces
    inline alignment.
    """
    sx, sy = cell
    gfx.sprite(sx, sy, x, y, scale, 0)
