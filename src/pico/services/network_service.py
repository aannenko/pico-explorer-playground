import time

from utilities import ntp, wifi


class NetworkService:
    def __init__(
        self,
        ssid: str,
        password: str,
        time_zone_offset: int,
        status_fn,
        sync_interval_ms: int = 12 * 60 * 60 * 1000,
        tick_scheduler=None,
    ) -> None:
        self._ssid = ssid
        self._password = password
        self._tz_offset = time_zone_offset
        self._status = status_fn
        self._sync_interval_ms = sync_interval_ms
        self._last_sync_ticks: int = 0

        if tick_scheduler is not None:
            tick_scheduler.register(self._tick)

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
        self._last_sync_ticks = time.ticks_ms()

    def _tick(self) -> None:
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_sync_ticks) >= self._sync_interval_ms:
            self._last_sync_ticks = now
            if self.connect_wifi(throw_on_fail=False):
                self.sync_time(throw_on_fail=False)

    def _show_time_subtext(self, label: str) -> None:
        now = time.gmtime()
        hour, minute = (now[3] + self._tz_offset) % 24, now[4]
        self._status(label, f"at {hour:02}:{minute:02}")
