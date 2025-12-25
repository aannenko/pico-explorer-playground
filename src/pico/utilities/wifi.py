import time
import machine

from micropython import const
from network import (
    WLAN,
    STA_IF,
    STAT_GOT_IP,
    STAT_WRONG_PASSWORD,
    STAT_CONNECTING,
    STAT_NO_AP_FOUND,
    STAT_CONNECT_FAIL,
)

_ATTEMPT_TTL_MS = const(10_000)
_CONNECTING_SLEEP_MS = const(100)
_DISCONNECTED_SLEEP_MS = const(1_000)


def try_connect(ssid: str, password: str, timeout_ms: int = 300_000) -> bool:
    if not ssid:
        return False

    if timeout_ms < _ATTEMPT_TTL_MS:
        timeout_ms = _ATTEMPT_TTL_MS

    wlan = WLAN(STA_IF)
    if not wlan.active():
        wlan.active(True)

    now_ms = time.ticks_ms()
    deadline_ms = time.ticks_add(now_ms, timeout_ms)
    attempt_start_ms = time.ticks_add(now_ms, -_ATTEMPT_TTL_MS)

    if wlan.isconnected() and wlan.config("ssid") != ssid:
        wlan.disconnect()
        time.sleep_ms(_DISCONNECTED_SLEEP_MS)

    is_exception_raised = False
    while True:
        status = wlan.status()
        if status == STAT_GOT_IP:
            return True  # connected

        if status == STAT_WRONG_PASSWORD:
            wlan.disconnect()
            return False  # wrong password

        now_ms = time.ticks_ms()
        remaining_ms = time.ticks_diff(deadline_ms, now_ms)
        if remaining_ms <= 0:
            return False  # timeout

        if status == STAT_CONNECTING:
            if time.ticks_diff(now_ms, attempt_start_ms) < _ATTEMPT_TTL_MS:
                time.sleep_ms(_CONNECTING_SLEEP_MS)
                continue
            else:  # took too long to connect
                wlan.disconnect()
                time.sleep_ms(_DISCONNECTED_SLEEP_MS)
        elif is_exception_raised or status in (STAT_NO_AP_FOUND, STAT_CONNECT_FAIL):
            time.sleep_ms(_DISCONNECTED_SLEEP_MS)

        attempt_start_ms = now_ms
        try:
            wlan.connect(ssid, password)
            is_exception_raised = False
            machine.idle()
        except Exception as e:
            is_exception_raised = True
            print("[wifi] exception:", e)
