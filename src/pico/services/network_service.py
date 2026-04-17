import time

from micropython import const
from utilities import ntp, wifi

_IDLE = const(0)
_WIFI = const(1)
_NTP = const(2)


class NetworkService:
    def __init__(
        self,
        ssid: str,
        password: str,
        sync_interval_ms: int = 12 * 60 * 60 * 1000,
        tick_scheduler=None,
    ) -> None:
        self._ssid = ssid
        self._password = password
        self._sync_interval_ms = sync_interval_ms
        self._last_sync_ticks: int = 0
        self._phase: int = _IDLE

        if tick_scheduler is not None:
            tick_scheduler.register(self._tick)

    def connect_and_sync_initial(self, status_fn=None) -> None:
        # status_fn is only used during the initial blocking bootstrap;
        # it is not retained, so the boot-time StatusDisplay does not need
        # to live beyond this call.
        def _notify(msg: str) -> None:
            if status_fn is not None:
                status_fn(msg)

        _notify("wifi")
        result = wifi.connect(self._ssid, self._password)
        if result != wifi.CONNECTED:
            _notify("wifi fail")
            raise RuntimeError("Could not connect to WiFi")

        _notify("sync time")
        result = ntp.sync_time(attempts=5)
        if result != ntp.SYNCED:
            _notify("ntp fail")
            raise RuntimeError("Could not sync time")

        self._last_sync_ticks = time.ticks_ms()

    def _tick(self) -> None:
        try:
            self._tick_inner()
        except Exception as e:
            print("[net] tick err:", e)

    def _tick_inner(self) -> None:
        if self._phase == _IDLE:
            now = time.ticks_ms()
            if time.ticks_diff(now, self._last_sync_ticks) < self._sync_interval_ms:
                return
            if wifi.is_connected():
                self._phase = _NTP
            else:
                wifi.start_connect(self._ssid, self._password)
                self._phase = _WIFI

        if self._phase == _WIFI:
            s = wifi.state
            if s == wifi.CONNECTED:
                self._phase = _NTP
            elif s == wifi.FAILED:
                self._last_sync_ticks = time.ticks_ms()
                self._phase = _IDLE
            else:
                return  # still CONNECTING — come back next tick

        if self._phase == _NTP:
            ntp.sync_time()
            self._last_sync_ticks = time.ticks_ms()
            self._phase = _IDLE
