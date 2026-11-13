from __future__ import annotations

import math

import pytest

import displays.sensors as sensors
from displays.palette import (
    BLACK,
    DARK_GRAY,
    GRAY,
    GREEN,
    GREEN_SHADE,
    ORANGE,
    ORANGE_SHADE,
    PINK,
    PINK_SHADE,
    SKY,
    SKY_SHADE,
    WHITE,
)
from displays.shared import _icons_data as icons
from services.sample_history import MISSING, SampleHistory

from _fakes import FakePicoGraphics, bitmap8_width, circle_pixels
from conftest import utc_epoch

_NAN = float("nan")
_BANDS = ((18.0, 25.0, 29.0), (1000.0, 1013.0, 1025.0), (30.0, 50.0, 70.0), (100.0, 200.0, 350.0))
_MONDAY_1308 = utc_epoch(2026, 11, 2, 13, 8, 0)
_READING = (20.1, 1013.0, 47.0, 312.0, "Stable")
_WARMING = (20.1, 1013.0, 47.0, _NAN, "Unstable")
_FIELDS = (ORANGE, PINK, SKY, GREEN)
_SHADES = (ORANGE_SHADE, PINK_SHADE, SKY_SHADE, GREEN_SHADE)
# (x, y, width, height) per quadrant, in metric order.
_QUADRANTS = ((0, 0, 119, 119), (122, 0, 118, 119), (0, 122, 119, 118), (122, 122, 118, 118))
_GRAPH_ROWS = ((1, 23), (1, 23), (217, 239), (217, 239))
_GRAPH_COLUMNS = 119
# bitmap8 glyphs with ink in the cell's bottom row, read off pimoroni-pico's font8_data.cpp.
_DESCENDERS = ",;gjpqy"


class _Reader:
    def __init__(self, reading: tuple[float, float, float, float, str]) -> None:
        self.reading = reading

    def read(self) -> tuple[float, float, float, float, str]:
        return self.reading


class _Clock:
    def __init__(self, now: int) -> None:
        self.now_sec = now
        self.reads = 0

    def now(self) -> int:
        self.reads += 1
        return self.now_sec


def _sampler(reader: _Reader):  # -> () -> tuple[int, int, int, int]
    return lambda: sensors.encode_reading(reader.read())


def _gas_sample(kohm: float) -> int:
    return sensors.encode_reading((20.0, 1013.0, 47.0, kohm, "Stable"))[3]


def _history(
    temp: list[float] | None = None,
    press: list[float] | None = None,
    hum: list[float] | None = None,
    gas: list[float] | None = None,
) -> SampleHistory:
    """A history committed from per-metric samples given newest first; a shorter list's older samples are NaN."""
    metrics = (
        temp if temp is not None else [20.1, 19.0, 21.5],
        press if press is not None else [1013.0, 1011.0, 1012.0],
        hum if hum is not None else [47.0, 45.0, 49.0],
        gas if gas is not None else [312.0, 250.0, 280.0],
    )
    count = max(len(metric) for metric in metrics)
    readings = iter(
        [
            tuple(metric[age] if age < len(metric) else _NAN for metric in metrics) + ("Stable",)
            for age in range(count - 1, -1, -1)
        ]
    )
    history = SampleHistory(
        lambda: sensors.encode_reading(next(readings)), metric_count=4, capacity=_GRAPH_COLUMNS, ticks_per_commit=1
    )
    for _ in range(count - 1):
        history.tick()
    return history


class _Rig:
    def __init__(
        self,
        reading: tuple[float, float, float, float, str] = _READING,
        history: SampleHistory | None = None,
        reader: _Reader | None = None,
        now: int = _MONDAY_1308,
    ) -> None:
        self.gfx = FakePicoGraphics()
        self.geom = sensors.Geometry(self.gfx, "bitmap8", 8, 3, 2, 500)
        self.reader = reader or _Reader(reading)
        self.clock = _Clock(now)
        self.history = history if history is not None else _history()
        self.display = sensors.Display(self.geom, self.reader.read, self.clock.now, self.history, _BANDS)
        self.gfx.calls.clear()

    def entered(self) -> _Rig:
        self.display.initialize()
        self.gfx.calls.clear()
        return self


def _draws(gfx: FakePicoGraphics) -> list[tuple[str, tuple, int | None]]:
    """Each draw call as ``(name, args, pen)``; a text's args end with its scale."""
    pen = None
    draws: list[tuple[str, tuple, int | None]] = []
    for name, args, kwargs in gfx.calls:
        if name == "set_pen":
            pen = args[0]
        elif name == "text":
            draws.append((name, args + (kwargs["scale"],), pen))
        elif name in ("rectangle", "circle", "clear"):
            draws.append((name, args, pen))
    return draws


def _texts(gfx: FakePicoGraphics) -> list[tuple[str, int, int, int, int]]:
    return [(*args, pen) for name, args, pen in _draws(gfx) if name == "text"]


def _rects(gfx: FakePicoGraphics) -> list[tuple[int, int, int, int, int]]:
    return [(*args, pen) for name, args, pen in _draws(gfx) if name == "rectangle"]


def _text_box(text: str, x: int, y: int, scale: int) -> tuple[int, int, int, int]:
    rows = 8 if any(ch in _DESCENDERS for ch in text) else 7
    return (x, y, bitmap8_width(text, scale), rows * scale)


def _inside(inner: tuple[int, int, int, int], outer: tuple[int, int, int, int]) -> bool:
    x, y, w, h = inner
    ox, oy, ow, oh = outer
    return ox <= x and oy <= y and x + w <= ox + ow and y + h <= oy + oh


def _columns(
    gfx: FakePicoGraphics, pen: int, rows: tuple[int, int] = (0, 239)
) -> dict[int, tuple[int, int]]:
    """Each 1-px column drawn in ``pen`` within ``rows`` as ``x: (top_y, bottom_y)``."""
    return {
        x: (y, y + h - 1)
        for x, y, w, h, rect_pen in _rects(gfx)
        if w == 1 and rect_pen == pen and rows[0] <= y and y + h - 1 <= rows[1]
    }


@pytest.fixture
def blits(monkeypatch) -> list[tuple[tuple[int, int, bytes], int, int, int]]:
    calls: list[tuple[tuple[int, int, bytes], int, int, int]] = []
    monkeypatch.setattr(
        sensors.icons_p4, "draw_icon", lambda gfx, icon, x, y, scale=1: calls.append((icon, x, y, scale))
    )
    return calls


# Pure helpers


def test_format_value_boundaries() -> None:
    fn = sensors._format_value
    assert [fn(v, 1) for v in (22.4, -9.9, 99.9, -99.9, 0.0)] == ["22.4", "-9.9", "99.9", "-99.9", "0.0"]
    assert [fn(v, 0) for v in (963.0, 1010.0, -50.0)] == ["963", "1010", "-50"]
    # -99.99 would format as "-100.0", 75 px against the 63 px "-88.8" budget.
    assert [fn(v, 1) for v in (100.0, -100.0, -99.99, 99.99)] == ["100", "-100", "-100", "100"]
    assert [fn(v, 1) for v in (250.7, 999.9, -100.7, 1234.7)] == ["251", "1000", "-101", "1235"]
    assert [fn(v, 1) for v in (9999.0, 10000.0, 99999.0, -999.0, -1000.0, -99999.5)] == [
        "9999",
        "9999",
        "9999",
        "-999",
        "-999",
        "-999",
    ]


def test_band_index_puts_a_value_on_an_edge_in_the_band_above() -> None:
    edges = (18.0, 25.0, 29.0)
    values = (-5.0, 17.99, 18.0, 24.99, 25.0, 28.99, 29.0, 45.0)
    assert [sensors._band_index(v, edges) for v in values] == [0, 0, 1, 1, 2, 2, 3, 3]


def test_graph_bounds_pad_a_wide_span() -> None:
    bounds = sensors._graph_bounds(100, 200, 40)
    assert bounds == (92, 208)
    assert all(type(bound) is int for bound in bounds)


def test_graph_bounds_widen_a_narrow_span_about_its_middle() -> None:
    assert sensors._graph_bounds(200, 210, 40) == (182, 228)


def test_encode_reading_scales_each_metric_and_gives_missing_for_nan_or_non_positive_gas() -> None:
    samples = sensors.encode_reading((-5.26, 1013.24, 47.0, 312.0, "Stable"))
    assert samples == (-263, 5066, 2350, round(math.log(312.0) * 100000))
    assert all(type(sample) is int for sample in samples)
    assert sensors.encode_reading((_NAN, 1013.0, 47.0, _NAN, "Unstable"))[::3] == (MISSING, MISSING)
    assert sensors.encode_reading((20.0, 1013.0, 47.0, 0.0, "Stable"))[3] == MISSING


def test_format_badge() -> None:
    assert sensors._format_badge(_MONDAY_1308) == ("Mon", "13:08", "2 Nov")
    assert sensors._format_badge(utc_epoch(2027, 3, 28, 0, 5, 59)) == ("Sun", "00:05", "28 Mar")
    assert sensors._format_badge(utc_epoch(2027, 5, 30, 23, 59, 0)) == ("Sun", "23:59", "30 May")


# Layout


def test_geometry_matches_the_approved_design() -> None:
    geom = _Rig().geom
    assert geom.graph_height == 23
    assert geom.badge_rects == ((105, 87, 30, 14), (89, 109, 63, 21), (91, 138, 58, 16))
    assert geom.badge_r == 54


def test_texts_and_icons_keep_8_px_from_each_other_the_edges_and_the_gutter(blits) -> None:
    rig = _Rig()
    rig.display.initialize()
    texts = {text: (x, y) for text, x, y, _scale, _pen in _texts(rig.gfx)}
    y = {text: text_y for text, (_x, text_y) in texts.items()}
    blit_xy = {icon: (x, icon_y) for icon, x, icon_y, _scale in blits}
    thermo_x, thermo_y = blit_xy[icons.ICON_THERMO_GREEN]
    thermo_width = icons.ICON_THERMO_GREEN[0] * 2
    thermo_height = icons.ICON_THERMO_GREEN[1] * 2
    value_ink_rows = 7 * 3
    label_ink_rows = 7 * 2

    assert {
        y["19.0..21.5"] - (_GRAPH_ROWS[0][1] + 1),
        y["20.1"] - (y["19.0..21.5"] + label_ink_rows),
        thermo_y - (y["20.1"] + value_ink_rows),
        _QUADRANTS[0][3] - (thermo_y + thermo_height),
        blit_xy[icons.UNIT_CELSIUS][0] - (thermo_x + thermo_width),
        y["13:08"] - (y["Mon"] + label_ink_rows),
        y["2 Nov"] - (y["13:08"] + value_ink_rows),
        texts["20.1"][0],
        thermo_x,
        240 - (texts["1013"][0] + bitmap8_width("1013", 3)),
    } == {8}


def test_history_holds_the_widest_graph_and_the_narrowest_spans_24_hours() -> None:
    geom = _Rig().geom
    assert geom.graph_columns == 119
    assert geom.ticks_per_commit == 1465
    assert 118 * geom.ticks_per_commit * 500 >= 24 * 3600 * 1000 > 118 * (geom.ticks_per_commit - 1) * 500


def test_badge_clear_rects_stay_inside_the_ring_with_five_pixels_to_spare() -> None:
    geom = _Rig().geom
    inner_r = geom.badge_r - 4

    def margin_pixels(rect: tuple[int, int, int, int]) -> set[tuple[int, int]]:
        x, y, w, h = rect
        return {(px, py) for px in range(x - 1, x + w + 1) for py in range(y - 1, y + h + 1)}

    inside = circle_pixels(120, 120, inner_r - 5)
    assert all(margin_pixels(rect) <= inside for rect in geom.badge_rects)
    smaller = circle_pixels(120, 120, inner_r - 6)
    assert not all(margin_pixels(rect) <= smaller for rect in geom.badge_rects)


def test_circle_fills_exactly_the_pixels_whose_squared_distance_is_under_r_times_r_plus_one() -> None:
    for r in range(1, 120):
        pixels = circle_pixels(0, 0, r)
        assert pixels == {(x, y) for x in range(-r, r + 1) for y in range(-r, r + 1) if x * x + y * y < r * (r + 1)}


def test_value_scale_that_pushes_values_under_the_badge_is_refused() -> None:
    gfx = FakePicoGraphics()
    geom = sensors.Geometry(gfx, "bitmap8", 8, 4, 2, 500)
    with pytest.raises(RuntimeError, match="overlap or leave"):
        sensors.Display(geom, _Reader(_READING).read, lambda: 0, _history(), _BANDS)


def test_short_panel_leaves_no_room_for_a_graph() -> None:
    class _ShortPanel(FakePicoGraphics):
        def get_bounds(self) -> tuple[int, int]:
            return (240, 160)

    with pytest.raises(RuntimeError, match="no room for graph"):
        sensors.Geometry(_ShortPanel(), "bitmap8", 8, 3, 2, 500)


def test_check_layout_refuses_overlap_leaving_the_quadrant_or_the_badge() -> None:
    geom = _Rig().geom
    quadrant = (0, 0, 119, 119)
    sensors._check_layout(((4, 4, 10, 10), (14, 4, 10, 10)), quadrant, geom)
    for rects in (
        ((4, 4, 10, 10), (13, 4, 10, 10)),
        ((112, 4, 10, 10),),
        ((90, 90, 10, 10),),
    ):
        with pytest.raises(RuntimeError, match="overlap or leave"):
            sensors._check_layout(rects, quadrant, geom)


# First frame


def test_first_frame_paints_fields_then_the_badge_ring_and_pushes_once() -> None:
    rig = _Rig()
    rig.display.initialize()

    assert rig.gfx.calls[0] == ("set_font", ("bitmap8",), {})
    draws = _draws(rig.gfx)
    assert draws[0] == ("clear", (), BLACK)
    fields = [(x, y, w, h) for x, y, w, h, pen in _rects(rig.gfx) if (x, y, w, h) in _QUADRANTS]
    assert fields == list(_QUADRANTS)
    assert [pen for x, y, w, h, pen in _rects(rig.gfx) if (x, y, w, h) in _QUADRANTS] == list(_FIELDS)
    circles = [(args, pen) for name, args, pen in draws if name == "circle"]
    assert circles == [((120, 120, 54), BLACK), ((120, 120, 52), DARK_GRAY), ((120, 120, 50), BLACK)]
    assert draws.index(("circle", (120, 120, 54), BLACK)) > max(
        draws.index(("rectangle", quadrant, field)) for quadrant, field in zip(_QUADRANTS, _FIELDS)
    )
    assert [c for c in rig.gfx.calls if c[0] == "update"] == [("update", (), {})]


def test_first_frame_texts_align_to_their_quadrants_outer_margins() -> None:
    rig = _Rig()
    rig.display.initialize()

    def right(text: str, scale: int) -> int:
        return 232 - bitmap8_width(text, scale)

    assert set(_texts(rig.gfx)) == {
        ("Mon", 105, 87, 2, GRAY),
        ("13:08", 90, 109, 3, WHITE),
        ("2 Nov", 97, 138, 2, GRAY),
        ("20.1", 8, 54, 3, BLACK),
        ("19.0..21.5", 8, 32, 2, DARK_GRAY),
        ("1013", right("1013", 3), 54, 3, BLACK),
        ("1011..1013", right("1011..1013", 2), 32, 2, DARK_GRAY),
        ("47.0", 8, 166, 3, BLACK),
        ("45.0..49.0", 8, 195, 2, DARK_GRAY),
        ("312", right("312", 3), 166, 3, BLACK),
        ("250..312", right("250..312", 2), 195, 2, DARK_GRAY),
    }


def test_first_frame_icons_sit_on_the_outer_margin_and_units_inside_them(blits) -> None:
    _Rig().display.initialize()

    assert blits == [
        (icons.UNIT_CELSIUS, 36, 90, 2),
        (icons.UNIT_MBAR, 180, 90, 2),
        (icons.UNIT_PERCENT, 38, 138, 2),
        (icons.UNIT_KOHM, 182, 137, 2),
        (icons.ICON_THERMO_GREEN, 8, 83, 2),
        (icons.ICON_GAUGE_HIGH, 204, 83, 2),
        (icons.ICON_DROP_MED, 8, 130, 2),
        (icons.ICON_MASK_GREEN, 206, 130, 2),
    ]


def test_first_frame_graphs_end_at_each_quadrants_right_edge_and_fill_to_its_graph_bottom() -> None:
    rig = _Rig()
    rig.display.initialize()

    for (x, _y, width, _height), (top_y, bottom_y), shade in zip(_QUADRANTS, _GRAPH_ROWS, _SHADES):
        columns = _columns(rig.gfx, shade)
        right_x = x + width - 1
        assert sorted(columns) == [right_x - 2, right_x - 1, right_x]
        assert all(top_y <= y0 and y1 == bottom_y for y0, y1 in columns.values())


# Updates


def test_render_without_changes_draws_and_pushes_nothing(monkeypatch) -> None:
    rig = _Rig().entered()

    def float_math(*_args):
        raise AssertionError("an unchanged render converted a sample")

    monkeypatch.setattr(sensors, "_encode", float_math)
    monkeypatch.setattr(sensors, "_decode", float_math)
    rig.display.render()
    rig.reader.reading = tuple(list(_READING))
    rig.display.render()
    assert rig.gfx.calls == []


def test_changed_value_redraws_only_its_cell() -> None:
    rig = _Rig().entered()
    rig.reader.reading = (20.2, 1013.0, 47.0, 312.0, "Stable")
    rig.display.render()

    assert _rects(rig.gfx) == [(8, 54, 63, 21, ORANGE)]
    assert _texts(rig.gfx) == [("20.2", 8, 54, 3, BLACK)]
    assert rig.gfx.calls[-1] == ("update", (), {})


def test_band_crossing_swaps_only_that_quadrants_icon(blits) -> None:
    rig = _Rig().entered()
    blits.clear()

    rig.reader.reading = (25.0, 1013.0, 47.0, 312.0, "Stable")
    rig.display.render()
    assert blits == [(icons.ICON_THERMO_ORANGE, 8, 83, 2)]
    assert (8, 83, 20, 28, ORANGE) in _rects(rig.gfx)

    blits.clear()
    rig.reader.reading = (25.5, 1030.0, 75.0, 400.0, "Stable")
    rig.display.render()
    assert blits == [
        (icons.ICON_GAUGE_MAX, 204, 83, 2),
        (icons.ICON_DROP_MAX, 8, 130, 2),
        (icons.ICON_MASK_BLUE, 206, 130, 2),
    ]


def test_commit_redraws_every_graph_once() -> None:
    rig = _Rig().entered()
    rig.history.commit_count += 1
    rig.display.render()
    graph_clears = [(x, y, w, h) for x, y, w, h, pen in _rects(rig.gfx) if w > 1 and h == 23]
    assert graph_clears == [(0, 1, 119, 23), (122, 1, 118, 23), (0, 217, 119, 23), (122, 217, 118, 23)]

    rig.gfx.calls.clear()
    rig.display.render()
    assert rig.gfx.calls == []


# Graphs


def test_nan_sample_leaves_its_column_empty_and_breaks_the_line() -> None:
    rig = _Rig(history=_history(temp=[20.0, _NAN, 22.0]))
    rig.display.initialize()

    fills = _columns(rig.gfx, ORANGE_SHADE)
    assert sorted(fills) == [116, 118]
    lines = _columns(rig.gfx, DARK_GRAY, _GRAPH_ROWS[0])
    assert 117 not in lines
    assert lines[116] == (fills[116][0], fills[116][0])
    assert lines[118] == (fills[118][0], fills[118][0])


def test_line_joins_each_point_to_the_previous_column() -> None:
    rig = _Rig(history=_history(temp=[20.0, 22.0]))
    rig.display.initialize()

    fills = _columns(rig.gfx, ORANGE_SHADE)
    lines = _columns(rig.gfx, DARK_GRAY, _GRAPH_ROWS[0])
    assert lines[117] == (fills[117][0], fills[117][0])
    assert lines[118] == (fills[117][0], fills[118][0])


def test_steady_history_plots_mid_height() -> None:
    rig = _Rig(history=_history(temp=[21.0, 21.0, 21.0]))
    rig.display.initialize()
    assert {top for top, _bottom in _columns(rig.gfx, ORANGE_SHADE).values()} == {12}


def test_gas_plots_on_a_log_scale() -> None:
    rig = _Rig(history=_history(gas=[400.0, 200.0, 100.0]))
    rig.display.initialize()
    fills = _columns(rig.gfx, GREEN_SHADE)
    y400, y200, y100 = fills[239][0], fills[238][0], fills[237][0]
    assert abs(y200 - (y400 + y100) / 2) <= 1


def test_right_quadrant_ignores_the_oldest_sample_its_narrower_graph_drops() -> None:
    history = _history(temp=[20.0] * 118 + [30.0], press=[1010.0] * 118 + [1100.0])
    rig = _Rig(history=history)
    rig.display.initialize()

    assert 0 in _columns(rig.gfx, ORANGE_SHADE)
    assert min(_columns(rig.gfx, PINK_SHADE)) == 122
    ranges = [text for text, _x, y, _scale, _pen in _texts(rig.gfx) if y == 32]
    assert "20.0..30.0" in ranges
    assert not any("1100" in text for text in ranges)


def test_log_scale_window_without_positive_samples_draws_no_graph() -> None:
    rig = _Rig(reading=(20.1, 1013.0, 47.0, 0.0, "Stable"), history=_history(gas=[0.0, -1.0]))
    rig.display.initialize()

    assert _columns(rig.gfx, GREEN_SHADE) == {}
    assert [text for text, x, y, _scale, _pen in _texts(rig.gfx) if x > 120 and y == 195] == ["0.0..0.0"]


def test_points_land_within_half_a_row_of_their_exact_height() -> None:
    temps = [-5.26, -0.04, _NAN, 3.15, -2.71, 0.0, 1.99, _NAN, -4.44]
    rig = _Rig(history=_history(temp=temps))
    rig.display.initialize()

    samples = [sensors.encode_reading((t, 1013.0, 47.0, 312.0, "Stable"))[0] for t in reversed(temps)]
    min_span = rig.display._quadrants[0]._min_span
    lo, hi = sensors._graph_bounds(min(s for s in samples if s != MISSING), max(samples), min_span)
    top_y, bottom_y = _GRAPH_ROWS[0]
    fills = _columns(rig.gfx, ORANGE_SHADE)
    first_x = 119 - len(samples)
    assert sorted(fills) == [first_x + i for i, s in enumerate(samples) if s != MISSING]
    for x, (y, _bottom) in fills.items():
        exact_y = bottom_y - (samples[x - first_x] - lo) * (bottom_y - top_y) / (hi - lo)
        assert abs(y - exact_y) <= 0.5


def test_any_metric_turning_valid_backfills_a_nan_newest_sample() -> None:
    history = _history(temp=[_NAN, 21.0])
    _Rig(history=history).display.initialize()
    assert history.samples[0][-1] == sensors.encode_reading(_READING)[0]


# Ranges


def test_range_widens_to_a_live_reading_beyond_the_history_and_no_further() -> None:
    rig = _Rig().entered()
    rig.reader.reading = (23.4, 1013.0, 47.0, 312.0, "Stable")
    rig.display.render()
    assert ("19.0..23.4", 8, 32, 2, DARK_GRAY) in _texts(rig.gfx)

    rig.gfx.calls.clear()
    rig.reader.reading = (21.0, 1013.0, 47.0, 312.0, "Stable")
    rig.display.render()
    assert _texts(rig.gfx) == [("21.0", 8, 54, 3, BLACK)]


def test_a_range_end_shows_what_its_reading_showed() -> None:
    rig = _Rig(history=_history(press=[1013.0, 1014.53, 1012.0]))
    rig.display.initialize()
    assert [text for text, x, y, _scale, _pen in _texts(rig.gfx) if x > 120 and y == 32] == ["1012..1015"]


# Gas warm-up


def test_warming_gas_shows_placeholders_keeps_the_default_icon_and_hides_its_graph(blits) -> None:
    rig = _Rig(reading=_WARMING, history=_history(gas=[_NAN]))
    rig.display.initialize()

    texts = _texts(rig.gfx)
    assert ("--", 211, 166, 3, DARK_GRAY) in texts
    assert ("warming...", 144, 195, 2, DARK_GRAY) in texts
    assert (icons.ICON_MASK_ORANGE, 206, 130, 2) in blits
    assert _columns(rig.gfx, GREEN_SHADE) == {}


def test_gas_icon_holds_while_warming_then_catches_up(blits) -> None:
    rig = _Rig().entered()
    blits.clear()

    rig.reader.reading = _WARMING
    rig.display.render()
    assert blits == []

    rig.reader.reading = (20.1, 1013.0, 47.0, 400.0, "Stable")
    rig.display.render()
    assert blits == [(icons.ICON_MASK_BLUE, 206, 130, 2)]


def test_gas_turning_invalid_clears_its_graph_once() -> None:
    rig = _Rig().entered()
    rig.reader.reading = _WARMING
    rig.display.render()

    assert (122, 217, 118, 23, GREEN) in _rects(rig.gfx)
    assert ("warming...", 144, 195, 2, DARK_GRAY) in _texts(rig.gfx)

    rig.gfx.calls.clear()
    rig.history.commit_count += 1
    rig.reader.reading = tuple(list(_WARMING))
    rig.display.render()
    assert [r for r in _rects(rig.gfx) if r[0] >= 122 and r[1] >= 122] == []


def test_gas_turning_valid_redraws_its_graph_without_waiting_for_a_commit() -> None:
    rig = _Rig(reading=_WARMING).entered()
    rig.reader.reading = _READING
    rig.display.render()

    assert sorted(_columns(rig.gfx, GREEN_SHADE)) == [237, 238, 239]
    assert ("250..312", 232 - bitmap8_width("250..312", 2), 195, 2, DARK_GRAY) in _texts(rig.gfx)


def test_gas_turning_valid_backfills_a_nan_newest_sample_once() -> None:
    history = _history(gas=[_NAN])
    rig = _Rig(reading=_WARMING, history=history).entered()
    assert history.samples[3][-1] == MISSING

    rig.reader.reading = (20.1, 1013.0, 47.0, 250.0, "Stable")
    rig.display.render()
    rig.reader.reading = (20.1, 1013.0, 47.0, 260.0, "Stable")
    rig.display.render()
    assert history.samples[3][-1] == _gas_sample(250.0)


def test_entering_while_valid_keeps_the_committed_sample() -> None:
    history = _history(gas=[180.0, 170.0])
    rig = _Rig(reading=(20.1, 1013.0, 47.0, 250.0, "Stable"), history=history)
    rig.display.initialize()
    rig.display.deinitialize()
    rig.display.initialize()
    assert history.samples[3][-1] == _gas_sample(180.0)


def test_reentry_after_turning_valid_elsewhere_backfills_a_nan_sample() -> None:
    history = _history(gas=[_NAN])
    rig = _Rig(reading=_WARMING, history=history)
    rig.display.initialize()
    rig.display.deinitialize()

    rig.reader.reading = (20.1, 1013.0, 47.0, 250.0, "Stable")
    rig.display.initialize()
    assert history.samples[3][-1] == _gas_sample(250.0)


def test_a_full_history_fed_by_the_reader_backfills_its_newest_gas_sample() -> None:
    reader = _Reader(_WARMING)
    history = SampleHistory(_sampler(reader), metric_count=4, capacity=_GRAPH_COLUMNS, ticks_per_commit=1)
    for _ in range(_GRAPH_COLUMNS + 5):
        history.tick()
    rig = _Rig(reader=reader, history=history).entered()

    reader.reading = (20.1, 1013.0, 47.0, 250.0, "Stable")
    rig.display.render()

    assert history.samples[3][-1] == _gas_sample(250.0)
    assert history.samples[3][-2] == MISSING
    assert sorted(_columns(rig.gfx, GREEN_SHADE)) == [239]


def test_a_history_shorter_than_a_graph_is_refused() -> None:
    gfx = FakePicoGraphics()
    geom = sensors.Geometry(gfx, "bitmap8", 8, 3, 2, 500)
    history = SampleHistory(_sampler(_Reader(_READING)), metric_count=4, capacity=118, ticks_per_commit=1)
    with pytest.raises(ValueError, match="fewer samples than a graph has columns"):
        sensors.Display(geom, _Reader(_READING).read, lambda: 0, history, _BANDS)


# Badge


def test_badge_reads_the_clock_only_once_a_minute_boundary_passes(fake_ticks) -> None:
    fake_ticks[0] = 0
    rig = _Rig(now=_MONDAY_1308 + 30).entered()
    assert rig.clock.reads == 1

    fake_ticks[0] = 29_000
    rig.clock.now_sec = _MONDAY_1308 + 59
    rig.display.render()
    assert rig.clock.reads == 1

    fake_ticks[0] = 30_000
    rig.clock.now_sec = _MONDAY_1308 + 60
    rig.display.render()
    assert rig.clock.reads == 2
    assert _texts(rig.gfx) == [("13:09", 90, 109, 3, WHITE)]


def test_badge_turns_the_date_at_midnight(fake_ticks) -> None:
    fake_ticks[0] = 0
    rig = _Rig(now=utc_epoch(2026, 11, 1, 23, 59, 0)).entered()

    fake_ticks[0] = 60_000
    rig.clock.now_sec = utc_epoch(2026, 11, 2, 0, 0, 0)
    rig.display.render()
    assert [text for text, *_rest in _texts(rig.gfx)] == ["Mon", "00:00", "2 Nov"]


# Redraw containment


def _churn(rig: _Rig, fake_ticks: list[int]) -> None:
    """Drive every kind of redraw: values, bands, ranges, commits, gas warm-up and the clock."""
    widest_samples = sensors.encode_reading((-88.8, -88.8, -88.8, -88.8, "Stable"))
    for reading in (
        (-99.9, 1100.0, 100.0, 50000.0, "Stable"),
        (-12.3, 963.0, 5.5, 75.3, "Stable"),
        _WARMING,
        (35.0, 1040.0, 99.9, 9999.0, "Stable"),
    ):
        rig.reader.reading = reading
        rig.history.commit_count += 1
        for i in range(len(widest_samples)):
            metric = rig.history.samples[i]
            metric[:-1] = metric[1:]
            metric[-1] = widest_samples[i]
        fake_ticks[0] += 60_000
        rig.clock.now_sec = utc_epoch(2027, 5, 30, 23, 59, 0)
        rig.display.render()


def test_every_text_stays_inside_the_cell_erased_for_it(fake_ticks) -> None:
    rig = _Rig()
    rig.display.initialize()
    _churn(rig, fake_ticks)

    last_rect = None
    texts = 0
    for name, args, _pen in _draws(rig.gfx):
        if name == "rectangle":
            last_rect = args
        elif name == "text":
            text, x, y, scale = args
            assert _inside(_text_box(text, x, y, scale), last_rect), text
            texts += 1
    assert texts > 30


def test_redraws_after_the_first_frame_never_touch_the_badge_outside_its_cells(fake_ticks) -> None:
    rig = _Rig().entered()
    _churn(rig, fake_ticks)

    badge = circle_pixels(120, 120, rig.geom.badge_r)
    for name, args, _pen in _draws(rig.gfx):
        if name == "rectangle":
            box = args
        elif name == "text":
            box = _text_box(*args)
        else:
            continue
        if any(_inside(box, cell) for cell in rig.geom.badge_rects):
            continue
        x, y, w, h = box
        assert not any((px, py) in badge for px in range(x, x + w) for py in range(y, y + h)), (name, args)


# Lifecycle


def test_initialize_is_idempotent_and_reentry_repaints_everything() -> None:
    rig = _Rig()
    rig.display.initialize()
    first = list(rig.gfx.calls)

    rig.gfx.calls.clear()
    rig.display.initialize()
    assert rig.gfx.calls == []

    rig.display.deinitialize()
    rig.display.deinitialize()
    rig.display.initialize()
    assert rig.gfx.calls == first
