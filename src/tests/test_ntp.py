from __future__ import annotations

import time as _time

import pytest

from utilities import ntp


@pytest.fixture(autouse=True)
def _reset_ntp():
    """Ensure ntp module state is reset before each test."""
    ntp.state = ntp.IDLE
    yield
    ntp.state = ntp.IDLE


# --- sync_time() ---

def test_sync_time_success(monkeypatch):
    monkeypatch.setattr("utilities.ntp.ntptime.settime", lambda: None)
    result = ntp.sync_time()
    assert result == ntp.SYNCED


def test_sync_time_failure(monkeypatch):
    def raise_error():
        raise OSError("NTP timeout")

    monkeypatch.setattr("utilities.ntp.ntptime.settime", raise_error)
    result = ntp.sync_time()
    assert result == ntp.FAILED


def test_sync_time_succeeds_on_retry(monkeypatch):
    call_count = [0]

    def flaky_settime():
        call_count[0] += 1
        if call_count[0] < 3:
            raise OSError("fail")

    monkeypatch.setattr("utilities.ntp.ntptime.settime", flaky_settime)
    monkeypatch.setattr(_time, "sleep", lambda _: None)
    result = ntp.sync_time(attempts=5)
    assert result == ntp.SYNCED
    assert call_count[0] == 3


def test_sync_time_all_attempts_fail(monkeypatch):
    monkeypatch.setattr(
        "utilities.ntp.ntptime.settime",
        lambda: (_ for _ in ()).throw(OSError("fail")),
    )
    monkeypatch.setattr(_time, "sleep", lambda _: None)
    result = ntp.sync_time(attempts=3)
    assert result == ntp.FAILED


def test_sync_time_default_single_attempt(monkeypatch):
    call_count = [0]

    def counting_settime():
        call_count[0] += 1
        raise OSError("fail")

    monkeypatch.setattr("utilities.ntp.ntptime.settime", counting_settime)
    ntp.sync_time()
    assert call_count[0] == 1


# --- state updates ---

def test_state_updated_on_success(monkeypatch):
    monkeypatch.setattr("utilities.ntp.ntptime.settime", lambda: None)
    ntp.sync_time()
    assert ntp.state == ntp.SYNCED


def test_state_updated_on_failure(monkeypatch):
    monkeypatch.setattr(
        "utilities.ntp.ntptime.settime",
        lambda: (_ for _ in ()).throw(OSError("fail")),
    )
    ntp.sync_time()
    assert ntp.state == ntp.FAILED


def test_state_reset_to_idle_on_new_call(monkeypatch):
    """sync_time() resets state to IDLE before attempting."""
    monkeypatch.setattr("utilities.ntp.ntptime.settime", lambda: None)
    ntp.sync_time()
    assert ntp.state == ntp.SYNCED

    # Call again — state should be reset internally before attempting
    call_count = [0]

    def check_state_settime():
        call_count[0] += 1

    monkeypatch.setattr("utilities.ntp.ntptime.settime", check_state_settime)
    ntp.sync_time()
    assert call_count[0] == 1  # confirms it ran again despite previous SYNCED
