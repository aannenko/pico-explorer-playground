from __future__ import annotations

import re

import pytest

import displays.calendar as calendar
import displays.countdown as countdown
import displays.ring as ring
import displays.sensors as sensors
from displays.manager import DisplayManager
from scheduling.event import Event
from scheduling.event_window import EventWindow
from services.countdown_timer import DONE, PAUSED, RUNNING, CountdownTimer

from _fakes import FakePicoGraphics

_SENSORS_FONT = "sensors-font"
_COUNTDOWN_FONT = "countdown-font"
_CALENDAR_HEADER_FONT = "calendar-header-font"
_CALENDAR_BAR_FONT = "calendar-bar-font"
_FOREIGN_FONT = "foreign-font"
_CALENDAR_HEADER = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d$")
_NOW_SEC = 1_780_000_000
_READING = (22.0, 1010.0, 50.0, 120.0)
_SENSORS, _COUNTDOWN, _CALENDAR = 0, 1, 2


class _Panel(FakePicoGraphics):
    def __init__(self) -> None:
        super().__init__()
        self.font = "boot-font"
        self.font_for = None  # (str) -> str: the font the view drawing this text must have selected
        self.text_fonts: list[tuple[str, str, str]] = []  # (text, font_for(text), selected font)

    def set_font(self, font: str) -> None:
        super().set_font(font)
        self.font = font

    def text(self, text: str, x: int, y: int, *, scale: int) -> None:
        super().text(text, x, y, scale=scale)
        self.text_fonts.append((text, self.font_for(text), self.font))

    def measure_text(self, text: str, scale: int) -> int:
        self.text_fonts.append((text, self.font_for(text), self.font))
        return super().measure_text(text, scale)

    def line(self, *args) -> None:
        self.calls.append(("line", args, {}))

    def circle(self, *args) -> None:
        self.calls.append(("circle", args, {}))

    def polygon(self, *args) -> None:
        self.calls.append(("polygon", args, {}))


class _Clock:
    def __init__(self) -> None:
        self.now_sec = _NOW_SEC

    def now(self) -> int:
        return self.now_sec


class _Reader:
    def read(self) -> tuple[float, float, float, float, str]:
        return _READING + ("Stable",)


class _History:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.commit_count = 1
        self.sample_count = 1

    def value_at(self, metric_index: int, age: int) -> float:
        return _READING[metric_index]

    def update_latest(self, metric_index: int, value: float) -> None:
        pass


def _build_sensors(panel: _Panel, clock: _Clock) -> sensors.Display:
    geom = sensors.Geometry(
        pico_graphics=panel, font=_SENSORS_FONT, font_height=8, text_scale=3, tick_period_ms=500
    )
    return sensors.Display(
        renderer=sensors.Renderer(
            geometry=geom,
            colors=sensors.Colors(background=0, header_text=1, value_text=2, secondary_text=3),
        ),
        bme690_reader=_Reader(),
        time_service=clock,
        history=_History(geom.graph_width),
        graph_height=geom.graph_height,
        temp_bands=(16, 18, 25, 29, 31),
        pressure_bands=(980, 1000, 1013, 1025, 1040),
        humidity_bands=(10, 30, 50, 70, 90),
        gas_bands=(50, 100, 200, 350, 500),
    )


def _build_countdown(panel: _Panel, timer: CountdownTimer) -> countdown.Display:
    return countdown.Display(
        renderer=ring.Renderer(
            geometry=ring.Geometry(pico_graphics=panel, font=_COUNTDOWN_FONT, font_height=8, text_scale=3),
            colors=ring.Colors(background=0, ring=1, primary_text=2, secondary_text=3),
        ),
        countdown_timer=timer,
    )


def _build_calendar(panel: _Panel, clock: _Clock) -> calendar.Display:
    return calendar.Display(
        renderer=calendar.Renderer(
            geometry=calendar.Geometry(
                pico_graphics=panel,
                header_font=_CALENDAR_HEADER_FONT,
                header_font_height=8,
                header_text_scale=3,
                bar_font=_CALENDAR_BAR_FONT,
                bar_font_height=8,
                bar_text_scale=2,
            ),
            colors=calendar.Colors(background=0, header_text=1, axis_text=2, empty_row=3, now_line=4),
        ),
        event_windows=[
            EventWindow(iter([Event("WORK", _NOW_SEC - 600, 4 * 3600, color_index=0)]), stream_colors=[10])
        ],
        get_local_time=clock.now,
        real_remaining_sec=lambda local_epoch: local_epoch - clock.now_sec,
    )


def _calendar_font(text: str) -> str:
    return _CALENDAR_HEADER_FONT if _CALENDAR_HEADER.match(text) else _CALENDAR_BAR_FONT


@pytest.mark.parametrize("foreign_font_before_each_switch", [False, True])
def test_every_view_draws_and_measures_text_in_its_own_font(foreign_font_before_each_switch: bool) -> None:
    """PicoGraphics keeps one selected font for the panel every view shares."""
    panel = _Panel()
    clock = _Clock()
    timer = CountdownTimer(get_time=clock.now)
    panel.font_for = lambda text: _SENSORS_FONT
    sensors_display = _build_sensors(panel, clock)
    panel.font_for = lambda text: _COUNTDOWN_FONT
    countdown_display = _build_countdown(panel, timer)
    panel.font_for = _calendar_font
    calendar_display = _build_calendar(panel, clock)
    mgr = DisplayManager([sensors_display, countdown_display, calendar_display], tick_period_ms=500)
    view_fonts = (lambda text: _SENSORS_FONT, lambda text: _COUNTDOWN_FONT, _calendar_font)
    panel.font_for = lambda text: view_fonts[mgr._current](text)

    def enter(
        step,  # () -> None
        view_index: int,
    ) -> None:
        if foreign_font_before_each_switch:
            panel.set_font(_FOREIGN_FONT)
        step()
        assert mgr._current == view_index

    def tick(count: int) -> None:
        for _ in range(count):
            mgr.tick()

    mgr.initialize_current()
    tick(4)
    enter(mgr.next, _COUNTDOWN)
    mgr._do_on_button_b(0)
    mgr._do_on_button_a(0)
    assert timer.state == RUNNING
    clock.now_sec += 5
    tick(4)
    enter(mgr.next, _CALENDAR)
    tick(130)
    enter(mgr.previous, _COUNTDOWN)
    mgr._do_on_button_a(0)
    assert timer.state == PAUSED
    enter(mgr.next, _CALENDAR)
    enter(mgr.previous, _COUNTDOWN)
    mgr._do_on_button_a(0)
    clock.now_sec += 5 * 3600
    timer._tick()
    assert timer.state == DONE
    tick(4)
    enter(mgr.next, _CALENDAR)
    enter(mgr.previous, _COUNTDOWN)
    enter(mgr.previous, _SENSORS)
    tick(4)
    enter(mgr.previous, _CALENDAR)
    enter(mgr.next, _SENSORS)

    for font in (_SENSORS_FONT, _COUNTDOWN_FONT, _CALENDAR_HEADER_FONT, _CALENDAR_BAR_FONT):
        assert any(expected == font for _, expected, _ in panel.text_fonts), font
    assert [op for op in panel.text_fonts if op[1] != op[2]] == []
