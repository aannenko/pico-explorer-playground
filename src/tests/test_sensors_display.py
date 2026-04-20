from __future__ import annotations

import time

import displays.sensors as sensors

from conftest import RecordingRenderer


class _FakeTime:
    def __init__(self, fn):
        self.now = fn


class FakeRenderer(RecordingRenderer):
    pass


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

    assert ("header_write", ("2026-01-04 13:05",), {}) in renderer.calls
    # Values are bare numbers — unit and label live in the left column sprites.
    assert ("value_write", (0, "22.4"), {}) in renderer.calls
    assert ("value_write", (1, "963"), {}) in renderer.calls
    assert ("value_write", (2, "25.7"), {}) in renderer.calls
    assert ("value_write", (3, "65.7"), {}) in renderer.calls
    # No Stat: row — status is fused into the gas row.
    assert not any(c[0] == "secondary_write" and c[1][0] == 4 for c in renderer.calls)
    assert renderer.update_calls == 1


def test_gas_row_shows_warming_when_heater_unstable(monkeypatch) -> None:
    renderer = FakeRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    d = sensors.Display(
        renderer=renderer,
        bme690_reader=FakeBME690Reader((20.0, 1000.0, 50.0, 42.0, "Warming")),
        time_service=_FakeTime(lambda: 0),
    )

    d._update_display()

    assert ("value_write", (3, "warming..."), {}) in renderer.calls
    # No kOhm number when not stable.
    assert not any(c[0] == "value_write" and c[1][0] == 3 and c[1][1] != "warming..." for c in renderer.calls)


def test_thermo_cell_for_covers_all_four_bands() -> None:
    import displays.shared.icons_symbols as ics
    fn = sensors.Display._thermo_cell_for

    # Deep cold
    assert fn(-5.0) == ics.ICON_THERMO_BLUE
    assert fn(11.99) == ics.ICON_THERMO_BLUE
    # Green band: [12, 24)
    assert fn(12.0) == ics.ICON_THERMO_GREEN
    assert fn(23.99) == ics.ICON_THERMO_GREEN
    # Yellow band: [24, 28)
    assert fn(24.0) == ics.ICON_THERMO_YELLOW
    assert fn(27.99) == ics.ICON_THERMO_YELLOW
    # Red: >= 28
    assert fn(28.0) == ics.ICON_THERMO_RED
    assert fn(45.0) == ics.ICON_THERMO_RED


def test_temperature_band_change_triggers_single_icon_repaint(monkeypatch) -> None:
    import displays.shared.icons_symbols as ics
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    renderer = FakeRenderer()
    reader = FakeBME690Reader((20.0, 1000.0, 50.0, 42.0, "Stable"))  # green band
    d = sensors.Display(
        renderer=renderer,
        bme690_reader=reader,
        time_service=_FakeTime(lambda: 0),
    )
    d.initialize()

    # initialize() pre-set _thermo_cell to GREEN (ROWS[0]) so the first
    # _update_display inside initialize() must NOT repaint the row-0 icon.
    assert not any(c[0] == "redraw_row_icon" for c in renderer.calls)

    # Same band on next tick — still no repaint.
    renderer.calls.clear()
    reader._reading = (21.5, 1000.0, 50.0, 42.0, "Stable")
    d._update_display()
    assert not any(c[0] == "redraw_row_icon" for c in renderer.calls)

    # Crossing into yellow band — exactly one repaint, targeting row 0.
    renderer.calls.clear()
    reader._reading = (25.0, 1000.0, 50.0, 42.0, "Stable")
    d._update_display()
    repaints = [c for c in renderer.calls if c[0] == "redraw_row_icon"]
    assert repaints == [("redraw_row_icon", (0, ics.ICON_THERMO_YELLOW), {})]

    # Crossing into red.
    renderer.calls.clear()
    reader._reading = (30.0, 1000.0, 50.0, 42.0, "Stable")
    d._update_display()
    repaints = [c for c in renderer.calls if c[0] == "redraw_row_icon"]
    assert repaints == [("redraw_row_icon", (0, ics.ICON_THERMO_RED), {})]

    # Dropping into blue.
    renderer.calls.clear()
    reader._reading = (5.0, 1000.0, 50.0, 42.0, "Stable")
    d._update_display()
    repaints = [c for c in renderer.calls if c[0] == "redraw_row_icon"]
    assert repaints == [("redraw_row_icon", (0, ics.ICON_THERMO_BLUE), {})]


def test_initialize_paints_left_column_and_is_idempotent(monkeypatch) -> None:
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
    # Display no longer loads the spritesheet — app.build_app does that once
    # at startup while the heap is fresh.
    assert not any(c[0] == "load_spritesheet" for c in renderer.calls)
    # One draw_left_column call per configured row, in order.
    dlc_calls = [c for c in renderer.calls if c[0] == "draw_left_column"]
    assert len(dlc_calls) == len(sensors.Display.ROWS)
    for i, (icon, unit) in enumerate(sensors.Display.ROWS):
        assert dlc_calls[i] == ("draw_left_column", (i, icon, unit), {})
    assert renderer.update_calls == 1

    # Idempotent — second call should not reset / re-paint icons.
    renderer.calls.clear()
    renderer.update_calls = 0
    d.initialize()
    assert renderer.calls == []
    assert renderer.update_calls == 0


def test_update_display_skips_value_writes_when_reading_unchanged(monkeypatch) -> None:
    renderer = FakeRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    reader = FakeBME690Reader((22.4, 963.11, 25.7, 65.674, "Stable"))
    d = sensors.Display(
        renderer=renderer,
        bme690_reader=reader,
        time_service=_FakeTime(lambda: 0),
    )

    d._update_display()
    first_value_writes = sum(1 for c in renderer.calls if c[0] == "value_write")
    assert first_value_writes == 4

    # Second tick with the exact same tuple object returned — value_write
    # should be skipped entirely (identity compare).
    renderer.calls.clear()
    d._update_display()
    assert not any(c[0] == "value_write" for c in renderer.calls)
    # Header still writes every tick (time advances).
    assert any(c[0] == "header_write" for c in renderer.calls)


def test_update_display_repaints_values_when_reading_tuple_replaced(monkeypatch) -> None:
    renderer = FakeRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    reader = FakeBME690Reader((22.4, 963.11, 25.7, 65.674, "Stable"))
    d = sensors.Display(
        renderer=renderer,
        bme690_reader=reader,
        time_service=_FakeTime(lambda: 0),
    )
    d._update_display()

    # Real PimoroniBME690._do_read swaps _last_reading for a fresh tuple;
    # mimic that with tuple([...]) to defeat CPython's constant-tuple folding
    # (on MicroPython each expression evaluates to a fresh tuple anyway).
    reader._reading = tuple([22.4, 963.11, 25.7, 65.674, "Stable"])
    renderer.calls.clear()
    d._update_display()
    assert sum(1 for c in renderer.calls if c[0] == "value_write") == 4


def test_reinitialize_repaints_values_even_if_reader_returns_same_tuple(monkeypatch) -> None:
    renderer = FakeRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    reader = FakeBME690Reader((22.4, 963.11, 25.7, 65.674, "Stable"))
    d = sensors.Display(
        renderer=renderer,
        bme690_reader=reader,
        time_service=_FakeTime(lambda: 0),
    )
    d.initialize()
    d.deinitialize()
    renderer.calls.clear()
    d.initialize()
    # Even though reader returns the same tuple object, re-entry must paint
    # values (reset() blanked the screen).
    assert sum(1 for c in renderer.calls if c[0] == "value_write") == 4


def test_reinitialize_repaints_left_column(monkeypatch) -> None:
    renderer = FakeRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    d = sensors.Display(
        renderer=renderer,
        bme690_reader=FakeBME690Reader((22.4, 963.11, 25.7, 65.674, "Stable")),
        time_service=_FakeTime(lambda: 0),
    )

    d.initialize()
    d.deinitialize()
    renderer.calls.clear()
    d.initialize()

    # Left column IS re-painted on view re-entry (reset() cleared the screen).
    assert sum(1 for c in renderer.calls if c[0] == "draw_left_column") == len(sensors.Display.ROWS)


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
