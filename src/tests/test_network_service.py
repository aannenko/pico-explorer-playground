from __future__ import annotations

import pytest

from services import wifi_client
from services.network_service import NetworkService
from utilities import ntp


class FakeWifiClient:
    """Minimal stand-in for WifiClient — exposes the subset used by NetworkService."""

    def __init__(self, *, connect_result=None, is_connected=False, state=None):
        self._connect_result = (
            wifi_client.CONNECTED if connect_result is None else connect_result
        )
        self._is_connected = is_connected
        self.state = wifi_client.IDLE if state is None else state
        self.connect_calls: list[tuple[str, str]] = []
        self.start_connect_calls: list[tuple[str, str]] = []

    def connect(self, ssid, pw):
        self.connect_calls.append((ssid, pw))
        return self._connect_result

    def start_connect(self, ssid, pw):
        self.start_connect_calls.append((ssid, pw))

    def is_connected(self):
        return self._is_connected


def _mk_service(wifi=None, **kwargs):
    status_calls: list[tuple[str, ...]] = []

    def status_fn(text: str, subtext: str = "") -> None:
        status_calls.append((text, subtext))

    svc = NetworkService(
        ssid="TestSSID",
        password="TestPass",
        wifi=wifi if wifi is not None else FakeWifiClient(),
        **kwargs,
    )
    return svc, status_fn, status_calls


# --- connect_and_sync_initial ---

def test_connect_and_sync_initial_success(monkeypatch):
    monkeypatch.setattr(ntp, "sync_time", lambda attempts=1: ntp.SYNCED)

    svc, status_fn, status_calls = _mk_service(
        wifi=FakeWifiClient(connect_result=wifi_client.CONNECTED),
    )
    svc.connect_and_sync_initial(status_fn=status_fn)

    assert status_calls == [("wifi", ""), ("sync time", "")]


def test_connect_and_sync_initial_wifi_fail(monkeypatch):
    svc, status_fn, status_calls = _mk_service(
        wifi=FakeWifiClient(connect_result=wifi_client.FAILED),
    )

    with pytest.raises(RuntimeError, match="Could not connect to WiFi"):
        svc.connect_and_sync_initial(status_fn=status_fn)

    assert ("wifi fail", "") in status_calls


def test_connect_and_sync_initial_ntp_fail(monkeypatch):
    monkeypatch.setattr(ntp, "sync_time", lambda attempts=1: ntp.FAILED)

    svc, status_fn, status_calls = _mk_service(
        wifi=FakeWifiClient(connect_result=wifi_client.CONNECTED),
    )

    with pytest.raises(RuntimeError, match="Could not sync time"):
        svc.connect_and_sync_initial(status_fn=status_fn)

    assert ("ntp fail", "") in status_calls


def test_connect_and_sync_initial_no_status_fn(monkeypatch):
    monkeypatch.setattr(ntp, "sync_time", lambda attempts=1: ntp.SYNCED)

    svc, _status_fn, _status_calls = _mk_service(
        wifi=FakeWifiClient(connect_result=wifi_client.CONNECTED),
    )
    svc.connect_and_sync_initial()  # must not raise


# --- _tick() phase-based orchestration ---

def test_tick_does_nothing_before_interval(fake_ticks):
    wifi = FakeWifiClient()
    svc, _, _ = _mk_service(wifi=wifi, sync_interval_ms=1000)
    svc._tick()

    assert wifi.start_connect_calls == []


def test_tick_starts_wifi_when_not_connected(fake_ticks):
    fake_ticks[0] = 200
    wifi = FakeWifiClient(is_connected=False, state=wifi_client.CONNECTING)
    svc, _, _ = _mk_service(wifi=wifi, sync_interval_ms=100)
    svc._tick()

    assert len(wifi.start_connect_calls) == 1
    assert svc._phase == 1  # _WIFI


def test_tick_skips_wifi_when_connected(fake_ticks, monkeypatch):
    fake_ticks[0] = 200
    monkeypatch.setattr(ntp, "sync_time", lambda attempts=1: ntp.SYNCED)

    wifi = FakeWifiClient(is_connected=True)
    svc, _, _ = _mk_service(wifi=wifi, sync_interval_ms=100)
    svc._tick()

    assert wifi.start_connect_calls == []
    assert svc._phase == 0  # _IDLE (NTP completed in same tick)


def test_tick_wifi_connecting_stays_in_wifi_phase(fake_ticks, monkeypatch):
    fake_ticks[0] = 200
    wifi = FakeWifiClient(is_connected=False, state=wifi_client.CONNECTING)
    ntp_calls = [0]
    monkeypatch.setattr(ntp, "sync_time", lambda attempts=1: _inc_and_return(ntp_calls, ntp.SYNCED))

    svc, _, _ = _mk_service(wifi=wifi, sync_interval_ms=100)
    svc._tick()
    svc._tick()

    assert ntp_calls[0] == 0
    assert svc._phase == 1  # _WIFI


def test_tick_wifi_connected_transitions_to_ntp(fake_ticks, monkeypatch):
    fake_ticks[0] = 200
    wifi = FakeWifiClient(is_connected=False, state=wifi_client.CONNECTING)
    svc, _, _ = _mk_service(wifi=wifi, sync_interval_ms=100)
    svc._tick()
    assert svc._phase == 1  # _WIFI

    wifi.state = wifi_client.CONNECTED
    monkeypatch.setattr(ntp, "sync_time", lambda attempts=1: ntp.SYNCED)
    svc._tick()

    assert svc._phase == 0  # _IDLE


def test_tick_wifi_failed_resets_to_idle(fake_ticks):
    fake_ticks[0] = 200
    wifi = FakeWifiClient(is_connected=False, state=wifi_client.CONNECTING)
    svc, _, _ = _mk_service(wifi=wifi, sync_interval_ms=100)
    svc._tick()
    assert svc._phase == 1  # _WIFI

    wifi.state = wifi_client.FAILED
    svc._tick()

    assert svc._phase == 0  # _IDLE


def test_tick_ntp_sync_resets_to_idle(fake_ticks, monkeypatch):
    fake_ticks[0] = 200
    monkeypatch.setattr(ntp, "sync_time", lambda attempts=1: ntp.SYNCED)

    wifi = FakeWifiClient(is_connected=True)
    svc, _, _ = _mk_service(wifi=wifi, sync_interval_ms=100)
    svc._tick()

    assert svc._phase == 0  # _IDLE
    assert svc._last_sync_ticks == 200


def test_tick_updates_last_sync_on_wifi_fail(fake_ticks):
    fake_ticks[0] = 200
    wifi = FakeWifiClient(is_connected=False, state=wifi_client.FAILED)
    svc, _, _ = _mk_service(wifi=wifi, sync_interval_ms=100)
    svc._tick()

    assert svc._last_sync_ticks == 200


def test_tick_exception_safety(fake_ticks, capsys):
    fake_ticks[0] = 200

    class BoomWifi(FakeWifiClient):
        def is_connected(self):
            raise RuntimeError("boom")

    svc, _, _ = _mk_service(wifi=BoomWifi(), sync_interval_ms=100)
    svc._tick()  # must not raise — _tick wraps in try/except

    captured = capsys.readouterr()
    assert "[net] tick err:" in captured.out
    assert "boom" in captured.out


def test_tick_full_cycle(fake_ticks, monkeypatch):
    """Simulate IDLE → WIFI → NTP → IDLE across multiple ticks."""
    wifi = FakeWifiClient(is_connected=False, state=wifi_client.CONNECTING)

    ntp_calls = [0]
    monkeypatch.setattr(ntp, "sync_time", lambda attempts=1: _inc_and_return(ntp_calls, ntp.SYNCED))

    svc, _, _ = _mk_service(wifi=wifi, sync_interval_ms=100)

    fake_ticks[0] = 200
    svc._tick()  # IDLE → WIFI, wifi CONNECTING
    assert svc._phase == 1  # _WIFI

    svc._tick()  # wifi still CONNECTING
    assert svc._phase == 1  # _WIFI

    wifi.state = wifi_client.CONNECTED
    svc._tick()  # CONNECTED → NTP → sync → IDLE
    assert svc._phase == 0  # _IDLE
    assert svc._last_sync_ticks == 200
    assert ntp_calls[0] == 1


# --- Helpers ---

def _inc_and_return(counter: list[int], value):
    counter[0] += 1
    return value
