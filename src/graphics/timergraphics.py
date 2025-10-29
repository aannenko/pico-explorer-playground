from graphics.colors import Colors
from graphics.geometry import Geometry


class TimerGraphics:
    TEXT_CENTER = 0
    TEXT_ABOVE_CENTER = 1
    TEXT_BELOW_CENTER = 2

    def __init__(self, geometry: Geometry, colors: Colors) -> None:
        self._g = geometry
        self._c = colors
        self._segments_cleared = 0
        self._last_text_center = ""
        self._last_text_above_center = ""
        self._last_text_below_center = ""

    def reset(self) -> None:
        self._segments_cleared = 0
        self._last_text_center = ""
        self._last_text_above_center = ""
        self._last_text_below_center = ""

        self._g.display.set_pen(self._c.ring_color)
        self._g.display.circle(self._g.x_center, self._g.y_center, self._g.outer_circle_r)
        self._g.display.set_pen(self._c.background)
        self._g.display.circle(self._g.x_center, self._g.y_center, self._g.inner_circle_r)

    def ring_clear_segments(self, count: int) -> None:
        if count <= self._segments_cleared:
            return

        self._g.display.set_pen(self._c.background)
        if count >= self._g.RING_SEGMENTS:
            self._segments_cleared = self._g.RING_SEGMENTS
            self._g.display.circle(self._g.x_center, self._g.y_center, self._g.outer_circle_r)
            self._g.display.set_pen(self._c.primary_text_color)
            text_center_backup = self._last_text_center
            text_above_center_backup = self._last_text_above_center
            text_below_center_backup = self._last_text_below_center
            self._last_text_center = ""
            self._last_text_above_center = ""
            self._last_text_below_center = ""
            self.text_write(self.TEXT_CENTER, text_center_backup)
            self.text_write(self.TEXT_ABOVE_CENTER, text_above_center_backup)
            self.text_write(self.TEXT_BELOW_CENTER, text_below_center_backup)
            return

        count = count - self._segments_cleared
        total_points = (count + 1) * 2
        points = [(0, 0)] * total_points

        for i in range(count + 1):
            idx = self._segments_cleared + i
            points[i] = (self._g.x_outer_vertices[idx], self._g.y_outer_vertices[idx])
            points[total_points - 1 - i] = (self._g.x_inner_vertices[idx], self._g.y_inner_vertices[idx])

        self._g.display.polygon(points)

        self._segments_cleared += count

    def ring_clear_next_segment(self) -> None:
        if self._segments_cleared >= self._g.RING_SEGMENTS:
            return

        from_segment = self._segments_cleared
        to_segment = (from_segment + 1) % self._g.RING_SEGMENTS  # wrap around to 0 after the last segment

        self._g.display.set_pen(self._c.background)
        self._g.display.polygon([
            (self._g.x_outer_vertices[from_segment], self._g.y_outer_vertices[from_segment]),
            (self._g.x_outer_vertices[to_segment], self._g.y_outer_vertices[to_segment]),
            (self._g.x_inner_vertices[to_segment], self._g.y_inner_vertices[to_segment]),
            (self._g.x_inner_vertices[from_segment], self._g.y_inner_vertices[from_segment])
        ])

        self._segments_cleared += 1

    def text_clear(self, position: int) -> None:
        if not self._last_text_center:
            return

        text_x: int
        text_y: int
        text_width: int
        if position == self.TEXT_CENTER:
            text_x = self._g.text_center_rect_x
            text_y = self._g.text_center_y
            text_width = self._g.max_text_center_width
            self._last_text_center = ""
        elif position == self.TEXT_ABOVE_CENTER:
            text_x = self._g.text_above_center_rect_x
            text_y = self._g.text_above_center_y
            text_width = self._g.max_text_above_center_width
            self._last_text_above_center = ""
        elif position == self.TEXT_BELOW_CENTER:
            text_x = self._g.text_above_center_rect_x
            text_y = self._g.text_below_center_y
            text_width = self._g.max_text_above_center_width
            self._last_text_below_center = ""
        else:
            return

        self._g.display.set_pen(self._c.background)
        self._g.display.rectangle(text_x, text_y, text_width, self._g.text_height)

    def text_write(self, position: int, text: str) -> None:
        if text == self._last_text_center:
            return

        self.text_clear(position)

        if not text:
            return

        text_width = self._g.display.measure_text(text, scale=self._g.text_scale)
        text_x: int
        text_y: int
        if position == self.TEXT_CENTER:
            text_x = (self._g.width - text_width) // 2
            text_y = self._g.text_center_y
            self._last_text_center = text
            self._g.display.set_pen(self._c.primary_text_color)
        elif position == self.TEXT_ABOVE_CENTER:
            text_x = (self._g.width - text_width) // 2
            text_y = self._g.text_above_center_y
            self._last_text_above_center = text
            self._g.display.set_pen(self._c.secondary_text_color)
        elif position == self.TEXT_BELOW_CENTER:
            text_x = (self._g.width - text_width) // 2
            text_y = self._g.text_below_center_y
            self._last_text_below_center = text
            self._g.display.set_pen(self._c.secondary_text_color)
        else:
            return

        self._g.display.text(text, text_x, text_y, scale=self._g.text_scale)
