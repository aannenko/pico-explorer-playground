from __future__ import annotations

import pytest

from services.network_upkeep import NetworkUpkeep

from conftest import TICKS_PERIOD_MS as _TICKS_PERIOD_MS

_PERIOD_MS = 12 * 60 * 60 * 1000
_HOUR_MS = 60 * 60 * 1000


class _FakeWifi:
    def __init__(self, connected: bool) -> None:
        self.connected = connected

    def is_connected(self) -> bool:
        return self.connected


class _FakeScheduler:
    def __init__(self) -> None:
        self.callbacks: list = []

    def register(self, callback) -> None:
        self.callbacks.append(callback)


class _Recorder:
    """Records the upkeep's calls in order; each ``*_error`` is raised once by its call."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.sync_ok = True
        self.reconnect_error: Exception | None = None
        self.sync_error: Exception | None = None

    def start_reconnect(self) -> None:
        self.calls.append("reconnect")
        error, self.reconnect_error = self.reconnect_error, None
        if error is not None:
            raise error

    def sync_clock(self) -> bool:
        self.calls.append("sync")
        error, self.sync_error = self.sync_error, None
        if error is not None:
            raise error
        return self.sync_ok


def _scheduled_upkeep(wifi: _FakeWifi, recorder: _Recorder, period_ms: int = _PERIOD_MS) -> _FakeScheduler:
    """Build an upkeep; return the scheduler holding its tick."""
    scheduler = _FakeScheduler()
    NetworkUpkeep(
        wifi=wifi, start_reconnect=recorder.start_reconnect, sync_clock=recorder.sync_clock, period_ms=period_ms,
        tick_scheduler=scheduler,
    )
    return scheduler


def _tick_at(scheduler: _FakeScheduler, ticks: list[int], ticks_ms: int) -> None:
    ticks[0] = ticks_ms
    (tick,) = scheduler.callbacks
    tick()


def test_first_check_comes_a_full_period_after_construction(fake_ticks):
    recorder = _Recorder()
    fake_ticks[0] = 1_000
    scheduler = _scheduled_upkeep(_FakeWifi(connected=False), recorder)
    _tick_at(scheduler, fake_ticks, 1_000 + _PERIOD_MS - 1)
    assert recorder.calls == []
    _tick_at(scheduler, fake_ticks, 1_000 + _PERIOD_MS)
    assert recorder.calls == ["reconnect"]


def test_syncs_at_the_check_when_the_link_is_up(fake_ticks):
    recorder = _Recorder()
    scheduler = _scheduled_upkeep(_FakeWifi(connected=True), recorder)
    _tick_at(scheduler, fake_ticks, _PERIOD_MS)
    assert recorder.calls == ["reconnect", "sync"]


def test_syncs_right_after_a_dropped_link_reconnects(fake_ticks):
    wifi = _FakeWifi(connected=False)
    recorder = _Recorder()
    scheduler = _scheduled_upkeep(wifi, recorder)
    _tick_at(scheduler, fake_ticks, _PERIOD_MS)
    _tick_at(scheduler, fake_ticks, _PERIOD_MS + 500)
    assert recorder.calls == ["reconnect"]
    wifi.connected = True
    _tick_at(scheduler, fake_ticks, _PERIOD_MS + 1_000)
    assert recorder.calls == ["reconnect", "sync"]
    _tick_at(scheduler, fake_ticks, _PERIOD_MS + 1_500)
    assert recorder.calls == ["reconnect", "sync"]


def test_checks_once_per_period(fake_ticks):
    recorder = _Recorder()
    scheduler = _scheduled_upkeep(_FakeWifi(connected=True), recorder)
    for ticks_ms in (_PERIOD_MS, _PERIOD_MS + 500, 2 * _PERIOD_MS - 1):
        _tick_at(scheduler, fake_ticks, ticks_ms)
    assert recorder.calls == ["reconnect", "sync"]
    _tick_at(scheduler, fake_ticks, 2 * _PERIOD_MS)
    assert recorder.calls == ["reconnect", "sync"] * 2


def test_slow_sync_doesnt_shift_the_next_check(fake_ticks):
    recorder = _Recorder()
    sync_clock = recorder.sync_clock

    def slow_sync_clock() -> bool:
        fake_ticks[0] += 45_000
        return sync_clock()

    recorder.sync_clock = slow_sync_clock
    scheduler = _scheduled_upkeep(_FakeWifi(connected=True), recorder)
    _tick_at(scheduler, fake_ticks, _PERIOD_MS)
    _tick_at(scheduler, fake_ticks, 2 * _PERIOD_MS - 1)
    assert recorder.calls == ["reconnect", "sync"]
    _tick_at(scheduler, fake_ticks, 2 * _PERIOD_MS)
    assert recorder.calls == ["reconnect", "sync"] * 2


def test_late_sync_doesnt_shift_the_next_check(fake_ticks):
    wifi = _FakeWifi(connected=False)
    recorder = _Recorder()
    scheduler = _scheduled_upkeep(wifi, recorder)
    _tick_at(scheduler, fake_ticks, _PERIOD_MS)
    wifi.connected = True
    _tick_at(scheduler, fake_ticks, _PERIOD_MS + 3 * _HOUR_MS)
    _tick_at(scheduler, fake_ticks, 2 * _PERIOD_MS - 1)
    assert recorder.calls == ["reconnect", "sync"]
    _tick_at(scheduler, fake_ticks, 2 * _PERIOD_MS)
    assert recorder.calls == ["reconnect", "sync"] * 2


def test_failed_sync_waits_for_the_next_check(fake_ticks):
    recorder = _Recorder()
    recorder.sync_ok = False
    scheduler = _scheduled_upkeep(_FakeWifi(connected=True), recorder)
    _tick_at(scheduler, fake_ticks, _PERIOD_MS)
    _tick_at(scheduler, fake_ticks, _PERIOD_MS + 500)
    assert recorder.calls == ["reconnect", "sync"]


@pytest.mark.parametrize("start_ms", [0, _TICKS_PERIOD_MS - 3 * 24 * _HOUR_MS])
def test_pending_sync_waits_out_a_week_offline(wrapping_ticks, start_ms: int):
    wifi = _FakeWifi(connected=False)
    recorder = _Recorder()
    wrapping_ticks[0] = start_ms
    scheduler = _scheduled_upkeep(wifi, recorder)
    for hour in range(1, 7 * 24 + 1):
        _tick_at(scheduler, wrapping_ticks, start_ms + hour * _HOUR_MS)
    assert recorder.calls == ["reconnect"] * 14
    wifi.connected = True
    _tick_at(scheduler, wrapping_ticks, start_ms + 7 * 24 * _HOUR_MS + _HOUR_MS // 2)
    assert recorder.calls == ["reconnect"] * 14 + ["sync"]


def test_period_just_under_the_ticks_range_still_fires(wrapping_ticks):
    period_ms = _TICKS_PERIOD_MS // 2 - 1
    recorder = _Recorder()
    scheduler = _scheduled_upkeep(_FakeWifi(connected=True), recorder, period_ms=period_ms)
    for hour in range(1, period_ms // _HOUR_MS + 1):
        _tick_at(scheduler, wrapping_ticks, hour * _HOUR_MS)
    assert recorder.calls == []
    _tick_at(scheduler, wrapping_ticks, (period_ms // _HOUR_MS + 1) * _HOUR_MS)
    assert recorder.calls == ["reconnect", "sync"]


def test_reconnect_that_raises_is_logged_and_the_sync_still_follows_the_link(fake_ticks, capsys):
    wifi = _FakeWifi(connected=False)
    recorder = _Recorder()
    recorder.reconnect_error = OSError("no timer")
    scheduler = _scheduled_upkeep(wifi, recorder)
    _tick_at(scheduler, fake_ticks, _PERIOD_MS)
    assert "[upkeep] tick err:" in capsys.readouterr().out
    _tick_at(scheduler, fake_ticks, _PERIOD_MS + 500)
    assert recorder.calls == ["reconnect"]
    wifi.connected = True
    _tick_at(scheduler, fake_ticks, _PERIOD_MS + 1_000)
    assert recorder.calls == ["reconnect", "sync"]


def test_sync_that_raises_is_logged_and_waits_for_the_next_check(fake_ticks, capsys):
    recorder = _Recorder()
    recorder.sync_error = MemoryError()
    scheduler = _scheduled_upkeep(_FakeWifi(connected=True), recorder)
    _tick_at(scheduler, fake_ticks, _PERIOD_MS)
    assert "[upkeep] tick err:" in capsys.readouterr().out
    _tick_at(scheduler, fake_ticks, _PERIOD_MS + 500)
    assert recorder.calls == ["reconnect", "sync"]
    _tick_at(scheduler, fake_ticks, 2 * _PERIOD_MS)
    assert recorder.calls == ["reconnect", "sync"] * 2
