"""Tests for the outdoor air-quality service (AQI and pollen streams)."""

import pytest

from displays.palette import STREAM_COLORS, STREAM_ORANGE, STREAM_RED, STREAM_YELLOW
from scheduling.event_window import build_event_windows
from services.air_service import AirService, _AirHours
from services.fetch_machine import FetchCoordinator
from services.http_client import HttpConnectError

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
_CET_SEC = 3600


# ---------------------------------------------------------------------------
# _AirHours
# ---------------------------------------------------------------------------


def _row(aqi, **pollen) -> list:
    """One hour's values: the AQI, then each species' count, absent species 0."""
    return [aqi] + [pollen.get(species, 0) for species in _SPECIES]


def _hours(*rows, pollen_thresholds=_POLLEN_THR, max_events=10):
    """Feed hourly rows from ``_T0``; return the AQI and pollen events."""
    hours = _AirHours(_AQI_THR, pollen_thresholds, lambda utc: _CET_SEC, max_events, 0)
    for i, row in enumerate(rows):
        hours.add_hour(_T0 + i * _HOUR, row)
    return hours.aqi.events(), hours.pollen.events()


def _aqi(*rows):
    return _hours(*rows)[0]


def _pollen(*rows):
    return _hours(*rows)[1]


def test_below_threshold_hours_emit_nothing():
    assert _hours(_row(10)) == ([], [])


def test_none_values_emit_nothing():
    assert _hours(_row(None, grass=None)) == ([], [])


def test_single_aqi_hour_is_one_local_event():
    events = _aqi(_row(60))

    assert [(e.label, e.start_timestamp, e.wall_clock_duration_sec, e.color_index) for e in events] == [
        ("AQI", _T0 + _CET_SEC, _HOUR, STREAM_YELLOW)
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
    aqi, pollen = _hours(_row(60, grass=40))

    assert [(e.label, e.color_index) for e in aqi] == [("AQI", STREAM_YELLOW)]
    assert [(e.label, e.color_index) for e in pollen] == [("GRASS", STREAM_RED)]


def test_contiguous_hours_merge_at_their_highest_level():
    events = _aqi(_row(60), _row(85), _row(65))

    assert [(e.wall_clock_duration_sec, e.color_index) for e in events] == [(3 * _HOUR, STREAM_ORANGE)]


def test_species_change_splits_run_even_at_same_level():
    events = _pollen(_row(0, grass=2), _row(0, birch=2))

    assert [(e.label, e.color_index) for e in events] == [("GRASS", STREAM_YELLOW), ("BIRCH", STREAM_YELLOW)]


def test_gap_hour_breaks_the_run():
    events = _aqi(_row(60), _row(10), _row(60))

    assert [e.start_timestamp - _CET_SEC for e in events] == [_T0, _T0 + 2 * _HOUR]


def test_no_species_is_aqi_only():
    aqi, pollen = _hours([60], pollen_thresholds=[])

    assert [e.label for e in aqi] == ["AQI"]
    assert pollen == []


def test_each_stream_keeps_at_most_max_events():
    _, pollen = _hours(_row(0, grass=2), _row(0, birch=2), _row(0, grass=2), max_events=2)

    assert [e.label for e in pollen] == ["GRASS", "BIRCH"]


def test_emitted_color_indices_are_valid_palette_indices():
    aqi, pollen = _hours(_row(60, grass=2), _row(100, grass=40))

    for ev in aqi + pollen:
        assert 0 <= ev.color_index < len(STREAM_COLORS)


# ---------------------------------------------------------------------------
# Service integration
# ---------------------------------------------------------------------------

_HEADER = b"time,european_aqi (EAQI)," + b",".join(
    species.encode() + b"_pollen (grains/m\xc2\xb3)" for species in _SPECIES
)
_QUIET_ROW = b"10,0.0,0.0,0.0,0.0,0.0"
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
        self.lines = _csv(b"60,0.0,0.0,0.0,0.0,0.0")  # AQI warning
        self.raise_exc = None
        self.get_calls: list[tuple] = []
        self.service = AirService(
            latitude=lat,
            longitude=lon,
            aqi_thresholds=_AQI_THR,
            pollen_thresholds=_POLLEN_THR,
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
            get_utc_time=lambda: _T0,
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
    assert h.visible() == [("AQI", _T0 + _CET_SEC)]


def test_url_is_air_quality_with_species_and_timeout():
    h = _Harness(lat=50.5, lon=14.25)
    h.fetch()

    url, timeout = h.get_calls[0]
    assert url.startswith("http://air-quality-api.open-meteo.com")  # HTTP on purpose, not HTTPS
    assert "latitude=50.5" in url
    assert "past_hours=1" in url
    assert "hourly=european_aqi,alder_pollen,birch_pollen,grass_pollen,mugwort_pollen,ragweed_pollen" in url
    assert "uv_index" not in url
    assert timeout == 3


def test_one_fetch_publishes_aqi_and_pollen_to_their_own_streams():
    h = _Harness()
    h.lines = _csv(b"60,0.0,0.0,0.0,0.0,0.0", b"0,0.0,0.0,0.0,0.0,3.0")
    h.fetch()

    assert h.visible_names(0) == ["AQI"]
    assert h.visible_names(1) == ["RAGWEED"]


def test_http_error_backs_off_and_keeps_prior_snapshot():
    h = _Harness()
    h.fetch()
    assert h.visible_names() == ["AQI"]

    h.raise_exc = HttpConnectError("down")
    h.advance(1000)
    h.fetch()

    assert h.service._failures == 1
    assert h.service.generation == 1
    assert h.visible_names() == ["AQI"]


def test_truncated_body_backs_off_without_publishing():
    h = _Harness()
    h.lines = h.lines[:-1]

    h.fetch()

    assert h.service._failures == 1
    assert h.service.generation == 0
    assert h.visible_names() == []


def test_wifi_down_holds_without_fetching():
    h = _Harness(connected=False)

    for _ in range(3):
        h.service.tick()

    assert h.get_calls == []
    assert h.schedule.queue == []
