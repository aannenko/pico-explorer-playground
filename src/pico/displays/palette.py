"""The 16-colour palette: slot names, RGB values, label contrast and stream colours."""

# Keep module-level imports to ``micropython.const``: host tools import the
# colour definitions with only a ``const`` shim.
from micropython import const

# Slot indices, which are also the pens under PEN_P4: 0-3 achromatic, 4-7 the
# ordered ramp, 8-11 qualitative, 12-15 shades of four of those for graph fills.
BLACK = const(0)
WHITE = const(1)
GRAY = const(2)
DARK_GRAY = const(3)
BLUE = const(4)
GREEN = const(5)
YELLOW = const(6)
RED = const(7)
SKY = const(8)
ORANGE = const(9)
PINK = const(10)
BROWN = const(11)
ORANGE_SHADE = const(12)
PINK_SHADE = const(13)
SKY_SHADE = const(14)
GREEN_SHADE = const(15)

# Each shade's channels as a percentage of its base colour's.
_SHADE_PCT = const(90)

# Derived from Okabe-Ito and panel-calibrated: brighter than sRGB (esp. blues/reds)
# since the ST7789 renders darker than sRGB.
_AUTHORED_RGB = (
    (0, 0, 0),         # 0  BLACK
    (255, 255, 255),   # 1  WHITE
    (185, 185, 185),   # 2  GRAY
    (100, 100, 100),   # 3  DARK_GRAY
    (40, 150, 215),    # 4  BLUE
    (55, 200, 120),    # 5  GREEN
    (240, 228, 66),    # 6  YELLOW
    (238, 100, 45),    # 7  RED
    (120, 200, 250),   # 8  SKY
    (246, 176, 22),    # 9  ORANGE
    (225, 150, 195),   # 10 PINK
    (170, 105, 55),    # 11 BROWN
)

# The base colours of slots 12-15, in slot order.
_SHADED_SLOTS = (ORANGE, PINK, SKY, GREEN)

PALETTE_RGB = _AUTHORED_RGB + tuple(
    tuple(channel * _SHADE_PCT // 100 for channel in _AUTHORED_RGB[slot]) for slot in _SHADED_SLOTS
)

# The authored colours only: an icon can't use a graph-fill shade.
ICON_SLOTS = tuple(range(len(_AUTHORED_RGB)))

_WHITE_LABEL_MAX_LUMA = const(140)


def _auto_contrast(slot: int) -> int:
    """Return BLACK or WHITE, whichever reads better on ``slot``'s colour.

    Rec.601 luma in integer math; threshold tuned so the dark authored colours
    (DARK_GRAY, BLUE, RED, BROWN) take white text and the lighter ones black.
    """
    r, g, b = PALETTE_RGB[slot]
    lum = (r * 299 + g * 587 + b * 114) // 1000
    return BLACK if lum > _WHITE_LABEL_MAX_LUMA else WHITE


# Precompute contrast to avoid per-render luminance arithmetic.
LABEL_FOR_SLOT = tuple(_auto_contrast(i) for i in range(16))


STREAM_COLORS = [
    ORANGE,
    SKY,
    YELLOW,
    PINK,
    BLUE,
    BROWN,
    GRAY,
    GREEN,
    RED,
]

# STREAM_* indices are stable configuration values.
STREAM_ORANGE = const(0)
STREAM_SKY = const(1)
STREAM_YELLOW = const(2)
STREAM_PINK = const(3)
STREAM_BLUE = const(4)
STREAM_BROWN = const(5)
STREAM_GRAY = const(6)
STREAM_GREEN = const(7)
STREAM_RED = const(8)


def program_palette(gfx) -> None:  # gfx: PicoGraphics
    """Load ``PALETTE_RGB`` into all 16 palette slots of ``gfx``."""
    for i in range(16):
        r, g, b = PALETTE_RGB[i]
        gfx.update_pen(i, r, g, b)
