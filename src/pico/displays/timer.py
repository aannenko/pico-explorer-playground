import math
import micropython
import time

from array import array
from machine import Timer
from picographics import PicoGraphics  # type: ignore

RING_SEGMENTS = const(120)
SEGMENT_ANGLE = const(360 // RING_SEGMENTS)

# Coordinates in the form of X,Y; 5,5 is center, 0,0 is top-left, 9,9 is bottom-right
TEXT_CENTER = const(55)  # 5,5
TEXT_ABOVE_CENTER = const(54)  # 5,4
TEXT_BELOW_CENTER = const(56)  # 5,6

_RING_THICKNESS_DIVISOR = const(30)
_RING_OUTER_MARGIN = const(2)
_MAX_PRINTED_SEC = const(999 * 3600 + 59 * 60 + 59)  # 999:59:59


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
        pico_graphics.set_font(font)
        self.text_scale = text_scale
        self.text_height = font_height * text_scale
        self.line_spacing = self.text_height // 2

        self.max_text_center_width = int(math.sqrt(self.inner_circle_r**2 - (self.text_height // 2)**2) * 2)
        self.max_text_center_width -= self.max_text_center_width % 2
        self.text_center_rect_x = (self.width - self.max_text_center_width) // 2
        self.text_center_y = (self.height - self.text_height) // 2

        self.max_text_above_center_width = int(math.sqrt(self.inner_circle_r**2 - (self.text_height // 2 + self.text_height * 2)**2) * 2)
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

    def reset(self) -> None:
        self._segments_cleared = 0
        self._last_text_center = ""
        self._last_text_above_center = ""
        self._last_text_below_center = ""

        self._gfx.set_pen(self._colors.background)
        self._gfx.clear()

        self._gfx.set_pen(self._colors.ring)
        self._gfx.circle(self._geom.x_center, self._geom.y_center, self._geom.outer_circle_r)
        self._gfx.set_pen(self._colors.background)
        self._gfx.circle(self._geom.x_center, self._geom.y_center, self._geom.inner_circle_r)

    def ring_clear_segments(self, count: int) -> None:
        if count <= self._segments_cleared:
            return

        self._gfx.set_pen(self._colors.background)
        if count >= RING_SEGMENTS:
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

        count = count - self._segments_cleared
        total_points = (count + 1) * 2
        points = [(0, 0)] * total_points

        for i in range(count + 1):
            idx = self._segments_cleared + i
            points[i] = (self._geom.x_outer_vertices[idx], self._geom.y_outer_vertices[idx])
            points[total_points - 1 - i] = (self._geom.x_inner_vertices[idx], self._geom.y_inner_vertices[idx])

        self._gfx.polygon(points)

        self._segments_cleared += count

    def ring_clear_next_segment(self) -> None:
        if self._segments_cleared >= RING_SEGMENTS:
            return

        from_segment = self._segments_cleared
        to_segment = (from_segment + 1) % RING_SEGMENTS  # wrap around to 0 after the last segment

        self._gfx.set_pen(self._colors.background)
        self._gfx.polygon([
            (self._geom.x_outer_vertices[from_segment], self._geom.y_outer_vertices[from_segment]),
            (self._geom.x_outer_vertices[to_segment], self._geom.y_outer_vertices[to_segment]),
            (self._geom.x_inner_vertices[to_segment], self._geom.y_inner_vertices[to_segment]),
            (self._geom.x_inner_vertices[from_segment], self._geom.y_inner_vertices[from_segment])
        ])

        self._segments_cleared += 1

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


class Display:
    def __init__(
        self,
        renderer: Renderer,
        get_time=time.time,
        schedule=micropython.schedule,
        timer_factory=Timer,
    ) -> None:
        self._renderer = renderer

        # dependencies for easier testing
        self._get_time = get_time
        self._schedule = schedule
        self._timer_factory = timer_factory

        # method references for use with micropython.schedule
        self._update_each_second_ref = self._update_each_second
        self._schedule_update_each_second_ref = self._schedule_update_each_second
        self._clear_ring_segment_ref = self._clear_ring_segment
        self._schedule_clear_ring_segment_ref = self._schedule_clear_ring_segment
        self._chain_event_ref = self._chain_event
        self._schedule_chain_event_ref = self._schedule_chain_event

        # deinitialize() will reset these
        self._seconds_timer = self._timer_factory(-1)
        self._ring_timer = self._timer_factory(-1)
        self._event_timer = self._timer_factory(-1)
        self._events = iter(())
        self._event_start_timestamp = 0
        self._event_end_timestamp = 0
        self._active = False

    def _update_each_second(self, _: int) -> None:
        if not self._event_start_timestamp:
            return

        now = self._get_time()

        elapsed_sec = now - self._event_start_timestamp
        elap_hours = elapsed_sec // 3600
        if 0 <= elapsed_sec <= _MAX_PRINTED_SEC:
            elap_minutes = elapsed_sec // 60 % 60
            elap_seconds = elapsed_sec % 60
            self._renderer.text_write(
                TEXT_ABOVE_CENTER,
                f"{elap_hours:02}:{elap_minutes:02}:{elap_seconds:02}",
            )
        else:
            self._renderer.text_write(TEXT_ABOVE_CENTER, f"{elap_hours} h")

        remaining_sec = self._event_end_timestamp - now
        rem_hours = remaining_sec // 3600
        if 0 <= remaining_sec <= _MAX_PRINTED_SEC:
            rem_minutes = remaining_sec // 60 % 60
            rem_seconds = remaining_sec % 60
            self._renderer.text_write(
                TEXT_BELOW_CENTER,
                f"-{rem_hours:02}:{rem_minutes:02}:{rem_seconds:02}",
            )
        else:
            self._renderer.text_write(TEXT_BELOW_CENTER, f"-{rem_hours} h")

        self._renderer.update()

    def _schedule_update_each_second(self, _: Timer) -> None:
        self._schedule(self._update_each_second_ref, 0)

    def _clear_ring_segment(self, _: int) -> None:
        self._renderer.ring_clear_next_segment()
        self._renderer.update()

    def _schedule_clear_ring_segment(self, _: Timer) -> None:
        self._schedule(self._clear_ring_segment_ref, 0)

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

        # calculate elapsed time of the current event (clamped)
        elapsed_sec = now - event.start_timestamp
        if elapsed_sec < 0:
            elapsed_sec = 0
        elif elapsed_sec > event.duration_sec:
            elapsed_sec = event.duration_sec

        # draw event state
        self._renderer.reset()
        self._renderer.ring_clear_segments(RING_SEGMENTS * elapsed_sec // event.duration_sec)
        self._renderer.text_write(TEXT_CENTER, event.name)
        self._update_each_second(0)

        # schedule: ring ticking + next event start
        remaining_sec = event.duration_sec - elapsed_sec
        if remaining_sec > 0:
            self._ring_timer.init(
                mode=Timer.PERIODIC,
                period=event.duration_sec * 1000 // RING_SEGMENTS,
                callback=self._schedule_clear_ring_segment_ref,
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
            callback=self._schedule_update_each_second_ref,
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
