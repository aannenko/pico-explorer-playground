"""Calendar composition and selection after time spent on another screen."""

import importlib
import sys

import pytest

import config_defaults
import demo_streams
from displays.base import Display
from displays.manager import DisplayManager
from scheduling.stream import DISABLED, Stream
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

    def line(self, *args):
        self.calls.append(("line", args, {}))

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


@pytest.fixture
def app_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "config", config_defaults)
    previous = sys.modules.pop("app", None)
    try:
        yield importlib.import_module("app")
    finally:
        sys.modules.pop("app", None)
        if previous is not None:
            sys.modules["app"] = previous


@pytest.mark.parametrize("direction", ["next", "previous"])
@pytest.mark.parametrize("visited_before", [False, True])
def test_cycle_to_calendar_after_month_away_draws_first_frame(
    app_module, monkeypatch, direction, visited_before
):
    clock = [utc_epoch(2026, 9, 14, 7, 0, 0)]
    time_service = TimeService(
        tz_offset_hours=config_defaults.TIME_ZONE_OFFSET_HOURS,
        dst_start=config_defaults.DST_START,
        dst_end=config_defaults.DST_END,
        dst_offset_hours=config_defaults.DST_OFFSET_HOURS,
        get_time=lambda: clock[0],
    )
    monkeypatch.setattr(demo_streams.random, "choice", lambda items: items[0])
    monkeypatch.setattr(demo_streams.random, "randint", lambda low, high: high)
    panel = _Panel()
    calendar = app_module._build_calendar_display(
        panel,
        time_service,
        [
            Stream(iter(()), status_fn=lambda: DISABLED),
            Stream(iter(()), status_fn=lambda: DISABLED),
        ],
    )
    manager = DisplayManager(
        [
            _OtherDisplay(panel, "SENSORS"),
            _OtherDisplay(panel, "COUNTDOWN"),
            calendar,
        ],
        scheduler_period_ms=500,
    )
    manager.initialize_current()
    if visited_before:
        manager.previous_ref(0)
        manager.next_ref(0)
    clock[0] += 30 * 86400
    time_service._update_dst()

    event_type = demo_streams.Event
    produced = 0

    def budgeted_event(*args, **kwargs):
        nonlocal produced
        produced += 1
        if produced > 10:
            raise MemoryError("calendar entry replayed obsolete demo history")
        return event_type(*args, **kwargs)

    monkeypatch.setattr(demo_streams, "Event", budgeted_event)
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
    assert panel.presented[0] == "2026-10-14 09:00"
    assert len(calendar._streams) == 5
    assert len(calendar._streams[-1]._buffer) == 8
    assert produced == 9
