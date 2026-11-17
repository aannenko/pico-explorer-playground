from __future__ import annotations

import time

import pytest

import displays.calendar as calendar
from displays.palette import (
    BLACK,
    BROWN,
    DARK_GRAY,
    GRAY,
    SKY,
    STREAM_BROWN,
    STREAM_COLORS,
    STREAM_RED,
    STREAM_SKY,
    STREAM_YELLOW,
    WHITE,
    YELLOW,
)
from scheduling.event import Event
from scheduling.event_window import EventWindow

from _fakes import bitmap8_width, circle_pixels

_BASE = time.mktime((2026, 6, 4, 0, 0, 0, 0, 0))  # Thursday
_DAY = 24 * 3600


def _at(hour: int, minute: int, second: int = 0, day: int = 0) -> int:
    return _BASE + day * _DAY + hour * 3600 + minute * 60 + second


_NOW = _at(9, 12)
_SLOT_COUNT = 7
_RAIL_X = 50  # the rail's left column
_FIELD_X = 60
_FIELD_HEIGHT = 22


def _slot_y(slot: int) -> int:
    return 27 + 31 * slot


class _Raster:
    """A 240×240 ``PicoGraphics`` that paints: rectangles and circles fill with the current pen, as the firmware's
    do, and each text is recorded and painted as its ink box."""

    def __init__(self) -> None:
        self.pixels = [[None] * 240 for _ in range(240)]
        self.pen = None
        self.font = None
        self.texts: list[tuple[str, int, int, int]] = []
        self.updates = 0

    def get_bounds(self) -> tuple[int, int]:
        return (240, 240)

    def set_pen(self, pen: int) -> None:
        self.pen = pen

    def set_font(self, font: str) -> None:
        self.font = font

    def clear(self) -> None:
        self.texts.clear()
        self.rectangle(0, 0, 240, 240)

    def rectangle(self, x: int, y: int, w: int, h: int) -> None:
        for row in range(max(y, 0), min(y + h, 240)):
            for col in range(max(x, 0), min(x + w, 240)):
                self.pixels[row][col] = self.pen

    def circle(self, x: int, y: int, r: int) -> None:
        for col, row in circle_pixels(x, y, r):
            if 0 <= col < 240 and 0 <= row < 240:
                self.pixels[row][col] = self.pen

    def text(self, text: str, x: int, y: int, *, scale: int) -> None:
        self.texts.append((text, x, y, self.pen))
        self.rectangle(x, y, bitmap8_width(text, scale), 7 * scale)

    def measure_text(self, text: str, scale: int) -> int:
        return bitmap8_width(text, scale)

    def update(self) -> None:
        self.updates += 1

    def at(self, x: int, y: int) -> int | None:
        return self.pixels[y][x]

    def body_texts(self) -> list[tuple[str, int, int, int]]:
        return [entry for entry in self.texts if entry[2] > 0]

    def body_strings(self) -> list[str]:
        return [text for text, *_ in self.body_texts()]


def _ev(label: str, start: int, duration_min: int = 60, color_index: int = STREAM_SKY) -> Event:
    return Event(label, start, duration_min * 60, color_index=color_index)


def _display(*streams, now: int = _NOW, real_remaining_sec=None):
    """Each stream is a list of events."""
    gfx = _Raster()
    geometry = calendar.Geometry(gfx, "bitmap8", 8, 3, 2)
    windows = [EventWindow(iter(events), stream_colors=STREAM_COLORS) for events in streams]
    clock = [now]
    display = calendar.Display(
        geometry,
        windows,
        get_local_time=lambda: clock[0],
        real_remaining_sec=real_remaining_sec or (lambda local_epoch: local_epoch - clock[0]),
    )
    return display, gfx, clock


def _drawn(*streams, **kwargs) -> _Raster:
    display, gfx, _clock = _display(*streams, **kwargs)
    display.initialize()
    return gfx


def _right_x(text: str) -> int:
    return 240 - 6 - bitmap8_width(text, 2)


# ---------------------------------------------------------------------------
# Durations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sec, text",
    [
        (-30, "0m"), (0, "0m"), (1, "1m"), (60, "1m"), (61, "2m"), (59 * 60, "59m"), (59 * 60 + 1, "1h00"),
        (9 * 3600 + 48 * 60, "9h48"), (_DAY - 60, "23h59"), (_DAY, "1d00"), (2 * _DAY + 8 * 3600, "2d08"),
    ],
)
def test_durations_round_up_to_whole_minutes(sec, text):
    assert calendar._format_duration(sec) == text


# ---------------------------------------------------------------------------
# Lifecycle and cadence
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_initialize_draws_one_frame_and_is_idempotent(self):
        display, gfx, _clock = _display([_ev("RAIN", _at(11, 0))])

        display.initialize()
        display.initialize()

        assert gfx.updates == 1

    def test_reentry_draws_again(self):
        display, gfx, _clock = _display([_ev("RAIN", _at(11, 0))])

        display.initialize()
        display.deinitialize()
        display.initialize()

        assert gfx.updates == 2

    def test_leaving_releases_a_refreshed_window_and_reentry_refills_it(self):
        snapshot = [_ev("RAIN", _at(11, 0))]
        window = EventWindow(
            iter(snapshot), stream_colors=STREAM_COLORS, events_iter_factory=lambda: iter(snapshot),
            get_generation=lambda: 1,
        )
        gfx = _Raster()
        display = calendar.Display(
            calendar.Geometry(gfx, "bitmap8", 8, 3, 2), [window], get_local_time=lambda: _NOW,
            real_remaining_sec=lambda local_epoch: local_epoch - _NOW,
        )
        display.initialize()

        display.deinitialize()

        assert window._buffer == []
        assert display._visible == [()]
        display.initialize()
        assert "RAIN" in gfx.body_strings()

    def test_redraws_only_once_the_minute_changes(self, fake_ticks):
        display, gfx, clock = _display([_ev("RAIN", _at(11, 0))], now=_at(9, 12, 20))
        display.initialize()

        fake_ticks[0] = 39_999
        clock[0] = _at(9, 12, 59)
        display.render()
        assert gfx.updates == 1

        fake_ticks[0] = 40_000
        clock[0] = _at(9, 13)
        display.render()
        assert gfx.updates == 2
        assert ("09:13", 0, 0, WHITE) in gfx.texts
        assert ("in 1h47", _right_x("in 1h47"), _slot_y(0) + 4, BLACK) in gfx.texts

    def test_too_wide_a_header_fails_at_construction(self):
        with pytest.raises(RuntimeError, match="no room for header"):
            calendar.Geometry(_Raster(), "bitmap8", 8, 4, 2)

    def test_too_few_slots_fail_at_construction(self):
        with pytest.raises(RuntimeError, match="no room for two slots"):
            calendar.Geometry(_Raster(), "bitmap8", 8, 3, 14)


# ---------------------------------------------------------------------------
# Header and rail
# ---------------------------------------------------------------------------


class TestFrame:
    def test_header_shows_time_in_white_and_date_in_gray_at_a_fixed_x(self):
        gfx = _drawn([])

        assert ("09:12", 0, 0, WHITE) in gfx.texts
        assert ("Thu 4 Jun", 75, 0, GRAY) in gfx.texts

    def test_empty_agenda_is_the_rail_alone(self):
        gfx = _drawn([], [])

        assert gfx.body_texts() == []
        assert all(gfx.at(x, y) == DARK_GRAY for x in (_RAIL_X, _RAIL_X + 1) for y in range(27, 240))
        assert [gfx.at(x, 100) for x in (_RAIL_X - 1, _RAIL_X + 2, 150)] == [BLACK, BLACK, BLACK]
        assert gfx.at(_RAIL_X, 26) == BLACK

    def test_rail_runs_on_beside_a_day_header(self):
        gfx = _drawn([_ev("PAPER", _at(8, 0, day=1))])

        assert ("Tomorrow", _FIELD_X, _slot_y(0) + 4, GRAY) in gfx.texts
        assert all(gfx.at(_RAIL_X, y) == DARK_GRAY for y in range(_slot_y(0), _slot_y(1)))


# ---------------------------------------------------------------------------
# Slots
# ---------------------------------------------------------------------------


class TestSlots:
    def test_an_upcoming_event_fills_its_field_beside_its_dot(self):
        gfx = _drawn([_ev("RAIN", _at(16, 0), color_index=STREAM_YELLOW)])
        y = _slot_y(0)

        assert [gfx.at(_FIELD_X - 1, y + 2), gfx.at(_FIELD_X, y), gfx.at(239, y + 21)] == [BLACK, YELLOW, YELLOW]
        assert gfx.at(_FIELD_X, y + 22) == BLACK
        assert [gfx.at(51, y + 11), gfx.at(46, y + 11), gfx.at(45, y + 11)] == [YELLOW, YELLOW, BLACK]
        assert ("16:00", 42 - bitmap8_width("16:00", 2), y + 4, GRAY) in gfx.texts
        assert ("RAIN", 66, y + 4, BLACK) in gfx.texts
        assert ("in 6h48", _right_x("in 6h48"), y + 4, BLACK) in gfx.texts

    def test_slots_follow_one_another_at_a_fixed_pitch(self):
        gfx = _drawn([_ev("A", _at(10, 0)), _ev("B", _at(11, 0)), _ev("C", _at(12, 0))])

        assert [(text, y) for text, x, y, _pen in gfx.body_texts() if x == 66] == [
            ("A", _slot_y(0) + 4), ("B", _slot_y(1) + 4), ("C", _slot_y(2) + 4)
        ]
        assert [gfx.at(100, _slot_y(1) - 1), gfx.at(100, _slot_y(1))] == [BLACK, SKY]

    def test_an_event_in_progress_has_a_progress_bar_under_its_field(self):
        gfx = _drawn([_ev("BIO", _at(8, 0), 120, STREAM_BROWN)])
        y = _slot_y(0)
        # 72 of 120 minutes gone: 108 of the field's 180 px.
        elapsed_end = _FIELD_X + 108

        assert gfx.at(100, y + 21) == BROWN
        assert all(gfx.at(x, y + row) == WHITE for x in (_FIELD_X, elapsed_end - 1) for row in range(22, 26))
        assert all(gfx.at(x, y + row) == DARK_GRAY for x in (elapsed_end, 239) for row in range(22, 26))
        assert gfx.at(_FIELD_X, y + 26) == BLACK
        assert ("08:00", 0, y + 4, WHITE) in gfx.texts
        assert ("BIO", 66, y + 4, WHITE) in gfx.texts
        assert ("48m left", _right_x("48m left"), y + 4, WHITE) in gfx.texts

    def test_events_in_progress_come_first_in_start_order_across_windows(self):
        gfx = _drawn(
            [_ev("BIO", _at(8, 0), 120, STREAM_BROWN), _ev("PLAST", _at(10, 0), 60, STREAM_YELLOW)],
            [_ev("GRASS", _at(7, 0), 12 * 60, STREAM_RED), _ev("UV", _at(11, 0), 300, STREAM_RED)],
        )

        assert [text for text, x, *_ in gfx.body_texts() if x == 66] == ["GRASS", "BIO", "PLAST", "UV"]
        assert [gfx.at(_FIELD_X, _slot_y(slot) + 22) for slot in range(4)] == [WHITE, WHITE, BLACK, BLACK]

    def test_events_starting_together_keep_their_windows_order(self):
        gfx = _drawn([_ev("FIRST", _at(10, 0))], [_ev("SECOND", _at(10, 0))])

        assert [text for text, x, *_ in gfx.body_texts() if x == 66] == ["FIRST", "SECOND"]

    def test_ended_events_are_gone(self):
        gfx = _drawn([_ev("DONE", _at(8, 0), 72), _ev("NEXT", _at(10, 0))])

        assert "DONE" not in gfx.body_strings()

    def test_events_beyond_the_last_slot_are_not_shown(self):
        gfx = _drawn([_ev(str(i), _at(10 + i, 0)) for i in range(_SLOT_COUNT + 2)])

        labels = [text for text, x, *_ in gfx.body_texts() if x == 66]
        assert labels == [str(i) for i in range(_SLOT_COUNT)]

    def test_label_is_cut_to_end_before_the_time_left(self):
        gfx = _drawn([_ev("PLASTIC+METAL", _at(9, 0), 120, STREAM_YELLOW)])
        note_x = _right_x("1h48 left")

        label = next(text for text, x, *_ in gfx.body_texts() if x == 66)
        assert "PLASTIC+METAL".startswith(label)
        assert 66 + bitmap8_width(label, 2) <= note_x - 6 < 66 + bitmap8_width("PLASTIC+METAL"[:len(label) + 1], 2)

    def test_a_long_label_without_a_note_reaches_the_field_inset(self):
        full = "PLASTIC AND METAL WASTE"
        gfx = _drawn([_ev(full, _at(8, 0, day=1))])

        label = next(text for text, x, *_ in gfx.body_texts() if x == 66)
        assert full.startswith(label)
        assert 66 + bitmap8_width(label, 2) <= 240 - 6 < 66 + bitmap8_width(full[:len(label) + 1], 2)

    def test_an_event_in_progress_since_before_today_shows_its_weekday(self):
        gfx = _drawn([_ev("BIRCH", _at(6, 0, day=-1), 3 * 24 * 60, STREAM_RED)])

        assert ("Wed", 42 - bitmap8_width("Wed", 2), _slot_y(0) + 4, WHITE) in gfx.texts
        assert "1d20 left" in gfx.body_strings()

    def test_notes_use_the_real_time_left(self):
        gfx = _drawn(
            [_ev("UV", _at(9, 0), 60), _ev("RAIN", _at(11, 0))],
            real_remaining_sec=lambda local_epoch: local_epoch - _NOW + 3600,
        )

        notes = [text for text, *_ in gfx.body_texts() if text.endswith(" left") or text.startswith("in ")]
        assert notes == ["1h48 left", "in 2h48"]

    def test_a_clock_stepped_back_hides_events_past_the_horizon(self, fake_ticks):
        later = _NOW + calendar.HORIZON_SEC - 3600
        display, gfx, clock = _display([_ev("FAR", later)])
        display.initialize()
        assert "FAR" in gfx.body_strings()

        clock[0] = _NOW - 2 * _DAY
        fake_ticks[0] = 60_000
        display.render()

        assert "FAR" not in gfx.body_strings()


# ---------------------------------------------------------------------------
# Day headers
# ---------------------------------------------------------------------------


class TestDayHeaders:
    def test_a_later_days_first_event_follows_its_day_header(self):
        gfx = _drawn([_ev("RAIN", _at(14, 0)), _ev("PLAST", _at(8, 0, day=1)), _ev("BIO", _at(9, 0, day=1)),
                      _ev("MIXED", _at(8, 0, day=6))])

        assert [(text, y) for text, x, y, _pen in gfx.body_texts() if x in (_FIELD_X, 66)] == [
            ("RAIN", _slot_y(0) + 4),
            ("Tomorrow", _slot_y(1) + 4),
            ("PLAST", _slot_y(2) + 4),
            ("BIO", _slot_y(3) + 4),
            ("Wed 10 Jun", _slot_y(4) + 4),
            ("MIXED", _slot_y(5) + 4),
        ]

    def test_later_days_have_no_note(self):
        gfx = _drawn([_ev("PLAST", _at(8, 0, day=1))])

        assert gfx.body_strings() == ["Tomorrow", "PLAST", "08:00"]

    def test_no_day_header_in_the_last_slot(self):
        today = [_ev(str(i), _at(10 + i, 0)) for i in range(_SLOT_COUNT - 1)]
        gfx = _drawn(today + [_ev("PLAST", _at(8, 0, day=1))])

        assert "Tomorrow" not in gfx.body_strings()
        assert "PLAST" not in gfx.body_strings()

    def test_an_event_in_progress_gets_no_day_header(self):
        gfx = _drawn([_ev("BIRCH", _at(6, 0, day=-1), 3 * 24 * 60)])

        assert "Tomorrow" not in gfx.body_strings()
        assert ("BIRCH", 66, _slot_y(0) + 4, BLACK) in gfx.texts
