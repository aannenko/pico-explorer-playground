import time
import ntptime

from micropython import const

from utilities.log import log_exception

_RETRY_DELAY_SEC = const(10)


def sync_time(attempts: int = 1) -> bool:
    """Blocking NTP sync of the RTC; return whether one of ``attempts`` succeeded.

    Sleeps 10 s between attempts.
    """
    for i in range(attempts):
        try:
            ntptime.settime()
            return True
        except Exception as e:
            log_exception("[ntp] exception:", e)
            if i < attempts - 1:
                time.sleep(_RETRY_DELAY_SEC)

    return False
