from __future__ import annotations

import pytest

import displays.calendar as calendar
import displays.countdown as countdown
import displays.ring as ring
import displays.sensors as sensors
from displays.manager import DisplayManager
from scheduling.event import create_event
from services.countdown_timer import DONE, PAUSED, RUNNING, CountdownTimer
from services.sample_history import SampleHistory

from _fakes import FakePicoGraphics

_SENSORS_FONT = "sensors-font"
_COUNTDOWN_FONT = "countdown-font"
_CALENDAR_FONT = "calendar-font"
_FOREIGN_FONT = "foreign-font"
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


def _build_sensors(panel: _Panel, clock: _Clock) -> sensors.Display:
    geom = sensors.Geometry(
        pico_graphics=panel,
        font=_SENSORS_FONT,
        font_height=8,
        value_text_scale=3,
        label_text_scale=2,
        tick_period_ms=500,
    )
    reader = _Reader()
    return sensors.Display(
        geometry=geom,
        get_reading=reader.read,
        get_local_time=clock.now,
        history=SampleHistory(
            lambda: sensors.encode_reading(reader.read()),
            metric_count=4,
            capacity=geom.graph_columns,
            ticks_per_commit=1,
        ),
        band_edges=((18.0, 25.0, 29.0), (1000.0, 1013.0, 1025.0), (30.0, 50.0, 70.0), (100.0, 200.0, 350.0)),
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
        geometry=calendar.Geometry(
            pico_graphics=panel,
            font=_CALENDAR_FONT,
            font_height=8,
            header_text_scale=3,
            label_text_scale=2,
            glyph_width=8,
        ),
        streams=[((8, 8, bytes(32)), lambda now_utc: [create_event("WORK", _NOW_SEC - 600, 4 * 3600)])],
        get_utc_time=clock.now,
        to_local=lambda utc_epoch: utc_epoch,
        get_refresh_failed=lambda: False,
    )


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
    panel.font_for = lambda text: _CALENDAR_FONT
    calendar_display = _build_calendar(panel, clock)
    mgr = DisplayManager([sensors_display, countdown_display, calendar_display], tick_period_ms=500)
    view_fonts = (_SENSORS_FONT, _COUNTDOWN_FONT, _CALENDAR_FONT)
    panel.font_for = lambda text: view_fonts[mgr._current]

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

    for font in (_SENSORS_FONT, _COUNTDOWN_FONT, _CALENDAR_FONT):
        assert any(expected == font for _, expected, _ in panel.text_fonts), font
    assert [op for op in panel.text_fonts if op[1] != op[2]] == []
