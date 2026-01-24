from __future__ import annotations

from dataclasses import dataclass

import machine

import displays.sensors as sensors


class FakeRenderer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.update_calls = 0

    @property
    def value_pen(self) -> int:
        return 11

    @property
    def secondary_pen(self) -> int:
        return 22

    def reset(self) -> None:
        self.calls.append(("reset", (), {}))

    def header_write(self, text: str) -> None:
        self.calls.append(("header_write", (text,), {}))

    def line_write(self, line_idx: int, text: str, *, pen: int) -> None:
        self.calls.append(("line_write", (line_idx, text), {"pen": pen}))

    def update(self) -> None:
        self.update_calls += 1


class FakeBME690Reader:
    def __init__(self, reading: tuple[float, float, float, float, str]) -> None:
        self._reading = reading

    def read(self) -> tuple[float, float, float, float, str]:
        return self._reading


@dataclass
class FakeTimer:
    timer_id: int

    init_calls: list[dict] = None  # type: ignore[assignment]
    deinit_calls: int = 0

    def __post_init__(self) -> None:
        if self.init_calls is None:
            self.init_calls = []

    def init(self, **kwargs) -> None:
        self.init_calls.append(dict(kwargs))

    def deinit(self) -> None:
        self.deinit_calls += 1


def _mk_timer_factory():
    created: list[FakeTimer] = []

    def factory(timer_id: int) -> FakeTimer:
        t = FakeTimer(timer_id)
        created.append(t)
        return t

    return factory, created


def test_update_header_formats_expected_string(monkeypatch) -> None:
    renderer = FakeRenderer()

    # Make gmtime deterministic.
    monkeypatch.setattr(
        sensors.time,
        "gmtime",
        lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0),
    )

    d = sensors.Display(
        renderer=renderer,
        bme690_reader=FakeBME690Reader((0.0, 0.0, 0.0, 0.0, "Stable")),
        sensor_read_delay_ms=5000,
        time_zone_offset=0,
        get_time=lambda: 0,
        schedule=lambda fn, arg: fn(arg),
        timer_factory=lambda _id: FakeTimer(_id),
    )

    d._update_header(0)

    assert ("header_write", ("'26-01-04 13:05",), {}) in renderer.calls
    assert renderer.update_calls == 1


def test_update_sensor_writes_lines_with_primary_and_secondary_pens() -> None:
    renderer = FakeRenderer()

    reading = (22.4, 963.11, 25.7, 65.674, "Stable")
    d = sensors.Display(
        renderer=renderer,
        bme690_reader=FakeBME690Reader(reading),
        sensor_read_delay_ms=5000,
        time_zone_offset=0,
        get_time=lambda: 0,
        schedule=lambda fn, arg: fn(arg),
        timer_factory=lambda _id: FakeTimer(_id),
    )

    d._update_sensor(0)

    # First line uses value_pen, others secondary_pen.
    assert ("line_write", (0, "Temp: 22.4 C"), {"pen": 11}) in renderer.calls
    assert ("line_write", (1, "Prsr: 963 mb"), {"pen": 22}) in renderer.calls
    assert ("line_write", (2, "Hum: 25.70 %"), {"pen": 22}) in renderer.calls
    assert ("line_write", (3, "GasR: 65.7 kOhm"), {"pen": 22}) in renderer.calls
    assert ("line_write", (4, "Stat: Stable"), {"pen": 22}) in renderer.calls
    assert renderer.update_calls == 1


def test_initialize_starts_timers_and_is_idempotent(monkeypatch) -> None:
    timer_factory, timers = _mk_timer_factory()
    renderer = FakeRenderer()

    monkeypatch.setattr(
        sensors.time,
        "gmtime",
        lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0),
    )

    d = sensors.Display(
        renderer=renderer,
        bme690_reader=FakeBME690Reader((22.4, 963.11, 25.7, 65.674, "Stable")),
        sensor_read_delay_ms=5000,
        time_zone_offset=0,
        get_time=lambda: 0,
        schedule=lambda fn, arg: fn(arg),
        timer_factory=timer_factory,
    )

    d.initialize()

    assert len(timers) == 2
    seconds_timer, sensor_timer = timers

    assert seconds_timer.init_calls == [
        {
            "mode": machine.Timer.PERIODIC,
            "period": 1000,
            "callback": d._schedule_update_header_ref,
        }
    ]
    assert sensor_timer.init_calls == [
        {
            "mode": machine.Timer.PERIODIC,
            "period": 5000,
            "callback": d._schedule_update_sensor_ref,
        }
    ]

    # Idempotent
    d.initialize()
    assert seconds_timer.init_calls == [
        {
            "mode": machine.Timer.PERIODIC,
            "period": 1000,
            "callback": d._schedule_update_header_ref,
        }
    ]


def test_deinitialize_deinits_timers_and_is_idempotent() -> None:
    timer_factory, timers = _mk_timer_factory()
    renderer = FakeRenderer()

    d = sensors.Display(
        renderer=renderer,
        bme690_reader=FakeBME690Reader((0.0, 0.0, 0.0, 0.0, "Stable")),
        sensor_read_delay_ms=5000,
        time_zone_offset=0,
        get_time=lambda: 0,
        schedule=lambda fn, arg: fn(arg),
        timer_factory=timer_factory,
    )

    d.initialize()
    d.deinitialize()

    assert d._active is False
    assert [t.deinit_calls for t in timers] == [1, 1]

    d.deinitialize()
    assert [t.deinit_calls for t in timers] == [1, 1]
