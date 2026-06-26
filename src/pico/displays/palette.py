"""Display palette: the single 16-colour language, programmed once at boot.

The framebuffer holds 4-bit indices into a 16-slot palette, so a pen is just its
slot index (0-15).  This module owns:

* ``PALETTE_RGB`` — the 16 ``(r, g, b)`` slot colours (panel-calibrated, derived
  from Okabe-Ito; slots 12-15 are spare).
* named slot constants (``BLACK`` .. ``BROWN``) used everywhere a pen is needed.
* ``program_palette(gfx)`` — writes all 16 slots into the framebuffer once.
* ``LABEL_FOR_SLOT`` — per-slot auto-contrast (BLACK/WHITE) for text drawn on a
  coloured background; reused for sensor value markers and calendar bar labels.

Keeping module-level imports to ``micropython.const`` only (no ``picographics``;
``update_pen`` calls live inside function bodies) lets host tools import the
colour definitions with a trivial ``const`` shim.
"""

from micropython import const

# Slot indices into ``PALETTE_RGB`` (== the on-device pen value under PEN_P4).
# Slots 0-3 achromatic, 4-7 the ordered ramp, 8-11 qualitative, 12-15 spare.
BLACK = const(0)
WHITE = const(1)
GRAY = const(2)
DKGRAY = const(3)
BLUE = const(4)
GREEN = const(5)
YELLOW = const(6)
RED = const(7)
SKY = const(8)
ORANGE = const(9)
RPURPLE = const(10)
BROWN = const(11)

# The locked 16-colour language.  Panel-calibrated (brighter than sRGB, esp.
# blues/reds, since the ST7789 renders darker than sRGB).  Host tools import
# this tuple rather than copying it, so the colours can't drift.
PALETTE_RGB: tuple = (
    (0, 0, 0),         # 0  BLACK   — background; icon transparent index
    (255, 255, 255),   # 1  WHITE   — text; sensor value marker; now-line
    (185, 185, 185),   # 2  GRAY    — secondary text; waste MIXED
    (70, 70, 70),      # 3  DKGRAY  — calendar empty rows; dark icon detail
    (40, 150, 215),    # 4  BLUE    — sensor band low
    (55, 200, 120),    # 5  GREEN   — sensor band; severity ok; precip light
    (240, 228, 66),    # 6  YELLOW  — sensor band; severity warn; waste PLAST
    (238, 100, 45),    # 7  RED     — sensor band high; severity high; precip heavy
    (120, 200, 250),   # 8  SKY     — waste PAPER
    (246, 176, 22),    # 9  ORANGE  — countdown ring; work-week
    (225, 150, 195),   # 10 RPURPLE — bus / spare qualitative
    (170, 105, 55),    # 11 BROWN   — waste BIO (labelled row)
    (0, 0, 0),         # 12 spare
    (0, 0, 0),         # 13 spare
    (0, 0, 0),         # 14 spare
    (0, 0, 0),         # 15 spare
)

# Slots icons are allowed to use (the 12 authored colours, not the 4 spares).
# The icon converter matches authored pixels against only these so a stray
# spare-slot/off-palette colour still errors out instead of snapping to a spare.
ICON_SLOTS: tuple = tuple(range(12))


def _auto_contrast(slot: int) -> int:
    """Return BLACK or WHITE, whichever reads better on ``slot``'s colour.

    Rec.601 luma in integer math; threshold tuned so the dark ramp/qualitative
    colours (RED, BLUE, BROWN, DKGRAY) take white text and the rest black.
    """
    r, g, b = PALETTE_RGB[slot]
    lum = (r * 299 + g * 587 + b * 114) // 1000
    return BLACK if lum > 140 else WHITE


# Per-slot auto-contrast lookup (pen == slot under PEN_P4), computed once at
# import.  Consumers index it directly: ``LABEL_FOR_SLOT[bar_pen]`` /
# ``LABEL_FOR_SLOT[fill_slot]`` — no per-render luminance work.
LABEL_FOR_SLOT: tuple = tuple(_auto_contrast(i) for i in range(16))


# Curated stream-colour palette: each Event's ``color_index`` is a 0-based index
# into this list (use the STREAM_* constants below).  Each entry is a single
# palette slot; rows are distinguished by fixed position + label + colour.
STREAM_COLORS: list[int] = [
    ORANGE,   # 0 work-week
    SKY,      # 1 demo weather / waste PAPER
    YELLOW,   # 2 demo / waste PLAST / severity warn
    RPURPLE,  # 3 demo
    SKY,      # 4 demo (spare slot reuse)
    BROWN,    # 5 waste BIO
    GRAY,     # 6 waste MIXED
    GREEN,    # 7 severity ok / precip light
    RED,      # 8 severity high / precip heavy
]

# Named indices into STREAM_COLORS, so producers avoid magic slot numbers.
# Positions are stable — tests + config schema reference them.
STREAM_AMBER = const(0)
STREAM_SKY = const(1)
STREAM_YELLOW = const(2)
STREAM_PINK = const(3)
STREAM_TEAL = const(4)
STREAM_REDBROWN = const(5)
STREAM_GRAY = const(6)
STREAM_GREEN = const(7)
STREAM_RED = const(8)


def program_palette(gfx) -> None:  # gfx: PicoGraphics
    """Write all 16 palette slots into the framebuffer's pen table.

    Called once at boot (``main.py``) after the PEN_P4 framebuffer is created
    and before the first render.  Spare slots 12-15 are programmed to black so
    no slot holds an undefined colour.
    """
    for i in range(16):
        r, g, b = PALETTE_RGB[i]
        gfx.update_pen(i, r, g, b)
