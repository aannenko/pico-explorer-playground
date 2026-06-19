"""Display palette: maps RGB colors to PicoGraphics pen IDs.

Keeping pen creation isolated here keeps hardware coupling out of the
individual display modules and app composition code.
"""

from micropython import const

# Curated stream-color palette: each Event's ``color_index`` is a 0-based
# index into this list (use the STREAM_* constants below).  An entry is
# either a ``(main, alt)`` RGB pair — a run of the same index alternates
# main/alt so adjacent same-category bars stay distinguishable — or a single
# RGB triple, which renders as one solid color (no alternation).
#
# Okabe-Ito based, brightened for black-text contrast and color-blind
# safety.  Quantised to RGB332 on-device.
#   0=Amber 1=SkyBlue 2=Yellow 3=Pink 4=Teal 5=RedBrown 6=Gray
#   7=Green 8=Red  (precip intensity ramp; solid so merged bars look continuous)
STREAM_COLORS: list[tuple] = [
    ((240, 180, 50), (255, 210, 90)),    # 0 amber / light amber
    ((100, 190, 245), (150, 210, 255)),  # 1 sky blue / light blue
    ((180, 200, 50), (210, 240, 130)),   # 2 yellow / chartreuse
    ((230, 150, 190), (245, 185, 215)),  # 3 pink / light pink
    ((80, 200, 160), (130, 240, 230)),   # 4 teal / aqua
    ((200, 130, 95), (220, 160, 125)),   # 5 red-brown / tan (waste: bio)
    ((160, 160, 160), (195, 195, 195)),  # 6 gray / light gray (waste: mixed)
    (90, 205, 100),                      # 7 green (precip: light)
    (235, 80, 65),                       # 8 red (precip: heavy)
]

# Named indices into STREAM_COLORS, so producers avoid magic slot numbers.
STREAM_AMBER = const(0)
STREAM_SKY = const(1)
STREAM_YELLOW = const(2)
STREAM_PINK = const(3)
STREAM_TEAL = const(4)
STREAM_REDBROWN = const(5)
STREAM_GRAY = const(6)
STREAM_GREEN = const(7)
STREAM_RED = const(8)


# Sensor-view band colors: 4 rows × 4 bands × (pastel, bright) × (r, g, b).
# Row order matches ``sensors.Display.ROWS`` (temp / pressure / humidity /
# gas).  Band 0 is the lowest, band 3 the highest.  The pastel value fills
# the entire 24px-tall history column for a sample in that band; the
# bright value paints the single value-Y pixel inside the column.
#
# All values are quantised to RGB332 on-device (3-3-2 bits → 8 R levels, 8
# G levels, 4 B levels), so close neighbours may render identically.

# Named pairs reused across rows — tweak once, applies everywhere referenced.
RED       = ((90, 25, 25), (255, 90, 80))
YELLOW    = ((90, 70, 20), (255, 220, 90))
GREEN     = ((20, 70, 30), (90, 220, 110))
BLUE      = ((20, 30, 80), (80, 140, 255))
CYAN      = ((20, 60, 80), (90, 200, 230))
PALE_BLUE = ((50, 70, 90), (180, 220, 240))
PURPLE    = ((60, 30, 90), (190, 110, 230))  # used once (pressure band 0)

SENSOR_BAND_RGB: tuple = (
    (BLUE,   GREEN,     YELLOW,    RED),    # Temperature: cold / cool / warm / hot
    (PURPLE, CYAN,      PALE_BLUE, YELLOW), # Pressure:    stormy / low / normal / fair
    (YELLOW, PALE_BLUE, CYAN,      BLUE),   # Humidity:    dry / comfy-low / comfy-high / humid
    (RED,    YELLOW,    GREEN,     CYAN),   # Gas:         polluted / mild / decent / clean
)


class Palette:
    def __init__(
        self,
        black: int,
        gray: int,
        white: int,
        orange: int,
        dark_gray: int,
    ) -> None:
        self.black = black
        self.gray = gray
        self.white = white
        self.orange = orange
        self.dark_gray = dark_gray


def build_palette(gfx):  # gfx: PicoGraphics
    return Palette(
        black=gfx.create_pen(0, 0, 0),
        gray=gfx.create_pen(190, 190, 190),
        white=gfx.create_pen(255, 255, 255),
        orange=gfx.create_pen(255, 165, 0),
        dark_gray=gfx.create_pen(40, 40, 40),
    )


def build_sensor_band_pens(gfx):  # gfx: PicoGraphics
    """Build the 4×4 grid of (pastel_pen, bright_pen) pairs from ``SENSOR_BAND_RGB``.

    Returns a ``tuple[4][4][2]`` of pen ints (one pen per ``create_pen``
    call).  The display indexes as ``pens[metric_idx][band_idx]`` to get
    ``(pastel_pen, bright_pen)`` for a sample.
    """
    return tuple(
        tuple(
            (gfx.create_pen(*pastel), gfx.create_pen(*bright))
            for pastel, bright in row
        )
        for row in SENSOR_BAND_RGB
    )


def build_stream_pen_pairs(gfx, palette):  # gfx: PicoGraphics
    """Map an authored stream palette to ``(main_pen, alt_pen)`` pen pairs.

    Each ``palette`` entry is either a single RGB triple — which expands to
    ``(pen, pen)`` so a category renders as one solid color — or a
    ``(main_rgb, alt_rgb)`` pair whose two pens let adjacent same-category
    bars alternate.  ``EventWindow`` indexes the result by ``color_index``.
    """
    pairs: list[tuple[int, int]] = []
    for entry in palette:
        if isinstance(entry[0], int):
            pen = gfx.create_pen(*entry)
            pairs.append((pen, pen))
        else:
            main_rgb, alt_rgb = entry
            pairs.append((gfx.create_pen(*main_rgb), gfx.create_pen(*alt_rgb)))

    return tuple(pairs)
