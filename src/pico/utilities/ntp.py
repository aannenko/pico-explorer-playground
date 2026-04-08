import time
import ntptime

from micropython import const

IDLE = const(0)
SYNCED = const(1)
FAILED = const(2)

state = IDLE


def sync_time(attempts=1):
    """Blocking NTP sync. Returns final state (SYNCED or FAILED).

    Each attempt calls ntptime.settime() which blocks ~1-3s for the
    UDP roundtrip. Failed attempts are separated by a 10s sleep.
    """
    global state
    state = IDLE

    for i in range(attempts):
        try:
            ntptime.settime()
            state = SYNCED
            return SYNCED
        except Exception as e:
            print("[ntp] exception:", e)
            state = FAILED
            if i < attempts - 1:
                time.sleep(10)

    return FAILED
