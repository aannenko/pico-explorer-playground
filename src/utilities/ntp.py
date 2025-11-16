import ntptime
import time

def try_sync_time(attempts: int = 5) -> bool:
    for _ in range(attempts):
        try:
            ntptime.settime()
            return True
        except Exception as e:
            print("[ntp] exception:", e)

        time.sleep(10)
    return False
