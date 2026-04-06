import micropython
import time

from machine import Timer
from utilities import ntp, wifi


class NetworkService:
    def __init__(
        self,
        ssid: str,
        password: str,
        time_zone_offset: int,
        status_fn,
        schedule=micropython.schedule,
    ) -> None:
        self._ssid = ssid
        self._password = password
        self._tz_offset = time_zone_offset
        self._status = status_fn
        self._schedule = schedule

        self._connect_and_sync_ref = self._connect_and_sync
        self._schedule_connect_and_sync_ref = self._schedule_connect_and_sync

        self._sync_timer: Timer | None = None

    def connect_wifi(self, throw_on_fail: bool = False) -> bool:
        self._status("wifi")
        is_connected = wifi.try_connect(self._ssid, self._password)
        if not is_connected:
            if throw_on_fail:
                self._status("wifi fail")
                raise RuntimeError("Could not connect to WiFi")
            self._show_time_subtext("wifi")
        return is_connected

    def sync_time(self, throw_on_fail: bool = False) -> bool:
        self._status("sync time")
        is_time_synced = ntp.try_sync_time()
        if not is_time_synced:
            if throw_on_fail:
                self._status("ntp fail")
                raise RuntimeError("Could not sync time")
            self._show_time_subtext("sync time")
        return is_time_synced

    def connect_and_sync_initial(self) -> None:
        self.connect_wifi(throw_on_fail=True)
        self.sync_time(throw_on_fail=True)

    def start_periodic_sync(self, period_ms: int, timer_factory=Timer) -> None:
        self._sync_timer = timer_factory(
            -1,
            mode=Timer.PERIODIC,
            period=period_ms,
            callback=self._schedule_connect_and_sync_ref,
        )

    def _connect_and_sync(self, _: int) -> None:
        if self.connect_wifi(throw_on_fail=False):
            self.sync_time(throw_on_fail=False)

    def _schedule_connect_and_sync(self, _: Timer) -> None:
        self._schedule(self._connect_and_sync_ref, 0)

    def _show_time_subtext(self, label: str) -> None:
        now = time.gmtime()
        hour, minute = (now[3] + self._tz_offset) % 24, now[4]
        self._status(label, f"at {hour:02}:{minute:02}")
