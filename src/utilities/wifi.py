import time
import machine
from network import WLAN, STA_IF
import network

def try_connect(ssid: str, password: str, attempt_for_seconds: int = 300) -> bool:
    if not ssid:
        return False

    if attempt_for_seconds < 15:
        attempt_for_seconds = 15

    wlan = WLAN(STA_IF)
    if not wlan.active():
        wlan.active(True)

    deadline_ms = time.ticks_add(time.ticks_ms(), attempt_for_seconds * 1000)
    while True:
        status = wlan.status()
        if status == network.STAT_GOT_IP:
            return True  # connected

        if status == network.STAT_WRONG_PASSWORD:
            return False  # cannot connect

        now_ms = time.ticks_ms()
        remaining_ms = time.ticks_diff(deadline_ms, now_ms)
        if remaining_ms <= 0:
            return False  # timeout

        if status == network.STAT_CONNECTING:
            time.sleep_ms(100)
            continue

        if status in (network.STAT_NO_AP_FOUND, network.STAT_CONNECT_FAIL):
            if remaining_ms > 10_000:
                time.sleep_ms(10_000)
            else:
                return False

        wlan.connect(ssid, password)
        machine.idle()
