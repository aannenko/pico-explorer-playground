import time

from micropython import const
from picographics import PicoGraphics  # type: ignore

from displays.base import Display as _Display
from displays.palette import BLACK, DARK_GRAY, GRAY, LABEL_FOR_SLOT, RED, STREAM_COLORS, WHITE
from displays.shared import icons_p4
from displays.shared.header import (
    WEEKDAY_NAMES,
    WIDEST_TIME_TEXT,
    format_header_time,
    header_date_x,
    header_fits,
    widest_name,
)
from scheduling.event import Event
from utilities.log import log_exception

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
# Either side of a glyph: to the start times and to the fields.
_GLYPH_GAP_PX = const(8)
_BADGE_R_PX = const(7)
_BADGE_TEXT_SCALE = const(2)
_NO_STREAM = const(-1)


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
    for a progress bar under it, right of a rail of stream glyphs with the start times left of it.  The header keeps
    room after the widest date for the badge that marks a failed source.

    ``glyph_width`` is the widest glyph's width in its own pixels; glyphs are drawn at ``label_text_scale``.  Raises
    ``RuntimeError`` if the widest header and the badge don't fit the panel width or fewer than two slots fit under
    it.
    """

    def __init__(
        self,
        pico_graphics: PicoGraphics,
        font: str,
        font_height: int,
        header_text_scale: int,
        label_text_scale: int,
        glyph_width: int,
    ) -> None:
        self.pico_graphics = pico_graphics
        self.width, self.height = pico_graphics.get_bounds()
        self.font = font

        # The badge sits after the date, as far from it as the header's characters are from one another.
        badge_room = 2 * _BADGE_R_PX + 1 + header_text_scale
        if not header_fits(pico_graphics, font, header_text_scale, self.width - badge_room):
            raise RuntimeError("calendar geometry: no room for header (font/scale too large)")
        self.header_text_scale = header_text_scale
        self.date_x = header_date_x(pico_graphics, font, header_text_scale)
        self.label_text_scale = label_text_scale
        self.badge_x = self.width - _BADGE_R_PX - 1
        self.badge_y = ((font_height - _DESCENDER_ROWS) * header_text_scale - 1) // 2
        self.badge_text_x = self.badge_x - pico_graphics.measure_text("!", scale=_BADGE_TEXT_SCALE) // 2
        self.badge_text_y = self.badge_y - (font_height - _DESCENDER_ROWS) * _BADGE_TEXT_SCALE // 2

        # A start time, or the weekday of an event in progress since before today, ends at time_right.
        self.time_right = max(
            pico_graphics.measure_text(WIDEST_TIME_TEXT, scale=label_text_scale),
            pico_graphics.measure_text(widest_name(pico_graphics, WEEKDAY_NAMES, label_text_scale),
                                       scale=label_text_scale),
        )
        glyph_cell_width = glyph_width * label_text_scale
        self.rail_x = self.time_right + _GLYPH_GAP_PX + glyph_cell_width // 2
        self.field_x = self.time_right + _GLYPH_GAP_PX + glyph_cell_width + _GLYPH_GAP_PX

        self.field_height = (font_height - _DESCENDER_ROWS) * label_text_scale + 2 * _FIELD_PAD_PX
        self.slot_pitch = self.field_height + _BAR_PX + _SLOT_GAP_PX
        self.body_top = font_height * header_text_scale + _BODY_MARGIN_PX
        # A day header takes a slot, and the event after it another.
        self.slot_count = (self.height - self.body_top + _SLOT_GAP_PX) // self.slot_pitch
        if self.slot_count < 2:
            raise RuntimeError("calendar geometry: no room for two slots (font/scale too large)")


class Display(_Display):
    """Calendar view: an agenda of every stream's events in start order, from those in progress to those starting
    within ``HORIZON_SEC``, redrawn as each minute starts.

    Each event fills a slot: those in progress come first, each with a progress bar, and the first event of each
    later day follows a day header in a slot of its own.  Events beyond the last slot aren't shown, and events
    starting together keep their streams' order.  Labels are drawn as given, cut to fit, on a field of
    ``STREAM_COLORS[color_index]``, or of its last colour for an index past its end.

    Each of ``streams`` is a ``(glyph, getter)`` pair.  The glyph, an icon as ``icons_p4.draw_icon`` takes it, no
    wider than the geometry's ``glyph_width`` nor taller than a field, marks each of the stream's events on the rail,
    in the event's colour.
    The getter ``(now_utc) -> list[Event]`` returns the stream's events in start order; they may include events
    already over or starting after the horizon.  The calendar reads each list only while drawing and never changes
    it.  A getter that raises is logged and left out of that redraw, which draws the other streams under a red date
    with a badge after it; the same mark shows over every stream's events while ``get_refresh_failed`` says a
    source's latest refresh failed.  ``get_utc_time`` returns UTC epoch seconds, and ``to_local`` converts them to
    the local epoch the header, start times and days are drawn in.
    """

    def __init__(
        self,
        geometry: Geometry,
        streams: list,  # list[tuple[tuple[int, int, bytes], (int) -> list[Event]]]
        get_utc_time,  # () -> int
        to_local,  # (int) -> int
        get_refresh_failed,  # () -> bool
    ) -> None:
        self._geom = geometry
        self._gfx = geometry.pico_graphics
        self._streams = streams
        # Each stream's events, and the index of the next one to show, during a redraw.  Otherwise each holds the
        # shared empty tuple, so no snapshot stays pinned, and no empty list is allocated.
        self._visible: list[list[Event] | tuple[()]] = [()] * len(streams)
        self._cursors = [0] * len(streams)
        self._get_utc_time = get_utc_time
        self._to_local = to_local
        self._get_refresh_failed = get_refresh_failed
        self._active = False
        self._next_redraw_ms = 0

    def initialize(self) -> None:
        if self._active:
            return
        self._active = True
        self._redraw()

    def deinitialize(self) -> None:
        self._active = False

    def render(self) -> None:
        # The wall-clock read allocates, so wait for the minute to change on the alloc-free ticks.
        if time.ticks_diff(time.ticks_ms(), self._next_redraw_ms) >= 0:
            self._redraw()

    def _redraw(self) -> None:
        # Retried a minute on if anything below raises, the time reads included, rather than on every render.
        self._next_redraw_ms = time.ticks_add(time.ticks_ms(), _SEC_PER_MIN * _MS_PER_SEC)
        now_utc = self._get_utc_time()
        now_local = self._to_local(now_utc)
        self._next_redraw_ms = time.ticks_add(
            time.ticks_ms(), (_SEC_PER_MIN - now_local % _SEC_PER_MIN) * _MS_PER_SEC
        )
        try:
            self._draw(now_utc, now_local)
        finally:
            for i in range(len(self._visible)):
                self._visible[i] = ()

    def _draw(self, now_utc: int, now_local: int) -> None:
        window_end = now_utc + HORIZON_SEC
        streams = self._streams
        source_failed = self._get_refresh_failed()
        for i in range(len(streams)):
            self._cursors[i] = 0
            try:
                self._visible[i] = streams[i][1](now_utc)
                self._skip_over(i, now_utc)
            except Exception as exc:
                self._visible[i] = ()
                source_failed = True
                log_exception("[calendar] stream err:", exc)

        geom = self._geom
        gfx = self._gfx
        gfx.set_font(geom.font)
        gfx.set_pen(BLACK)
        gfx.clear()
        self._draw_header(now_local, source_failed)
        gfx.set_pen(DARK_GRAY)
        gfx.rectangle(geom.rail_x - _RAIL_PX // 2, geom.body_top, _RAIL_PX, geom.height - geom.body_top)

        today = now_local // _SEC_PER_DAY
        day = today
        slot = 0
        while slot < geom.slot_count:
            stream_index = self._next_stream_index(window_end)
            if stream_index == _NO_STREAM:
                break
            event = self._visible[stream_index][self._cursors[stream_index]]
            self._cursors[stream_index] += 1
            self._skip_over(stream_index, now_utc)
            start = event.start_utc
            start_local = self._to_local(start)
            in_progress = start <= now_utc < start + event.duration_sec
            if not in_progress and start_local // _SEC_PER_DAY != day:
                day = start_local // _SEC_PER_DAY
                if slot + 1 == geom.slot_count:
                    break
                self._draw_day_header(slot, start_local, today)
                slot += 1
            self._draw_event(slot, event, self._streams[stream_index][0], now_utc, start_local, in_progress, today)
            slot += 1
        gfx.update()

    def _skip_over(self, stream_index: int, now_utc: int) -> None:
        """Move stream ``stream_index``'s cursor past the events over by ``now_utc``."""
        # Checked once per cursor move: each check allocates the event's end, an epoch past the small-int range.
        events = self._visible[stream_index]
        cursor = self._cursors[stream_index]
        while cursor < len(events) and _is_over(events[cursor], now_utc):
            cursor += 1
        self._cursors[stream_index] = cursor

    def _next_stream_index(self, window_end: int) -> int:
        """Return the index of the stream whose next event starts first, before ``window_end``, or ``_NO_STREAM``."""
        best_index = _NO_STREAM
        best_start = window_end
        visible = self._visible
        cursors = self._cursors
        for i in range(len(visible)):
            events = visible[i]
            if cursors[i] < len(events):
                start = events[cursors[i]].start_utc
                if start < best_start:
                    best_index = i
                    best_start = start
        return best_index

    def _draw_header(self, now_local: int, source_failed: bool) -> None:
        geom = self._geom
        gfx = self._gfx
        time_text, date_text = format_header_time(now_local)
        gfx.set_pen(WHITE)
        gfx.text(time_text, 0, 0, scale=geom.header_text_scale)
        gfx.set_pen(RED if source_failed else GRAY)
        gfx.text(date_text, geom.date_x, 0, scale=geom.header_text_scale)
        if source_failed:
            gfx.circle(geom.badge_x, geom.badge_y, _BADGE_R_PX)
            gfx.set_pen(LABEL_FOR_SLOT[RED])
            gfx.text("!", geom.badge_text_x, geom.badge_text_y, scale=_BADGE_TEXT_SCALE)

    def _draw_day_header(self, slot: int, start_local: int, today: int) -> None:
        geom = self._geom
        if start_local // _SEC_PER_DAY == today + 1:
            text = "Tomorrow"
        else:
            text = format_header_time(start_local)[1]
        self._gfx.set_pen(GRAY)
        self._gfx.text(
            text, geom.field_x, geom.body_top + slot * geom.slot_pitch + _FIELD_PAD_PX, scale=geom.label_text_scale
        )

    def _draw_event(
        self,
        slot: int,
        event: Event,
        glyph: tuple[int, int, bytes],
        now_utc: int,
        start_local: int,
        in_progress: bool,
        today: int,
    ) -> None:
        """Draw ``event`` in ``slot``: its stream's ``glyph``, its field, label, time left or to go, progress bar and
        start time."""
        geom = self._geom
        gfx = self._gfx
        scale = geom.label_text_scale
        y = geom.body_top + slot * geom.slot_pitch
        text_y = y + _FIELD_PAD_PX
        field_width = geom.width - geom.field_x
        start = event.start_utc
        pen = _pen(event.color_index)

        # The rail breaks beside the field, so it doesn't show through the glyph.
        gfx.set_pen(BLACK)
        gfx.rectangle(geom.rail_x - _RAIL_PX // 2, y, _RAIL_PX, geom.field_height)
        glyph_width, glyph_height, _ = glyph
        icons_p4.draw_icon(
            gfx,
            glyph,
            geom.rail_x - glyph_width * scale // 2,
            y + (geom.field_height - glyph_height * scale) // 2,
            scale,
            pen=pen,
        )
        gfx.set_pen(pen)
        gfx.rectangle(geom.field_x, y, field_width, geom.field_height)

        # Only today's events say how soon they start: a later day's header dates them.
        if in_progress:
            note = _format_duration(start + event.duration_sec - now_utc) + " left"
        elif start_local // _SEC_PER_DAY == today:
            note = "in " + _format_duration(start - now_utc)
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
            elapsed_px = field_width * (now_utc - start) // event.duration_sec
            bar_y = y + geom.field_height
            gfx.set_pen(WHITE)
            gfx.rectangle(geom.field_x, bar_y, elapsed_px, _BAR_PX)
            gfx.set_pen(DARK_GRAY)
            gfx.rectangle(geom.field_x + elapsed_px, bar_y, field_width - elapsed_px, _BAR_PX)

        fields = time.gmtime(start_local)
        if in_progress and start_local // _SEC_PER_DAY < today:
            weekday_start = 3 * fields[6]
            time_text = WEEKDAY_NAMES[weekday_start:weekday_start + 3]
        else:
            time_text = f"{fields[3]:02}:{fields[4]:02}"
        gfx.set_pen(WHITE if in_progress else GRAY)
        gfx.text(time_text, geom.time_right - gfx.measure_text(time_text, scale=scale), text_y, scale=scale)


def _pen(color_index: int) -> int:
    """Return ``STREAM_COLORS[color_index]``, or its last colour for an index past its end."""
    last_index = len(STREAM_COLORS) - 1
    return STREAM_COLORS[color_index if color_index < last_index else last_index]


def _is_over(event: Event, at: int) -> bool:
    """Return whether ``event`` has started and ended by ``at``."""
    start = event.start_utc
    return start < at and start + event.duration_sec <= at