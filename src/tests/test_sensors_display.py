from __future__ import annotations

import time

import displays.sensors as sensors

from conftest import RecordingRenderer


class _FakeTime:
    def __init__(self, fn):
        self.now = fn


class FakeBME690Reader:
    def __init__(self, reading: tuple[float, float, float, float, str]) -> None:
        self._reading = reading

    def read(self) -> tuple[float, float, float, float, str]:
        return self._reading


class _FakeRingHistory:
    """Allocation-lean stand-in for ``services.ring_history.RingHistory``.

    Stores explicit per-metric sample lists (newest first) so display tests can
    set up partial-fill / wrap scenarios with no math.  ``commit_count`` is
    mutable so tests can simulate a commit without actually pushing samples.
    """

    def __init__(self, capacity: int = 108) -> None:
        self.capacity = capacity
        self.commit_count = 0
        # Per-metric list of samples, newest first.  Empty == nothing to draw.
        self._samples: list[list[float]] = [[] for _ in range(4)]

    def filled(self, metric_idx: int) -> int:
        return min(len(self._samples[metric_idx]), self.capacity)

    def value_at(self, metric_idx: int, value_idx: int) -> float:
        return self._samples[metric_idx][value_idx]

    def set_samples(self, metric_idx: int, samples_newest_first: list[float]) -> None:
        self._samples[metric_idx] = list(samples_newest_first)

    def bump_commit(self) -> None:
        self.commit_count += 1


# A 4×4×2 band-pen fake; each pen is a distinct int so test assertions can
# pinpoint which (metric, band, pastel/bright) triggered a draw.
def _make_band_pens() -> tuple:
    """metric m, band b, pen kind k (0=pastel, 1=bright) → 1000 + m*100 + b*10 + k."""
    return tuple(
        tuple(
            (1000 + m * 100 + b * 10 + 0, 1000 + m * 100 + b * 10 + 1)
            for b in range(4)
        )
        for m in range(4)
    )


_FAKE_BAND_PENS = _make_band_pens()
_FAKE_GRAPH_HEIGHT = 24


# Band kwargs for Display(...) constructions; values chosen for clear
# band-boundary coverage in the assertions below.  5 edges:
# (cap_min, t1, t2, t3, cap_max).
_TEST_BAND_KWARGS = {
    "temp_bands": (0, 12, 24, 28, 40),
    "pressure_bands": (980, 1000, 1013, 1025, 1040),
    "humidity_bands": (10, 30, 50, 70, 90),
    "gas_bands": (10, 50, 100, 200, 400),
}


def _make_display(
    renderer=None,
    reader=None,
    history=None,
    *,
    band_kwargs=None,
):
    """Construct a sensors.Display with sensible test defaults.

    Keeps individual tests focused on behavior rather than constructor noise.
    """
    return sensors.Display(
        renderer=renderer or RecordingRenderer(),
        bme690_reader=reader or FakeBME690Reader((22.0, 1010.0, 50.0, 100.0, "Stable")),
        time_service=_FakeTime(lambda: 0),
        history=history or _FakeRingHistory(),
        band_pens=_FAKE_BAND_PENS,
        graph_height=_FAKE_GRAPH_HEIGHT,
        **(band_kwargs or _TEST_BAND_KWARGS),
    )


def test_update_display_formats_header_and_sensor_lines(monkeypatch) -> None:
    renderer = RecordingRenderer()

    # Make gmtime deterministic.
    monkeypatch.setattr(
        time,
        "gmtime",
        lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0),
    )

    reading = (22.4, 963.11, 25.7, 65.674, "Stable")
    d = _make_display(renderer=renderer, reader=FakeBME690Reader(reading))

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


def test_gas_value_drops_decimal_at_or_above_100(monkeypatch) -> None:
    """Per the formatter rule (decimal only when ``-100 < value < 100``),
    a gas reading of 250.7 kΩ drops to integer ``"251"``."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    reading = (22.4, 963.0, 25.7, 250.7, "Stable")
    d = _make_display(renderer=renderer, reader=FakeBME690Reader(reading))
    d._update_display()

    # Temperature / humidity below 100 keep their decimal; gas at 250.7 drops it.
    assert ("value_write", (0, "22.4"), {}) in renderer.calls
    assert ("value_write", (2, "25.7"), {}) in renderer.calls
    assert ("value_write", (3, "251"), {}) in renderer.calls


def test_gas_value_renders_as_integer_at_boundary_99_9(monkeypatch) -> None:
    """``999.9`` is >= 100 → integer branch → ``round(999.9) == 1000``."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    d = _make_display(renderer=renderer, reader=FakeBME690Reader((22.4, 1010.0, 50.0, 999.9, "Stable")))
    d._update_display()
    assert ("value_write", (3, "1000"), {}) in renderer.calls


def test_humidity_drops_decimal_at_100(monkeypatch) -> None:
    """At 100 the in-range window ``(-100, 100)`` excludes the value (not
    strictly less than 100), so the integer branch fires → ``"100"``."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    d = _make_display(renderer=renderer, reader=FakeBME690Reader((22.0, 1010.0, 100.0, 65.0, "Stable")))
    d._update_display()
    assert ("value_write", (2, "100"), {}) in renderer.calls

    # 99.9 stays inside the window, keeps the decimal.
    d2 = _make_display(renderer=RecordingRenderer(), reader=FakeBME690Reader((22.0, 1010.0, 99.9, 65.0, "Stable")))
    d2._update_display()
    assert any(c == ("value_write", (2, "99.9"), {}) for c in d2._renderer.calls)


def test_negative_temperature_keeps_decimal_inside_range(monkeypatch) -> None:
    """``-12.3`` is inside ``(-100, 100)`` → decimal preserved.  ``-100.7``
    falls outside → integer branch → ``"-101"``."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    d = _make_display(renderer=renderer, reader=FakeBME690Reader((-12.3, 1010.0, 50.0, 65.0, "Stable")))
    d._update_display()
    assert ("value_write", (0, "-12.3"), {}) in renderer.calls

    # -99.9 stays inside the range (5 cells, 63 px, fits the budget).
    d2 = _make_display(renderer=RecordingRenderer(), reader=FakeBME690Reader((-99.9, 1010.0, 50.0, 65.0, "Stable")))
    d2._update_display()
    assert any(c == ("value_write", (0, "-99.9"), {}) for c in d2._renderer.calls)

    # -100.7 → integer branch → "-101" (4 cells).
    d3 = _make_display(renderer=RecordingRenderer(), reader=FakeBME690Reader((-100.7, 1010.0, 50.0, 65.0, "Stable")))
    d3._update_display()
    assert any(c == ("value_write", (0, "-101"), {}) for c in d3._renderer.calls)


def test_extreme_gas_value_is_clamped_to_9999(monkeypatch) -> None:
    """O1 regression: extreme out-of-range gas resistance (e.g. 50000 kΩ in
    a hypothetical clean-air spike) gets clamped to ``"9999"`` (4 cells,
    57 px on-device) so it can never overdraw the 63 px value cell."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    d = _make_display(renderer=renderer, reader=FakeBME690Reader((22.0, 1010.0, 50.0, 50000.0, "Stable")))
    d._update_display()
    assert ("value_write", (3, "9999"), {}) in renderer.calls


def test_negative_clamp_at_minus_999(monkeypatch) -> None:
    """Symmetric clamp on the negative side: any value rounding below -999
    renders as ``"-999"`` (4 cells, 54 px on-device)."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    d = _make_display(renderer=renderer, reader=FakeBME690Reader((-12000.0, 1010.0, 50.0, 65.0, "Stable")))
    d._update_display()
    assert ("value_write", (0, "-999"), {}) in renderer.calls


def test_fit_chars_helper_boundary_cases() -> None:
    """Direct exercise of the formatter to lock in its branch behavior."""
    fn = sensors.Display._fit_chars

    # In-range values (``-100 < round(value, decimals) < 100``) keep the decimal.
    assert fn(22.4, 1) == "22.4"
    assert fn(-9.9, 1) == "-9.9"
    assert fn(99.9, 1) == "99.9"
    assert fn(-99.9, 1) == "-99.9"
    assert fn(-12.3, 1) == "-12.3"
    assert fn(0.0, 1) == "0.0"

    # decimals=0 takes the integer branch unconditionally.
    assert fn(963.0, 0) == "963"
    assert fn(1010.0, 0) == "1010"
    assert fn(-50.0, 0) == "-50"

    # Boundary: at exactly +/-100, value is NOT in the open (-100, 100) range
    # → integer branch.
    assert fn(100.0, 1) == "100"
    assert fn(-100.0, 1) == "-100"

    # Rounding-edge: -99.99 formats to "-100.0" (would overdraw); the rounded
    # value is -100.0 which is NOT > -100, so we take the integer branch.
    assert fn(-99.99, 1) == "-100"
    # Mirror case: 99.99 formats to "100.0" (would fit but cross the rule);
    # rounded value is 100.0 which is NOT < 100, so integer branch fires.
    assert fn(99.99, 1) == "100"

    # Above +/-100 → integer.
    assert fn(250.7, 1) == "251"
    assert fn(999.9, 1) == "1000"
    assert fn(-100.7, 1) == "-101"
    assert fn(1234.7, 1) == "1235"

    # Clamp: integer outputs are bounded so the rendered width can't exceed
    # the 63 px budget set by ``_GRAPH_VALUE_SAMPLE = "-88.8"``.
    assert fn(9999.0, 0) == "9999"
    assert fn(10000.0, 0) == "9999"
    assert fn(99999.0, 1) == "9999"
    assert fn(-999.0, 0) == "-999"
    assert fn(-1000.0, 0) == "-999"
    assert fn(-99999.5, 1) == "-999"


def test_gas_row_shows_warming_when_heater_unstable(monkeypatch) -> None:
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    d = _make_display(renderer=renderer, reader=FakeBME690Reader((20.0, 1000.0, 50.0, 42.0, "Warming")))
    d._update_display()

    assert ("value_write", (3, "warming..."), {}) in renderer.calls
    # No kOhm number when not stable.
    assert not any(c[0] == "value_write" and c[1][0] == 3 and c[1][1] != "warming..." for c in renderer.calls)


def test_band_index_classifies_each_metric() -> None:
    """``_band_index`` returns 0..3 using only the 3 inner edges of the 5-tuple."""
    fn = sensors.Display._band_index

    # Temperature edges: (0, 12, 24, 28, 40) → inner = (12, 24, 28).
    temp = _TEST_BAND_KWARGS["temp_bands"]
    assert fn(-5.0, temp) == 0
    assert fn(11.99, temp) == 0
    assert fn(12.0, temp) == 1
    assert fn(23.99, temp) == 1
    assert fn(24.0, temp) == 2
    assert fn(27.99, temp) == 2
    assert fn(28.0, temp) == 3
    assert fn(45.0, temp) == 3

    # Pressure edges: (980, 1000, 1013, 1025, 1040) → inner = (1000, 1013, 1025).
    press = _TEST_BAND_KWARGS["pressure_bands"]
    assert fn(980.0, press) == 0
    assert fn(999.99, press) == 0
    assert fn(1000.0, press) == 1
    assert fn(1012.99, press) == 1
    assert fn(1013.0, press) == 2
    assert fn(1024.99, press) == 2
    assert fn(1025.0, press) == 3
    assert fn(1040.0, press) == 3

    # Humidity edges: (10, 30, 50, 70, 90) → inner = (30, 50, 70).
    hum = _TEST_BAND_KWARGS["humidity_bands"]
    assert fn(0.0, hum) == 0
    assert fn(29.99, hum) == 0
    assert fn(30.0, hum) == 1
    assert fn(49.99, hum) == 1
    assert fn(50.0, hum) == 2
    assert fn(69.99, hum) == 2
    assert fn(70.0, hum) == 3
    assert fn(100.0, hum) == 3

    # Gas edges: (10, 50, 100, 200, 400) → inner = (50, 100, 200).
    gas = _TEST_BAND_KWARGS["gas_bands"]
    assert fn(10.0, gas) == 0
    assert fn(49.99, gas) == 0
    assert fn(50.0, gas) == 1
    assert fn(99.99, gas) == 1
    assert fn(100.0, gas) == 2
    assert fn(199.99, gas) == 2
    assert fn(200.0, gas) == 3
    assert fn(500.0, gas) == 3


def test_rows_schema_invariants(monkeypatch) -> None:
    """ROWS holds static (unit, icons); ``_rows`` adds validated 5-edge bands."""
    # Static class-level ROWS: (unit_cell, icons) 2-tuples.
    for i, row in enumerate(sensors.Display.ROWS):
        assert len(row) == 2, f"ROWS[{i}] must be (unit, icons)"
        unit, icons = row
        assert len(unit) == 2, f"ROWS[{i}] unit_cell must be (sx, sy)"
        assert len(icons) == 4, f"ROWS[{i}] icons must hold 4 cells"
        for cell in icons:
            assert len(cell) == 2, f"ROWS[{i}] icons must contain (sx, sy) tuples"

    # Per-instance _rows: (unit, edges, icons) with validated 5-element
    # strictly-ascending edge tuples.
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))
    d = _make_display(reader=FakeBME690Reader((20.0, 1005.0, 40.0, 70.0, "Stable")))
    assert len(d._rows) == len(sensors.Display.ROWS)
    for i, row in enumerate(d._rows):
        assert len(row) == 3, f"_rows[{i}] must be (unit, edges, icons)"
        unit, edges, icons = row
        assert unit == sensors.Display.ROWS[i][0]
        assert icons == sensors.Display.ROWS[i][1]
        assert len(edges) == 5, f"_rows[{i}] edges must hold 5 values"
        assert list(edges) == sorted(edges), f"_rows[{i}] edges must be ascending"


def test_band_change_triggers_single_icon_repaint_per_metric(monkeypatch) -> None:
    import displays.shared.icons_symbols as ics
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    renderer = RecordingRenderer()
    # Reading chosen so every metric lands in its default band → no swaps
    # during initialize().
    reader = FakeBME690Reader((20.0, 1005.0, 40.0, 70.0, "Stable"))
    d = _make_display(renderer=renderer, reader=reader)
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

    renderer = RecordingRenderer()
    reader = FakeBME690Reader((20.0, 1005.0, 40.0, 70.0, "Stable"))
    d = _make_display(renderer=renderer, reader=reader)
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
    renderer = RecordingRenderer()

    monkeypatch.setattr(
        time,
        "gmtime",
        lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0),
    )

    d = _make_display(renderer=renderer, reader=FakeBME690Reader((22.4, 963.11, 25.7, 65.674, "Stable")))

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
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    reader = FakeBME690Reader((22.4, 963.11, 25.7, 65.674, "Stable"))
    d = _make_display(renderer=renderer, reader=reader)

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
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    reader = FakeBME690Reader((22.4, 963.11, 25.7, 65.674, "Stable"))
    d = _make_display(renderer=renderer, reader=reader)
    d._update_display()

    # Real PimoroniBME690._do_read swaps _last_reading for a fresh tuple;
    # mimic that with tuple([...]) to defeat CPython's constant-tuple folding
    # (on MicroPython each expression evaluates to a fresh tuple anyway).
    reader._reading = tuple([22.4, 963.11, 25.7, 65.674, "Stable"])
    renderer.calls.clear()
    d._update_display()
    assert sum(1 for c in renderer.calls if c[0] == "value_write") == 4


def test_reinitialize_repaints_values_even_if_reader_returns_same_tuple(monkeypatch) -> None:
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    reader = FakeBME690Reader((22.4, 963.11, 25.7, 65.674, "Stable"))
    d = _make_display(renderer=renderer, reader=reader)
    d.initialize()
    d.deinitialize()
    renderer.calls.clear()
    d.initialize()
    # Even though reader returns the same tuple object, re-entry must paint
    # values (reset() blanked the screen).
    assert sum(1 for c in renderer.calls if c[0] == "value_write") == 4


def test_reinitialize_repaints_left_column(monkeypatch) -> None:
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    d = _make_display(renderer=renderer, reader=FakeBME690Reader((22.4, 963.11, 25.7, 65.674, "Stable")))

    d.initialize()
    d.deinitialize()
    renderer.calls.clear()
    d.initialize()

    # Left column IS re-painted on view re-entry (reset() cleared the screen).
    assert sum(1 for c in renderer.calls if c[0] == "draw_left_column") == len(sensors.Display.ROWS)


def test_deinitialize_sets_inactive_and_is_idempotent(monkeypatch) -> None:
    renderer = RecordingRenderer()

    monkeypatch.setattr(
        time,
        "gmtime",
        lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0),
    )

    d = _make_display(renderer=renderer, reader=FakeBME690Reader((0.0, 0.0, 0.0, 0.0, "Stable")))

    d.initialize()
    d.deinitialize()

    assert d._active is False

    # Idempotent
    d.deinitialize()
    assert d._active is False


def test_bands_validation_rejects_wrong_length() -> None:
    """``_validated_bands`` rejects band tuples that don't hold exactly 5 edges."""
    import pytest
    for row_index in range(len(sensors.Display.ROWS)):
        for bad_value in ((10, 20, 30), (10, 20, 30, 40), (10, 20, 30, 40, 50, 60), ()):
            with pytest.raises(ValueError, match="5 band edges"):
                sensors.Display._validated_bands(row_index, bad_value)


def test_bands_validation_rejects_non_ascending() -> None:
    """``_validated_bands`` rejects band tuples that aren't strictly ascending."""
    import pytest
    for row_index in range(len(sensors.Display.ROWS)):
        for bad_value in (
            (10, 20, 20, 30, 40),       # duplicate
            (10, 30, 20, 30, 40),       # out-of-order
            (50, 40, 30, 20, 10),       # reversed
            (10, 10, 30, 40, 50),       # duplicate at start
            (10, 20, 30, 40, 40),       # duplicate at end
        ):
            with pytest.raises(ValueError, match="strictly ascending"):
                sensors.Display._validated_bands(row_index, bad_value)


# ─────────────────────────────────────────────────────────────────────
# Graph rendering: commit-driven redraws, gas warming, NaN, boundaries.
# ─────────────────────────────────────────────────────────────────────


def _graph_calls(renderer: RecordingRenderer) -> list[tuple]:
    """Filter renderer calls down to graph-related ones for readable assertions."""
    return [c for c in renderer.calls if c[0] in ("draw_graph_clear", "draw_graph_column")]


def test_y_for_boundary_values() -> None:
    """``_y_for`` boundary semantics: caps inclusive; out-of-range → None."""
    fn = sensors.Display._y_for
    edges = (10, 12, 24, 28, 40)
    # cap_max = 40 → top (y=0); cap_min = 10 → bottom (y=23).
    assert fn(40.0, edges, 24) == 0
    assert fn(10.0, edges, 24) == 23
    # Out of range: None.
    assert fn(9.99, edges, 24) is None
    assert fn(40.01, edges, 24) is None
    # Midpoint maps near the middle of the range.
    mid = fn(25.0, edges, 24)
    assert mid is not None and 10 <= mid <= 13


def test_first_render_after_commit_triggers_graph_redraw_for_all_metrics(monkeypatch) -> None:
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    history = _FakeRingHistory(capacity=10)
    for m in range(4):
        history.set_samples(m, [25.0])  # one in-range sample for every metric
    history.bump_commit()  # commit_count: 0 → 1 (force first redraw)

    d = _make_display(renderer=renderer, history=history)
    d._update_display()

    # 4 metrics × 1 draw_graph_clear (gas is stable so it's painted too).
    clears = [c for c in _graph_calls(renderer) if c[0] == "draw_graph_clear"]
    assert {c[1][0] for c in clears} == {0, 1, 2, 3}
    # One draw_graph_column per metric (1 sample each).
    cols = [c for c in _graph_calls(renderer) if c[0] == "draw_graph_column"]
    assert sorted(c[1][0] for c in cols) == [0, 1, 2, 3]


def test_subsequent_render_at_same_commit_count_does_not_redraw(monkeypatch) -> None:
    """Dedup invariant: render at unchanged commit + unchanged gas-state must
    issue zero graph draw calls."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    history = _FakeRingHistory()
    history.bump_commit()
    d = _make_display(renderer=renderer, history=history)
    d._update_display()  # initial redraw

    renderer.calls.clear()
    d._update_display()  # same commit_count, same gas-state
    assert _graph_calls(renderer) == []


def test_graph_redraws_when_commit_count_bumps_even_if_reading_identity_unchanged(monkeypatch) -> None:
    """B4 regression: graph redraw lives outside the reading-identity guard."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    history = _FakeRingHistory()
    history.set_samples(0, [22.0])
    d = _make_display(renderer=renderer, history=history)
    d._update_display()  # first redraw fires (last_commit=-1)
    renderer.calls.clear()

    # No new reading tuple (reader returns same object), but a commit happened.
    history.bump_commit()
    history.set_samples(0, [22.5, 22.0])
    d._update_display()

    # draw_graph_clear + at least one draw_graph_column for metric 0.
    graph_calls = _graph_calls(renderer)
    assert any(c[0] == "draw_graph_clear" and c[1][0] == 0 for c in graph_calls)
    assert any(c[0] == "draw_graph_column" and c[1][0] == 0 for c in graph_calls)


def test_gas_row_graph_not_touched_during_steady_warming(monkeypatch) -> None:
    """Steady warming (no transition): zero draw calls on the gas row."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    history = _FakeRingHistory()
    history.set_samples(3, [80.0, 75.0, 70.0])
    history.bump_commit()
    reader = FakeBME690Reader((22.0, 1010.0, 50.0, 75.0, "Warming"))
    d = _make_display(renderer=renderer, reader=reader, history=history)

    # First tick: _gas_was_stable is None → counts as a transition → would
    # clear the gas row once.  Drive to steady-state first.
    d._update_display()
    renderer.calls.clear()

    # Steady-state warming, same commit_count → no graph calls anywhere
    # (gas row owned by "warming..." text).
    d._update_display()
    gas_calls = [
        c for c in _graph_calls(renderer)
        if c[1][0] == 3
    ]
    assert gas_calls == []


def test_warming_to_stable_transition_triggers_gas_redraw(monkeypatch) -> None:
    """The Warming→Stable transition redraws the gas row even without a new commit."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    history = _FakeRingHistory()
    history.set_samples(3, [120.0])
    history.bump_commit()
    reader = FakeBME690Reader((22.0, 1010.0, 50.0, 120.0, "Warming"))
    d = _make_display(renderer=renderer, reader=reader, history=history)
    d._update_display()  # initial render (warming → no gas paint)
    renderer.calls.clear()

    # Flip to Stable WITHOUT a new commit.
    reader._reading = (22.0, 1010.0, 50.0, 120.0, "Stable")
    d._update_display()

    gas_calls = [c for c in _graph_calls(renderer) if c[1][0] == 3]
    # Expect one draw_graph_clear and at least one draw_graph_column.
    assert any(c[0] == "draw_graph_clear" for c in gas_calls)
    assert any(c[0] == "draw_graph_column" for c in gas_calls)


def test_stable_to_warming_transition_clears_gas_row_once(monkeypatch) -> None:
    """R2.3 regression: Stable→Warming clears the gas row once to wipe stale
    columns from the prior Stable state; no draw_graph_column for gas."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    history = _FakeRingHistory()
    history.set_samples(3, [120.0])
    history.bump_commit()
    reader = FakeBME690Reader((22.0, 1010.0, 50.0, 120.0, "Stable"))
    d = _make_display(renderer=renderer, reader=reader, history=history)
    d._update_display()  # Stable: gas row painted
    renderer.calls.clear()

    # Flip to Warming (no commit bump).
    reader._reading = (22.0, 1010.0, 50.0, 120.0, "Warming")
    d._update_display()

    gas_calls = [c for c in _graph_calls(renderer) if c[1][0] == 3]
    assert [c[0] for c in gas_calls] == ["draw_graph_clear"]


def test_subsequent_warming_ticks_do_nothing_to_gas_row(monkeypatch) -> None:
    """After the Stable→Warming clear fires once, subsequent warming ticks do nothing."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    history = _FakeRingHistory()
    history.set_samples(3, [120.0])
    history.bump_commit()
    reader = FakeBME690Reader((22.0, 1010.0, 50.0, 120.0, "Stable"))
    d = _make_display(renderer=renderer, reader=reader, history=history)
    d._update_display()                   # Stable
    reader._reading = (22.0, 1010.0, 50.0, 120.0, "Warming")
    d._update_display()                   # Stable→Warming clear
    renderer.calls.clear()

    d._update_display()                   # steady Warming
    assert _graph_calls(renderer) == []


def test_out_of_cap_value_renders_pastel_only(monkeypatch) -> None:
    """Out-of-cap: bright_pen is None and value_y is None in the draw call."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    # Temperature edges (0, 12, 24, 28, 40) — push value above cap_max.
    history = _FakeRingHistory()
    history.set_samples(0, [100.0])  # > cap_max=40
    history.bump_commit()
    d = _make_display(renderer=renderer, history=history)
    d._update_display()

    col_calls = [c for c in _graph_calls(renderer) if c[0] == "draw_graph_column" and c[1][0] == 0]
    assert len(col_calls) == 1
    _name, args, _kw = col_calls[0]
    line_idx, col, pastel_pen, bright_pen, value_y = args
    # Pastel pen present (band 3 for above-cap), bright suppressed.
    assert pastel_pen == _FAKE_BAND_PENS[0][3][0]
    assert bright_pen is None
    assert value_y is None


def test_in_cap_value_renders_pastel_and_bright(monkeypatch) -> None:
    """In-cap: both pastel and bright pens present; value_y is a valid int."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    history = _FakeRingHistory()
    history.set_samples(0, [25.0])  # in band 2 of (0,12,24,28,40)
    history.bump_commit()
    d = _make_display(renderer=renderer, history=history)
    d._update_display()

    col_calls = [c for c in _graph_calls(renderer) if c[0] == "draw_graph_column" and c[1][0] == 0]
    assert len(col_calls) == 1
    _name, args, _kw = col_calls[0]
    _line, _col, pastel_pen, bright_pen, value_y = args
    assert pastel_pen == _FAKE_BAND_PENS[0][2][0]
    assert bright_pen == _FAKE_BAND_PENS[0][2][1]
    # value_y matches the documented _y_for formula for graph_height=24.
    expected = sensors.Display._y_for(25.0, _TEST_BAND_KWARGS["temp_bands"], _FAKE_GRAPH_HEIGHT)
    assert value_y == expected


def test_nan_value_skips_the_column_entirely(monkeypatch) -> None:
    """R2.4 regression: NaN → no draw_graph_column for that index; column
    shows row background after the per-row draw_graph_clear."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    history = _FakeRingHistory()
    # Two samples: NaN (newest) and a valid one.
    history.set_samples(0, [float("nan"), 22.0])
    history.bump_commit()
    d = _make_display(renderer=renderer, history=history)
    d._update_display()

    col_calls = [c for c in _graph_calls(renderer) if c[0] == "draw_graph_column" and c[1][0] == 0]
    # Only the valid sample produced a draw_graph_column call.
    assert len(col_calls) == 1
    _name, args, _kw = col_calls[0]
    # The valid sample is the second-most-recent (rel_index=1) → col = capacity - 1 - 1.
    _line, col, _pastel, _bright, _y = args
    assert col == history.capacity - 1 - 1


def test_partial_fill_draws_only_rightmost_filled_columns(monkeypatch) -> None:
    """With ``filled(metric) < capacity``, only the rightmost ``filled`` columns
    receive a draw_graph_column call; the rest stay as cleared background."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    history = _FakeRingHistory(capacity=10)
    # 3 valid in-range samples for temperature.
    history.set_samples(0, [22.0, 21.0, 20.0])
    history.bump_commit()
    d = _make_display(renderer=renderer, history=history)
    d._update_display()

    cols = [
        c[1][1] for c in _graph_calls(renderer)
        if c[0] == "draw_graph_column" and c[1][0] == 0
    ]
    # Right-aligned: cols (capacity-1, capacity-2, capacity-3).
    assert sorted(cols) == [7, 8, 9]


def test_line_write_clear_rect_never_extends_into_graph(monkeypatch) -> None:
    """B1 regression: a value update must not clear any pixels at x >= graph_x."""
    # This test uses the real Geometry + real Renderer to exercise the actual
    # value_clear_width derivation.
    from displays.sensors import Geometry, Renderer, Colors
    from tests.test_sensors_renderer import FakePicoGraphics

    gfx = FakePicoGraphics()
    geom = Geometry(
        pico_graphics=gfx,
        font="bitmap8",
        font_height=8,
        text_scale=3,
        tick_period_ms=500,
    )
    colors = Colors(background=1, header_text=2, value_text=3, secondary_text=4)
    r = Renderer(geom, colors)

    # Repeatedly write changing values across all 4 rows — like real device usage.
    for tick, vals in enumerate((("21.0", "1010", "50.5", "65.0"),
                                 ("22.1", "1011", "50.6", "66.0"),
                                 ("22.2", "1012", "50.7", "67.0"))):
        for i, v in enumerate(vals):
            r.value_write(i, v)

    for name, args, _kw in gfx.calls:
        if name == "rectangle":
            x, _y, w, _h = args
            assert x + w <= geom.graph_x, (
                "line_write rectangle (x={}, w={}) leaks into graph rect (graph_x={})".format(
                    x, w, geom.graph_x
                )
            )


def test_reentry_with_intervening_commit_redraws_all_graphs(monkeypatch) -> None:
    """R2.11: leave sensors view, advance commit_count while away, return →
    all eligible graphs repaint on first render after re-entry."""
    renderer = RecordingRenderer()
    monkeypatch.setattr(time, "gmtime", lambda _t: (2026, 1, 4, 13, 5, 0, 0, 0, 0))

    history = _FakeRingHistory()
    history.set_samples(0, [22.0])
    history.set_samples(1, [1010.0])
    history.set_samples(2, [50.0])
    history.set_samples(3, [120.0])
    history.bump_commit()

    reader = FakeBME690Reader((22.0, 1010.0, 50.0, 120.0, "Stable"))
    d = _make_display(renderer=renderer, reader=reader, history=history)
    d.initialize()              # paints graphs
    d.deinitialize()            # leave view

    # Simulate background commits piling up while away.
    history.set_samples(0, [23.0, 22.0])
    history.bump_commit()
    history.bump_commit()

    renderer.calls.clear()
    d.initialize()              # re-enter

    # All 4 graphs paint on re-entry (reset() cleared the screen).
    clears = [c for c in _graph_calls(renderer) if c[0] == "draw_graph_clear"]
    assert sorted(c[1][0] for c in clears) == [0, 1, 2, 3]
    # And the temperature row picked up the new (2-sample) history.
    cols = [c for c in _graph_calls(renderer) if c[0] == "draw_graph_column" and c[1][0] == 0]
    assert len(cols) == 2

