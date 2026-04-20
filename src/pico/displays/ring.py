import math
import micropython


from array import array
from micropython import const
from picographics import PicoGraphics  # type: ignore

RING_SEGMENTS = const(120)
SEGMENT_ANGLE = const(360 // RING_SEGMENTS)

# Coordinates in the form of X,Y; 5,5 is center, 0,0 is top-left, 9,9 is bottom-right
TEXT_CENTER = const(55)  # 5,5
TEXT_ABOVE_CENTER = const(54)  # 5,4
TEXT_BELOW_CENTER = const(56)  # 5,6

_RING_THICKNESS_DIVISOR = const(30)
_RING_OUTER_MARGIN = const(2)


class Colors:
    def __init__(
        self,
        background: int,
        ring: int,
        primary_text: int,
        secondary_text: int,
    ) -> None:
        self.background = background
        self.ring = ring
        self.primary_text = primary_text
        self.secondary_text = secondary_text


class Geometry:
    @micropython.native
    def __init__(
        self,
        pico_graphics: PicoGraphics,
        font: str,
        font_height: int,
        text_scale: int,
    ) -> None:
        self.graphics = pico_graphics

        # Display geometry
        self.width, self.height = pico_graphics.get_bounds()
        self.x_center = self.width // 2 + self.width % 2
        self.y_center = self.height // 2 + self.height % 2

        # Ring geometry
        self.ring_thickness = min(self.width, self.height) // _RING_THICKNESS_DIVISOR
        self.outer_circle_r = min(self.x_center, self.y_center) - _RING_OUTER_MARGIN
        self.inner_circle_r = self.outer_circle_r - self.ring_thickness
        self.outer_poly_r = self.outer_circle_r + 2
        self.inner_poly_r = self.inner_circle_r - 1

        empty_list = [0] * RING_SEGMENTS
        self.x_outer_vertices = array("H", empty_list)
        self.y_outer_vertices = array("H", empty_list)
        self.x_inner_vertices = array("H", empty_list)
        self.y_inner_vertices = array("H", empty_list)

        x_center = self.x_center
        y_center = self.y_center
        outer_r = self.outer_poly_r
        inner_r = self.inner_poly_r

        for i in range(RING_SEGMENTS):
            angle = math.radians(SEGMENT_ANGLE * i - 90)
            cos = math.cos(angle)
            sin = math.sin(angle)

            self.x_outer_vertices[i] = int(x_center + outer_r * cos)
            self.y_outer_vertices[i] = int(y_center + outer_r * sin)
            self.x_inner_vertices[i] = int(x_center + inner_r * cos)
            self.y_inner_vertices[i] = int(y_center + inner_r * sin)

        # Text geometry
        self.font = font
        pico_graphics.set_font(font)
        self.text_scale = text_scale
        self.text_height = font_height * text_scale
        self.line_spacing = self.text_height // 2

        self.max_text_center_width = int(math.sqrt(self.inner_circle_r**2 - (self.text_height // 2) ** 2) * 2)
        self.max_text_center_width -= self.max_text_center_width % 2
        self.text_center_rect_x = (self.width - self.max_text_center_width) // 2
        self.text_center_y = (self.height - self.text_height) // 2

        self.max_text_above_center_width = int(
            math.sqrt(self.inner_circle_r**2 - (self.text_height // 2 + self.text_height * 2) ** 2) * 2
        )
        self.max_text_above_center_width -= self.max_text_above_center_width % 2
        self.text_above_center_rect_x = (self.width - self.max_text_above_center_width) // 2
        self.text_above_center_y = self.text_center_y - self.text_height - self.line_spacing

        self.text_below_center_y = self.text_center_y + self.text_height + self.line_spacing


class Renderer:
    def __init__(self, geometry: Geometry, colors: Colors) -> None:
        self._geom = geometry
        self._gfx = geometry.graphics
        self._colors = colors

        self._segments_cleared = 0
        self._last_text_center = ""
        self._last_text_above_center = ""
        self._last_text_below_center = ""

        # Pre-allocated buffer for single-segment clears (hot path)
        self._seg_buf = [(0, 0), (0, 0), (0, 0), (0, 0)]

    def reset(self) -> None:
        self._segments_cleared: int = 0
        self._last_text_center: str = ""
        self._last_text_above_center: str = ""
        self._last_text_below_center: str = ""

        self._gfx.set_font(self._geom.font)
        self._gfx.set_pen(self._colors.background)
        self._gfx.clear()

        self._gfx.set_pen(self._colors.ring)
        self._gfx.circle(self._geom.x_center, self._geom.y_center, self._geom.outer_circle_r)
        self._gfx.set_pen(self._colors.background)
        self._gfx.circle(self._geom.x_center, self._geom.y_center, self._geom.inner_circle_r)

    @property
    def segments_cleared(self) -> int:
        return self._segments_cleared

    def ring_clear_segments(self, total_count: int) -> None:
        if total_count <= self._segments_cleared:
            return

        self._gfx.set_pen(self._colors.background)
        if total_count >= RING_SEGMENTS:
            self._segments_cleared = RING_SEGMENTS
            self._gfx.circle(self._geom.x_center, self._geom.y_center, self._geom.outer_circle_r)
            self._gfx.set_pen(self._colors.primary_text)
            text_center_backup = self._last_text_center
            text_above_center_backup = self._last_text_above_center
            text_below_center_backup = self._last_text_below_center
            self._last_text_center = ""
            self._last_text_above_center = ""
            self._last_text_below_center = ""
            self.text_write(TEXT_CENTER, text_center_backup)
            self.text_write(TEXT_ABOVE_CENTER, text_above_center_backup)
            self.text_write(TEXT_BELOW_CENTER, text_below_center_backup)
            return

        count = total_count - self._segments_cleared

        # Fast path: single segment (common per-tick case) — no allocation
        if count == 1:
            idx = self._segments_cleared
            nxt = idx + 1
            geom = self._geom
            buf = self._seg_buf
            buf[0] = (geom.x_outer_vertices[idx], geom.y_outer_vertices[idx])
            buf[1] = (geom.x_outer_vertices[nxt], geom.y_outer_vertices[nxt])
            buf[2] = (geom.x_inner_vertices[nxt], geom.y_inner_vertices[nxt])
            buf[3] = (geom.x_inner_vertices[idx], geom.y_inner_vertices[idx])
            self._gfx.polygon(buf)
            self._segments_cleared += 1
            return

        # Multi-segment path (rare — initialize with progress)
        total_points = (count + 1) * 2
        points = [(0, 0)] * total_points

        for i in range(count + 1):
            idx = self._segments_cleared + i
            points[i] = (self._geom.x_outer_vertices[idx], self._geom.y_outer_vertices[idx])
            points[total_points - 1 - i] = (self._geom.x_inner_vertices[idx], self._geom.y_inner_vertices[idx])

        self._gfx.polygon(points)

        self._segments_cleared += count

    def text_clear(self, position: int) -> None:
        if position == TEXT_CENTER:
            if not self._last_text_center:
                return
            text_x = self._geom.text_center_rect_x
            text_y = self._geom.text_center_y
            text_width = self._geom.max_text_center_width
            self._last_text_center = ""
        elif position == TEXT_ABOVE_CENTER:
            if not self._last_text_above_center:
                return
            text_x = self._geom.text_above_center_rect_x
            text_y = self._geom.text_above_center_y
            text_width = self._geom.max_text_above_center_width
            self._last_text_above_center = ""
        elif position == TEXT_BELOW_CENTER:
            if not self._last_text_below_center:
                return
            text_x = self._geom.text_above_center_rect_x
            text_y = self._geom.text_below_center_y
            text_width = self._geom.max_text_above_center_width
            self._last_text_below_center = ""
        else:
            return

        self._gfx.set_pen(self._colors.background)
        self._gfx.rectangle(text_x, text_y, text_width, self._geom.text_height)

    def text_write(self, position: int, text: str) -> None:
        if position == TEXT_CENTER:
            current_text = self._last_text_center
        elif position == TEXT_ABOVE_CENTER:
            current_text = self._last_text_above_center
        elif position == TEXT_BELOW_CENTER:
            current_text = self._last_text_below_center
        else:
            return

        if text == current_text:
            return

        self.text_clear(position)

        if not text:
            return

        text_width = self._gfx.measure_text(text, scale=self._geom.text_scale)
        if position == TEXT_CENTER:
            text_x = (self._geom.width - text_width) // 2
            text_y = self._geom.text_center_y
            self._last_text_center = text
            self._gfx.set_pen(self._colors.primary_text)
        elif position == TEXT_ABOVE_CENTER:
            text_x = (self._geom.width - text_width) // 2
            text_y = self._geom.text_above_center_y
            self._last_text_above_center = text
            self._gfx.set_pen(self._colors.secondary_text)
        elif position == TEXT_BELOW_CENTER:
            text_x = (self._geom.width - text_width) // 2
            text_y = self._geom.text_below_center_y
            self._last_text_below_center = text
            self._gfx.set_pen(self._colors.secondary_text)
        else:
            return

        self._gfx.text(text, text_x, text_y, scale=self._geom.text_scale)

    def update(self) -> None:
        self._gfx.update()
