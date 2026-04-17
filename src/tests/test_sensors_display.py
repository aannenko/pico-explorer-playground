from __future__ import annotations

import time

import displays.sensors as sensors


class _FakeTime:
    def __init__(self, fn):
        self.now = fn


class FakeRenderer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.update_calls = 0

    def reset(self) -> None:
        self.calls.append(("reset", (), {}))

    def header_write(self, text: str) -> None:
        self.calls.append(("header_write", (text,), {}))

    def value_write(self, line_idx: int, text: str) -> None:
        self.calls.append(("value_write", (line_idx, text), {}))

    def secondary_write(self, line_idx: int, text: str) -> None:
        self.calls.append(("secondary_write", (line_idx, text), {}))

    def update(self) -> None:
        self.update_calls += 1


class FakeBME690Reader:
    def __init__(self, reading: tuple[float, float, float, float, str]) -> None:
        self._reading = reading

    def read(self) -> tuple[float, float, float, float, str]:
        return self._reading


def test_update_display_formats_header_and_sensor_lines(monkeypatch) -> None:
    renderer = FakeRenderer()

    # Make gmtime deterministic.
    monkeypatch.setattr(
        time,
        "gmtime",
        lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0),
    )

    reading = (22.4, 963.11, 25.7, 65.674, "Stable")
    d = sensors.Display(
        renderer=renderer,
        bme690_reader=FakeBME690Reader(reading),
        time_service=_FakeTime(lambda: 0),
    )

    d._update_display()

    assert ("header_write", ("'26-01-04 13:05",), {}) in renderer.calls
    assert ("value_write", (0, "Temp: 22.4 C"), {}) in renderer.calls
    assert ("secondary_write", (1, "Prsr: 963 mb"), {}) in renderer.calls
    assert ("secondary_write", (2, "Hum: 25.70 %"), {}) in renderer.calls
    assert ("secondary_write", (3, "GasR: 65.7 kOhm"), {}) in renderer.calls
    assert ("secondary_write", (4, "Stat: Stable"), {}) in renderer.calls
    assert renderer.update_calls == 1


def test_initialize_renders_and_is_idempotent(monkeypatch) -> None:
    renderer = FakeRenderer()

    monkeypatch.setattr(
        time,
        "gmtime",
        lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0),
    )

    d = sensors.Display(
        renderer=renderer,
        bme690_reader=FakeBME690Reader((22.4, 963.11, 25.7, 65.674, "Stable")),
        time_service=_FakeTime(lambda: 0),
    )

    d.initialize()

    assert d._active is True
    assert ("reset", (), {}) in renderer.calls
    assert renderer.update_calls == 1

    # Idempotent — second call should not reset or update again.
    renderer.calls.clear()
    renderer.update_calls = 0
    d.initialize()
    assert renderer.calls == []
    assert renderer.update_calls == 0


def test_deinitialize_sets_inactive_and_is_idempotent(monkeypatch) -> None:
    renderer = FakeRenderer()

    monkeypatch.setattr(
        time,
        "gmtime",
        lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0),
    )

    d = sensors.Display(
        renderer=renderer,
        bme690_reader=FakeBME690Reader((0.0, 0.0, 0.0, 0.0, "Stable")),
        time_service=_FakeTime(lambda: 0),
    )

    d.initialize()
    d.deinitialize()

    assert d._active is False

    # Idempotent
    d.deinitialize()
    assert d._active is False
