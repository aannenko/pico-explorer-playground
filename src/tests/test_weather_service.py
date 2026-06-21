"""Tests for the weather forecast service (precipitation + UV)."""

import time

import pytest

from displays.palette import (
    STREAM_COLORS,
    STREAM_GREEN,
    STREAM_RED,
    STREAM_YELLOW,
)
from scheduling.event_window import build_event_windows
from scheduling.stream import DISABLED, ERROR, FRESH, STALE, Stream
from services._fetch_state import BACKOFF, FetchCoordinator
from services.http_client import HttpConnectError
from services.weather_service import (
    WeatherService,
    _build_events,
    _intensity,
    _weather_type,
)

_UV = (6, 8)  # (warning, severe) UV thresholds used across the suite


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, expected",
    [
        (51, "RAIN"), (61, "RAIN"), (67, "RAIN"), (80, "RAIN"),
        (71, "SNOW"), (75, "SNOW"), (85, "SNOW"), (86, "SNOW"),
        (95, "STORM"), (99, "STORM"),
        (0, None), (3, None), (45, None),
    ],
)
def test_weather_type_mapping(code, expected):
    assert _weather_type(code) == expected


@pytest.mark.parametrize(
    "mm, expected",
    [
        (0.0, (1, STREAM_GREEN)),
        (2.49, (1, STREAM_GREEN)),
        (2.5, (2, STREAM_YELLOW)),
        (7.59, (2, STREAM_YELLOW)),
        (7.6, (3, STREAM_RED)),
        (20.0, (3, STREAM_RED)),
    ],
)
def test_intensity_rank_and_color(mm, expected):
    assert _intensity(mm) == expected


# ---------------------------------------------------------------------------
# _build_events
# ---------------------------------------------------------------------------


def _payload(*hours, uv=None) -> dict:
    """Open-Meteo-shaped payload from (iso, prob, mm, code) tuples.

    ``uv`` (a list aligned with the hours) is added only when given, so the
    precip-only tests exercise the missing-uv_index path.
    """
    hourly = {
        "time": [h[0] for h in hours],
        "precipitation_probability": [h[1] for h in hours],
        "precipitation": [h[2] for h in hours],
        "weathercode": [h[3] for h in hours],
    }
    if uv is not None:
        hourly["uv_index"] = uv
    return {"hourly": hourly}


_T0 = "2026-06-04T10:00"
_T1 = "2026-06-04T11:00"
_T2 = "2026-06-04T12:00"
_EPOCH0 = time.mktime((2026, 6, 4, 10, 0, 0, 0, 0))
_HOUR = 3600


def _be(payload, threshold=30):
    return _build_events(payload, threshold, _UV)


# --- precipitation ---------------------------------------------------------


def test_below_threshold_hours_emit_nothing():
    assert _be(_payload((_T0, 10, 1.0, 61), (_T1, 0, 0.0, 0))) == []


def test_prob_equal_threshold_emits():
    assert len(_be(_payload((_T0, 30, 1.0, 61)))) == 1


def test_non_precip_code_emits_no_bar_even_above_threshold():
    assert _be(_payload((_T0, 90, 0.0, 0))) == []


def test_empty_time_array_yields_no_events():
    payload = {"hourly": {"time": [], "precipitation_probability": [],
                          "precipitation": [], "weathercode": []}}
    assert _be(payload) == []


def test_mismatched_array_lengths_raise():
    payload = {
        "hourly": {
            "time": [_T0, _T1],
            "precipitation_probability": [80],
            "precipitation": [1.0],
            "weathercode": [61],
        }
    }
    with pytest.raises(ValueError):
        _be(payload)


def test_single_qualifying_hour_emits_one_event():
    events = _be(_payload((_T0, 50, 1.0, 61)))

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
    assert _be(_payload((_T0, 80, mm, 61)))[0].color_index == expected_index


def test_contiguous_equal_runs_merge():
    events = _be(_payload(
        (_T0, 80, 1.0, 61), (_T1, 80, 1.2, 61), (_T2, 80, 0.8, 61),
    ))
    assert len(events) == 1
    assert events[0].wall_clock_duration_sec == 3 * _HOUR
    assert events[0].start_timestamp == _EPOCH0


def test_intensity_band_change_splits_run():
    events = _be(_payload((_T0, 80, 1.0, 61), (_T1, 80, 5.0, 61)))
    assert [e.color_index for e in events] == [STREAM_GREEN, STREAM_YELLOW]


def test_type_change_splits_run_even_at_same_intensity():
    events = _be(_payload((_T0, 80, 1.0, 61), (_T1, 80, 1.0, 71)))
    assert [e.name for e in events] == ["RAIN", "SNOW"]


def test_gap_hour_breaks_the_run():
    events = _be(_payload(
        (_T0, 80, 1.0, 61), (_T1, 0, 0.0, 0), (_T2, 80, 1.0, 61),
    ))
    assert len(events) == 2
    assert events[1].start_timestamp == _EPOCH0 + 2 * _HOUR


def test_time_discontinuity_does_not_merge_into_wide_bar():
    events = _be(_payload((_T0, 80, 1.0, 61), (_T2, 80, 1.0, 61)))  # 2h jump
    assert len(events) == 2
    assert all(e.wall_clock_duration_sec == _HOUR for e in events)
    assert events[1].start_timestamp == _EPOCH0 + 2 * _HOUR


def test_none_precipitation_amount_treated_as_zero():
    assert _be(_payload((_T0, 80, None, 61)))[0].color_index == STREAM_GREEN


# --- UV + conflict policy (A: severity-honest) -----------------------------


def test_uv_renders_when_no_precip():
    # Low precip probability, high UV -> a UV bar.
    events = _be(_payload((_T0, 0, 0.0, 0), uv=[7]))
    assert len(events) == 1
    assert events[0].name == "UV"
    assert events[0].color_index == STREAM_YELLOW  # warning


def test_severe_uv_maps_to_red():
    assert _be(_payload((_T0, 0, 0.0, 0), uv=[9]))[0].color_index == STREAM_RED


def test_severe_uv_beats_light_precip():
    # Green drizzle (rank 1) collides with severe UV (level 2) -> UV wins.
    events = _be(_payload((_T0, 80, 1.0, 61), uv=[9]))
    assert events[0].name == "UV"
    assert events[0].color_index == STREAM_RED


def test_precip_wins_tie_over_warning_uv():
    # Green drizzle (rank 1) vs warning UV (level 1) -> tie -> precip first.
    events = _be(_payload((_T0, 80, 1.0, 61), uv=[7]))
    assert events[0].name == "RAIN"


def test_heavier_precip_wins_over_severe_uv():
    # Moderate rain (rank 2) ties severe UV (level 2) -> precip first wins.
    events = _be(_payload((_T0, 80, 5.0, 61), uv=[9]))
    assert events[0].name == "RAIN"
    assert events[0].color_index == STREAM_YELLOW


def test_uv_below_threshold_emits_nothing():
    assert _be(_payload((_T0, 0, 0.0, 0), uv=[3])) == []


def test_malformed_uv_index_precip_still_renders():
    # A non-list uv_index must not fail the whole fetch — precip still shows.
    payload = _payload((_T0, 80, 1.0, 61))
    payload["hourly"]["uv_index"] = None
    events = _be(payload)
    assert [e.name for e in events] == ["RAIN"]


def test_short_uv_index_precip_still_renders():
    payload = _payload((_T0, 80, 1.0, 61), (_T1, 80, 1.0, 61))
    payload["hourly"]["uv_index"] = [9]  # wrong length -> UV suppressed
    events = _be(payload)
    assert all(e.name == "RAIN" for e in events)


def test_non_list_uv_index_precip_still_renders():
    # A non-list uv_index that happens to have len()==n (e.g. a string) must
    # not break _level / fail the fetch — precip still shows.
    payload = _payload((_T0, 80, 1.0, 61))
    payload["hourly"]["uv_index"] = "9"
    events = _be(payload)
    assert [e.name for e in events] == ["RAIN"]


def test_uv_index_with_non_numeric_element_precip_still_renders():
    # A correctly-sized uv_index list carrying a stray non-numeric element must
    # not reach _level and crash the fetch — that hour's UV is dropped silently
    # and precip still renders.
    payload = _payload((_T0, 80, 1.0, 61))
    payload["hourly"]["uv_index"] = ["oops"]
    events = _be(payload)
    assert [e.name for e in events] == ["RAIN"]


def test_emitted_color_indices_are_valid_palette_indices():
    payload = _payload(
        (_T0, 80, 1.0, 61), (_T1, 80, 5.0, 71), (_T2, 80, 10.0, 95),
        uv=[3, 3, 3],
    )
    for ev in _be(payload):
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
    def __init__(self, lat=50.0, lon=14.0, connected=True) -> None:
        self.clock_val = 0
        self.wifi = _FakeWifi(connected)
        self.schedule = _FakeSchedule()
        self.coord = FetchCoordinator()
        self.payload = _payload((_T0, 80, 1.0, 61))
        self.raise_exc = None
        self.get_calls: list[tuple] = []
        self.service = WeatherService(
            latitude=lat,
            longitude=lon,
            prob_threshold=30,
            uv_thresholds=_UV,
            wifi=self.wifi,
            coordinator=self.coord,
            schedule=self.schedule,
            clock=lambda: self.clock_val,
            http_get=self._http_get,
            interval_ms=1000,
            forecast_hours=4,
            past_hours=1,
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

    h.service.tick()
    assert h.get_calls == []
    assert h.service.status == STALE

    h.schedule.run_all()

    assert len(h.get_calls) == 1
    assert h.service.generation == 1
    assert h.visible_names() == ["RAIN"]
    assert h.service.status == FRESH


def test_url_includes_coordinates_uv_and_timeout():
    h = _Harness(lat=50.5, lon=14.25)
    h.service.tick()
    h.schedule.run_all()

    url, timeout = h.get_calls[0]
    assert url.startswith("http://")  # HTTP on purpose — avoids RP2040 TLS ENOMEM
    assert "latitude=50.5" in url
    assert "longitude=14.25" in url
    assert "timezone=auto" in url
    assert "past_hours=1" in url
    assert "hourly=precipitation_probability" in url
    assert "uv_index" in url
    assert timeout == 3


def test_uv_renders_through_the_service():
    h = _Harness()
    h.payload = _payload((_T0, 0, 0.0, 0), uv=[9])  # no precip, severe UV
    h.service.tick()
    h.schedule.run_all()
    assert h.visible_names() == ["UV"]


def test_second_fetch_refreshes_window():
    h = _Harness()
    h.service.tick()
    h.schedule.run_all()
    assert h.visible_names() == ["RAIN"]

    h.payload = _payload((_T0, 80, 1.0, 71))  # now SNOW
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
    assert h.service.generation == 1
    assert h.visible_names() == ["RAIN"]


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
