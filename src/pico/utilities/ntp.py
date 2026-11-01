import time
import ntptime

from micropython import const

from utilities.log import log_exception

IDLE = const(0)
SYNCED = const(1)
FAILED = const(2)

_RETRY_DELAY_S = const(10)

state = IDLE


def sync_time(attempts=1):
    """Blocking NTP sync; returns ``SYNCED`` or ``FAILED``."""
    global state
    state = IDLE

    for i in range(attempts):
        try:
            ntptime.settime()
            state = SYNCED
            return SYNCED
        except Exception as e:
            log_exception("[ntp] exception:", e)
            state = FAILED
            if i < attempts - 1:
                time.sleep(_RETRY_DELAY_S)

    return FAILED
