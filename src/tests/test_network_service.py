from __future__ import annotations

import pytest

from services import wifi_client
from services.network_service import NetworkService

_SSID = "TestSSID"
_PASSWORD = "TestPass"


class FakeWifiClient:
    """Minimal stand-in for WifiClient — exposes the subset used by NetworkService."""

    def __init__(self, *, connect_result=None, is_connected=False):
        self._connect_result = (
            wifi_client.CONNECTED if connect_result is None else connect_result
        )
        self.connected = is_connected
        self.connect_calls: list[tuple[str, str]] = []
        self.start_connect_calls: list[tuple[str, str]] = []

    def connect(self, ssid, pw):
        self.connect_calls.append((ssid, pw))
        return self._connect_result

    def start_connect(self, ssid, pw):
        self.start_connect_calls.append((ssid, pw))

    def is_connected(self):
        return self.connected


def _mk_service(wifi=None):
    progress_calls: list[tuple[str, ...]] = []

    def on_progress(text: str, subtext: str = "") -> None:
        progress_calls.append((text, subtext))

    svc = NetworkService(
        ssid=_SSID,
        password=_PASSWORD,
        wifi=wifi if wifi is not None else FakeWifiClient(),
    )
    return svc, on_progress, progress_calls


# --- connect_initial ---

def test_connect_initial_success():
    wifi = FakeWifiClient(connect_result=wifi_client.CONNECTED)
    svc, on_progress, progress_calls = _mk_service(wifi=wifi)
    svc.connect_initial(on_progress=on_progress)

    assert wifi.connect_calls == [(_SSID, _PASSWORD)]
    assert progress_calls == [("wifi", "")]


def test_connect_initial_wifi_fail():
    svc, on_progress, progress_calls = _mk_service(
        wifi=FakeWifiClient(connect_result=wifi_client.FAILED),
    )

    with pytest.raises(RuntimeError, match="Could not connect to WiFi"):
        svc.connect_initial(on_progress=on_progress)

    assert progress_calls == [("wifi", ""), ("wifi fail", "")]


def test_connect_initial_without_on_progress():
    svc, _on_progress, _progress_calls = _mk_service(
        wifi=FakeWifiClient(connect_result=wifi_client.CONNECTED),
    )
    svc.connect_initial()


# --- start_reconnect ---

def test_start_reconnect_connects_a_dropped_link():
    wifi = FakeWifiClient(is_connected=False)
    svc, _, _ = _mk_service(wifi=wifi)
    svc.start_reconnect()

    assert wifi.start_connect_calls == [(_SSID, _PASSWORD)]


def test_start_reconnect_leaves_a_live_link_alone():
    wifi = FakeWifiClient(is_connected=True)
    svc, _, _ = _mk_service(wifi=wifi)
    svc.start_reconnect()

    assert wifi.start_connect_calls == []
