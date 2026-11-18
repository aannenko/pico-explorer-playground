"""Calendar composition and selection after time spent on another screen."""

import pytest

import config_defaults
from displays.base import Display
from displays.manager import DisplayManager
from displays.palette import STREAM_YELLOW
from scheduling.event import create_event, Event
from scheduling.providers import waste
from services.time_service import TimeService

from _fakes import FakePicoGraphics
from conftest import utc_epoch


class _Panel(FakePicoGraphics):
    def __init__(self):
        super().__init__()
        self.frame = []
        self.presented = ()
        self.updates = 0

    def clear(self):
        super().clear()
        self.frame.clear()

    def text(self, text, x, y, *, scale):
        super().text(text, x, y, scale=scale)
        self.frame.append(text)

    def update(self):
        super().update()
        self.presented = tuple(self.frame)
        self.updates += 1


class _OtherDisplay(Display):
    def __init__(self, panel, name):
        self.panel = panel
        self.name = name

    def initialize(self):
        self.panel.clear()
        self.panel.text(self.name, 0, 0, scale=1)
        self.panel.update()


def _no_events(now_utc: int) -> list[Event]:
    return []


def _time_service(get_time) -> TimeService:
    return TimeService(
        tz_offset_hours=config_defaults.TIME_ZONE_OFFSET_HOURS,
        dst_start_rule=config_defaults.DST_START_RULE,
        dst_end_rule=config_defaults.DST_END_RULE,
        dst_offset_hours=config_defaults.DST_OFFSET_HOURS,
        get_time=get_time,
    )


@pytest.mark.parametrize("direction", ["next", "previous"])
@pytest.mark.parametrize("visited_before", [False, True])
def test_cycle_to_calendar_after_month_away_draws_first_frame(
    app_module, monkeypatch, direction, visited_before
):
    clock = [utc_epoch(2026, 9, 14, 7, 0, 0)]
    panel = _Panel()
    calendar = app_module._build_calendar_display(
        app_module._build_calendar_geometry(panel),
        _time_service(lambda: clock[0]),
        [_no_events] * 4,
    )
    manager = DisplayManager(
        [
            _OtherDisplay(panel, "SENSORS"),
            _OtherDisplay(panel, "COUNTDOWN"),
            calendar,
        ],
        tick_period_ms=500,
    )
    manager.initialize_current()
    if visited_before:
        manager.previous_ref(0)
        manager.next_ref(0)
    clock[0] += 30 * 86400

    event_factory = waste.create_event
    produced = 0

    def budgeted_event(*args, **kwargs):
        nonlocal produced
        produced += 1
        # A redraw lists at most a slot count of pickups, however long the calendar was away.
        if produced > calendar._geom.slot_count:
            raise MemoryError("calendar entry built more waste events than it can show")
        return event_factory(*args, **kwargs)

    monkeypatch.setattr(waste, "create_event", budgeted_event)
    if direction == "next":
        manager.next_ref(0)
        assert panel.presented == ("COUNTDOWN",)
        callback = manager.next_ref
    else:
        assert panel.presented == ("SENSORS",)
        callback = manager.previous_ref
    updates_before = panel.updates

    callback(0)

    assert manager._current == 2
    assert panel.updates == updates_before + 1
    # Wednesday 14 Oct is a MIXED pickup day, 08:00-10:00, and Friday 16 Oct a PAPER one.
    assert panel.presented[:2] == ("09:00", "Wed 14 Oct")
    assert "MIXED" in panel.presented
    assert "Fri 16 Oct" in panel.presented


def test_time_left_is_real_across_the_fall_back(app_module) -> None:
    # Sat 2026-10-24 12:00 CEST: an event ending Mon 09:00 CET is 45 h away on the
    # clock and 46 h in real time.
    utc = utc_epoch(2026, 10, 24, 10, 0, 0)
    end_utc = utc_epoch(2026, 10, 26, 8, 0, 0)
    panel = _Panel()
    calendar = app_module._build_calendar_display(
        app_module._build_calendar_geometry(panel),
        _time_service(lambda: utc),
        [lambda now_utc: [create_event("UV", utc - 600, end_utc - (utc - 600), color_index=STREAM_YELLOW)]],
    )

    calendar.initialize()

    assert "1d22 left" in panel.presented


@pytest.mark.parametrize(
    "utc, agenda",
    [
        # Sat 24 Oct 2026, 12:00 CEST, before the fall-back.
        (utc_epoch(2026, 10, 24, 10, 0, 0), ("Wed 28 Oct", "MIXED", "08:00", "Fri 30 Oct", "PAPER", "08:00")),
        # Sat 27 Mar 2027, 12:00 CET, before the spring-forward.
        (utc_epoch(2027, 3, 27, 11, 0, 0), ("Wed 31 Mar", "MIXED", "08:00", "Fri 2 Apr", "PAPER", "08:00")),
    ],
)
def test_pickups_past_a_dst_change_keep_their_wall_clock_time(app_module, utc: int, agenda: tuple) -> None:
    panel = _Panel()
    calendar = app_module._build_calendar_display(
        app_module._build_calendar_geometry(panel), _time_service(lambda: utc), [_no_events] * 4
    )

    calendar.initialize()

    assert panel.presented[2:] == agenda
