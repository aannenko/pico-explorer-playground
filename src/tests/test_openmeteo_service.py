"""Tests for the Open-Meteo service: its CSV parser and its precipitation, UV, AQI and pollen warning streams."""

import pytest

from conftest import FakeBody, make_timer_factory
from displays.palette import STREAM_COLORS, STREAM_ORANGE, STREAM_RED, STREAM_YELLOW
from services.http_client import HttpConnectError, HttpParseError, Response
from services.openmeteo_service import OpenMeteoService, _AirHours, _parse_hourly_csv, _precip_label, _WeatherHours
from services.tick_scheduler import TickScheduler

_UV = (6, 8, 11)  # UV thresholds used across the suite
_POLLEN_THR = [
    ("alder", "ALDER", (1, 11, 101)),
    ("birch", "BIRCH", (1, 11, 51)),
    ("grass", "GRASS", (1, 6, 31)),
    ("mugwort", "MGWRT", (1, 6, 11)),
    ("ragweed", "RGWD", (1, 6, 11)),
]
_SPECIES = [species for species, _, _ in _POLLEN_THR]
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


def test_prob_equal_threshold_emits():
    assert len(_precip((30, 1.0, 61, 0))) == 1


@pytest.mark.parametrize("row", [(10, 1.0, 61, 0), (None, 1.0, 61, 0), (90, 1.0, None, 0), (90, 0.0, 0, 0)])
def test_a_probability_below_the_threshold_or_missing_or_a_non_precipitation_code_emits_nothing(row):
    assert _precip(row) == []


@pytest.mark.parametrize(
    "mm, expected_index",
    [
        (0.0, STREAM_YELLOW),
        (2.49, STREAM_YELLOW),
        (2.5, STREAM_ORANGE),
        (7.59, STREAM_ORANGE),
        (7.6, STREAM_RED),
        (20.0, STREAM_RED),
        (None, STREAM_YELLOW),
    ],
)
def test_a_qualifying_hour_is_one_event_at_its_amount_s_level(mm, expected_index):
    events = _precip((80, mm, 61, 0))

    assert [(e.label, e.start_utc, e.duration_sec, e.color_index) for e in events] == [
        ("RAIN", _T0, _HOUR, expected_index)
    ]


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
    """Feed hourly rows from ``_T0``; return the AQI events and each species' pollen events."""
    hours = _AirHours(_AQI_THR, pollen_thresholds, max_events, 0)
    for i, row in enumerate(rows):
        hours.add_hour(_T0 + i * _HOUR, row)
    return hours.aqi.events(), [builder.events() for builder in hours.pollen]


def _aqi(*rows):
    return _air_hours(*rows)[0]


def _pollen(*rows) -> dict[str, list[tuple[str, int]]]:
    """Each species' pollen events, as ``(label, color_index)``, by species."""
    return {
        species: [(e.label, e.color_index) for e in events] for species, events in zip(_SPECIES, _air_hours(*rows)[1])
    }


def _by_species(**pollen) -> dict[str, list[tuple[str, int]]]:
    """The expected ``_pollen`` result: ``pollen``'s species, and no events for the others."""
    return {species: pollen.get(species, []) for species in _SPECIES}


@pytest.mark.parametrize("row", [_row(10), _row(None, grass=None)], ids=["below-threshold", "missing"])
def test_air_below_threshold_or_missing_emits_nothing(row):
    assert _air_hours(row) == ([], [[]] * len(_SPECIES))


@pytest.mark.parametrize(
    "aqi, expected_index",
    [(60, STREAM_YELLOW), (79, STREAM_YELLOW), (80, STREAM_ORANGE), (99, STREAM_ORANGE), (100, STREAM_RED)],
)
def test_an_aqi_hour_is_one_event_at_its_level(aqi, expected_index):
    events = _aqi(_row(aqi))

    assert [(e.label, e.start_utc, e.duration_sec, e.color_index) for e in events] == [
        ("AQI", _T0, _HOUR, expected_index)
    ]


@pytest.mark.parametrize(
    "grains, expected_index", [(1, STREAM_YELLOW), (11, STREAM_ORANGE), (51, STREAM_RED)]
)
def test_pollen_level_uses_the_species_thresholds(grains, expected_index):
    assert _pollen(_row(10, birch=grains)) == _by_species(birch=[("BIRCH", expected_index)])


def test_each_species_warns_in_its_own_stream_at_its_own_level():
    # 20 grass grains is level 2, while 12 mugwort grains is already level 3.
    assert _pollen(_row(0, grass=20, mugwort=12)) == _by_species(
        grass=[("GRASS", STREAM_ORANGE)], mugwort=[("MGWRT", STREAM_RED)]
    )


def test_aqi_and_pollen_in_the_same_hour_both_emit():
    aqi, pollen = _air_hours(_row(60, grass=40))

    assert [(e.label, e.color_index) for e in aqi] == [("AQI", STREAM_YELLOW)]
    assert [(e.label, e.color_index) for e in pollen[_SPECIES.index("grass")]] == [("GRASS", STREAM_RED)]


def test_aqi_contiguous_hours_merge_at_their_highest_level():
    events = _aqi(_row(60), _row(85), _row(65))

    assert [(e.duration_sec, e.color_index) for e in events] == [(3 * _HOUR, STREAM_ORANGE)]


def test_a_species_run_continues_through_another_species_hours():
    _, pollen = _air_hours(_row(0, grass=2), _row(0, grass=2, birch=60), _row(0, grass=2))

    grass = pollen[_SPECIES.index("grass")]
    birch = pollen[_SPECIES.index("birch")]
    assert [(e.start_utc, e.duration_sec) for e in grass] == [(_T0, 3 * _HOUR)]
    assert [(e.label, e.start_utc, e.duration_sec, e.color_index) for e in birch] == [
        ("BIRCH", _T0 + _HOUR, _HOUR, STREAM_RED)
    ]


def test_aqi_gap_hour_breaks_the_run():
    events = _aqi(_row(60), _row(10), _row(60))

    assert [e.start_utc for e in events] == [_T0, _T0 + 2 * _HOUR]


def test_no_species_is_aqi_only():
    aqi, pollen = _air_hours([60], pollen_thresholds=[])

    assert [e.label for e in aqi] == ["AQI"]
    assert pollen == []


def test_each_pollen_stream_keeps_at_most_max_events():
    _, pollen = _air_hours(
        _row(0, grass=2), _row(0), _row(0, grass=2, birch=2), _row(0), _row(0, grass=2), max_events=2
    )

    assert [e.start_utc for e in pollen[_SPECIES.index("grass")]] == [_T0, _T0 + 2 * _HOUR]
    assert [e.start_utc for e in pollen[_SPECIES.index("birch")]] == [_T0 + 2 * _HOUR]


def test_air_color_indices_are_valid_palette_indices():
    aqi, pollen = _air_hours(_row(60, grass=2), _row(100, grass=40))

    for ev in aqi + [ev for events in pollen for ev in events]:
        assert 0 <= ev.color_index < len(STREAM_COLORS)


# ---------------------------------------------------------------------------
# _parse_hourly_csv
# ---------------------------------------------------------------------------

_META = [b"latitude,longitude", b"50.0,14.0", b""]
_PARSER_HEADER = b"time,precipitation (mm),uv_index ()"


def _body(header: bytes, *rows: bytes) -> list[bytes]:
    return _META + [header] + list(rows)


def _parse(lines: list[bytes], metrics: str = "precipitation,uv_index", row_count: int = 2) -> list[tuple]:
    """Parse ``lines``; return the ``(utc_epoch, values)`` rows the parser passed on."""
    hours = []
    _parse_hourly_csv(iter(lines), metrics, row_count, lambda utc, values: hours.append((utc, values)))
    return hours


def test_passes_each_row_in_metric_order_with_missing_values_as_none():
    hours = _parse(_body(_PARSER_HEADER, b"%d,0.20,NaN" % _T0, b"%d,,3" % (_T0 + _HOUR)))

    assert hours == [(_T0, [0.2, None]), (_T0 + _HOUR, [None, 3])]


def test_digits_only_parse_to_ints_and_other_numbers_to_floats():
    hours = _parse(_body(_PARSER_HEADER, b"%d,46,1.5" % _T0, b"%d,1e2,-3" % (_T0 + _HOUR)))

    assert hours == [(_T0, [46, 1.5]), (_T0 + _HOUR, [100.0, -3.0])]
    assert [[type(value) for value in values] for _, values in hours] == [[int, float], [float, float]]


def test_a_column_without_a_unit_matches_its_metric():
    hours = _parse(_body(b"time,precipitation,uv_index", b"%d,1,2" % _T0, b"%d,3,4" % (_T0 + _HOUR)))

    assert [values for _, values in hours] == [[1, 2], [3, 4]]


@pytest.mark.parametrize(
    "lines",
    [
        _body(_PARSER_HEADER, b"%d,0" % _T0, b"%d,0,0" % (_T0 + _HOUR)),  # a short row
        _body(_PARSER_HEADER, b"%d,0,x" % _T0, b"%d,0,0" % (_T0 + _HOUR)),  # a non-number
        _body(b"time,precipitation (mm)", b"%d,0" % _T0),  # a header short of a metric
        _body(  # a metric named as a prefix of another column
            b"time,precipitation_probability (%),uv_index ()", b"%d,0,0" % _T0, b"%d,0,0" % (_T0 + _HOUR)
        ),
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

_PRECIP_INDEX, _UV_INDEX, _AQI_INDEX = range(3)
_RAGWEED_INDEX = 3 + _SPECIES.index("ragweed")


def _names(precip: list[str], uv: list[str], aqi: list[str], **pollen) -> list[list[str]]:
    """The expected ``_Harness.visible_names()``: these streams' labels, then ``pollen``'s species' labels and no
    others'."""
    return [precip, uv, aqi] + [pollen.get(species, []) for species in _SPECIES]

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


class _FakeHttpClient:
    """Serves the forecast and air-quality requests a real ``Response`` over their own body, or raises their own
    exception."""

    def __init__(self) -> None:
        self.forecast_lines = _forecast_csv(b"80,1.0,61,0")  # rain
        self.air_lines = _air_csv(b"60,0.0,0.0,0.0,0.0,0.0")  # AQI warning
        self.forecast_exc = None
        self.air_exc = None
        self.read_exc = None
        self.urls: list[str] = []
        self.bodies: list[FakeBody] = []

    def get(self, url: str) -> Response:
        self.urls.append(url)
        is_air = url.startswith("http://air-quality-api.")
        exc = self.air_exc if is_air else self.forecast_exc
        if exc is not None:
            raise exc
        body = FakeBody([b"\n".join(self.air_lines if is_air else self.forecast_lines)], self.read_exc)
        self.bodies.append(body)
        return Response(body, deadline_ms=10_000)


class _Harness:
    """An ``OpenMeteoService`` on a real ``TickScheduler``, whose ticks the test runs, and a ``_FakeHttpClient``."""

    def __init__(self, lat=50.0, lon=14.0, forecast_hours=_FORECAST_HOURS, pollen_thresholds=_POLLEN_THR) -> None:
        self.clock_val = 0
        timer_factory, _ = make_timer_factory()
        self.scheduler = TickScheduler(schedule=lambda callback, arg: None, timer_factory=timer_factory)
        self.http_client = _FakeHttpClient()
        self.utc_now = _T0
        self.service = OpenMeteoService(
            latitude=lat,
            longitude=lon,
            prob_threshold_pct=30,
            uv_thresholds=_UV,
            aqi_thresholds=_AQI_THR,
            pollen_thresholds=pollen_thresholds,
            http_client=self.http_client,
            tick_scheduler=self.scheduler,
            get_ticks_ms=lambda: self.clock_val,
            interval_ms=1000,
            forecast_hours=forecast_hours,
            past_hours=_PAST_HOURS,
            max_events=10,
            get_utc_time=lambda: self.utc_now,
        )
        self.streams = self.service.build_streams()

    def requested_hosts(self) -> list[str]:
        return [url.split("/")[2] for url in self.http_client.urls]

    def fetch(self) -> None:
        self.scheduler._tick(0)

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

    assert bool(h.http_client.urls) == enabled


def test_one_fetch_publishes_every_stream_in_order():
    h = _Harness()
    h.http_client.forecast_lines = _forecast_csv(b"80,1.0,61,0", b"0,0.0,0,9")
    h.http_client.air_lines = _air_csv(b"60,0.0,0.0,0.0,0.0,0.0", b"0,0.0,2.0,0.0,0.0,3.0")

    h.fetch()

    assert h.requested_hosts() == ["api.open-meteo.com", "air-quality-api.open-meteo.com"]
    assert h.visible_names() == [["RAIN"], ["UV"], ["AQI"], [], ["BIRCH"], [], [], ["RGWD"]]
    assert h.visible(_PRECIP_INDEX) == [("RAIN", _T0)]
    assert h.visible(_RAGWEED_INDEX) == [("RGWD", _T0 + _HOUR)]
    assert [body.closed for body in h.http_client.bodies] == [True, True]


def test_pollen_streams_follow_the_configured_species_in_their_order():
    h = _Harness(pollen_thresholds=[("ragweed", "RGWD", (1, 6, 11)), ("birch", "BIRCH", (1, 11, 51))])
    h.http_client.air_lines = _csv(
        b"time,european_aqi (EAQI),ragweed_pollen (grains/m\xc2\xb3),birch_pollen (grains/m\xc2\xb3)",
        b"10,0.0,0.0",
        b"10,NaN,60.0",
        b"10,7.0,0.0",
    )

    h.fetch()

    assert "&hourly=european_aqi,ragweed_pollen,birch_pollen&" in h.http_client.urls[1]
    assert h.visible_names() == [["RAIN"], [], [], ["RGWD"], ["BIRCH"]]


def test_urls_ask_for_csv_in_utc_unix_time_with_coordinates_and_metrics():
    h = _Harness(lat=50.5, lon=14.25)
    h.fetch()

    forecast_url, air_url = h.http_client.urls
    assert forecast_url.startswith("http://api.open-meteo.com/v1/forecast?")  # HTTP on purpose, not HTTPS
    assert air_url.startswith("http://air-quality-api.open-meteo.com/v1/air-quality?")
    for url in (forecast_url, air_url):
        for part in ("format=csv", "timeformat=unixtime", "timezone=GMT", "latitude=50.5", "longitude=14.25",
                     "forecast_hours=4", "past_hours=1"):
            assert part in url
    assert "hourly=precipitation_probability,precipitation,weathercode,uv_index" in forecast_url
    assert "hourly=european_aqi,alder_pollen,birch_pollen,grass_pollen,mugwort_pollen,ragweed_pollen" in air_url


def test_air_quality_forecast_is_capped_at_the_api_maximum():
    h = _Harness(forecast_hours=200)
    h.http_client.forecast_lines = _csv(
        _FORECAST_HEADER, _FORECAST_QUIET_ROW, b"80,1.0,61,0", row_count=_PAST_HOURS + 200
    )
    h.http_client.air_lines = _csv(
        _AIR_HEADER, _AIR_QUIET_ROW, b"60,0.0,0.0,0.0,0.0,0.0", row_count=_PAST_HOURS + 168
    )

    h.fetch()

    forecast_url, air_url = h.http_client.urls
    assert "forecast_hours=200" in forecast_url
    assert "forecast_hours=168" in air_url
    assert h.visible_names() == _names(["RAIN"], [], ["AQI"])


def test_warnings_over_by_the_fetch_are_not_published():
    h = _Harness()
    h.http_client.forecast_lines = _forecast_csv(b"80,1.0,61,0", b"0,0.0,0,0", b"80,1.0,71,0")
    h.utc_now = _T0 + 2 * _HOUR

    h.fetch()

    assert [e.label for e in h.service._events[_PRECIP_INDEX]] == ["SNOW"]


def test_second_fetch_refreshes_the_streams():
    h = _Harness()
    h.fetch()
    assert h.visible_names() == _names(["RAIN"], [], ["AQI"])

    h.http_client.forecast_lines = _forecast_csv(b"80,1.0,71,0")
    h.http_client.air_lines = _air_csv(b"10,0.0,0.0,2.0,0.0,0.0")
    h.advance(1000)
    h.fetch()

    assert h.visible_names() == _names(["SNOW"], [], [], grass=["GRASS"])


@pytest.mark.parametrize(
    "attribute, value, requested_hosts, body_count",
    [
        pytest.param("forecast_exc", HttpConnectError("down"), ["api.open-meteo.com"], 0, id="forecast-request"),
        pytest.param(
            "air_exc", HttpConnectError("down"), ["api.open-meteo.com", "air-quality-api.open-meteo.com"], 1,
            id="air-request",
        ),
        pytest.param("read_exc", OSError(9999, "connection reset"), ["api.open-meteo.com"], 1, id="read"),
        pytest.param(
            "forecast_lines", _forecast_csv(b"80,1.0,71,0")[:-1], ["api.open-meteo.com"], 1, id="forecast-truncated"
        ),
        pytest.param(
            "air_lines", _air_csv(b"10,0.0,0.0,2.0,0.0,0.0")[:-1],
            ["api.open-meteo.com", "air-quality-api.open-meteo.com"], 2, id="air-truncated",
        ),
    ],
)
def test_a_failed_request_aborts_the_refresh_without_publishing_and_closes_its_bodies(
    attribute: str, value, requested_hosts: list[str], body_count: int
) -> None:
    h = _Harness()
    h.fetch()
    previous = [stream(h.utc_now) for stream in h.streams]
    h.http_client.forecast_lines = _forecast_csv(b"80,1.0,71,0")
    h.http_client.air_lines = _air_csv(b"10,0.0,0.0,2.0,0.0,0.0")
    setattr(h.http_client, attribute, value)
    h.advance(1000)

    h.fetch()

    assert h.requested_hosts()[2:] == requested_hosts
    assert h.service._failures == 1
    assert h.visible_names() == _names(["RAIN"], [], ["AQI"])
    assert all(stream(h.utc_now) is old for stream, old in zip(h.streams, previous))
    assert [body.closed for body in h.http_client.bodies[2:]] == [True] * body_count
