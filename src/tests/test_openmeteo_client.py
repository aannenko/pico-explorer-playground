"""Tests for the shared Open-Meteo client."""

import pytest

from services import openmeteo_client
from services.http_client import HttpParseError

_META = [
    b"latitude,longitude,elevation,utc_offset_seconds,timezone,timezone_abbreviation",
    b"50.07752,14.427236,208.0,0,GMT,GMT",
    b"",
]
_T0 = 1_794_855_600
_HOUR = 3600


class _FakeLines:
    def __init__(self, lines) -> None:
        self.lines = lines
        self.calls: list[tuple] = []

    def __call__(self, url, on_line, timeout_sec=None) -> None:
        self.calls.append((url, timeout_sec))
        for line in self.lines:
            on_line(line)


def _body(header: bytes, *rows: bytes) -> list[bytes]:
    return _META + [header] + list(rows)


def _forecast(lines, forecast_hours=1, past_hours=1, metrics="precipitation,uv_index"):
    http = _FakeLines(lines)
    hours = []
    openmeteo_client.fetch_forecast(
        http, 50.5, 14.25, metrics, 7, forecast_hours, past_hours, lambda utc, values: hours.append((utc, values))
    )
    return http, hours


_HEADER = b"time,precipitation (mm),uv_index ()"


def test_forecast_url_asks_for_csv_in_utc_unix_time():
    http, _ = _forecast(_body(_HEADER, b"%d,0.00,1.50" % _T0, b"%d,0.10,2.00" % (_T0 + _HOUR)))

    url, timeout = http.calls[0]
    assert url.startswith("http://api.open-meteo.com/v1/forecast?")  # HTTP on purpose, not HTTPS
    for part in ("format=csv", "timeformat=unixtime", "timezone=GMT", "latitude=50.5", "longitude=14.25",
                 "hourly=precipitation,uv_index", "forecast_hours=1", "past_hours=1"):
        assert part in url
    assert timeout == 7


def test_passes_each_row_in_metric_order_with_missing_values_as_none():
    _, hours = _forecast(_body(_HEADER, b"%d,0.20,NaN" % _T0, b"%d,,3" % (_T0 + _HOUR)))

    assert hours == [(_T0, [0.2, None]), (_T0 + _HOUR, [None, 3.0])]


def test_digits_only_parse_to_ints_and_other_numbers_to_floats():
    _, hours = _forecast(_body(_HEADER, b"%d,46,1.5" % _T0, b"%d,1e2,-3" % (_T0 + _HOUR)))

    assert hours == [(_T0, [46, 1.5]), (_T0 + _HOUR, [100.0, -3.0])]
    assert [[type(value) for value in values] for _, values in hours] == [[int, float], [float, float]]


def test_a_metric_named_as_a_prefix_of_another_column_is_rejected():
    header = b"time,precipitation_probability (%),uv_index ()"

    with pytest.raises(HttpParseError):
        _forecast(_body(header, b"%d,0,0" % _T0, b"%d,0,0" % (_T0 + _HOUR)))


def test_a_column_without_a_unit_matches_its_metric():
    _, hours = _forecast(_body(b"time,precipitation,uv_index", b"%d,1,2" % _T0, b"%d,3,4" % (_T0 + _HOUR)))

    assert [values for _, values in hours] == [[1.0, 2.0], [3.0, 4.0]]


@pytest.mark.parametrize(
    "lines",
    [
        _body(_HEADER, b"%d,0" % _T0, b"%d,0,0" % (_T0 + _HOUR)),  # a short row
        _body(_HEADER, b"%d,0,x" % _T0, b"%d,0,0" % (_T0 + _HOUR)),  # a non-number
        _body(b"time,precipitation (mm)", b"%d,0" % _T0),  # a header short of a metric
        _body(_HEADER, b"%d,0,0" % _T0),  # a row missing
        _body(_HEADER),  # only the header
        _body(_HEADER, b"%d,0,0" % _T0, b"%d,0,0" % (_T0 + _HOUR), b"%d,0,0" % (_T0 + 2 * _HOUR)),  # a row extra
        _body(_HEADER, b"%d,0,0" % _T0, b"%d,0,0" % _T0),  # a repeated hour
        _body(_HEADER, b"%d,0,0" % (_T0 + _HOUR), b"%d,0,0" % _T0),  # hours out of order
        _META,  # no header
        [b"<html>", b"<head>", b"<title>Login</title>", b"</head>", _HEADER],  # the header too late
    ],
)
def test_a_malformed_body_raises_parse_error(lines):
    with pytest.raises(HttpParseError):
        _forecast(lines)


def test_air_quality_url_and_parse():
    http = _FakeLines(_body(b"time,european_aqi (EAQI),grass_pollen (grains/m\xc2\xb3)", b"%d,46,0.0" % _T0))
    hours = []

    openmeteo_client.fetch_air_quality(
        http, 50.0, 14.0, "european_aqi,grass_pollen", 3, 1, 0, lambda utc, values: hours.append((utc, values))
    )

    url, timeout = http.calls[0]
    assert url.startswith("http://air-quality-api.open-meteo.com/v1/air-quality?")
    assert "hourly=european_aqi,grass_pollen" in url
    assert timeout == 3
    assert hours == [(_T0, [46.0, 0.0])]


def test_air_quality_forecast_is_capped_at_the_api_maximum():
    cap = openmeteo_client.AIR_QUALITY_MAX_FORECAST_HOURS
    rows = [b"%d,1" % (_T0 + i * _HOUR) for i in range(cap)]
    http = _FakeLines(_body(b"time,european_aqi (EAQI)", *rows))

    openmeteo_client.fetch_air_quality(http, 50.0, 14.0, "european_aqi", 3, cap + 24, 0, lambda utc, values: None)

    assert cap == 168
    assert "forecast_hours=168" in http.calls[0][0]


def test_location_is_unset_only_when_both_coordinates_are_zero():
    assert openmeteo_client.is_location_set(0.0, 0.0) is False
    assert openmeteo_client.is_location_set(0.0, 14.42) is True
    assert openmeteo_client.is_location_set(50.08, 0.0) is True
