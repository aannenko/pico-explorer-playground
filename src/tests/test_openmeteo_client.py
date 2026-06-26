"""Tests for the shared Open-Meteo client helpers."""

import time

import pytest

from services import openmeteo_client


class _FakeHttp:
    def __init__(self, payload=None) -> None:
        self.payload = payload if payload is not None else {"ok": True}
        self.calls: list[tuple] = []

    def __call__(self, url, timeout_s=None) -> dict:
        self.calls.append((url, timeout_s))
        return self.payload


# ---------------------------------------------------------------------------
# URL building + fetch entry points
# ---------------------------------------------------------------------------


def test_fetch_forecast_builds_forecast_url_and_passes_timeout():
    http = _FakeHttp({"hourly": {}})

    result = openmeteo_client.fetch_forecast(http, 50.5, 14.25, "precipitation", 7, 4, 1)

    assert result == {"hourly": {}}
    url, timeout = http.calls[0]
    assert url.startswith("http://api.open-meteo.com/v1/forecast?")  # HTTP on purpose, not HTTPS
    assert "latitude=50.5" in url
    assert "longitude=14.25" in url
    assert "hourly=precipitation" in url
    assert "timezone=auto" in url
    assert "forecast_hours=4" in url
    assert "past_hours=1" in url
    assert timeout == 7


def test_fetch_air_quality_builds_air_quality_url():
    http = _FakeHttp()

    openmeteo_client.fetch_air_quality(http, 50.0, 14.0, "european_aqi,grass_pollen", 3, 4, 2)

    url, timeout = http.calls[0]
    assert url.startswith("http://air-quality-api.open-meteo.com/v1/air-quality?")
    assert "hourly=european_aqi,grass_pollen" in url
    assert "forecast_hours=4" in url
    assert "past_hours=2" in url
    assert timeout == 3


def test_fetch_honours_explicit_hours():
    http = _FakeHttp()
    openmeteo_client.fetch_forecast(http, 1.0, 2.0, "x", 3, hours=6, past_hours=3)
    assert "forecast_hours=6" in http.calls[0][0]
    assert "past_hours=3" in http.calls[0][0]


# ---------------------------------------------------------------------------
# parse_iso_local  (relocated from the precip suite)
# ---------------------------------------------------------------------------


def test_parse_iso_local_matches_mktime():
    assert openmeteo_client.parse_iso_local("2026-06-04T15:00") == time.mktime(
        (2026, 6, 4, 15, 0, 0, 0, 0)
    )


def test_parse_iso_local_midnight():
    assert openmeteo_client.parse_iso_local("2026-12-31T00:00") == time.mktime(
        (2026, 12, 31, 0, 0, 0, 0, 0)
    )


# ---------------------------------------------------------------------------
# extract_hourly
# ---------------------------------------------------------------------------


def test_extract_hourly_returns_arrays_in_key_order():
    payload = {"hourly": {"time": [1, 2], "a": [10, 20], "b": [30, 40]}}

    times, a, b = openmeteo_client.extract_hourly(payload, ("time", "a", "b"))

    assert times == [1, 2]
    assert a == [10, 20]
    assert b == [30, 40]


def test_extract_hourly_empty_arrays_ok():
    payload = {"hourly": {"time": [], "a": []}}
    assert openmeteo_client.extract_hourly(payload, ("time", "a")) == [[], []]


def test_extract_hourly_raises_on_mismatched_lengths():
    payload = {"hourly": {"time": [1, 2], "a": [10]}}
    with pytest.raises(ValueError):
        openmeteo_client.extract_hourly(payload, ("time", "a"))


def test_extract_hourly_raises_on_missing_key():
    payload = {"hourly": {"time": [1, 2]}}
    with pytest.raises(KeyError):
        openmeteo_client.extract_hourly(payload, ("time", "absent"))


def test_extract_hourly_raises_on_missing_hourly():
    with pytest.raises(KeyError):
        openmeteo_client.extract_hourly({"unexpected": "shape"}, ("time",))
