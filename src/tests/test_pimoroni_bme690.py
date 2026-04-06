from __future__ import annotations

from dataclasses import dataclass

import services.sensors.pimoroni_bme690 as pimoroni_bme690


class FakeI2C:
    def __init__(self, **kwargs) -> None:
        self.kwargs = dict(kwargs)


class FakeBreakoutBME69X:
    next_reading: tuple[float, float, float, float, int] = (0.0, 0.0, 0.0, 0.0, 0)

    def __init__(self, i2c: FakeI2C) -> None:
        self.i2c = i2c
        self.configure_calls: list[tuple[object, ...]] = []

    def configure(self, *args) -> None:
        self.configure_calls.append(tuple(args))

    def read(self):
        # Return a tuple long enough for slicing [0:5]
        temp, press, hum, gas_r, status = self.next_reading
        return (temp, press, hum, gas_r, status, 123, 456)


@dataclass
class FakeTimer:
    timer_id: int

    def init(self, **_kwargs) -> None:
        pass

    def deinit(self) -> None:
        pass


def _noop_schedule(fn, arg):
    # Don't call fn — we only want the initial _do_read in the constructor.
    pass


def test_read_applies_offsets_converts_units_and_stable_status(monkeypatch) -> None:
    monkeypatch.setattr(pimoroni_bme690, "PimoroniI2C", FakeI2C)
    monkeypatch.setattr(pimoroni_bme690, "PICO_EXPLORER_I2C_PINS", {"sda": 4, "scl": 5})
    monkeypatch.setattr(pimoroni_bme690, "BreakoutBME69X", FakeBreakoutBME69X)

    monkeypatch.setattr(pimoroni_bme690, "STATUS_HEATER_STABLE", 0b10)
    monkeypatch.setattr(pimoroni_bme690, "FILTER_COEFF_3", 3)
    monkeypatch.setattr(pimoroni_bme690, "STANDBY_TIME_1000_MS", 1000)
    monkeypatch.setattr(pimoroni_bme690, "OVERSAMPLING_2X", 2)
    monkeypatch.setattr(pimoroni_bme690, "OVERSAMPLING_1X", 1)

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
        schedule=_noop_schedule,
        timer_factory=FakeTimer,
    )

    temp, press_mb, hum, gas_kohm, heater = reader.read()

    assert temp == 21.5
    assert press_mb == 1000.0
    assert hum == 48.0
    assert gas_kohm == 2.5
    assert heater == "Stable"


def test_read_maps_unstable_status(monkeypatch) -> None:
    monkeypatch.setattr(pimoroni_bme690, "PimoroniI2C", FakeI2C)
    monkeypatch.setattr(pimoroni_bme690, "PICO_EXPLORER_I2C_PINS", {"sda": 4, "scl": 5})
    monkeypatch.setattr(pimoroni_bme690, "BreakoutBME69X", FakeBreakoutBME69X)

    monkeypatch.setattr(pimoroni_bme690, "STATUS_HEATER_STABLE", 0b10)

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
        schedule=_noop_schedule,
        timer_factory=FakeTimer,
    )

    *_vals, heater = reader.read()
    assert heater == "Unstable"
