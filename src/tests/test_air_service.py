"""Tests for the outdoor air-quality service (AQI + pollen)."""

import time

import pytest

from displays.palette import STREAM_COLORS, STREAM_RED, STREAM_YELLOW
from scheduling.event_window import build_event_windows
from scheduling.stream import DISABLED, ERROR, FRESH, STALE, Stream
from services._fetch_machine import FetchCoordinator
from services.http_client import HttpConnectError
from services.air_service import (
    AirService,
    _build_events,
    _pollen_winner,
)

_SPECIES = ["grass", "birch", "alder", "mugwort", "ragweed"]
_AQI_THR = (60, 80)
_POLLEN_THR = (50, 100)

_T0 = "2026-06-04T10:00"
_T1 = "2026-06-04T11:00"
_T2 = "2026-06-04T12:00"
_EPOCH0 = time.mktime((2026, 6, 4, 10, 0, 0, 0, 0))
_HOUR = 3600


def _aq_payload(times, aqi, **pollen) -> dict:
    """Air-quality-shaped payload; absent species default to all-zero hours."""
    hourly = {"time": list(times), "european_aqi": list(aqi)}
    for sp in _SPECIES:
        hourly[sp + "_pollen"] = list(pollen.get(sp, [0] * len(times)))
    return {"hourly": hourly}


def _events(aq):
    return _build_events(aq, _SPECIES, _AQI_THR, _POLLEN_THR)


# ---------------------------------------------------------------------------
# _pollen_winner (bespoke: tie by highest count, not list order)
# ---------------------------------------------------------------------------


def test_pollen_winner_all_below_returns_none_label():
    assert _pollen_winner(("GRASS", "BIRCH"), [10, 20], 50, 100) == (0, None)


def test_pollen_winner_highest_severity_wins():
    assert _pollen_winner(("GRASS", "BIRCH"), [55, 120], 50, 100) == (2, "BIRCH")


def test_pollen_winner_tie_broken_by_count_not_order():
    # Both warning-level; the higher raw count wins even though it is listed 2nd.
    assert _pollen_winner(("GRASS", "MUGW"), [55, 70], 50, 100) == (1, "MUGW")


def test_pollen_winner_skips_none_values():
    assert _pollen_winner(("GRASS", "BIRCH"), [None, 55], 50, 100) == (1, "BIRCH")


# ---------------------------------------------------------------------------
# _build_events
# ---------------------------------------------------------------------------


def test_below_threshold_hours_emit_nothing():
    assert _events(_aq_payload([_T0], [10])) == []


def test_none_values_emit_nothing():
    assert _events(_aq_payload([_T0], [None], grass=[None])) == []


def test_empty_payload_yields_no_events():
    assert _events(_aq_payload([], [])) == []


def test_single_aqi_warning_hour():
    events = _events(_aq_payload([_T0], [60]))

    assert len(events) == 1
    ev = events[0]
    assert ev.name == "AQI"
    assert ev.color_index == STREAM_YELLOW
    assert ev.start_timestamp == _EPOCH0
    assert ev.wall_clock_duration_sec == _HOUR


def test_severe_maps_to_red():
    assert _events(_aq_payload([_T0], [80]))[0].color_index == STREAM_RED


def test_pollen_label_is_uppercased_species_name():
    assert _events(_aq_payload([_T0], [10], birch=[120]))[0].name == "BIRCH"


def test_aqi_wins_tie_over_pollen():
    # Equal level AQI vs pollen -> AQI wins (listed first).
    events = _events(_aq_payload([_T0], [60], grass=[55]))
    assert events[0].name == "AQI"


def test_pollen_wins_when_strictly_higher():
    events = _events(_aq_payload([_T0], [60], grass=[120]))
    assert events[0].name == "GRASS"
    assert events[0].color_index == STREAM_RED


def test_contiguous_same_metric_and_level_merge():
    events = _events(_aq_payload([_T0, _T1], [60, 65]))
    assert len(events) == 1
    assert events[0].wall_clock_duration_sec == 2 * _HOUR


def test_severity_change_splits_run():
    events = _events(_aq_payload([_T0, _T1], [60, 80]))
    assert [e.color_index for e in events] == [STREAM_YELLOW, STREAM_RED]


def test_metric_change_splits_run_even_at_same_level():
    events = _events(_aq_payload([_T0, _T1], [60, 10], grass=[0, 55]))
    assert [e.name for e in events] == ["AQI", "GRASS"]
    assert [e.color_index for e in events] == [STREAM_YELLOW, STREAM_YELLOW]


def test_gap_hour_breaks_the_run():
    events = _events(_aq_payload([_T0, _T1, _T2], [60, 10, 60]))
    assert len(events) == 2
    assert events[1].start_timestamp == _EPOCH0 + 2 * _HOUR


def test_time_discontinuity_does_not_merge_into_wide_bar():
    events = _events(_aq_payload([_T0, _T2], [60, 60]))  # 2h jump
    assert len(events) == 2
    assert all(e.wall_clock_duration_sec == _HOUR for e in events)
    assert events[1].start_timestamp == _EPOCH0 + 2 * _HOUR


def test_mismatched_array_lengths_raise():
    payload = {
        "hourly": {
            "time": [_T0, _T1],
            "european_aqi": [60],
            "grass_pollen": [0, 0], "birch_pollen": [0, 0], "alder_pollen": [0, 0],
            "mugwort_pollen": [0, 0], "ragweed_pollen": [0, 0],
        }
    }
    with pytest.raises(ValueError):
        _events(payload)


def test_missing_pollen_key_raises():
    payload = {"hourly": {"time": [_T0], "european_aqi": [10]}}
    with pytest.raises(KeyError):
        _events(payload)


def test_empty_species_is_aqi_only():
    aq = {"hourly": {"time": [_T0], "european_aqi": [60]}}
    events = _build_events(aq, [], _AQI_THR, _POLLEN_THR)
    assert len(events) == 1
    assert events[0].name == "AQI"


def test_emitted_color_indices_are_valid_palette_indices():
    for ev in _events(_aq_payload([_T0, _T1], [60, 80])):
        assert ev.color_index in (STREAM_YELLOW, STREAM_RED)
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
        self.payload = _aq_payload([_T0], [60])  # AQI warning
        self.raise_exc = None
        self.get_calls: list[tuple] = []
        self.service = AirService(
            latitude=lat,
            longitude=lon,
            species=_SPECIES,
            aqi_thresholds=_AQI_THR,
            pollen_thresholds=_POLLEN_THR,
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

    h.service.tick()  # harvest: publish the parsed snapshot
    assert h.service.generation == 1
    assert h.visible_names() == ["AQI"]
    assert h.service.status == FRESH


def test_url_is_air_quality_with_species_and_timeout():
    h = _Harness(lat=50.5, lon=14.25)
    h.service.tick()
    h.schedule.run_all()

    url, timeout = h.get_calls[0]
    assert url.startswith("http://air-quality-api.open-meteo.com")  # HTTP on purpose, not HTTPS
    assert "latitude=50.5" in url
    assert "past_hours=1" in url
    assert "hourly=european_aqi,grass_pollen,birch_pollen,alder_pollen,mugwort_pollen,ragweed_pollen" in url
    assert "uv_index" not in url
    assert timeout == 3


def test_http_error_backs_off_and_keeps_prior_snapshot():
    h = _Harness()
    h.service.tick()
    h.schedule.run_all()
    h.service.tick()  # harvest -> ["AQI"]
    assert h.visible_names() == ["AQI"]

    h.raise_exc = HttpConnectError("down")
    h.advance(1000)
    h.service.tick()
    h.schedule.run_all()
    h.service.tick()  # harvest the failure -> backoff

    assert h.service._failures == 1
    assert h.service.generation == 1
    assert h.visible_names() == ["AQI"]


def test_malformed_payload_backs_off_without_publishing():
    h = _Harness()
    h.payload = {"unexpected": "shape"}

    h.service.tick()
    h.schedule.run_all()
    assert len(h.get_calls) == 1

    h.service.tick()  # harvest the parse failure -> backoff
    assert h.service._failures == 1
    assert h.service.generation == 0
    assert h.visible_names() == []


def test_wifi_down_holds_without_fetching():
    h = _Harness(connected=False)

    for _ in range(3):
        h.service.tick()

    assert h.get_calls == []
    assert h.schedule.queue == []
    assert h.service.status == STALE


def test_error_status_after_repeated_failures():
    h = _Harness()
    h.raise_exc = HttpConnectError("down")

    for _ in range(3):
        h.advance(700_000)
        h.service.tick()
        h.schedule.run_all()
        h.service.tick()  # harvest records the failure

    assert h.service.status == ERROR
    assert h.window.status() == ERROR
