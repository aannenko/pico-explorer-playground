"""Tests for the Open-Meteo service: its CSV parser and its precipitation, UV, AQI and pollen warning streams."""

import pytest

from displays.palette import STREAM_COLORS, STREAM_ORANGE, STREAM_RED, STREAM_YELLOW
from services.fetch_machine import FetchCoordinator
from services.http_client import HttpConnectError, HttpParseError
from services.openmeteo_service import OpenMeteoService, _AirHours, _HourlyCsv, _precip_label, _WeatherHours

_UV = (6, 8, 11)  # UV thresholds used across the suite
_POLLEN_THR = [
    ("alder", (1, 11, 101)),
    ("birch", (1, 11, 51)),
    ("grass", (1, 6, 31)),
    ("mugwort", (1, 6, 11)),
    ("ragweed", (1, 6, 11)),
]
_SPECIES = [species for species, _ in _POLLEN_THR]
_AQI_THR = (60, 80, 100)
_T0 = 1_794_855_600
_HOUR = 3600


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "wmo_code, expected",
    [
        (51, "RAIN"), (61, "RAIN"), (67, "RAIN"), (80, "RAIN"), (82, "RAIN"),
        (71, "SNOW"), (75, "SNOW"), (77, "SNOW"), (85, "SNOW"), (86, "SNOW"),
        (95, "STORM"), (99, "STORM"), (61.0, "RAIN"),
        (0, None), (3, None), (45, None), (50, None), (68, None), (70, None),
        (78, None), (79, None), (83, None), (84, None), (87, None), (94, None), (100, None), (None, None),
    ],
)
def test_precip_label_mapping(wmo_code, expected):
    assert _precip_label(wmo_code) == expected


# ---------------------------------------------------------------------------
# _WeatherHours
# ---------------------------------------------------------------------------


def _weather_hours(*rows, threshold=30, max_events=10):
    """Feed hourly ``(prob, mm, code, uv)`` rows from ``_T0``; return the precipitation and UV events."""
    hours = _WeatherHours(threshold, _UV, max_events, 0)
    for i, row in enumerate(rows):
        hours.add_hour(_T0 + i * _HOUR, list(row))
    return hours.precip.events(), hours.uv.events()


def _precip(*rows, threshold=30):
    return _weather_hours(*rows, threshold=threshold)[0]


def _uv(*rows):
    return _weather_hours(*rows)[1]


# --- precipitation ---------------------------------------------------------


def test_precip_below_threshold_hours_emit_nothing():
    assert _precip((10, 1.0, 61, 0), (0, 0.0, 0, 0)) == []


def test_prob_equal_threshold_emits():
    assert len(_precip((30, 1.0, 61, 0))) == 1


@pytest.mark.parametrize("row", [(None, 1.0, 61, 0), (90, 1.0, None, 0), (90, 0.0, 0, 0)])
def test_a_missing_probability_or_a_non_precipitation_code_emits_nothing(row):
    assert _precip(row) == []


def test_single_qualifying_hour_emits_one_event():
    events = _precip((50, 1.0, 61, 0))

    assert [(e.label, e.start_utc, e.duration_sec, e.color_index) for e in events] == [
        ("RAIN", _T0, _HOUR, STREAM_YELLOW)
    ]


@pytest.mark.parametrize(
    "mm, expected_index",
    [
        (0.0, STREAM_YELLOW),
        (2.49, STREAM_YELLOW),
        (2.5, STREAM_ORANGE),
        (7.59, STREAM_ORANGE),
        (7.6, STREAM_RED),
        (20.0, STREAM_RED),
    ],
)
def test_amount_sets_the_level(mm, expected_index):
    assert _precip((80, mm, 61, 0))[0].color_index == expected_index


def test_none_precipitation_amount_still_warns_at_level_1():
    assert _precip((80, None, 61, 0))[0].color_index == STREAM_YELLOW


def test_precip_contiguous_hours_merge_at_their_highest_level():
    events = _precip((80, 1.0, 61, 0), (80, 5.0, 61, 0), (80, 0.8, 61, 0))

    assert [(e.duration_sec, e.color_index) for e in events] == [(3 * _HOUR, STREAM_ORANGE)]


def test_type_change_splits_run_even_at_same_level():
    assert [e.label for e in _precip((80, 1.0, 61, 0), (80, 1.0, 71, 0))] == ["RAIN", "SNOW"]


def test_precip_gap_hour_breaks_the_run():
    events = _precip((80, 1.0, 61, 0), (0, 0.0, 0, 0), (80, 1.0, 61, 0))

    assert [e.start_utc for e in events] == [_T0, _T0 + 2 * _HOUR]


def test_weather_streams_keep_at_most_max_events():
    precip, _ = _weather_hours((80, 1.0, 61, 0), (80, 1.0, 71, 0), (80, 1.0, 61, 0), max_events=2)

    assert [e.label for e in precip] == ["RAIN", "SNOW"]


# --- UV --------------------------------------------------------------------


@pytest.mark.parametrize(
    "uv_index, expected_index",
    [(6, STREAM_YELLOW), (7.9, STREAM_YELLOW), (8, STREAM_ORANGE), (10.9, STREAM_ORANGE), (11, STREAM_RED)],
)
def test_uv_index_sets_the_level(uv_index, expected_index):
    assert [(e.label, e.color_index) for e in _uv((0, 0.0, 0, uv_index))] == [("UV", expected_index)]


@pytest.mark.parametrize("uv_index", [5.9, None])
def test_uv_below_threshold_or_missing_emits_nothing(uv_index):
    assert _uv((0, 0.0, 0, uv_index)) == []


def test_precipitation_and_uv_in_the_same_hour_both_emit():
    precip, uv = _weather_hours((80, 1.0, 61, 9))

    assert [(e.label, e.start_utc) for e in precip] == [("RAIN", _T0)]
    assert [(e.label, e.start_utc) for e in uv] == [("UV", _T0)]


def test_weather_color_indices_are_valid_palette_indices():
    precip, uv = _weather_hours((80, 1.0, 61, 7), (80, 5.0, 71, 9), (80, 10.0, 95, 12))

    for ev in precip + uv:
        assert 0 <= ev.color_index < len(STREAM_COLORS)


# ---------------------------------------------------------------------------
# _AirHours
# ---------------------------------------------------------------------------


def _row(aqi, **pollen) -> list:
    """One hour's values: the AQI, then each species' count, absent species 0."""
    return [aqi] + [pollen.get(species, 0) for species in _SPECIES]


def _air_hours(*rows, pollen_thresholds=_POLLEN_THR, max_events=10):
    """Feed hourly rows from ``_T0``; return the AQI and pollen events."""
    hours = _AirHours(_AQI_THR, pollen_thresholds, max_events, 0)
    for i, row in enumerate(rows):
        hours.add_hour(_T0 + i * _HOUR, row)
    return hours.aqi.events(), hours.pollen.events()


def _aqi(*rows):
    return _air_hours(*rows)[0]


def _pollen(*rows):
    return _air_hours(*rows)[1]


def test_air_below_threshold_hours_emit_nothing():
    assert _air_hours(_row(10)) == ([], [])


def test_none_values_emit_nothing():
    assert _air_hours(_row(None, grass=None)) == ([], [])


def test_single_aqi_hour_is_one_event():
    events = _aqi(_row(60))

    assert [(e.label, e.start_utc, e.duration_sec, e.color_index) for e in events] == [
        ("AQI", _T0, _HOUR, STREAM_YELLOW)
    ]


@pytest.mark.parametrize(
    "aqi, expected_index",
    [(60, STREAM_YELLOW), (79, STREAM_YELLOW), (80, STREAM_ORANGE), (99, STREAM_ORANGE), (100, STREAM_RED)],
)
def test_aqi_sets_the_level(aqi, expected_index):
    assert _aqi(_row(aqi))[0].color_index == expected_index


@pytest.mark.parametrize(
    "grains, expected_index", [(1, STREAM_YELLOW), (11, STREAM_ORANGE), (51, STREAM_RED)]
)
def test_pollen_level_uses_the_species_thresholds(grains, expected_index):
    assert [(e.label, e.color_index) for e in _pollen(_row(10, birch=grains))] == [("BIRCH", expected_index)]


def test_dominant_pollen_compares_levels_by_each_species_thresholds():
    # 20 grass grains is level 2, while 12 mugwort grains is already level 3.
    assert [(e.label, e.color_index) for e in _pollen(_row(0, grass=20, mugwort=12))] == [("MUGWORT", STREAM_RED)]


def test_dominant_pollen_tie_goes_to_the_first_listed_not_the_higher_count():
    assert [e.label for e in _pollen(_row(0, grass=7, mugwort=10))] == ["GRASS"]


def test_dominant_pollen_skips_none_values():
    assert [e.label for e in _pollen(_row(0, grass=None, mugwort=2))] == ["MUGWORT"]


def test_aqi_and_pollen_in_the_same_hour_both_emit():
    aqi, pollen = _air_hours(_row(60, grass=40))

    assert [(e.label, e.color_index) for e in aqi] == [("AQI", STREAM_YELLOW)]
    assert [(e.label, e.color_index) for e in pollen] == [("GRASS", STREAM_RED)]


def test_aqi_contiguous_hours_merge_at_their_highest_level():
    events = _aqi(_row(60), _row(85), _row(65))

    assert [(e.duration_sec, e.color_index) for e in events] == [(3 * _HOUR, STREAM_ORANGE)]


def test_species_change_splits_run_even_at_same_level():
    events = _pollen(_row(0, grass=2), _row(0, birch=2))

    assert [(e.label, e.color_index) for e in events] == [("GRASS", STREAM_YELLOW), ("BIRCH", STREAM_YELLOW)]


def test_aqi_gap_hour_breaks_the_run():
    events = _aqi(_row(60), _row(10), _row(60))

    assert [e.start_utc for e in events] == [_T0, _T0 + 2 * _HOUR]


def test_no_species_is_aqi_only():
    aqi, pollen = _air_hours([60], pollen_thresholds=[])

    assert [e.label for e in aqi] == ["AQI"]
    assert pollen == []


def test_air_streams_keep_at_most_max_events():
    _, pollen = _air_hours(_row(0, grass=2), _row(0, birch=2), _row(0, grass=2), max_events=2)

    assert [e.label for e in pollen] == ["GRASS", "BIRCH"]


def test_air_color_indices_are_valid_palette_indices():
    aqi, pollen = _air_hours(_row(60, grass=2), _row(100, grass=40))

    for ev in aqi + pollen:
        assert 0 <= ev.color_index < len(STREAM_COLORS)


# ---------------------------------------------------------------------------
# _HourlyCsv
# ---------------------------------------------------------------------------

_META = [b"latitude,longitude", b"50.0,14.0", b""]
_PARSER_HEADER = b"time,precipitation (mm),uv_index ()"


def _body(header: bytes, *rows: bytes) -> list[bytes]:
    return _META + [header] + list(rows)


def _parse(lines: list[bytes], metrics: str = "precipitation,uv_index", row_count: int = 2) -> list[tuple]:
    """Feed ``lines`` to a parser, then finish it; return the ``(utc_epoch, values)`` rows it passed on."""
    hours = []
    reader = _HourlyCsv(metrics, row_count, lambda utc, values: hours.append((utc, values)))
    for line in lines:
        reader.feed(line)
    reader.finish()
    return hours


def test_passes_each_row_in_metric_order_with_missing_values_as_none():
    hours = _parse(_body(_PARSER_HEADER, b"%d,0.20,NaN" % _T0, b"%d,,3" % (_T0 + _HOUR)))

    assert hours == [(_T0, [0.2, None]), (_T0 + _HOUR, [None, 3])]


def test_digits_only_parse_to_ints_and_other_numbers_to_floats():
    hours = _parse(_body(_PARSER_HEADER, b"%d,46,1.5" % _T0, b"%d,1e2,-3" % (_T0 + _HOUR)))

    assert hours == [(_T0, [46, 1.5]), (_T0 + _HOUR, [100.0, -3.0])]
    assert [[type(value) for value in values] for _, values in hours] == [[int, float], [float, float]]


def test_a_metric_named_as_a_prefix_of_another_column_is_rejected():
    header = b"time,precipitation_probability (%),uv_index ()"

    with pytest.raises(HttpParseError):
        _parse(_body(header, b"%d,0,0" % _T0, b"%d,0,0" % (_T0 + _HOUR)))


def test_a_column_without_a_unit_matches_its_metric():
    hours = _parse(_body(b"time,precipitation,uv_index", b"%d,1,2" % _T0, b"%d,3,4" % (_T0 + _HOUR)))

    assert [values for _, values in hours] == [[1, 2], [3, 4]]


@pytest.mark.parametrize(
    "lines",
    [
        _body(_PARSER_HEADER, b"%d,0" % _T0, b"%d,0,0" % (_T0 + _HOUR)),  # a short row
        _body(_PARSER_HEADER, b"%d,0,x" % _T0, b"%d,0,0" % (_T0 + _HOUR)),  # a non-number
        _body(b"time,precipitation (mm)", b"%d,0" % _T0),  # a header short of a metric
        _body(_PARSER_HEADER, b"%d,0,0" % _T0),  # a row missing
        _body(_PARSER_HEADER),  # only the header
        _body(  # a row extra
            _PARSER_HEADER, b"%d,0,0" % _T0, b"%d,0,0" % (_T0 + _HOUR), b"%d,0,0" % (_T0 + 2 * _HOUR)
        ),
        _body(_PARSER_HEADER, b"%d,0,0" % _T0, b"%d,0,0" % _T0),  # a repeated hour
        _body(_PARSER_HEADER, b"%d,0,0" % (_T0 + _HOUR), b"%d,0,0" % _T0),  # hours out of order
        _META,  # no header
        [b"<html>", b"<head>", b"<title>Login</title>", b"</head>", _PARSER_HEADER],  # the header too late
    ],
)
def test_a_malformed_body_raises_parse_error(lines):
    with pytest.raises(HttpParseError):
        _parse(lines)


# ---------------------------------------------------------------------------
# Service integration
# ---------------------------------------------------------------------------

_PRECIP_INDEX, _UV_INDEX, _AQI_INDEX, _POLLEN_INDEX = range(4)

_FORECAST_HEADER = b"time,precipitation_probability (%),precipitation (mm),weathercode (wmo code),uv_index ()"
_FORECAST_QUIET_ROW = b"0,0.00,0,0.00"
_AIR_HEADER = b"time,european_aqi (EAQI)," + b",".join(
    species.encode() + b"_pollen (grains/m\xc2\xb3)" for species in _SPECIES
)
_AIR_QUIET_ROW = b"10,0.0,0.0,0.0,0.0,0.0"
_PAST_HOURS = 1
_FORECAST_HOURS = 4
_ROW_COUNT = _PAST_HOURS + _FORECAST_HOURS


def _csv(header: bytes, quiet_row: bytes, *rows: bytes, row_count: int = _ROW_COUNT) -> list[bytes]:
    """A CSV body of ``row_count`` hourly rows from ``_T0``: ``rows``, padded with ``quiet_row`` hours."""
    rows += (quiet_row,) * (row_count - len(rows))
    return _body(header, *(b"%d,%s" % (_T0 + i * _HOUR, row) for i, row in enumerate(rows)))


def _forecast_csv(*rows: bytes) -> list[bytes]:
    return _csv(_FORECAST_HEADER, _FORECAST_QUIET_ROW, *rows)


def _air_csv(*rows: bytes) -> list[bytes]:
    return _csv(_AIR_HEADER, _AIR_QUIET_ROW, *rows)


class _FakeWifi:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected

    def is_connected(self) -> bool:
        return self.connected


class _FakeSchedule:
    def __init__(self) -> None:
        self.queue: list[tuple] = []

    def __call__(self, callback, arg) -> None:
        self.queue.append((callback, arg))

    def run_all(self) -> None:
        pending, self.queue = self.queue, []
        for callback, arg in pending:
            callback(arg)


class _Harness:
    """Serves the forecast and air-quality requests their own body, or raises their own exception."""

    def __init__(self, lat=50.0, lon=14.0, connected=True, forecast_hours=_FORECAST_HOURS) -> None:
        self.clock_val = 0
        self.wifi = _FakeWifi(connected)
        self.schedule = _FakeSchedule()
        self.coord = FetchCoordinator()
        self.forecast_lines = _forecast_csv(b"80,1.0,61,0")  # rain
        self.air_lines = _air_csv(b"60,0.0,0.0,0.0,0.0,0.0")  # AQI warning
        self.forecast_exc = None
        self.air_exc = None
        self.get_calls: list[tuple] = []
        self.utc_now = _T0
        self.service = OpenMeteoService(
            latitude=lat,
            longitude=lon,
            prob_threshold_pct=30,
            uv_thresholds=_UV,
            aqi_thresholds=_AQI_THR,
            pollen_thresholds=_POLLEN_THR,
            wifi=self.wifi,
            coordinator=self.coord,
            schedule=self.schedule,
            get_ticks_ms=lambda: self.clock_val,
            http_get_lines=self._http_get_lines,
            timeout_sec=7,
            interval_ms=1000,
            forecast_hours=forecast_hours,
            past_hours=_PAST_HOURS,
            max_events=10,
            get_utc_time=lambda: self.utc_now,
        )
        self.streams = self.service.build_streams()

    def _http_get_lines(self, url, on_line, timeout_sec=None):
        self.get_calls.append((url, timeout_sec))
        is_air = url.startswith("http://air-quality-api.")
        exc = self.air_exc if is_air else self.forecast_exc
        if exc is not None:
            raise exc
        for line in self.air_lines if is_air else self.forecast_lines:
            on_line(line)

    def requested_hosts(self) -> list[str]:
        return [url.split("/")[2] for url, _ in self.get_calls]

    def fetch(self) -> None:
        self.service.tick()
        self.schedule.run_all()
        self.service.tick()  # harvest

    def advance(self, ms: int) -> None:
        self.clock_val += ms

    def visible(self, stream_index: int) -> list[tuple[str, int]]:
        return [(e.label, e.start_utc) for e in self.streams[stream_index](self.utc_now)]


    def visible_names(self) -> list[list[str]]:
        return [[label for label, _ in self.visible(i)] for i in range(len(self.streams))]


@pytest.mark.parametrize("lat, lon, enabled", [(0.0, 0.0, False), (0.0, 14.42, True), (50.08, 0.0, True)])
def test_disabled_only_when_both_coordinates_are_zero(lat, lon, enabled):
    h = _Harness(lat=lat, lon=lon)

    h.fetch()

    assert bool(h.get_calls) == enabled


def test_one_fetch_publishes_all_four_streams_in_order():
    h = _Harness()
    h.forecast_lines = _forecast_csv(b"80,1.0,61,0", b"0,0.0,0,9")
    h.air_lines = _air_csv(b"60,0.0,0.0,0.0,0.0,0.0", b"0,0.0,0.0,0.0,0.0,3.0")

    h.service.tick()
    assert h.get_calls == []

    h.schedule.run_all()
    assert h.requested_hosts() == ["api.open-meteo.com", "air-quality-api.open-meteo.com"]

    h.service.tick()  # harvest: publish the parsed snapshot
    assert h.service._generation == 1
    assert h.visible_names() == [["RAIN"], ["UV"], ["AQI"], ["RAGWEED"]]
    assert h.visible(_PRECIP_INDEX) == [("RAIN", _T0)]
    assert h.visible(_POLLEN_INDEX) == [("RAGWEED", _T0 + _HOUR)]


def test_urls_ask_for_csv_in_utc_unix_time_with_coordinates_metrics_and_timeout():
    h = _Harness(lat=50.5, lon=14.25)
    h.fetch()

    (forecast_url, forecast_timeout), (air_url, air_timeout) = h.get_calls
    assert forecast_url.startswith("http://api.open-meteo.com/v1/forecast?")  # HTTP on purpose, not HTTPS
    assert air_url.startswith("http://air-quality-api.open-meteo.com/v1/air-quality?")
    for url in (forecast_url, air_url):
        for part in ("format=csv", "timeformat=unixtime", "timezone=GMT", "latitude=50.5", "longitude=14.25",
                     "forecast_hours=4", "past_hours=1"):
            assert part in url
    assert "hourly=precipitation_probability,precipitation,weathercode,uv_index" in forecast_url
    assert "hourly=european_aqi,alder_pollen,birch_pollen,grass_pollen,mugwort_pollen,ragweed_pollen" in air_url
    assert forecast_timeout == air_timeout == 7


def test_air_quality_forecast_is_capped_at_the_api_maximum():
    h = _Harness(forecast_hours=200)
    h.forecast_lines = _csv(_FORECAST_HEADER, _FORECAST_QUIET_ROW, row_count=_PAST_HOURS + 200)
    h.air_lines = _csv(_AIR_HEADER, _AIR_QUIET_ROW, row_count=_PAST_HOURS + 168)

    h.fetch()

    (forecast_url, _), (air_url, _) = h.get_calls
    assert "forecast_hours=200" in forecast_url
    assert "forecast_hours=168" in air_url
    assert h.service._generation == 1


def test_warnings_over_by_the_fetch_are_not_published():
    h = _Harness()
    h.forecast_lines = _forecast_csv(b"80,1.0,61,0", b"0,0.0,0,0", b"80,1.0,71,0")
    h.utc_now = _T0 + 2 * _HOUR

    h.fetch()

    assert [e.label for e in h.service._events[_PRECIP_INDEX]] == ["SNOW"]


def test_second_fetch_refreshes_the_streams():
    h = _Harness()
    h.fetch()
    assert h.visible_names() == [["RAIN"], [], ["AQI"], []]

    h.forecast_lines = _forecast_csv(b"80,1.0,71,0")
    h.air_lines = _air_csv(b"10,0.0,0.0,2.0,0.0,0.0")
    h.advance(1000)
    h.fetch()

    assert h.service._generation == 2
    assert h.visible_names() == [["SNOW"], [], [], ["GRASS"]]


def test_wifi_down_holds_without_fetching():
    h = _Harness(connected=False)

    for _ in range(3):
        h.service.tick()

    assert h.get_calls == []
    assert h.schedule.queue == []


def test_a_failed_forecast_request_skips_the_air_request_and_keeps_the_prior_snapshot():
    h = _Harness()
    h.fetch()

    h.forecast_exc = HttpConnectError("down")
    h.advance(1000)
    h.fetch()

    assert h.requested_hosts()[2:] == ["api.open-meteo.com"]
    assert h.service._failures == 1
    assert h.service._generation == 1
    assert h.visible_names() == [["RAIN"], [], ["AQI"], []]


def test_a_failed_air_request_publishes_no_stream_and_backs_off():
    h = _Harness()
    h.fetch()

    h.forecast_lines = _forecast_csv(b"80,1.0,71,0")
    h.air_exc = HttpConnectError("down")
    h.advance(1000)
    h.fetch()

    assert h.service._failures == 1
    assert h.service._generation == 1
    assert h.visible_names() == [["RAIN"], [], ["AQI"], []]


def test_a_truncated_body_backs_off_without_publishing():
    h = _Harness()
    h.air_lines = h.air_lines[:-1]

    h.fetch()

    assert h.service._failures == 1
    assert h.service._generation == 0
    assert h.visible_names() == [[], [], [], []]
