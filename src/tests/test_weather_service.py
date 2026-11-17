"""Tests for the weather forecast service (precipitation and UV streams)."""

import pytest

from displays.palette import (
    STREAM_COLORS,
    STREAM_ORANGE,
    STREAM_RED,
    STREAM_YELLOW,
)
from scheduling.event_window import build_event_windows
from services.fetch_machine import FetchCoordinator
from services.http_client import HttpConnectError
from services.weather_service import WeatherService, _precip_label, _WeatherHours

_UV = (6, 8, 11)  # UV thresholds used across the suite
_T0 = 1_794_855_600
_HOUR = 3600
_CET_SEC = 3600


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


def _hours(*rows, threshold=30, max_events=10):
    """Feed hourly ``(prob, mm, code, uv)`` rows from ``_T0``; return the precipitation and UV events."""
    hours = _WeatherHours(threshold, _UV, lambda utc: _CET_SEC, max_events, 0)
    for i, row in enumerate(rows):
        hours.add_hour(_T0 + i * _HOUR, list(row))
    return hours.precip.events(), hours.uv.events()


def _precip(*rows, threshold=30):
    return _hours(*rows, threshold=threshold)[0]


def _uv(*rows):
    return _hours(*rows)[1]


# --- precipitation ---------------------------------------------------------


def test_below_threshold_hours_emit_nothing():
    assert _precip((10, 1.0, 61, 0), (0, 0.0, 0, 0)) == []


def test_prob_equal_threshold_emits():
    assert len(_precip((30, 1.0, 61, 0))) == 1


@pytest.mark.parametrize("row", [(None, 1.0, 61, 0), (90, 1.0, None, 0), (90, 0.0, 0, 0)])
def test_a_missing_probability_or_a_non_precipitation_code_emits_nothing(row):
    assert _precip(row) == []


def test_single_qualifying_hour_emits_one_local_event():
    events = _precip((50, 1.0, 61, 0))

    assert [(e.label, e.start_timestamp, e.wall_clock_duration_sec, e.color_index) for e in events] == [
        ("RAIN", _T0 + _CET_SEC, _HOUR, STREAM_YELLOW)
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


def test_contiguous_hours_merge_at_their_highest_level():
    events = _precip((80, 1.0, 61, 0), (80, 5.0, 61, 0), (80, 0.8, 61, 0))

    assert [(e.wall_clock_duration_sec, e.color_index) for e in events] == [(3 * _HOUR, STREAM_ORANGE)]


def test_type_change_splits_run_even_at_same_level():
    assert [e.label for e in _precip((80, 1.0, 61, 0), (80, 1.0, 71, 0))] == ["RAIN", "SNOW"]


def test_gap_hour_breaks_the_run():
    events = _precip((80, 1.0, 61, 0), (0, 0.0, 0, 0), (80, 1.0, 61, 0))

    assert [e.start_timestamp - _CET_SEC for e in events] == [_T0, _T0 + 2 * _HOUR]


def test_each_stream_keeps_at_most_max_events():
    precip, _ = _hours((80, 1.0, 61, 0), (80, 1.0, 71, 0), (80, 1.0, 61, 0), max_events=2)

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
    precip, uv = _hours((80, 1.0, 61, 9))

    assert [(e.label, e.start_timestamp) for e in precip] == [("RAIN", _T0 + _CET_SEC)]
    assert [(e.label, e.start_timestamp) for e in uv] == [("UV", _T0 + _CET_SEC)]


def test_emitted_color_indices_are_valid_palette_indices():
    precip, uv = _hours((80, 1.0, 61, 7), (80, 5.0, 71, 9), (80, 10.0, 95, 12))

    for ev in precip + uv:
        assert 0 <= ev.color_index < len(STREAM_COLORS)


# ---------------------------------------------------------------------------
# Service integration
# ---------------------------------------------------------------------------

_HEADER = b"time,precipitation_probability (%),precipitation (mm),weathercode (wmo code),uv_index ()"
_QUIET_ROW = b"0,0.00,0,0.00"
# past_hours + forecast_hours of the harness.
_ROW_COUNT = 5


def _csv(*rows: bytes, row_count: int = _ROW_COUNT) -> list[bytes]:
    """A CSV body of hourly rows from ``_T0``, padded with quiet hours to ``row_count``."""
    rows += (_QUIET_ROW,) * (row_count - len(rows))
    return [b"latitude,longitude", b"50.0,14.0", b"", _HEADER] + [
        b"%d,%s" % (_T0 + i * _HOUR, row) for i, row in enumerate(rows)
    ]


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
        self.lines = _csv(b"80,1.0,61,0")
        self.raise_exc = None
        self.get_calls: list[tuple] = []
        self.utc_now = _T0
        self.service = WeatherService(
            latitude=lat,
            longitude=lon,
            prob_threshold_pct=30,
            uv_thresholds=_UV,
            wifi=self.wifi,
            coordinator=self.coord,
            schedule=self.schedule,
            get_ticks_ms=lambda: self.clock_val,
            http_get_lines=self._http_get_lines,
            interval_ms=1000,
            forecast_hours=4,
            past_hours=1,
            utc_offset_sec=lambda utc: _CET_SEC,
            max_events=10,
            get_utc_time=lambda: self.utc_now,
        )
        self.windows = build_event_windows(((1, 2),) * len(STREAM_COLORS), self.service.build_streams())

    def _http_get_lines(self, url, on_line, timeout_sec=None):
        self.get_calls.append((url, timeout_sec))
        if self.raise_exc is not None:
            raise self.raise_exc
        for line in self.lines:
            on_line(line)

    def fetch(self) -> None:
        self.service.tick()
        self.schedule.run_all()
        self.service.tick()  # harvest

    def advance(self, ms: int) -> None:
        self.clock_val += ms

    def visible(self, stream_index: int = 0) -> list[tuple[str, int]]:
        window = self.windows[stream_index]
        local_t0 = _T0 + _CET_SEC
        return [(e.label, e.start_timestamp) for e, _ in window.get_visible(local_t0, local_t0 + 100 * _HOUR)]

    def visible_names(self, stream_index: int = 0) -> list[str]:
        return [label for label, _ in self.visible(stream_index)]


def test_disabled_when_coordinates_unset():
    h = _Harness(lat=0.0, lon=0.0)

    for _ in range(5):
        h.service.tick()

    assert h.get_calls == []


def test_fetch_publishes_local_events():
    h = _Harness()

    h.service.tick()
    assert h.get_calls == []

    h.schedule.run_all()
    assert len(h.get_calls) == 1

    h.service.tick()  # harvest: publish the parsed snapshot
    assert h.service.generation == 1
    assert h.visible() == [("RAIN", _T0 + _CET_SEC)]


def test_url_includes_coordinates_metrics_and_timeout():
    h = _Harness(lat=50.5, lon=14.25)
    h.fetch()

    url, timeout = h.get_calls[0]
    assert url.startswith("http://")  # HTTP on purpose, not HTTPS
    for part in ("latitude=50.5", "longitude=14.25", "format=csv", "forecast_hours=4", "past_hours=1",
                 "hourly=precipitation_probability,precipitation,weathercode,uv_index"):
        assert part in url
    assert timeout == 3


def test_one_fetch_publishes_precipitation_and_uv_to_their_own_streams():
    h = _Harness()
    h.lines = _csv(b"80,1.0,61,0", b"0,0.0,0,9")
    h.fetch()

    assert h.visible_names(0) == ["RAIN"]
    assert h.visible_names(1) == ["UV"]


def test_warnings_over_by_the_fetch_are_not_published():
    h = _Harness()
    h.lines = _csv(b"80,1.0,61,0", b"0,0.0,0,0", b"80,1.0,71,0")
    h.utc_now = _T0 + 2 * _HOUR

    h.fetch()

    assert h.service._events[0][0].label == "SNOW"
    assert len(h.service._events[0]) == 1


def test_second_fetch_refreshes_window():
    h = _Harness()
    h.fetch()
    assert h.visible_names() == ["RAIN"]

    h.lines = _csv(b"80,1.0,71,0")
    h.advance(1000)
    h.fetch()

    assert h.service.generation == 2
    assert h.visible_names() == ["SNOW"]


def test_wifi_down_holds_without_fetching():
    h = _Harness(connected=False)

    for _ in range(3):
        h.service.tick()

    assert h.get_calls == []
    assert h.schedule.queue == []


def test_http_error_backs_off_and_keeps_prior_snapshot():
    h = _Harness()
    h.fetch()
    assert h.visible_names() == ["RAIN"]

    h.raise_exc = HttpConnectError("down")
    h.advance(1000)
    h.fetch()

    assert h.service._failures == 1
    assert h.service.generation == 1
    assert h.visible_names() == ["RAIN"]


def test_truncated_body_backs_off_and_keeps_prior_snapshot():
    h = _Harness()
    h.fetch()

    h.lines = _csv(b"80,1.0,71,0")[:-1]
    h.advance(1000)
    h.fetch()

    assert h.service._failures == 1
    assert h.service.generation == 1
    assert h.visible_names() == ["RAIN"]
