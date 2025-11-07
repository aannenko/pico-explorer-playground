import math

from array import array
from picographics import PicoGraphics


class Geometry:
    RING_SEGMENTS = const(120)
    SEGMENT_ANGLE = const(360 // RING_SEGMENTS)
    FONT = const("bitmap6")  # bitmap6 by default when we don't set the font
    FONT_HEIGHT = const(6)

    def __init__(self, display: PicoGraphics) -> None:
        self.display = display

        # Display geometry
        self.height, self.width = display.get_bounds()
        self.x_center = self.width // 2 + self.width % 2
        self.y_center = self.height // 2 + self.height % 2

        # Ring geometry
        self.ring_thickness = min(self.width, self.height) // 30
        self.outer_circle_r = min(self.x_center, self.y_center) - 2
        self.inner_circle_r = self.outer_circle_r - self.ring_thickness
        self.outer_poly_r = self.outer_circle_r + 2
        self.inner_poly_r = self.inner_circle_r - 1

        angles_rad = array('f', (math.radians(self.SEGMENT_ANGLE * i - 90) for i in range(self.RING_SEGMENTS)))
        cos_values = array('f', (math.cos(angle) for angle in angles_rad))
        sin_values = array('f', (math.sin(angle) for angle in angles_rad))

        self.x_outer_vertices = array('H', (int(self.x_center + self.outer_poly_r * cos_val) for cos_val in cos_values))
        self.y_outer_vertices = array('H', (int(self.y_center + self.outer_poly_r * sin_val) for sin_val in sin_values))
        self.x_inner_vertices = array('H', (int(self.x_center + self.inner_poly_r * cos_val) for cos_val in cos_values))
        self.y_inner_vertices = array('H', (int(self.y_center + self.inner_poly_r * sin_val) for sin_val in sin_values))

        # Text geometry
        display.set_font(self.FONT)
        self.text_scale = min(self.width, self.height) // 80
        self.text_height = self.FONT_HEIGHT * self.text_scale

        self.max_text_center_width = int(math.sqrt(self.inner_circle_r**2 - (self.text_height // 2)**2) * 2)
        self.max_text_center_width -= self.max_text_center_width % 2
        self.text_center_rect_x = (self.width - self.max_text_center_width) // 2
        self.text_center_y = (self.height - self.text_height) // 2

        self.max_text_above_center_width = int(math.sqrt(self.inner_circle_r**2 - (self.text_height // 2 + self.text_height * 2)**2) * 2)
        self.max_text_above_center_width -= self.max_text_above_center_width % 2
        self.text_above_center_rect_x = (self.width - self.max_text_above_center_width) // 2
        self.text_above_center_y = self.text_center_y - self.text_height * 2

        self.text_below_center_y = self.text_center_y + self.text_height * 2
