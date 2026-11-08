from services import wifi_client
from services.wifi_client import WifiClient


class NetworkService:
    """Connects WiFi with its credentials: blocking at boot, in the background after."""

    def __init__(self, ssid: str, password: str, wifi: WifiClient) -> None:
        self._ssid = ssid
        self._password = password
        self._wifi = wifi

    def connect_initial(self, on_progress=None) -> None:  # on_progress: (str) -> None
        """Block until WiFi connects, else raise ``RuntimeError``.

        ``on_progress`` receives progress messages during this call only; it isn't
        retained, so reconnects never draw over the active view.
        """
        def _notify(msg: str) -> None:
            if on_progress is not None:
                on_progress(msg)

        _notify("wifi")
        result = self._wifi.connect(self._ssid, self._password)
        if result != wifi_client.CONNECTED:
            _notify("wifi fail")
            raise RuntimeError("Could not connect to WiFi")

    def start_reconnect(self) -> None:
        """Unless the link is up, start reconnecting without blocking.

        A reconnect already in progress carries on rather than restarting.
        """
        if not self._wifi.is_connected():
            self._wifi.start_connect(self._ssid, self._password)
