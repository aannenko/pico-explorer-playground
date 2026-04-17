from __future__ import annotations

import pytest

import services.pimoroni_bme690 as pimoroni_bme690

from conftest import FakeTimer, make_timer_factory


class FakeI2C:
    def __init__(self, **kwargs) -> None:
        self.kwargs = dict(kwargs)


class FakeBreakoutBME69X:
    next_reading: tuple[float, float, float, float, int] = (0.0, 0.0, 0.0, 0.0, 0)

    def __init__(self, i2c: FakeI2C) -> None:
        self.i2c = i2c
        self.configure_calls: list[tuple[object, ...]] = []
        self.read_count: int = 0

    def configure(self, *args) -> None:
        self.configure_calls.append(tuple(args))

    def read(self):
        self.read_count += 1
        # Return a tuple long enough for slicing [0:5]
        temp, press, hum, gas_r, status = self.next_reading
        return (temp, press, hum, gas_r, status, 123, 456)


@pytest.fixture(autouse=True)
def _patch_driver(monkeypatch) -> None:
    monkeypatch.setattr(pimoroni_bme690, "PimoroniI2C", FakeI2C)
    monkeypatch.setattr(pimoroni_bme690, "PICO_EXPLORER_I2C_PINS", {"sda": 4, "scl": 5})
    monkeypatch.setattr(pimoroni_bme690, "BreakoutBME69X", FakeBreakoutBME69X)
    monkeypatch.setattr(pimoroni_bme690, "STATUS_HEATER_STABLE", 0b10)
    monkeypatch.setattr(pimoroni_bme690, "FILTER_COEFF_3", 3)
    monkeypatch.setattr(pimoroni_bme690, "STANDBY_TIME_1000_MS", 1000)
    monkeypatch.setattr(pimoroni_bme690, "OVERSAMPLING_2X", 2)
    monkeypatch.setattr(pimoroni_bme690, "OVERSAMPLING_1X", 1)


def test_read_applies_offsets_converts_units_and_stable_status() -> None:
    FakeBreakoutBME69X.next_reading = (
        20.0,  # C
        100_000.0,  # Pa
        50.0,  # %
        2_500.0,  # Ohm
        0b10,  # heater stable
    )

    reader = pimoroni_bme690.PimoroniBME690(
        temp_offset=1.5,
        hum_offset=-2.0,
    )

    temp, press_mb, hum, gas_kohm, heater = reader.read()

    assert temp == 21.5
    assert press_mb == 1000.0
    assert hum == 48.0
    assert gas_kohm == 2.5
    assert heater == "Stable"


def test_read_maps_unstable_status() -> None:
    FakeBreakoutBME69X.next_reading = (
        0.0,
        101_325.0,
        0.0,
        0.0,
        0,  # heater unstable
    )

    reader = pimoroni_bme690.PimoroniBME690(
        temp_offset=0.0,
        hum_offset=0.0,
    )

    *_vals, heater = reader.read()
    assert heater == "Unstable"


def test_init_starts_periodic_timer_at_configured_interval() -> None:
    FakeBreakoutBME69X.next_reading = (0.0, 0.0, 0.0, 0.0, 0)

    timer_factory, timers = make_timer_factory()

    reader = pimoroni_bme690.PimoroniBME690(
        temp_offset=0.0,
        hum_offset=0.0,
        sensor_read_delay_ms=7000,
        timer_factory=timer_factory,
    )

    assert len(timers) == 1
    call = timers[0].init_calls[0]
    assert call["period"] == 7000
    import machine
    assert call["mode"] == machine.Timer.PERIODIC
    assert callable(call["callback"])
    # Initial read happens synchronously in __init__.
    assert reader._bme.read_count == 1


def test_timer_callback_schedules_read_and_guards_reentry() -> None:
    FakeBreakoutBME69X.next_reading = (10.0, 100_000.0, 40.0, 1_000.0, 0)

    scheduled: list[tuple] = []

    reader = pimoroni_bme690.PimoroniBME690(
        temp_offset=0.0,
        hum_offset=0.0,
        schedule=lambda fn, arg: scheduled.append((fn, arg)),
        timer_factory=FakeTimer,
    )

    initial_reads = reader._bme.read_count

    # Two IRQ fires back-to-back before the scheduled callback runs →
    # second one must be a no-op to avoid double-scheduling the read.
    reader._timer_callback(None)
    reader._timer_callback(None)
    assert len(scheduled) == 1

    # Run the deferred read and confirm _pending is released.
    fn, arg = scheduled[0]
    fn(arg)
    assert reader._bme.read_count == initial_reads + 1
    assert reader._pending is False

    # Next IRQ now schedules again.
    reader._timer_callback(None)
    assert len(scheduled) == 2


def test_timer_callback_clears_pending_if_schedule_raises() -> None:
    FakeBreakoutBME69X.next_reading = (0.0, 0.0, 0.0, 0.0, 0)

    def raising_schedule(_fn, _arg):
        raise RuntimeError("queue full")

    reader = pimoroni_bme690.PimoroniBME690(
        temp_offset=0.0,
        hum_offset=0.0,
        schedule=raising_schedule,
        timer_factory=FakeTimer,
    )

    reader._timer_callback(None)
    # _pending must roll back so the next timer IRQ can retry.
    assert reader._pending is False
