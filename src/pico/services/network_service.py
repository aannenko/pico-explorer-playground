import time

from micropython import const
from services import wifi_client
from services.wifi_client import WifiClient
from utilities import ntp
from utilities.log import log_exception

_IDLE = const(0)
_WIFI = const(1)
_NTP = const(2)


class NetworkService:
    """NTP clock sync over WiFi: a blocking initial sync, then periodic resyncs."""

    def __init__(
        self,
        ssid: str,
        password: str,
        wifi: WifiClient,
        sync_interval_ms: int = 12 * 60 * 60 * 1000,
        tick_scheduler=None,
    ) -> None:
        self._ssid = ssid
        self._password = password
        self._wifi = wifi
        self._sync_interval_ms = sync_interval_ms
        self._last_sync_ticks = 0
        self._phase = _IDLE

        if tick_scheduler is not None:
            tick_scheduler.register(self._tick)

    def connect_and_sync_initial(self, status_fn=None) -> None:  # status_fn: (str) -> None
        """Block until WiFi connects and NTP syncs, else raise ``RuntimeError``.

        ``status_fn`` receives progress messages during this call only; it isn't
        retained, so periodic resyncs never draw over the active view.
        """
        def _notify(msg: str) -> None:
            if status_fn is not None:
                status_fn(msg)

        _notify("wifi")
        result = self._wifi.connect(self._ssid, self._password)
        if result != wifi_client.CONNECTED:
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
            log_exception("[net] tick err:", e)

    def _tick_inner(self) -> None:
        if self._phase == _IDLE:
            now = time.ticks_ms()
            if time.ticks_diff(now, self._last_sync_ticks) < self._sync_interval_ms:
                return
            if self._wifi.is_connected():
                self._phase = _NTP
            else:
                self._wifi.start_connect(self._ssid, self._password)
                self._phase = _WIFI

        if self._phase == _WIFI:
            s = self._wifi.state
            if s == wifi_client.CONNECTED:
                self._phase = _NTP
            elif s == wifi_client.FAILED:
                self._last_sync_ticks = time.ticks_ms()
                self._phase = _IDLE
            else:
                return

        if self._phase == _NTP:
            ntp.sync_time()
            self._last_sync_ticks = time.ticks_ms()
            self._phase = _IDLE
