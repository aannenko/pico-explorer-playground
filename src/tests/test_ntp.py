from __future__ import annotations

import time as _time

from utilities import ntp


# --- sync_time() ---

def test_sync_time_success(monkeypatch):
    monkeypatch.setattr("utilities.ntp.ntptime.settime", lambda: None)
    assert ntp.sync_time() is True


def test_sync_time_failure(monkeypatch, capsys):
    def raise_error():
        raise OSError("NTP timeout")

    monkeypatch.setattr("utilities.ntp.ntptime.settime", raise_error)
    assert ntp.sync_time() is False
    out = capsys.readouterr().out
    assert out.startswith("[ntp] exception:")
    assert "OSError: NTP timeout" in out


def test_sync_time_succeeds_on_retry(monkeypatch):
    call_count = [0]

    def flaky_settime():
        call_count[0] += 1
        if call_count[0] < 3:
            raise OSError("fail")

    monkeypatch.setattr("utilities.ntp.ntptime.settime", flaky_settime)
    monkeypatch.setattr(_time, "sleep", lambda _: None)
    assert ntp.sync_time(attempts=5) is True
    assert call_count[0] == 3


def test_sync_time_all_attempts_fail(monkeypatch):
    monkeypatch.setattr(
        "utilities.ntp.ntptime.settime",
        lambda: (_ for _ in ()).throw(OSError("fail")),
    )
    monkeypatch.setattr(_time, "sleep", lambda _: None)
    assert ntp.sync_time(attempts=3) is False


def test_sync_time_default_single_attempt(monkeypatch):
    call_count = [0]

    def counting_settime():
        call_count[0] += 1
        raise OSError("fail")

    monkeypatch.setattr("utilities.ntp.ntptime.settime", counting_settime)
    ntp.sync_time()
    assert call_count[0] == 1
