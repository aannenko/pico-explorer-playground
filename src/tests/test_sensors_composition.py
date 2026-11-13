from __future__ import annotations

import pytest

import config_defaults
import displays.sensors as sensors
from displays.shared import _icons_data as icons
from services.tick_scheduler import TickScheduler

from _fakes import FakePicoGraphics
from conftest import make_timer_factory, utc_epoch


class _StatusDisplay:
    def __init__(self) -> None:
        self.shown: list[tuple[str, str]] = []

    def show(self, text: str, subtext: str = "") -> None:
        self.shown.append((text, subtext))


class _Reader:
    def read(self) -> tuple[float, float, float, float, str]:
        return (26.0, 1013.0, 47.0, 312.0, "Stable")


class _Clock:
    def now(self) -> int:
        return utc_epoch(2026, 11, 2, 13, 8, 0)


def test_shipped_sensor_bands_pass_validation(app_module) -> None:
    status = _StatusDisplay()
    app_module._validate_sensor_bands_or_halt(status)
    assert status.shown == []


@pytest.mark.parametrize(
    "bands",
    [
        (30.0, 30.0, 70.0),
        (70.0, 50.0, 30.0),
        (30.0, 50.0),
        (10.0, 30.0, 50.0, 70.0, 90.0),
        50.0,
        (30.0, "50", 70.0),
    ],
)
def test_bad_sensor_bands_halt_on_the_status_display(app_module, monkeypatch, bands) -> None:
    monkeypatch.setattr(config_defaults, "SENSOR_HUMIDITY_BANDS", bands)
    status = _StatusDisplay()
    with pytest.raises(SystemExit):
        app_module._validate_sensor_bands_or_halt(status)
    assert status.shown == [("Bad config", "edit & reboot")]


def test_sensors_display_composes_from_config_and_samples_on_the_scheduler(app_module, monkeypatch) -> None:
    blits: list[tuple[int, int, bytes]] = []
    monkeypatch.setattr(sensors.icons_p4, "draw_icon", lambda gfx, icon, x, y, scale=1: blits.append(icon))
    timer_factory, timers = make_timer_factory()
    tick_scheduler = TickScheduler(schedule=lambda callback, arg: callback(arg), timer_factory=timer_factory)
    panel = FakePicoGraphics()

    display = app_module._build_sensors_display(panel, tick_scheduler, _Reader(), _Clock())
    display.initialize()
    assert icons.ICON_THERMO_ORANGE in blits
    assert ("text", ("26.0", 8, 54), {"scale": 3}) in panel.calls

    tick_scheduler.start()
    tick = timers[0].init_calls[0]["callback"]
    for _ in range(display._geom.ticks_per_commit):
        tick(None)
    panel.calls.clear()
    display.render()
    assert ("rectangle", (0, 1, 119, 23), {}) in panel.calls
