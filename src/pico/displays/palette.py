"""Display palette: maps RGB colors to PicoGraphics pen IDs.

Keeping pen creation isolated here keeps hardware coupling out of the
individual display modules and app composition code.
"""

# Predefined stream color pairs (color_a, color_b) as RGB tuples.
# Based on the Okabe-Ito palette, brightened for black-text contrast.
# Color-blind safe: avoids red-green confusion; distinguishable under
# protanopia and deuteranopia.  Within-stream pairs use analogous hue shift.
DEFAULT_STREAM_COLORS: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = [
    ((240, 180, 50), (255, 210, 90)),    # orange / amber
    ((100, 190, 245), (150, 210, 255)),  # sky blue / light blue
    ((180, 200, 50), (210, 240, 130)),   # yellow / chartreuse
    ((230, 150, 190), (245, 185, 215)),  # pink / light pink
    ((80, 200, 160), (130, 240, 230)),   # teal / aqua
]


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
