import math
import micropython
import time

from array import array
from machine import Timer
from picographics import PicoGraphics


class Colors:
    def __init__(
        self,
        background: int,
        ring_color: int,
        primary_text_color: int,
        secondary_text_color: int,
    ) -> None:
        self.background = background
        self.ring_color = ring_color
        self.primary_text_color = primary_text_color
        self.secondary_text_color = secondary_text_color


class Geometry:
    RING_SEGMENTS = const(120)
    SEGMENT_ANGLE = const(360 // RING_SEGMENTS)
    FONT = "bitmap6"  # bitmap6 by default when we don't set the font
    FONT_HEIGHT = const(6)

    def __init__(self, pico_graphics: PicoGraphics) -> None:
        self.painter = pico_graphics

        # Display geometry
        self.width, self.height = pico_graphics.get_bounds()
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
        pico_graphics.set_font(self.FONT)
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


class Graphics:
    TEXT_CENTER = const(0)
    TEXT_ABOVE_CENTER = const(1)
    TEXT_BELOW_CENTER = const(2)

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

        self._g.painter.set_pen(self._c.ring_color)
        self._g.painter.circle(self._g.x_center, self._g.y_center, self._g.outer_circle_r)
        self._g.painter.set_pen(self._c.background)
        self._g.painter.circle(self._g.x_center, self._g.y_center, self._g.inner_circle_r)

    def ring_clear_segments(self, count: int) -> None:
        if count <= self._segments_cleared:
            return

        self._g.painter.set_pen(self._c.background)
        if count >= self._g.RING_SEGMENTS:
            self._segments_cleared = self._g.RING_SEGMENTS
            self._g.painter.circle(self._g.x_center, self._g.y_center, self._g.outer_circle_r)
            self._g.painter.set_pen(self._c.primary_text_color)
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

        self._g.painter.polygon(points)

        self._segments_cleared += count

    def ring_clear_next_segment(self) -> None:
        if self._segments_cleared >= self._g.RING_SEGMENTS:
            return

        from_segment = self._segments_cleared
        to_segment = (from_segment + 1) % self._g.RING_SEGMENTS  # wrap around to 0 after the last segment

        self._g.painter.set_pen(self._c.background)
        self._g.painter.polygon([
            (self._g.x_outer_vertices[from_segment], self._g.y_outer_vertices[from_segment]),
            (self._g.x_outer_vertices[to_segment], self._g.y_outer_vertices[to_segment]),
            (self._g.x_inner_vertices[to_segment], self._g.y_inner_vertices[to_segment]),
            (self._g.x_inner_vertices[from_segment], self._g.y_inner_vertices[from_segment])
        ])

        self._segments_cleared += 1

    def text_clear(self, position: int) -> None:
        if (
            position == self.TEXT_CENTER and not self._last_text_center
            or position == self.TEXT_ABOVE_CENTER and not self._last_text_above_center
            or position == self.TEXT_BELOW_CENTER and not self._last_text_below_center
        ):
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

        self._g.painter.set_pen(self._c.background)
        self._g.painter.rectangle(text_x, text_y, text_width, self._g.text_height)

    def text_write(self, position: int, text: str) -> None:
        if position == self.TEXT_CENTER:
            current_text = self._last_text_center
        elif position == self.TEXT_ABOVE_CENTER:
            current_text = self._last_text_above_center
        elif position == self.TEXT_BELOW_CENTER:
            current_text = self._last_text_below_center
        else:
            return

        if text == current_text:
            return

        self.text_clear(position)

        if not text:
            return

        text_width = self._g.painter.measure_text(text, scale=self._g.text_scale)
        text_x: int
        text_y: int
        if position == self.TEXT_CENTER:
            text_x = (self._g.width - text_width) // 2
            text_y = self._g.text_center_y
            self._last_text_center = text
            self._g.painter.set_pen(self._c.primary_text_color)
        elif position == self.TEXT_ABOVE_CENTER:
            text_x = (self._g.width - text_width) // 2
            text_y = self._g.text_above_center_y
            self._last_text_above_center = text
            self._g.painter.set_pen(self._c.secondary_text_color)
        elif position == self.TEXT_BELOW_CENTER:
            text_x = (self._g.width - text_width) // 2
            text_y = self._g.text_below_center_y
            self._last_text_below_center = text
            self._g.painter.set_pen(self._c.secondary_text_color)
        else:
            return

        self._g.painter.text(text, text_x, text_y, scale=self._g.text_scale)

    def update(self) -> None:
        self._g.painter.update()


class Display:
    def __init__(
        self,
        graphics: Graphics,
        timezone_offset_hours: int,
        get_time=time.time,
        gmtime=time.gmtime,
        schedule=micropython.schedule,
        timer_factory=Timer,
    ) -> None:
        self._graphics = graphics
        self._timezone_offset_hours = timezone_offset_hours

        # method references for use with micropython.schedule
        self._update_ring_ref = self._update_ring
        self._schedule_update_ring_ref = self._schedule_update_ring
        self._update_timers_ref = self._update_timers
        self._schedule_update_timers_ref = self._schedule_update_timers
        self._chain_event_ref = self._chain_event
        self._schedule_chain_event_ref = self._schedule_chain_event

        # dependencies for easier testing
        self._schedule = schedule
        self._get_time = get_time
        self._gmtime = gmtime
        self._timer_factory = timer_factory

        # deinitialize() will reset these
        self._seconds_timer = self._timer_factory(-1)
        self._ring_timer = self._timer_factory(-1)
        self._event_timer = self._timer_factory(-1)
        self._events = iter(())
        self._event_start_timestamp = 0
        self._event_end_timestamp = 0
        self._active = False

    def _update_ring(self, _: int) -> None:
        self._graphics.ring_clear_next_segment()
        self._graphics.update()

    def _schedule_update_ring(self, _: Timer) -> None:
        self._schedule(self._update_ring_ref, 0)

    def _update_timers(self, _: int) -> None:
        if not self._event_start_timestamp:
            return

        now = self._get_time()
        MAX_PRINTED_SEC = const(999 * 3600 + 59 * 60 + 59)  # 999:59:59

        elapsed_sec = now - self._event_start_timestamp
        if 0 <= elapsed_sec <= MAX_PRINTED_SEC:
            elap_hours = elapsed_sec // 3600
            elap_minutes = elapsed_sec // 60 % 60
            elap_seconds = elapsed_sec % 60
            self._graphics.text_write(
                Graphics.TEXT_ABOVE_CENTER,
                f"{elap_hours:02}:{elap_minutes:02}:{elap_seconds:02}",
            )

        remaining_sec = self._event_end_timestamp - now
        if 0 <= remaining_sec <= MAX_PRINTED_SEC:
            rem_hours = remaining_sec // 3600
            rem_minutes = remaining_sec // 60 % 60
            rem_seconds = remaining_sec % 60
            self._graphics.text_write(
                Graphics.TEXT_BELOW_CENTER,
                f"-{rem_hours:02}:{rem_minutes:02}:{rem_seconds:02}",
            )

        self._graphics.update()

    def _schedule_update_timers(self, _: Timer) -> None:
        self._schedule(self._update_timers_ref, 0)

    def _chain_event(self, _: int) -> None:
        # stop any previous periodic updates
        try:
            self._event_timer.deinit()
            self._ring_timer.deinit()
        except Exception:
            pass

        now = self._get_time()

        # get next event which is not yet expired
        try:
            event = next(self._events)
            while (
                event.duration_sec <= 0
                or event.start_timestamp + event.duration_sec <= now
            ):
                event = next(self._events)
        except StopIteration:
            return  # iterator ended; nothing more to do

        if event.start_timestamp > now:
            # event is in the future; schedule next check at its start
            self._event_timer.init(
                mode=Timer.ONE_SHOT,
                period=(event.start_timestamp - now) * 1000,
                callback=self._schedule_chain_event_ref,
            )
            return

        self._event_start_timestamp = event.start_timestamp
        self._event_end_timestamp = event.start_timestamp + event.duration_sec

        # compute elapsed within current event (clamped)
        elapsed_sec = now - event.start_timestamp
        if elapsed_sec < 0:
            elapsed_sec = 0
        elif elapsed_sec > event.duration_sec:
            elapsed_sec = event.duration_sec

        # draw event state
        self._graphics.reset()
        self._graphics.ring_clear_segments(
            Geometry.RING_SEGMENTS * elapsed_sec // event.duration_sec
        )
        self._graphics.text_write(Graphics.TEXT_CENTER, event.name)
        self._graphics.update()

        # schedule: ring ticking + next event start
        remaining_sec = event.duration_sec - elapsed_sec
        if remaining_sec > 0:
            self._ring_timer.init(
                mode=Timer.PERIODIC,
                period=event.duration_sec * 1000 // Geometry.RING_SEGMENTS,
                callback=self._schedule_update_ring_ref,
            )
            self._event_timer.init(
                mode=Timer.ONE_SHOT,
                period=remaining_sec * 1000,
                callback=self._schedule_chain_event_ref,
            )
        else:
            # already past the end of the event; schedule next event "soon"
            self._event_timer.init(
                mode=Timer.ONE_SHOT,
                period=10,
                callback=self._schedule_chain_event_ref,
            )

    def _schedule_chain_event(self, _: Timer) -> None:
        self._schedule(self._chain_event_ref, 0)

    def initialize(self, events) -> None:
        if self._active:
            return
        self._active = True
        self._events = events
        self._chain_event(0)
        self._seconds_timer.init(
            mode=Timer.PERIODIC,
            period=1000,
            callback=self._schedule_update_timers_ref,
        )

    def deinitialize(self) -> None:
        if not self._active:
            return
        self._active = False
        self._seconds_timer.deinit()
        self._event_timer.deinit()
        self._ring_timer.deinit()
        self._events = iter(())
        self._event_start_timestamp = 0
        self._event_end_timestamp = 0
