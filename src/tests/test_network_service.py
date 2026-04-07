from __future__ import annotations

import pytest

import services.network_service as ns_mod
from services.network_service import NetworkService
from utilities import ntp, wifi


def _mk_service(
    wifi_result: bool = True,
    ntp_result: bool = True,
    gmtime_tuple=(2026, 3, 15, 14, 30, 0, 5, 74, 0),
    monkeypatch=None,
    **kwargs,
):
    status_calls: list[tuple[str, ...]] = []

    def status_fn(text: str, subtext: str = "") -> None:
        status_calls.append((text, subtext))

    if monkeypatch:
        monkeypatch.setattr(wifi, "try_connect", lambda ssid, pw: wifi_result)
        monkeypatch.setattr(ntp, "try_sync_time", lambda: ntp_result)
        monkeypatch.setattr(ns_mod.time, "gmtime", lambda: gmtime_tuple)

    svc = NetworkService(
        ssid="TestSSID",
        password="TestPass",
        time_zone_offset=1,
        status_fn=status_fn,
        **kwargs,
    )

    return svc, status_calls


def test_connect_wifi_success(monkeypatch) -> None:
    svc, status_calls = _mk_service(wifi_result=True, monkeypatch=monkeypatch)
    result = svc.connect_wifi()

    assert result is True
    assert status_calls == [("wifi", "")]


def test_connect_wifi_fail_no_throw(monkeypatch) -> None:
    svc, status_calls = _mk_service(wifi_result=False, monkeypatch=monkeypatch)
    result = svc.connect_wifi(throw_on_fail=False)

    assert result is False
    assert len(status_calls) == 2
    assert status_calls[0] == ("wifi", "")
    # Second call is _show_time_subtext with time info
    assert status_calls[1][0] == "wifi"
    assert "at" in status_calls[1][1]


def test_connect_wifi_fail_throw(monkeypatch) -> None:
    svc, status_calls = _mk_service(wifi_result=False, monkeypatch=monkeypatch)

    with pytest.raises(RuntimeError, match="Could not connect to WiFi"):
        svc.connect_wifi(throw_on_fail=True)

    assert ("wifi fail", "") in status_calls


def test_sync_time_success(monkeypatch) -> None:
    svc, status_calls = _mk_service(ntp_result=True, monkeypatch=monkeypatch)
    result = svc.sync_time()

    assert result is True
    assert status_calls == [("sync time", "")]


def test_sync_time_fail_no_throw(monkeypatch) -> None:
    svc, status_calls = _mk_service(ntp_result=False, monkeypatch=monkeypatch)
    result = svc.sync_time(throw_on_fail=False)

    assert result is False
    assert len(status_calls) == 2
    assert status_calls[0] == ("sync time", "")
    assert status_calls[1][0] == "sync time"
    assert "at" in status_calls[1][1]


def test_sync_time_fail_throw(monkeypatch) -> None:
    svc, status_calls = _mk_service(ntp_result=False, monkeypatch=monkeypatch)

    with pytest.raises(RuntimeError, match="Could not sync time"):
        svc.sync_time(throw_on_fail=True)

    assert ("ntp fail", "") in status_calls


def test_connect_and_sync_initial_calls_both(monkeypatch) -> None:
    svc, status_calls = _mk_service(
        wifi_result=True, ntp_result=True, monkeypatch=monkeypatch,
    )
    svc.connect_and_sync_initial()

    assert status_calls == [("wifi", ""), ("sync time", "")]


def test_tick_syncs_after_interval(monkeypatch) -> None:
    ticks_value = [0]
    monkeypatch.setattr(ns_mod.time, "ticks_ms", lambda: ticks_value[0])
    monkeypatch.setattr(ns_mod.time, "ticks_diff", lambda a, b: a - b)

    svc, status_calls = _mk_service(
        wifi_result=True, ntp_result=True, monkeypatch=monkeypatch,
        sync_interval_ms=100,
    )

    # Advance past the interval.
    ticks_value[0] = 200
    svc._tick()

    assert ("wifi", "") in status_calls
    assert ("sync time", "") in status_calls


def test_tick_skips_ntp_on_wifi_fail(monkeypatch) -> None:
    ticks_value = [0]
    monkeypatch.setattr(ns_mod.time, "ticks_ms", lambda: ticks_value[0])
    monkeypatch.setattr(ns_mod.time, "ticks_diff", lambda a, b: a - b)

    svc, status_calls = _mk_service(
        wifi_result=False, ntp_result=True, monkeypatch=monkeypatch,
        sync_interval_ms=100,
    )

    ticks_value[0] = 200
    svc._tick()

    assert status_calls[0] == ("wifi", "")
    sync_calls = [c for c in status_calls if c[0] == "sync time"]
    assert sync_calls == []


def test_tick_does_nothing_before_interval(monkeypatch) -> None:
    monkeypatch.setattr(ns_mod.time, "ticks_ms", lambda: 0)
    monkeypatch.setattr(ns_mod.time, "ticks_diff", lambda a, b: a - b)

    svc, status_calls = _mk_service(
        wifi_result=True, ntp_result=True, monkeypatch=monkeypatch,
        sync_interval_ms=1000,
    )

    svc._tick()
    assert status_calls == []


def test_show_time_subtext_formats_time(monkeypatch) -> None:
    # gmtime returns hour=14, minute=30; with tz_offset=1 -> 15:30
    svc, status_calls = _mk_service(
        gmtime_tuple=(2026, 3, 15, 14, 30, 0, 5, 74, 0),
        monkeypatch=monkeypatch,
    )
    svc._show_time_subtext("test")

    assert status_calls == [("test", "at 15:30")]
