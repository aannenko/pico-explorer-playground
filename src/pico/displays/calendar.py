import time

from micropython import const
from picographics import PicoGraphics  # type: ignore

from displays.base import Display as _Display
from displays.palette import BLACK, DARK_GRAY, GRAY, LABEL_FOR_SLOT, WHITE
from displays.shared.header import (
    WEEKDAY_NAMES,
    WIDEST_TIME_TEXT,
    format_header_time,
    header_date_x,
    header_fits,
    widest_name,
)
from scheduling.event import Event
from scheduling.event_window import EventWindow

HORIZON_SEC = const(7 * 24 * 3600)

_SEC_PER_MIN = const(60)
_SEC_PER_DAY = const(24 * 3600)
_MIN_PER_HOUR = const(60)
_HOURS_PER_DAY = const(24)
_MS_PER_SEC = const(1000)

_BODY_MARGIN_PX = const(3)
# bitmap8's bottom cell row holds only descenders, which labels never use.
_DESCENDER_ROWS = const(1)
# Above and below a field's text.
_FIELD_PAD_PX = const(4)
# From a field's edges to its texts, and between them.
_TEXT_INSET_PX = const(6)
_BAR_PX = const(4)
_SLOT_GAP_PX = const(5)
_RAIL_PX = const(2)
_DOT_R_PX = const(5)
# Either side of a dot: to the start times and to the fields.
_DOT_GAP_PX = const(4)
_NO_WINDOW = const(-1)


def _format_duration(sec: int) -> str:
    """Return ``sec``, rounded up to whole minutes, as minutes under an hour (``"48m"``), hours and minutes under a
    day (``"9h48"``), else days and hours (``"2d08"``); zero or less is ``"0m"``."""
    # Rounded up: a redraw lands just after its minute starts, so a whole-minute time is that many minutes away on
    # the header's clock.
    minutes = (sec + _SEC_PER_MIN - 1) // _SEC_PER_MIN if sec > 0 else 0
    if minutes < _MIN_PER_HOUR:
        return str(minutes) + "m"
    hours = minutes // _MIN_PER_HOUR
    if hours < _HOURS_PER_DAY:
        return f"{hours}h{minutes % _MIN_PER_HOUR:02}"
    return f"{hours // _HOURS_PER_DAY}d{hours % _HOURS_PER_DAY:02}"


def _fitting_prefix(gfx: PicoGraphics, text: str, room_px: int, text_scale: int) -> str:
    """Return the longest prefix of ``text``, in whole characters, that fits ``room_px``; it may be empty."""
    # Slices only when text doesn't fit, as each slice is a new str.
    length = len(text)
    while length and gfx.measure_text(text, scale=text_scale) > room_px:
        length -= 1
        text = text[:length]
    return text


class Geometry:
    """Pixel layout of the Calendar view: a header over ``slot_count`` equal slots, each a colour field with room
    for a progress bar under it, right of a rail with the start times left of it.

    Raises ``RuntimeError`` if the widest header doesn't fit the panel width or fewer than two slots fit under it.
    """

    def __init__(
        self,
        pico_graphics: PicoGraphics,
        font: str,
        font_height: int,
        header_text_scale: int,
        label_text_scale: int,
    ) -> None:
        self.pico_graphics = pico_graphics
        self.width, self.height = pico_graphics.get_bounds()
        self.font = font

        if not header_fits(pico_graphics, font, header_text_scale, self.width):
            raise RuntimeError("calendar geometry: no room for header (font/scale too large)")
        self.header_text_scale = header_text_scale
        self.date_x = header_date_x(pico_graphics, font, header_text_scale)
        self.label_text_scale = label_text_scale

        # A start time, or the weekday of an event in progress since before today, ends at time_right.
        self.time_right = max(
            pico_graphics.measure_text(WIDEST_TIME_TEXT, scale=label_text_scale),
            pico_graphics.measure_text(widest_name(pico_graphics, WEEKDAY_NAMES, label_text_scale),
                                       scale=label_text_scale),
        )
        self.rail_x = self.time_right + _DOT_GAP_PX + _DOT_R_PX
        self.field_x = self.rail_x + _DOT_R_PX + _DOT_GAP_PX

        self.field_height = (font_height - _DESCENDER_ROWS) * label_text_scale + 2 * _FIELD_PAD_PX
        self.slot_pitch = self.field_height + _BAR_PX + _SLOT_GAP_PX
        self.body_top = font_height * header_text_scale + _BODY_MARGIN_PX
        # A day header takes a slot, and the event after it another.
        self.slot_count = (self.height - self.body_top + _SLOT_GAP_PX) // self.slot_pitch
        if self.slot_count < 2:
            raise RuntimeError("calendar geometry: no room for two slots (font/scale too large)")


class Display(_Display):
    """Calendar view: an agenda of every window's events in start order, from those in progress to those starting
    within ``HORIZON_SEC``, redrawn as each minute starts.

    Each event fills a slot: those in progress come first, each with a progress bar, and the first event of each
    later day follows a day header in a slot of its own.  Events beyond the last slot aren't shown, and events
    starting together keep their windows' order.  Labels are drawn as given, cut to fit.

    ``get_local_time`` must return local epoch seconds, and ``real_remaining_sec(local_epoch)`` the real seconds
    from now until ``local_epoch``.
    """

    def __init__(
        self,
        geometry: Geometry,
        windows: list[EventWindow],
        get_local_time,  # () -> int
        real_remaining_sec,  # (int) -> int
    ) -> None:
        self._geom = geometry
        self._gfx = geometry.pico_graphics
        self._windows = windows
        # Each window's visible events, and the index of the next one to show, for the current redraw.  An unshown
        # window holds the shared empty tuple, where an empty list would be allocated.
        self._visible: list[list[tuple[Event, int]] | tuple[()]] = [()] * len(windows)
        self._cursors = [0] * len(windows)
        self._get_local_time = get_local_time
        self._real_remaining_sec = real_remaining_sec
        self._active = False
        self._next_redraw_ms = 0

    def initialize(self) -> None:
        if self._active:
            return
        self._active = True
        self._redraw()

    def deinitialize(self) -> None:
        self._active = False
        # Unseen, a window would keep an older network snapshot alive beside the service's current one.
        for i in range(len(self._windows)):
            self._windows[i].release()
            self._visible[i] = ()

    def render(self) -> None:
        # The wall-clock read allocates, so wait for the minute to change on the alloc-free ticks.
        if time.ticks_diff(time.ticks_ms(), self._next_redraw_ms) >= 0:
            self._redraw()

    def _redraw(self) -> None:
        now = self._get_local_time()
        # Set before drawing, so a redraw that raises is retried at the next minute, not on every render.
        self._next_redraw_ms = time.ticks_add(time.ticks_ms(), (_SEC_PER_MIN - now % _SEC_PER_MIN) * _MS_PER_SEC)
        window_end = now + HORIZON_SEC
        windows = self._windows
        for i in range(len(windows)):
            self._visible[i] = windows[i].get_visible(now, window_end)
            self._cursors[i] = 0

        geom = self._geom
        gfx = self._gfx
        gfx.set_font(geom.font)
        gfx.set_pen(BLACK)
        gfx.clear()
        self._draw_header(now)
        gfx.set_pen(DARK_GRAY)
        gfx.rectangle(geom.rail_x - _RAIL_PX // 2, geom.body_top, _RAIL_PX, geom.height - geom.body_top)

        today = now // _SEC_PER_DAY
        day = today
        slot = 0
        while slot < geom.slot_count:
            window_index = self._next_window_index(window_end)
            if window_index == _NO_WINDOW:
                break
            event, pen = self._visible[window_index][self._cursors[window_index]]
            self._cursors[window_index] += 1
            start = event.start_timestamp
            in_progress = start <= now < start + event.wall_clock_duration_sec
            if not in_progress and start // _SEC_PER_DAY != day:
                day = start // _SEC_PER_DAY
                if slot + 1 == geom.slot_count:
                    break
                self._draw_day_header(slot, start, today)
                slot += 1
            self._draw_event(slot, event, pen, now, in_progress, today)
            slot += 1
        gfx.update()

    def _next_window_index(self, window_end: int) -> int:
        """Return the index of the window whose next event starts first, before ``window_end``, or ``_NO_WINDOW``."""
        # window_end bounds it as well: after the clock steps back, a window can hold events past it.
        best_index = _NO_WINDOW
        best_start = window_end
        visible = self._visible
        cursors = self._cursors
        for i in range(len(visible)):
            events = visible[i]
            if cursors[i] < len(events):
                start = events[cursors[i]][0].start_timestamp
                if start < best_start:
                    best_index = i
                    best_start = start
        return best_index

    def _draw_header(self, now: int) -> None:
        geom = self._geom
        gfx = self._gfx
        time_text, date_text = format_header_time(now)
        gfx.set_pen(WHITE)
        gfx.text(time_text, 0, 0, scale=geom.header_text_scale)
        gfx.set_pen(GRAY)
        gfx.text(date_text, geom.date_x, 0, scale=geom.header_text_scale)

    def _draw_day_header(self, slot: int, start: int, today: int) -> None:
        geom = self._geom
        if start // _SEC_PER_DAY == today + 1:
            text = "Tomorrow"
        else:
            text = format_header_time(start)[1]
        self._gfx.set_pen(GRAY)
        self._gfx.text(
            text, geom.field_x, geom.body_top + slot * geom.slot_pitch + _FIELD_PAD_PX, scale=geom.label_text_scale
        )

    def _draw_event(self, slot: int, event: Event, pen: int, now: int, in_progress: bool, today: int) -> None:
        """Draw ``event`` in ``slot``: its dot, field, label, time left or to go, progress bar and start time."""
        geom = self._geom
        gfx = self._gfx
        scale = geom.label_text_scale
        y = geom.body_top + slot * geom.slot_pitch
        text_y = y + _FIELD_PAD_PX
        field_width = geom.width - geom.field_x
        start = event.start_timestamp

        gfx.set_pen(pen)
        gfx.circle(geom.rail_x, y + geom.field_height // 2, _DOT_R_PX)
        gfx.rectangle(geom.field_x, y, field_width, geom.field_height)

        # Only today's events say how soon they start: a later day's header dates them.
        if in_progress:
            note = _format_duration(self._real_remaining_sec(start + event.wall_clock_duration_sec)) + " left"
        elif start // _SEC_PER_DAY == today:
            note = "in " + _format_duration(self._real_remaining_sec(start))
        else:
            note = ""
        label_x = geom.field_x + _TEXT_INSET_PX
        label_end = geom.width - _TEXT_INSET_PX
        if note:
            note_x = label_end - gfx.measure_text(note, scale=scale)
            label_end = note_x - _TEXT_INSET_PX
        gfx.set_pen(LABEL_FOR_SLOT[pen])
        gfx.text(_fitting_prefix(gfx, event.label, label_end - label_x, scale), label_x, text_y, scale=scale)
        if note:
            gfx.text(note, note_x, text_y, scale=scale)

        if in_progress:
            elapsed_px = field_width * (now - start) // event.wall_clock_duration_sec
            bar_y = y + geom.field_height
            gfx.set_pen(WHITE)
            gfx.rectangle(geom.field_x, bar_y, elapsed_px, _BAR_PX)
            gfx.set_pen(DARK_GRAY)
            gfx.rectangle(geom.field_x + elapsed_px, bar_y, field_width - elapsed_px, _BAR_PX)

        fields = time.gmtime(start)
        if in_progress and start // _SEC_PER_DAY < today:
            weekday_start = 3 * fields[6]
            time_text = WEEKDAY_NAMES[weekday_start:weekday_start + 3]
        else:
            time_text = f"{fields[3]:02}:{fields[4]:02}"
        gfx.set_pen(WHITE if in_progress else GRAY)
        gfx.text(time_text, geom.time_right - gfx.measure_text(time_text, scale=scale), text_y, scale=scale)
