from __future__ import annotations

import time

import pytest

from network import STAT_GOT_IP, STAT_WRONG_PASSWORD, STAT_CONNECTING, STAT_NO_AP_FOUND, STAT_CONNECT_FAIL
from services import wifi_client
from services.wifi_client import WifiClient

from conftest import FakeTimer


class FakeWLAN:
    """Configurable WLAN stub for wifi state machine tests."""

    def __init__(self):
        self._active = False
        self._connected = False
        self._ssid = ""
        self._status_value = 0
        self._connect_calls: list[tuple[str, str]] = []
        self._disconnect_calls = 0

    def active(self, state=None):
        if state is not None:
            self._active = state
        return self._active

    def isconnected(self):
        return self._connected

    def config(self, key):
        if key == "ssid":
            return self._ssid
        return ""

    def status(self):
        return self._status_value

    def connect(self, ssid, password):
        self._connect_calls.append((ssid, password))

    def disconnect(self):
        self._disconnect_calls += 1


@pytest.fixture()
def fake_wlan(monkeypatch):
    """Provide a FakeWLAN and patch the network.WLAN constructor."""
    wlan = FakeWLAN()
    monkeypatch.setattr("services.wifi_client.WLAN", lambda _mode: wlan)
    return wlan


@pytest.fixture()
def fake_timer(monkeypatch):
    """Single FakeTimer instance patched in as services.wifi_client.Timer."""
    timer = FakeTimer()

    def timer_factory(_id=-1):
        return timer

    timer_factory.PERIODIC = FakeTimer.PERIODIC
    timer_factory.ONE_SHOT = FakeTimer.ONE_SHOT
    monkeypatch.setattr("services.wifi_client.Timer", timer_factory)
    return timer


@pytest.fixture()
def wifi():
    """Fresh WifiClient per test."""
    return WifiClient()


@pytest.fixture()
def started_wifi(wifi, fake_wlan, fake_timer, fake_ticks):
    """Wifi already in CONNECTING state with standard (SSID, password) used."""
    wifi.start_connect("MySSID", "pass")
    return wifi, fake_wlan, fake_timer, fake_ticks


# --- start_connect() ---

def test_start_connect_transitions_to_connecting(started_wifi):
    wifi, fake_wlan, *_ = started_wifi
    assert wifi.state == wifi_client.CONNECTING
    assert fake_wlan._connect_calls == [("MySSID", "pass")]


def test_start_connect_starts_timer(started_wifi):
    _, _, fake_timer, _ = started_wifi
    assert fake_timer.init_called


def test_start_connect_idempotent_when_connecting(started_wifi):
    wifi, fake_wlan, *_ = started_wifi
    connect_count = len(fake_wlan._connect_calls)
    wifi.start_connect("MySSID", "pass")
    assert len(fake_wlan._connect_calls) == connect_count


def test_start_connect_resets_from_connected(started_wifi):
    wifi, fake_wlan, _, _ = started_wifi
    fake_wlan._status_value = STAT_GOT_IP
    wifi._tick(wifi._generation)  # → CONNECTED
    assert wifi.state == wifi_client.CONNECTED

    wifi.start_connect("MySSID", "pass")
    assert wifi.state == wifi_client.CONNECTING


def test_start_connect_resets_from_failed(wifi, fake_wlan, fake_timer, fake_ticks):
    wifi.start_connect("", "pass")  # FAILED (empty ssid)
    assert wifi.state == wifi_client.FAILED

    wifi.start_connect("MySSID", "pass")
    assert wifi.state == wifi_client.CONNECTING


def test_start_connect_empty_ssid_fails(wifi, fake_wlan, fake_timer, fake_ticks):
    wifi.start_connect("", "pass")
    assert wifi.state == wifi_client.FAILED
    assert not fake_timer.init_called


# --- _tick() transitions ---

def test_tick_connecting_to_connected(started_wifi):
    wifi, fake_wlan, *_ = started_wifi
    fake_wlan._status_value = STAT_GOT_IP
    wifi._tick(wifi._generation)
    assert wifi.state == wifi_client.CONNECTED


def test_tick_connecting_wrong_password(started_wifi):
    wifi, fake_wlan, *_ = started_wifi
    fake_wlan._status_value = STAT_WRONG_PASSWORD
    wifi._tick(wifi._generation)
    assert wifi.state == wifi_client.FAILED
    assert fake_wlan._disconnect_calls >= 1


def test_tick_connecting_stays_connecting(started_wifi):
    wifi, fake_wlan, *_ = started_wifi
    fake_wlan._status_value = STAT_CONNECTING
    wifi._tick(wifi._generation)
    assert wifi.state == wifi_client.CONNECTING


# --- _tick() retry on transient failure ---

def test_tick_retry_on_no_ap_found(started_wifi):
    wifi, fake_wlan, *_ = started_wifi
    connect_count = len(fake_wlan._connect_calls)

    fake_wlan._status_value = STAT_NO_AP_FOUND
    wifi._tick(wifi._generation)
    assert len(fake_wlan._connect_calls) == connect_count + 1


def test_tick_retry_on_connect_fail(started_wifi):
    wifi, fake_wlan, *_ = started_wifi
    connect_count = len(fake_wlan._connect_calls)

    fake_wlan._status_value = STAT_CONNECT_FAIL
    wifi._tick(wifi._generation)
    assert len(fake_wlan._connect_calls) == connect_count + 1


def test_tick_retry_on_attempt_ttl_exceeded(started_wifi):
    wifi, fake_wlan, _, ticks = started_wifi
    connect_count = len(fake_wlan._connect_calls)

    fake_wlan._status_value = STAT_CONNECTING
    ticks[0] = 15_000  # exceeds _ATTEMPT_TTL_MS (10s)
    wifi._tick(wifi._generation)
    assert fake_wlan._disconnect_calls >= 1
    assert len(fake_wlan._connect_calls) == connect_count + 1


def test_tick_retry_on_unknown_status(started_wifi):
    """Unknown WLAN status (e.g. STAT_IDLE=0) triggers retry after TTL."""
    wifi, fake_wlan, _, ticks = started_wifi
    connect_count = len(fake_wlan._connect_calls)

    fake_wlan._status_value = 0  # STAT_IDLE / CYW43_LINK_DOWN
    wifi._tick(wifi._generation)
    assert len(fake_wlan._connect_calls) == connect_count

    ticks[0] = 15_000
    wifi._tick(wifi._generation)
    assert fake_wlan._disconnect_calls >= 1
    assert len(fake_wlan._connect_calls) == connect_count + 1


# --- Cooldown pacing ---

def test_tick_cooldown_is_noop(started_wifi):
    wifi, fake_wlan, _, ticks = started_wifi

    fake_wlan._status_value = STAT_NO_AP_FOUND
    wifi._tick(wifi._generation)
    connect_count = len(fake_wlan._connect_calls)

    ticks[0] = 500
    wifi._tick(wifi._generation)
    assert wifi.state == wifi_client.CONNECTING
    assert len(fake_wlan._connect_calls) == connect_count


def test_tick_after_cooldown_elapses(started_wifi):
    wifi, fake_wlan, _, ticks = started_wifi

    fake_wlan._status_value = STAT_NO_AP_FOUND
    wifi._tick(wifi._generation)

    ticks[0] = 2000
    fake_wlan._status_value = STAT_GOT_IP
    wifi._tick(wifi._generation)
    assert wifi.state == wifi_client.CONNECTED


# --- Timer stop on terminal state ---

def test_tick_stops_timer_on_connected(started_wifi):
    wifi, fake_wlan, fake_timer, _ = started_wifi
    fake_wlan._status_value = STAT_GOT_IP
    wifi._tick(wifi._generation)
    assert fake_timer.deinit_called


def test_tick_stops_timer_on_failed(started_wifi):
    wifi, fake_wlan, fake_timer, _ = started_wifi
    fake_wlan._status_value = STAT_WRONG_PASSWORD
    wifi._tick(wifi._generation)
    assert fake_timer.deinit_called


# --- Generation counter ---

def test_tick_stale_generation_ignored(started_wifi):
    wifi, *_ = started_wifi
    stale_gen = wifi._generation

    wifi.reset()
    assert wifi.state == wifi_client.IDLE

    wifi._tick(stale_gen)
    assert wifi.state == wifi_client.IDLE


# --- connect() blocking ---

def test_connect_success(wifi, fake_wlan, fake_ticks, monkeypatch):
    monkeypatch.setattr(time, "sleep_ms", lambda _: None)

    call_count = [0]
    original_tick = wifi._tick

    def patched_tick(gen):
        original_tick(gen)
        call_count[0] += 1
        if call_count[0] >= 2:
            fake_wlan._status_value = STAT_GOT_IP

    monkeypatch.setattr(wifi, "_tick", patched_tick)
    result = wifi.connect("MySSID", "pass")
    assert result == wifi_client.CONNECTED


def test_connect_failure(wifi, fake_wlan, fake_ticks, monkeypatch):
    monkeypatch.setattr(time, "sleep_ms", lambda _: None)

    fake_wlan._status_value = STAT_WRONG_PASSWORD
    result = wifi.connect("MySSID", "pass")
    assert result == wifi_client.FAILED


def test_connect_timeout(wifi, fake_wlan, fake_ticks, monkeypatch):
    def fake_sleep_ms(_):
        fake_ticks[0] += 500_000

    monkeypatch.setattr(time, "sleep_ms", fake_sleep_ms)

    fake_wlan._status_value = STAT_CONNECTING
    result = wifi.connect("MySSID", "pass", timeout_ms=10_000)
    assert result == wifi_client.FAILED
    assert wifi.state == wifi_client.IDLE


def test_connect_empty_ssid(wifi):
    result = wifi.connect("", "pass")
    assert result == wifi_client.FAILED


# --- reset() ---

def test_reset_stops_timer(started_wifi):
    wifi, _, fake_timer, _ = started_wifi
    wifi.reset()
    assert fake_timer.deinit_called


def test_reset_from_connecting(started_wifi):
    wifi, *_ = started_wifi
    assert wifi.state == wifi_client.CONNECTING
    wifi.reset()
    assert wifi.state == wifi_client.IDLE


def test_reset_from_connected(started_wifi):
    wifi, fake_wlan, *_ = started_wifi
    fake_wlan._status_value = STAT_GOT_IP
    wifi._tick(wifi._generation)
    wifi.reset()
    assert wifi.state == wifi_client.IDLE


# --- is_connected() ---

def test_is_connected_true(started_wifi):
    wifi, fake_wlan, *_ = started_wifi
    fake_wlan._status_value = STAT_GOT_IP
    fake_wlan._connected = True
    wifi._tick(wifi._generation)
    assert wifi.is_connected() is True


def test_is_connected_false(wifi):
    assert wifi.is_connected() is False


def test_is_connected_checks_hardware(started_wifi):
    """is_connected() checks actual WLAN, not just state variable."""
    wifi, fake_wlan, *_ = started_wifi
    fake_wlan._status_value = STAT_GOT_IP
    fake_wlan._connected = False
    wifi._tick(wifi._generation)
    assert wifi.state == wifi_client.CONNECTED
    assert wifi.is_connected() is False
