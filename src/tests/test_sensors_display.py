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


# Band kwargs for Display(...) constructions; values chosen for clear
# band-boundary coverage in the assertions below.
_TEST_BAND_KWARGS = {
    "temp_bands": (12, 24, 28),
    "pressure_bands": (1000, 1013, 1025),
    "humidity_bands": (30, 50, 70),
    "gas_bands": (50, 100, 200),
}


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
        **_TEST_BAND_KWARGS,
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


def test_three_digit_gas_value_renders_without_decimal(monkeypatch) -> None:
    renderer = FakeRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    reading = (22.4, 963.0, 25.7, 250.7, "Stable")
    d = sensors.Display(
        renderer=renderer,
        bme690_reader=FakeBME690Reader(reading),
        time_service=_FakeTime(lambda: 0),
        **_TEST_BAND_KWARGS,
    )

    d._update_display()

    # Two-digit rows keep the decimal; gas at >=100 drops it.
    assert ("value_write", (0, "22.4"), {}) in renderer.calls
    assert ("value_write", (2, "25.7"), {}) in renderer.calls
    assert ("value_write", (3, "251"), {}) in renderer.calls


def test_gas_row_shows_warming_when_heater_unstable(monkeypatch) -> None:
    renderer = FakeRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    d = sensors.Display(
        renderer=renderer,
        bme690_reader=FakeBME690Reader((20.0, 1000.0, 50.0, 42.0, "Warming")),
        time_service=_FakeTime(lambda: 0),
        **_TEST_BAND_KWARGS,
    )

    d._update_display()

    assert ("value_write", (3, "warming..."), {}) in renderer.calls
    # No kOhm number when not stable.
    assert not any(c[0] == "value_write" and c[1][0] == 3 and c[1][1] != "warming..." for c in renderer.calls)


def test_icon_for_value_classifies_each_metric() -> None:
    import displays.shared.icons_symbols as ics
    fn = sensors.Display._icon_for_value
    # _icon_for_value is a @staticmethod — drive it directly from the static
    # ROWS schema + the test band tuples, no Display instance needed.
    bands_by_row = (
        _TEST_BAND_KWARGS["temp_bands"],
        _TEST_BAND_KWARGS["pressure_bands"],
        _TEST_BAND_KWARGS["humidity_bands"],
        _TEST_BAND_KWARGS["gas_bands"],
    )
    rows = [
        (sensors.Display.ROWS[i][0], bands_by_row[i], sensors.Display.ROWS[i][1])
        for i in range(len(sensors.Display.ROWS))
    ]

    # Row 0 — Temperature (°C): blue<12 ≤ green<24 ≤ yellow<28 ≤ red.
    _u, bands, icons = rows[0]
    assert fn(-5.0,  bands, icons) == ics.ICON_THERMO_BLUE
    assert fn(11.99, bands, icons) == ics.ICON_THERMO_BLUE
    assert fn(12.0,  bands, icons) == ics.ICON_THERMO_GREEN
    assert fn(23.99, bands, icons) == ics.ICON_THERMO_GREEN
    assert fn(24.0,  bands, icons) == ics.ICON_THERMO_YELLOW
    assert fn(27.99, bands, icons) == ics.ICON_THERMO_YELLOW
    assert fn(28.0,  bands, icons) == ics.ICON_THERMO_RED
    assert fn(45.0,  bands, icons) == ics.ICON_THERMO_RED

    # Row 1 — Pressure (hPa): low<1000 ≤ mid_low<1013 ≤ mid_high<1025 ≤ high.
    _u, bands, icons = rows[1]
    assert fn(980.0,   bands, icons) == ics.ICON_GAUGE_LOW
    assert fn(999.99,  bands, icons) == ics.ICON_GAUGE_LOW
    assert fn(1000.0,  bands, icons) == ics.ICON_GAUGE_MID_LOW
    assert fn(1012.99, bands, icons) == ics.ICON_GAUGE_MID_LOW
    assert fn(1013.0,  bands, icons) == ics.ICON_GAUGE_MID_HIGH
    assert fn(1024.99, bands, icons) == ics.ICON_GAUGE_MID_HIGH
    assert fn(1025.0,  bands, icons) == ics.ICON_GAUGE_HIGH
    assert fn(1040.0,  bands, icons) == ics.ICON_GAUGE_HIGH

    # Row 2 — Humidity (%RH): low<30 ≤ mid_low<50 ≤ mid_high<70 ≤ high.
    _u, bands, icons = rows[2]
    assert fn(0.0,   bands, icons) == ics.ICON_DROP_LOW
    assert fn(29.99, bands, icons) == ics.ICON_DROP_LOW
    assert fn(30.0,  bands, icons) == ics.ICON_DROP_MID_LOW
    assert fn(49.99, bands, icons) == ics.ICON_DROP_MID_LOW
    assert fn(50.0,  bands, icons) == ics.ICON_DROP_MID_HIGH
    assert fn(69.99, bands, icons) == ics.ICON_DROP_MID_HIGH
    assert fn(70.0,  bands, icons) == ics.ICON_DROP_HIGH
    assert fn(100.0, bands, icons) == ics.ICON_DROP_HIGH

    # Row 3 — Gas resistance (kΩ): low<50 ≤ mid_low<100 ≤ mid_high<200 ≤ high.
    _u, bands, icons = rows[3]
    assert fn(10.0,   bands, icons) == ics.ICON_GAS_LOW
    assert fn(49.99,  bands, icons) == ics.ICON_GAS_LOW
    assert fn(50.0,   bands, icons) == ics.ICON_GAS_MID_LOW
    assert fn(99.99,  bands, icons) == ics.ICON_GAS_MID_LOW
    assert fn(100.0,  bands, icons) == ics.ICON_GAS_MID_HIGH
    assert fn(199.99, bands, icons) == ics.ICON_GAS_MID_HIGH
    assert fn(200.0,  bands, icons) == ics.ICON_GAS_HIGH
    assert fn(500.0,  bands, icons) == ics.ICON_GAS_HIGH


def test_rows_schema_invariants(monkeypatch) -> None:
    """ROWS holds static (unit, icons); ``_rows`` adds validated bands."""
    # Static class-level ROWS: (unit_cell, icons) 2-tuples.
    for i, row in enumerate(sensors.Display.ROWS):
        assert len(row) == 2, f"ROWS[{i}] must be (unit, icons)"
        unit, icons = row
        assert len(unit) == 2, f"ROWS[{i}] unit_cell must be (sx, sy)"
        assert len(icons) == 4, f"ROWS[{i}] icons must hold 4 cells"
        for cell in icons:
            assert len(cell) == 2, f"ROWS[{i}] icons must contain (sx, sy) tuples"

    # Per-instance _rows: (unit, bands, icons) with validated 3-element
    # ascending band tuples.
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))
    d = sensors.Display(
        renderer=FakeRenderer(),
        bme690_reader=FakeBME690Reader((20.0, 1005.0, 40.0, 70.0, "Stable")),
        time_service=_FakeTime(lambda: 0),
        **_TEST_BAND_KWARGS,
    )
    assert len(d._rows) == len(sensors.Display.ROWS)
    for i, row in enumerate(d._rows):
        assert len(row) == 3, f"_rows[{i}] must be (unit, bands, icons)"
        unit, bands, icons = row
        assert unit == sensors.Display.ROWS[i][0]
        assert icons == sensors.Display.ROWS[i][1]
        assert len(bands) == 3, f"_rows[{i}] bands must hold 3 thresholds"
        assert list(bands) == sorted(bands), f"_rows[{i}] bands must be ascending"


def test_band_change_triggers_single_icon_repaint_per_metric(monkeypatch) -> None:
    import displays.shared.icons_symbols as ics
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    renderer = FakeRenderer()
    # Reading chosen so every metric lands in its default band → no swaps
    # during initialize().
    reader = FakeBME690Reader((20.0, 1005.0, 40.0, 70.0, "Stable"))
    d = sensors.Display(
        renderer=renderer,
        bme690_reader=reader,
        time_service=_FakeTime(lambda: 0),
        **_TEST_BAND_KWARGS,
    )
    d.initialize()

    # initialize() pre-set _row_icons to each row's MID_LOW-band icon, so
    # the first _update_display inside initialize() must NOT repaint any icon.
    assert not any(c[0] == "redraw_row_icon" for c in renderer.calls)

    # Same bands on next tick — still no repaint.
    renderer.calls.clear()
    reader._reading = (21.5, 1010.0, 45.0, 80.0, "Stable")
    d._update_display()
    assert not any(c[0] == "redraw_row_icon" for c in renderer.calls)

    # Crossing temperature into yellow band — exactly one repaint, row 0.
    renderer.calls.clear()
    reader._reading = (25.0, 1010.0, 45.0, 80.0, "Stable")
    d._update_display()
    repaints = [c for c in renderer.calls if c[0] == "redraw_row_icon"]
    assert repaints == [("redraw_row_icon", (0, ics.ICON_THERMO_YELLOW), {})]

    # Crossing pressure into HIGH band — exactly one repaint, row 1.
    renderer.calls.clear()
    reader._reading = (25.0, 1030.0, 45.0, 80.0, "Stable")
    d._update_display()
    repaints = [c for c in renderer.calls if c[0] == "redraw_row_icon"]
    assert repaints == [("redraw_row_icon", (1, ics.ICON_GAUGE_HIGH), {})]

    # Crossing humidity into HIGH band — exactly one repaint, row 2.
    renderer.calls.clear()
    reader._reading = (25.0, 1030.0, 75.0, 80.0, "Stable")
    d._update_display()
    repaints = [c for c in renderer.calls if c[0] == "redraw_row_icon"]
    assert repaints == [("redraw_row_icon", (2, ics.ICON_DROP_HIGH), {})]

    # Crossing gas into MID_HIGH band — exactly one repaint, row 3.
    renderer.calls.clear()
    reader._reading = (25.0, 1030.0, 75.0, 150.0, "Stable")
    d._update_display()
    repaints = [c for c in renderer.calls if c[0] == "redraw_row_icon"]
    assert repaints == [("redraw_row_icon", (3, ics.ICON_GAS_MID_HIGH), {})]

    # Dropping temperature into blue — single row-0 repaint.
    renderer.calls.clear()
    reader._reading = (5.0, 1030.0, 75.0, 150.0, "Stable")
    d._update_display()
    repaints = [c for c in renderer.calls if c[0] == "redraw_row_icon"]
    assert repaints == [("redraw_row_icon", (0, ics.ICON_THERMO_BLUE), {})]


def test_gas_icon_stays_put_while_heater_warms(monkeypatch) -> None:
    """While ``status != "Stable"`` the gas row icon must not follow gas_r."""
    import displays.shared.icons_symbols as ics
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    renderer = FakeRenderer()
    reader = FakeBME690Reader((20.0, 1005.0, 40.0, 70.0, "Stable"))
    d = sensors.Display(
        renderer=renderer,
        bme690_reader=reader,
        time_service=_FakeTime(lambda: 0),
        **_TEST_BAND_KWARGS,
    )
    d.initialize()
    assert d._row_icons[3] == ics.ICON_GAS_MID_LOW

    # New reading: gas value would change band, but heater is warming → no swap.
    renderer.calls.clear()
    reader._reading = (20.0, 1005.0, 40.0, 250.0, "Warming")
    d._update_display()
    assert not any(
        c[0] == "redraw_row_icon" and c[1][0] == 3 for c in renderer.calls
    )
    assert d._row_icons[3] == ics.ICON_GAS_MID_LOW

    # When the heater stabilises again, the icon catches up in a single swap.
    renderer.calls.clear()
    reader._reading = (20.0, 1005.0, 40.0, 250.0, "Stable")
    d._update_display()
    repaints = [c for c in renderer.calls if c[0] == "redraw_row_icon"]
    assert repaints == [("redraw_row_icon", (3, ics.ICON_GAS_HIGH), {})]


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
        **_TEST_BAND_KWARGS,
    )

    d.initialize()

    assert d._active is True
    assert ("reset", (), {}) in renderer.calls
    # Display no longer loads the spritesheet — app.build_app does that once
    # at startup while the heap is fresh.
    assert not any(c[0] == "load_spritesheet" for c in renderer.calls)
    # One draw_left_column call per configured row, in order. The default
    # icon for each row is the MID_LOW-band icon (icons[1]).
    dlc_calls = [c for c in renderer.calls if c[0] == "draw_left_column"]
    assert len(dlc_calls) == len(sensors.Display.ROWS)
    for i, (unit, icons) in enumerate(sensors.Display.ROWS):
        default_icon = icons[1]
        assert dlc_calls[i] == ("draw_left_column", (i, default_icon, unit), {})
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
        **_TEST_BAND_KWARGS,
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
        **_TEST_BAND_KWARGS,
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
        **_TEST_BAND_KWARGS,
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
        **_TEST_BAND_KWARGS,
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
        **_TEST_BAND_KWARGS,
    )

    d.initialize()
    d.deinitialize()

    assert d._active is False

    # Idempotent
    d.deinitialize()
    assert d._active is False


def test_bands_validation_rejects_wrong_length() -> None:
    """``_validated_bands`` rejects band tuples that don't hold exactly 3 thresholds."""
    import pytest
    for row_index in range(len(sensors.Display.ROWS)):
        for bad_value in ((10, 20), (10, 20, 30, 40), ()):
            with pytest.raises(ValueError, match="3 band thresholds"):
                sensors.Display._validated_bands(row_index, bad_value)


def test_bands_validation_rejects_non_ascending() -> None:
    """``_validated_bands`` rejects band tuples that aren't strictly ascending."""
    import pytest
    for row_index in range(len(sensors.Display.ROWS)):
        for bad_value in ((10, 20, 20), (10, 30, 20), (30, 20, 10), (10, 10, 30)):
            with pytest.raises(ValueError, match="strictly ascending"):
                sensors.Display._validated_bands(row_index, bad_value)
