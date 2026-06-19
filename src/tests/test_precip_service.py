"""Tests for the precipitation forecast service."""

import time

import pytest

from displays.palette import STREAM_COLORS, STREAM_GREEN, STREAM_RED, STREAM_YELLOW
from scheduling.event_window import build_event_windows
from scheduling.stream import DISABLED, ERROR, FRESH, STALE, Stream
from services._fetch_state import BACKOFF, FETCHING, FetchCoordinator
from services.http_client import HttpConnectError
from services.precip_service import (
    PrecipService,
    _build_events,
    _intensity_index,
    _parse_iso_local,
    _weather_type,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, expected",
    [
        (51, "RAIN"),   # drizzle
        (61, "RAIN"),   # rain
        (67, "RAIN"),   # freezing rain
        (80, "RAIN"),   # rain showers
        (71, "SNOW"),   # snow fall
        (75, "SNOW"),   # heavy snow
        (85, "SNOW"),   # snow showers
        (86, "SNOW"),   # heavy snow showers
        (95, "STORM"),  # thunderstorm
        (99, "STORM"),  # thunderstorm w/ hail
        (0, None),      # clear -> not precipitation
        (3, None),      # overcast -> not precipitation
        (45, None),     # fog -> not precipitation
    ],
)
def test_weather_type_mapping(code, expected):
    assert _weather_type(code) == expected


@pytest.mark.parametrize(
    "mm, expected",
    [
        (0.0, STREAM_GREEN),
        (2.49, STREAM_GREEN),
        (2.5, STREAM_YELLOW),
        (7.59, STREAM_YELLOW),
        (7.6, STREAM_RED),
        (20.0, STREAM_RED),
    ],
)
def test_intensity_index_bands(mm, expected):
    assert _intensity_index(mm) == expected


def test_parse_iso_local_matches_mktime():
    assert _parse_iso_local("2026-06-04T15:00") == time.mktime((2026, 6, 4, 15, 0, 0, 0, 0))


def test_parse_iso_local_midnight():
    assert _parse_iso_local("2026-12-31T00:00") == time.mktime((2026, 12, 31, 0, 0, 0, 0, 0))


# ---------------------------------------------------------------------------
# _build_events
# ---------------------------------------------------------------------------


def _payload(*hours) -> dict:
    """Build an Open-Meteo-shaped payload from (iso, prob, mm, code) tuples."""
    return {
        "hourly": {
            "time": [h[0] for h in hours],
            "precipitation_probability": [h[1] for h in hours],
            "precipitation": [h[2] for h in hours],
            "weathercode": [h[3] for h in hours],
        }
    }


_T0 = "2026-06-04T10:00"
_EPOCH0 = time.mktime((2026, 6, 4, 10, 0, 0, 0, 0))
_HOUR = 3600


def test_below_threshold_hours_emit_nothing():
    payload = _payload(
        (_T0, 10, 1.0, 61),
        ("2026-06-04T11:00", 0, 0.0, 0),
    )
    assert _build_events(payload, 30) == []


def test_prob_equal_threshold_emits():
    # The gate is strict ``<``: a probability exactly at the threshold shows.
    assert len(_build_events(_payload((_T0, 30, 1.0, 61)), 30)) == 1


def test_non_precip_code_emits_no_bar_even_above_threshold():
    # High probability but a clear-sky code: no precipitation bar.
    assert _build_events(_payload((_T0, 90, 0.0, 0)), 30) == []


def test_empty_time_array_yields_no_events():
    payload = {
        "hourly": {
            "time": [],
            "precipitation_probability": [],
            "precipitation": [],
            "weathercode": [],
        }
    }
    assert _build_events(payload, 30) == []


def test_mismatched_array_lengths_raise():
    # A structurally-valid dict whose hourly arrays disagree in length must
    # raise so the fetch state machine backs off rather than publishing a
    # silently-truncated forecast.
    payload = {
        "hourly": {
            "time": [_T0, "2026-06-04T11:00"],
            "precipitation_probability": [80],
            "precipitation": [1.0],
            "weathercode": [61],
        }
    }
    with pytest.raises(ValueError):
        _build_events(payload, 30)


def test_single_qualifying_hour_emits_one_event():
    payload = _payload((_T0, 50, 1.0, 61))

    events = _build_events(payload, 30)

    assert len(events) == 1
    ev = events[0]
    assert ev.name == "RAIN"
    assert ev.start_timestamp == _EPOCH0
    assert ev.wall_clock_duration_sec == _HOUR
    assert ev.color_index == STREAM_GREEN


@pytest.mark.parametrize(
    "mm, expected_index",
    [(1.0, STREAM_GREEN), (5.0, STREAM_YELLOW), (10.0, STREAM_RED)],
)
def test_all_three_intensity_bands_emit(mm, expected_index):
    events = _build_events(_payload((_T0, 80, mm, 61)), 30)
    assert events[0].color_index == expected_index


def test_contiguous_equal_runs_merge():
    payload = _payload(
        (_T0, 80, 1.0, 61),
        ("2026-06-04T11:00", 80, 1.2, 61),
        ("2026-06-04T12:00", 80, 0.8, 61),
    )

    events = _build_events(payload, 30)

    assert len(events) == 1
    assert events[0].wall_clock_duration_sec == 3 * _HOUR
    assert events[0].start_timestamp == _EPOCH0


def test_intensity_band_change_splits_run():
    payload = _payload(
        (_T0, 80, 1.0, 61),            # green
        ("2026-06-04T11:00", 80, 5.0, 61),  # yellow
    )

    events = _build_events(payload, 30)

    assert [e.color_index for e in events] == [STREAM_GREEN, STREAM_YELLOW]
    assert all(e.wall_clock_duration_sec == _HOUR for e in events)


def test_type_change_splits_run_even_at_same_intensity():
    payload = _payload(
        (_T0, 80, 1.0, 61),            # RAIN, green
        ("2026-06-04T11:00", 80, 1.0, 71),  # SNOW, green
    )

    events = _build_events(payload, 30)

    assert [e.name for e in events] == ["RAIN", "SNOW"]
    assert [e.color_index for e in events] == [STREAM_GREEN, STREAM_GREEN]


def test_gap_hour_breaks_the_run():
    payload = _payload(
        (_T0, 80, 1.0, 61),
        ("2026-06-04T11:00", 0, 0.0, 0),    # below threshold -> gap
        ("2026-06-04T12:00", 80, 1.0, 61),
    )

    events = _build_events(payload, 30)

    assert len(events) == 2
    assert events[0].start_timestamp == _EPOCH0
    assert events[1].start_timestamp == _EPOCH0 + 2 * _HOUR


def test_time_discontinuity_does_not_merge_into_wide_bar():
    # Same type+band but a 2-hour jump in the series (e.g. a DST spring-forward
    # skip) must not merge into one over-wide bar — the contiguity guard splits
    # them into two correct 1-hour bars.
    payload = _payload(
        (_T0, 80, 1.0, 61),
        ("2026-06-04T12:00", 80, 1.0, 61),  # 2h after _T0, not 1h
    )

    events = _build_events(payload, 30)

    assert len(events) == 2
    assert all(e.wall_clock_duration_sec == _HOUR for e in events)
    assert events[1].start_timestamp == _EPOCH0 + 2 * _HOUR


def test_none_precipitation_amount_treated_as_zero():
    events = _build_events(_payload((_T0, 80, None, 61)), 30)
    assert events[0].color_index == STREAM_GREEN


def test_emitted_color_indices_are_valid_palette_indices():
    payload = _payload(
        (_T0, 80, 1.0, 61),
        ("2026-06-04T11:00", 80, 5.0, 71),
        ("2026-06-04T12:00", 80, 10.0, 95),
    )

    for ev in _build_events(payload, 30):
        assert ev.color_index in (STREAM_GREEN, STREAM_YELLOW, STREAM_RED)
        assert 0 <= ev.color_index < len(STREAM_COLORS)


# ---------------------------------------------------------------------------
# Service integration
# ---------------------------------------------------------------------------


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
    def __init__(self, lat=50.0, lon=14.0, threshold=30, connected=True) -> None:
        self.clock_val = 0
        self.wifi = _FakeWifi(connected)
        self.schedule = _FakeSchedule()
        self.coord = FetchCoordinator()
        self.payload = _payload((_T0, 80, 1.0, 61))
        self.raise_exc = None
        self.get_calls: list[tuple] = []
        self.service = PrecipService(
            latitude=lat,
            longitude=lon,
            prob_threshold=threshold,
            wifi=self.wifi,
            coordinator=self.coord,
            schedule=self.schedule,
            clock=lambda: self.clock_val,
            http_get=self._http_get,
            interval_ms=1000,
        )
        stream = Stream(
            self.service.events_iter(),
            events_fn=self.service.events_iter,
            generation_fn=lambda: self.service.generation,
            status_fn=lambda: self.service.status,
        )
        self.window = build_event_windows(((1, 2),) * len(STREAM_COLORS), [stream])[0]

    def _http_get(self, url, timeout_s=None):
        self.get_calls.append((url, timeout_s))
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.payload

    def advance(self, ms: int) -> None:
        self.clock_val += ms

    def visible_names(self) -> list[str]:
        return [e.name for e, _ in self.window.get_visible(_EPOCH0 - _HOUR, _EPOCH0 + 100 * _HOUR)]


def test_disabled_when_coordinates_unset():
    h = _Harness(lat=0.0, lon=0.0)

    for _ in range(5):
        h.service.tick()

    assert h.get_calls == []
    assert h.service.status == DISABLED
    assert h.window.status() == DISABLED


def test_fetch_publishes_events_and_goes_fresh():
    h = _Harness()

    h.service.tick()  # -> FETCHING, fetch deferred
    assert h.get_calls == []
    assert h.service.status == STALE

    h.schedule.run_all()  # fetch + parse + store

    assert len(h.get_calls) == 1
    assert h.service.generation == 1
    assert h.visible_names() == ["RAIN"]
    assert h.service.status == FRESH


def test_url_includes_coordinates_and_timeout():
    h = _Harness(lat=50.5, lon=14.25)
    h.service.tick()
    h.schedule.run_all()

    url, timeout = h.get_calls[0]
    assert url.startswith("http://")  # HTTP on purpose — avoids RP2040 TLS ENOMEM
    assert "latitude=50.5" in url
    assert "longitude=14.25" in url
    assert "timezone=auto" in url
    assert "hourly=precipitation_probability" in url
    assert timeout == 3


def test_second_fetch_refreshes_window():
    h = _Harness()
    h.service.tick()
    h.schedule.run_all()
    assert h.visible_names() == ["RAIN"]

    h.payload = _payload(("2026-06-04T10:00", 80, 1.0, 71))  # now SNOW
    h.advance(1000)
    h.service.tick()
    h.schedule.run_all()

    assert h.service.generation == 2
    assert h.visible_names() == ["SNOW"]


def test_wifi_down_holds_without_fetching():
    h = _Harness(connected=False)

    for _ in range(3):
        h.service.tick()

    assert h.get_calls == []
    assert h.schedule.queue == []
    assert h.service.status == STALE


def test_http_error_backs_off_and_keeps_prior_snapshot():
    h = _Harness()
    h.service.tick()
    h.schedule.run_all()
    assert h.visible_names() == ["RAIN"]

    h.raise_exc = HttpConnectError("down")
    h.advance(1000)
    h.service.tick()
    h.schedule.run_all()

    assert h.service._fetch.state == BACKOFF
    assert h.service.generation == 1  # no publish on failure
    assert h.visible_names() == ["RAIN"]  # prior snapshot retained


def test_malformed_payload_backs_off_without_publishing():
    h = _Harness()
    h.payload = {"unexpected": "shape"}

    h.service.tick()
    h.schedule.run_all()

    assert len(h.get_calls) == 1
    assert h.service._fetch.state == BACKOFF
    assert h.service.generation == 0
    assert h.visible_names() == []


def test_error_status_after_repeated_failures():
    h = _Harness()
    h.raise_exc = HttpConnectError("down")

    for _ in range(3):
        h.advance(700_000)
        h.service.tick()
        h.schedule.run_all()

    assert h.service.status == ERROR
    assert h.window.status() == ERROR


def test_payload_exposed_for_uv_sharing():
    h = _Harness()
    h.service.tick()
    h.schedule.run_all()

    assert h.service.payload is h.payload
