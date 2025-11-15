import time
import machine
from network import (
    WLAN,
    STA_IF,
    STAT_GOT_IP,
    STAT_WRONG_PASSWORD,
    STAT_CONNECTING,
    STAT_NO_AP_FOUND,
    STAT_CONNECT_FAIL,
)

ATTEMPT_TTL_MS = const(10_000)
CONNECTING_SLEEP_MS = const(100)
DISCONNECTED_SLEEP_MS = const(1_000)


def try_connect(ssid: str, password: str, timeout_ms: int = 300_000) -> bool:
    if not ssid:
        return False

    if timeout_ms < ATTEMPT_TTL_MS:
        timeout_ms = ATTEMPT_TTL_MS

    wlan = WLAN(STA_IF)
    if not wlan.active():
        wlan.active(True)

    if wlan.isconnected() and wlan.config("ssid") != ssid:
        wlan.disconnect()
        machine.idle()

    now_ms = time.ticks_ms()
    deadline_ms = time.ticks_add(now_ms, timeout_ms)
    attempt_start_ms = time.ticks_add(now_ms, -ATTEMPT_TTL_MS)

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
            if time.ticks_diff(now_ms, attempt_start_ms) < ATTEMPT_TTL_MS:
                time.sleep_ms(CONNECTING_SLEEP_MS)
                continue
            else:  # took too long to connect
                wlan.disconnect()
                time.sleep_ms(DISCONNECTED_SLEEP_MS)
        elif status == STAT_NO_AP_FOUND or status == STAT_CONNECT_FAIL:
            if remaining_ms > DISCONNECTED_SLEEP_MS:
                time.sleep_ms(DISCONNECTED_SLEEP_MS)
            else:
                return False  # timeout

        attempt_start_ms = now_ms
        wlan.connect(ssid, password)
        machine.idle()
