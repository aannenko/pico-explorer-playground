from __future__ import annotations

import time

import pytest

import displays.calendar as calendar
from displays.palette import (
    BLACK,
    BROWN,
    DARK_GRAY,
    GRAY,
    RED,
    SKY,
    STREAM_BROWN,
    STREAM_COLORS,
    STREAM_RED,
    STREAM_SKY,
    STREAM_YELLOW,
    WHITE,
    YELLOW,
)
from conftest import DST_END, DST_START, utc_epoch
from scheduling.event import create_event, Event
from services.time_service import TimeService

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
        return [entry for entry in self.texts if entry[2] >= _slot_y(0)]

    def body_strings(self) -> list[str]:
        return [text for text, *_ in self.body_texts()]


def _ev(label: str, start: int, duration_min: int = 60, color_index: int = STREAM_SKY) -> Event:
    return create_event(label, start, duration_min * 60, color_index=color_index)


def _stream(events: list[Event]):  # -> (int) -> list[Event]
    return lambda now_utc: events


def _display(
    *streams,
    now: int = _NOW,
    to_local=None,  # (int) -> int
    refresh_failed: list[bool] | None = None,
):
    """Each stream is a list of events, or a getter; local time is UTC unless ``to_local`` says otherwise, and no
    refresh has failed unless ``refresh_failed`` holds ``[True]``."""
    gfx = _Raster()
    geometry = calendar.Geometry(gfx, "bitmap8", 8, 3, 2)
    clock = [now]
    failed = refresh_failed if refresh_failed is not None else [False]
    display = calendar.Display(
        geometry,
        [_stream(stream) if isinstance(stream, list) else stream for stream in streams],
        get_utc_time=lambda: clock[0],
        to_local=to_local or (lambda utc_epoch: utc_epoch),
        get_refresh_failed=lambda: failed[0],
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

    def test_no_events_stay_pinned_between_redraws(self):
        display, _gfx, _clock = _display([_ev("RAIN", _at(11, 0))])

        display.initialize()

        assert display._visible == [()]

    def test_a_redraw_that_raises_pins_no_events_and_retries_at_the_next_minute(self, fake_ticks):
        def raise_memory_error(*args) -> None:
            raise MemoryError

        display, gfx, _clock = _display([_ev("RAIN", _at(11, 0))], now=_at(9, 12, 20))
        gfx.circle = raise_memory_error

        with pytest.raises(MemoryError):
            display.initialize()

        assert display._visible == [()]
        fake_ticks[0] = 39_999
        display.render()
        assert gfx.updates == 0

    def test_a_failed_time_read_is_retried_a_minute_later(self, fake_ticks):
        reads = [0]

        def failing_utc_time() -> int:
            reads[0] += 1
            raise MemoryError

        gfx = _Raster()
        display = calendar.Display(
            calendar.Geometry(gfx, "bitmap8", 8, 3, 2), [], get_utc_time=failing_utc_time,
            to_local=lambda utc_epoch: utc_epoch, get_refresh_failed=lambda: False,
        )
        with pytest.raises(MemoryError):
            display.initialize()

        fake_ticks[0] = 59_999
        display.render()
        assert reads[0] == 1
        fake_ticks[0] = 60_000
        with pytest.raises(MemoryError):
            display.render()
        assert reads[0] == 2

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
# A failing stream
# ---------------------------------------------------------------------------

_BADGE_X = 232  # the badge's centre
_BADGE_Y = 10
_BADGE_R = 7


def _failing_stream(now_utc: int) -> list[Event]:
    raise MemoryError


class TestFailingStream:
    def test_the_other_streams_are_drawn_under_a_red_date_and_a_badge(self, capsys):
        display, gfx, _clock = _display([_ev("RAIN", _at(11, 0))], _failing_stream, [_ev("UV", _at(12, 0))])

        display.initialize()

        assert gfx.updates == 1
        assert [text for text, x, *_ in gfx.body_texts() if x == 66] == ["RAIN", "UV"]
        assert ("Thu 4 Jun", 75, 0, RED) in gfx.texts
        assert ("!", 231, 3, WHITE) in gfx.texts
        assert {gfx.at(x, y) for x, y in circle_pixels(_BADGE_X, _BADGE_Y, _BADGE_R)} == {RED, WHITE}
        assert display._visible == [(), (), ()]
        assert "[calendar] stream err:" in capsys.readouterr().out

    def test_the_mark_clears_once_every_stream_reads_again(self, fake_ticks):
        reads = [0]

        def flaky_stream(now_utc: int) -> list[Event]:
            reads[0] += 1
            if reads[0] == 1:
                raise MemoryError
            return [_ev("PAPER", _at(10, 0))]

        display, gfx, clock = _display([_ev("RAIN", _at(11, 0))], flaky_stream, now=_at(9, 12, 20))
        display.initialize()
        fake_ticks[0] = 40_000
        clock[0] = _at(9, 13)
        display.render()

        assert gfx.updates == 2
        assert [text for text, x, *_ in gfx.body_texts() if x == 66] == ["PAPER", "RAIN"]
        assert ("Thu 4 Jun", 75, 0, GRAY) in gfx.texts
        assert gfx.at(_BADGE_X, _BADGE_Y) == BLACK

    def test_the_badge_clears_the_widest_date_by_a_character_gap(self):
        gfx = _drawn(_failing_stream, now=time.mktime((2028, 3, 20, 9, 12, 0, 0, 0)))

        assert ("Mon 20 Mar", 75, 0, RED) in gfx.texts
        badge_left = min(x for x, _y in circle_pixels(_BADGE_X, _BADGE_Y, _BADGE_R))
        assert badge_left - (75 + bitmap8_width("Mon 20 Mar", 3)) == 3

    def test_a_header_without_room_for_the_badge_fails_at_construction(self):
        gfx = _Raster()
        gfx.get_bounds = lambda: (230, 240)

        with pytest.raises(RuntimeError, match="no room for header"):
            calendar.Geometry(gfx, "bitmap8", 8, 3, 2)

    def test_a_failed_refresh_marks_the_frame_over_every_streams_events(self, fake_ticks):
        failed = [True]
        display, gfx, clock = _display(
            [_ev("RAIN", _at(11, 0))], [_ev("UV", _at(12, 0))], now=_at(9, 12, 20), refresh_failed=failed
        )

        display.initialize()

        assert [text for text, x, *_ in gfx.body_texts() if x == 66] == ["RAIN", "UV"]
        assert ("Thu 4 Jun", 75, 0, RED) in gfx.texts
        assert ("!", 231, 3, WHITE) in gfx.texts

        failed[0] = False
        fake_ticks[0] = 40_000
        clock[0] = _at(9, 13)
        display.render()

        assert ("Thu 4 Jun", 75, 0, GRAY) in gfx.texts
        assert gfx.at(_BADGE_X, _BADGE_Y) == BLACK


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

    def test_events_in_progress_come_first_in_start_order_across_streams(self):
        gfx = _drawn(
            [_ev("BIO", _at(8, 0), 120, STREAM_BROWN), _ev("PLAST", _at(10, 0), 60, STREAM_YELLOW)],
            [_ev("GRASS", _at(7, 0), 12 * 60, STREAM_RED), _ev("UV", _at(11, 0), 300, STREAM_RED)],
        )

        assert [text for text, x, *_ in gfx.body_texts() if x == 66] == ["GRASS", "BIO", "PLAST", "UV"]
        assert [gfx.at(_FIELD_X, _slot_y(slot) + 22) for slot in range(4)] == [WHITE, WHITE, BLACK, BLACK]

    def test_events_starting_together_keep_their_streams_order(self):
        gfx = _drawn([_ev("FIRST", _at(10, 0))], [_ev("SECOND", _at(10, 0))])

        assert [text for text, x, *_ in gfx.body_texts() if x == 66] == ["FIRST", "SECOND"]

    def test_ended_events_are_gone(self):
        gfx = _drawn([_ev("DONE", _at(8, 0), 72), _ev("NEXT", _at(10, 0))])

        assert "DONE" not in gfx.body_strings()

    def test_an_event_in_progress_outlives_a_later_one_that_ended(self):
        gfx = _drawn([_ev("LONG", _at(8, 0), 180), _ev("SHORT", _at(8, 30), 30), _ev("NEXT", _at(10, 0))])

        assert [text for text, x, *_ in gfx.body_texts() if x == 66] == ["LONG", "NEXT"]

    def test_a_zero_duration_event_starting_now_is_upcoming(self):
        gfx = _drawn([_ev("NOW", _NOW, 0)])

        assert ("in 0m", _right_x("in 0m"), _slot_y(0) + 4, BLACK) in gfx.texts
        assert gfx.at(_FIELD_X, _slot_y(0) + 22) == BLACK

    def test_a_colour_index_past_the_palette_takes_its_last_colour(self):
        gfx = _drawn([_ev("ODD", _at(10, 0), color_index=len(STREAM_COLORS) + 3)])

        assert gfx.at(100, _slot_y(0) + 2) == STREAM_COLORS[-1]

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

    def test_an_event_starting_at_the_horizon_is_not_shown(self):
        gfx = _drawn([_ev("NEAR", _NOW + calendar.HORIZON_SEC - 1), _ev("FAR", _NOW + calendar.HORIZON_SEC)])

        assert "NEAR" in gfx.body_strings()
        assert "FAR" not in gfx.body_strings()

    def test_a_clock_stepped_back_shows_again_the_events_not_over_then(self, fake_ticks):
        display, gfx, clock = _display([_ev("DONE", _at(8, 0), 72), _ev("NEXT", _at(10, 0))])
        display.initialize()
        assert "DONE" not in gfx.body_strings()

        clock[0] = _at(9, 0)
        fake_ticks[0] = 60_000
        display.render()

        assert "DONE" in gfx.body_strings()


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


# ---------------------------------------------------------------------------
# Time frames: order and timing in UTC, drawing in local time
# ---------------------------------------------------------------------------


def _cet() -> TimeService:
    return TimeService(
        tz_offset_hours=1, dst_start_rule=DST_START, dst_end_rule=DST_END, dst_offset_hours=1, get_time=lambda: 0
    )


def _cet_drawn(now_utc: int, *events: Event) -> _Raster:
    display, gfx, _clock = _display(list(events), now=now_utc, to_local=_cet().to_local)
    display.initialize()
    return gfx


class TestTimeFrames:
    def test_a_start_across_the_spring_forward_is_an_hour_away_at_its_local_time(self):
        # 01:30 CET, then 03:30 CEST an hour later.
        gfx = _cet_drawn(utc_epoch(2026, 3, 29, 0, 30, 0), _ev("RAIN", utc_epoch(2026, 3, 29, 1, 30, 0)))

        assert "03:30" in gfx.body_strings()
        assert "in 1h00" in gfx.body_strings()

    def test_an_event_across_the_fall_back_shows_its_local_start_and_real_progress(self):
        # From 02:00 CEST to 04:00 CET, three real hours; now 02:30 CET, half way.
        gfx = _cet_drawn(utc_epoch(2026, 10, 25, 1, 30, 0), _ev("RAIN", utc_epoch(2026, 10, 25, 0, 0, 0), 180))
        y = _slot_y(0)

        assert ("02:00", 0, y + 4, WHITE) in gfx.texts
        assert "1h30 left" in gfx.body_strings()
        assert [gfx.at(_FIELD_X + 89, y + 22), gfx.at(_FIELD_X + 90, y + 22)] == [WHITE, DARK_GRAY]

    def test_an_event_in_the_repeated_hours_second_pass_is_upcoming_during_the_first(self):
        # Now 02:45 CEST; the event starts at 02:30 CET, 45 minutes later.
        gfx = _cet_drawn(utc_epoch(2026, 10, 25, 0, 45, 0), _ev("RAIN", utc_epoch(2026, 10, 25, 1, 30, 0)))

        assert ("02:30", 42 - bitmap8_width("02:30", 2), _slot_y(0) + 4, GRAY) in gfx.texts
        assert "in 45m" in gfx.body_strings()

    def test_events_across_the_fall_back_keep_their_real_order(self):
        # Now 02:15 CEST: LATER starts at 02:30 CET, after EARLIER at 02:45 CEST, though its wall time is earlier.
        display, gfx, _clock = _display(
            [_ev("LATER", utc_epoch(2026, 10, 25, 1, 30, 0))],
            [_ev("EARLIER", utc_epoch(2026, 10, 25, 0, 45, 0))],
            now=utc_epoch(2026, 10, 25, 0, 15, 0),
            to_local=_cet().to_local,
        )
        display.initialize()

        assert [text for text, x, *_ in gfx.body_texts() if x == 66] == ["EARLIER", "LATER"]

    def test_days_are_local_dates(self):
        # 23:30 CET on Thursday 8 Jan, and an event at 00:30 CET, still 8 Jan in UTC.
        gfx = _cet_drawn(utc_epoch(2026, 1, 8, 22, 30, 0), _ev("BIO", utc_epoch(2026, 1, 8, 23, 30, 0)))

        assert gfx.body_strings() == ["Tomorrow", "BIO", "00:30"]
        assert ("23:30", 0, 0, WHITE) in gfx.texts

    def test_today_is_the_local_date(self):
        # 00:30 CET on Friday 9 Jan, still Thursday in UTC: an event at 08:00 CET is today's.
        gfx = _cet_drawn(utc_epoch(2026, 1, 8, 23, 30, 0), _ev("BIO", utc_epoch(2026, 1, 9, 7, 0, 0)))

        assert gfx.body_strings() == ["BIO", "in 7h30", "08:00"]

    def test_an_event_in_progress_since_after_local_midnight_shows_its_start_time(self):
        # Since 00:10 CET on Friday 9 Jan, Thursday in UTC.
        gfx = _cet_drawn(utc_epoch(2026, 1, 8, 23, 30, 0), _ev("BIO", utc_epoch(2026, 1, 8, 23, 10, 0), 120))

        assert ("00:10", 42 - bitmap8_width("00:10", 2), _slot_y(0) + 4, WHITE) in gfx.texts

    def test_the_horizon_is_real_time_from_now(self):
        gfx = _cet_drawn(_NOW, _ev("NEAR", _NOW + calendar.HORIZON_SEC - 1), _ev("FAR", _NOW + calendar.HORIZON_SEC))

        assert "NEAR" in gfx.body_strings()
        assert "FAR" not in gfx.body_strings()

    def test_redraws_as_each_local_minute_starts(self, fake_ticks):
        # Local time runs 30 s ahead of UTC: at 09:12:10 UTC the local minute ends in 20 s.
        display, gfx, clock = _display([], now=_at(9, 12, 10), to_local=lambda utc_epoch: utc_epoch + 30)
        display.initialize()

        fake_ticks[0] = 19_999
        display.render()
        assert gfx.updates == 1

        fake_ticks[0] = 20_000
        display.render()
        assert gfx.updates == 2