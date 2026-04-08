from __future__ import annotations

import pytest

import services.network_service as ns_mod
from services.network_service import NetworkService
from utilities import ntp, wifi


def _mk_service(**kwargs):
    status_calls: list[tuple[str, ...]] = []

    def status_fn(text: str, subtext: str = "") -> None:
        status_calls.append((text, subtext))

    svc = NetworkService(
        ssid="TestSSID",
        password="TestPass",
        time_zone_offset=1,
        status_fn=status_fn,
        **kwargs,
    )

    return svc, status_calls


# --- connect_and_sync_initial ---

def test_connect_and_sync_initial_success(monkeypatch):
    monkeypatch.setattr(wifi, "connect", lambda ssid, pw: wifi.CONNECTED)
    monkeypatch.setattr(ntp, "sync_time", lambda attempts=1: ntp.SYNCED)

    svc, status_calls = _mk_service()
    svc.connect_and_sync_initial()

    assert status_calls == [("wifi", ""), ("sync time", "")]


def test_connect_and_sync_initial_wifi_fail(monkeypatch):
    monkeypatch.setattr(wifi, "connect", lambda ssid, pw: wifi.FAILED)

    svc, status_calls = _mk_service()

    with pytest.raises(RuntimeError, match="Could not connect to WiFi"):
        svc.connect_and_sync_initial()

    assert ("wifi fail", "") in status_calls


def test_connect_and_sync_initial_ntp_fail(monkeypatch):
    monkeypatch.setattr(wifi, "connect", lambda ssid, pw: wifi.CONNECTED)
    monkeypatch.setattr(ntp, "sync_time", lambda attempts=1: ntp.FAILED)

    svc, status_calls = _mk_service()

    with pytest.raises(RuntimeError, match="Could not sync time"):
        svc.connect_and_sync_initial()

    assert ("ntp fail", "") in status_calls


# --- _tick() phase-based orchestration ---

def test_tick_does_nothing_before_interval(monkeypatch):
    monkeypatch.setattr(ns_mod.time, "ticks_ms", lambda: 0)
    monkeypatch.setattr(ns_mod.time, "ticks_diff", lambda a, b: a - b)

    start_connect_calls = [0]
    monkeypatch.setattr(wifi, "start_connect", lambda ssid, pw: _inc(start_connect_calls))

    svc, _ = _mk_service(sync_interval_ms=1000)
    svc._tick()

    assert start_connect_calls[0] == 0


def test_tick_starts_wifi_when_not_connected(monkeypatch):
    ticks = [200]
    monkeypatch.setattr(ns_mod.time, "ticks_ms", lambda: ticks[0])
    monkeypatch.setattr(ns_mod.time, "ticks_diff", lambda a, b: a - b)

    start_connect_calls = [0]
    monkeypatch.setattr(wifi, "is_connected", lambda: False)
    monkeypatch.setattr(wifi, "start_connect", lambda ssid, pw: _inc(start_connect_calls))
    monkeypatch.setattr(wifi, "state", wifi.CONNECTING)

    svc, _ = _mk_service(sync_interval_ms=100)
    svc._tick()

    assert start_connect_calls[0] == 1
    assert svc._phase == 1  # _WIFI


def test_tick_skips_wifi_when_connected(monkeypatch):
    ticks = [200]
    monkeypatch.setattr(ns_mod.time, "ticks_ms", lambda: ticks[0])
    monkeypatch.setattr(ns_mod.time, "ticks_diff", lambda a, b: a - b)

    start_connect_calls = [0]
    monkeypatch.setattr(wifi, "is_connected", lambda: True)
    monkeypatch.setattr(wifi, "start_connect", lambda ssid, pw: _inc(start_connect_calls))
    monkeypatch.setattr(ntp, "sync_time", lambda attempts=1: ntp.SYNCED)

    svc, _ = _mk_service(sync_interval_ms=100)
    svc._tick()

    assert start_connect_calls[0] == 0  # WiFi not reconnected
    assert svc._phase == 0  # _IDLE (NTP completed in same tick)


def test_tick_wifi_connecting_stays_in_wifi_phase(monkeypatch):
    ticks = [200]
    monkeypatch.setattr(ns_mod.time, "ticks_ms", lambda: ticks[0])
    monkeypatch.setattr(ns_mod.time, "ticks_diff", lambda a, b: a - b)

    monkeypatch.setattr(wifi, "is_connected", lambda: False)
    monkeypatch.setattr(wifi, "start_connect", lambda ssid, pw: None)
    monkeypatch.setattr(wifi, "state", wifi.CONNECTING)

    ntp_calls = [0]
    monkeypatch.setattr(ntp, "sync_time", lambda attempts=1: _inc_and_return(ntp_calls, ntp.SYNCED))

    svc, _ = _mk_service(sync_interval_ms=100)
    svc._tick()  # enters _WIFI, state CONNECTING
    svc._tick()  # still CONNECTING

    assert ntp_calls[0] == 0
    assert svc._phase == 1  # _WIFI


def test_tick_wifi_connected_transitions_to_ntp(monkeypatch):
    ticks = [200]
    monkeypatch.setattr(ns_mod.time, "ticks_ms", lambda: ticks[0])
    monkeypatch.setattr(ns_mod.time, "ticks_diff", lambda a, b: a - b)

    monkeypatch.setattr(wifi, "is_connected", lambda: False)
    monkeypatch.setattr(wifi, "start_connect", lambda ssid, pw: None)
    monkeypatch.setattr(wifi, "state", wifi.CONNECTING)

    svc, _ = _mk_service(sync_interval_ms=100)
    svc._tick()  # enters _WIFI, CONNECTING
    assert svc._phase == 1  # _WIFI

    monkeypatch.setattr(wifi, "state", wifi.CONNECTED)
    monkeypatch.setattr(ntp, "sync_time", lambda attempts=1: ntp.SYNCED)
    svc._tick()  # CONNECTED → _NTP → sync → _IDLE

    assert svc._phase == 0  # _IDLE


def test_tick_wifi_failed_resets_to_idle(monkeypatch):
    ticks = [200]
    monkeypatch.setattr(ns_mod.time, "ticks_ms", lambda: ticks[0])
    monkeypatch.setattr(ns_mod.time, "ticks_diff", lambda a, b: a - b)

    monkeypatch.setattr(wifi, "is_connected", lambda: False)
    monkeypatch.setattr(wifi, "start_connect", lambda ssid, pw: None)
    monkeypatch.setattr(wifi, "state", wifi.CONNECTING)

    svc, _ = _mk_service(sync_interval_ms=100)
    svc._tick()  # enters _WIFI
    assert svc._phase == 1  # _WIFI

    monkeypatch.setattr(wifi, "state", wifi.FAILED)
    svc._tick()

    assert svc._phase == 0  # _IDLE


def test_tick_ntp_sync_resets_to_idle(monkeypatch):
    ticks = [200]
    monkeypatch.setattr(ns_mod.time, "ticks_ms", lambda: ticks[0])
    monkeypatch.setattr(ns_mod.time, "ticks_diff", lambda a, b: a - b)

    monkeypatch.setattr(wifi, "is_connected", lambda: True)
    monkeypatch.setattr(ntp, "sync_time", lambda attempts=1: ntp.SYNCED)

    svc, _ = _mk_service(sync_interval_ms=100)
    svc._tick()

    assert svc._phase == 0  # _IDLE
    assert svc._last_sync_ticks == 200


def test_tick_updates_last_sync_on_wifi_fail(monkeypatch):
    ticks = [200]
    monkeypatch.setattr(ns_mod.time, "ticks_ms", lambda: ticks[0])
    monkeypatch.setattr(ns_mod.time, "ticks_diff", lambda a, b: a - b)

    monkeypatch.setattr(wifi, "is_connected", lambda: False)
    monkeypatch.setattr(wifi, "start_connect", lambda ssid, pw: None)
    monkeypatch.setattr(wifi, "state", wifi.FAILED)

    svc, _ = _mk_service(sync_interval_ms=100)
    svc._tick()

    assert svc._last_sync_ticks == 200


def test_tick_exception_safety(monkeypatch):
    ticks = [200]
    monkeypatch.setattr(ns_mod.time, "ticks_ms", lambda: ticks[0])
    monkeypatch.setattr(ns_mod.time, "ticks_diff", lambda a, b: a - b)

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(wifi, "is_connected", boom)

    svc, _ = _mk_service(sync_interval_ms=100)
    # Should not raise — _tick wraps in try/except
    svc._tick()


def test_tick_full_cycle(monkeypatch):
    """Simulate IDLE → WIFI → NTP → IDLE across multiple ticks."""
    ticks = [0]
    monkeypatch.setattr(ns_mod.time, "ticks_ms", lambda: ticks[0])
    monkeypatch.setattr(ns_mod.time, "ticks_diff", lambda a, b: a - b)

    wifi_states = iter([wifi.CONNECTING, wifi.CONNECTING, wifi.CONNECTED])
    monkeypatch.setattr(wifi, "is_connected", lambda: False)
    monkeypatch.setattr(wifi, "start_connect", lambda ssid, pw: None)

    # Use a class to make wifi.state dynamic
    class WiFiState:
        current = wifi.CONNECTING

    monkeypatch.setattr(
        type(wifi), "state",
        property(lambda self: WiFiState.current),
    ) if False else None  # Can't property-patch a module; use getattr approach

    # Patch wifi module's state attribute dynamically
    monkeypatch.setattr(wifi, "state", wifi.CONNECTING)

    ntp_calls = [0]
    monkeypatch.setattr(ntp, "sync_time", lambda attempts=1: _inc_and_return(ntp_calls, ntp.SYNCED))

    svc, _ = _mk_service(sync_interval_ms=100)

    ticks[0] = 200
    svc._tick()  # IDLE → WIFI, wifi CONNECTING
    assert svc._phase == 1  # _WIFI

    svc._tick()  # wifi CONNECTING
    assert svc._phase == 1  # _WIFI

    monkeypatch.setattr(wifi, "state", wifi.CONNECTED)
    svc._tick()  # wifi CONNECTED → NTP → sync → IDLE
    assert svc._phase == 0  # _IDLE
    assert svc._last_sync_ticks == 200
    assert ntp_calls[0] == 1


# --- Helpers ---

def _inc(counter: list[int]) -> None:
    counter[0] += 1


def _inc_and_return(counter: list[int], value):
    counter[0] += 1
    return value
