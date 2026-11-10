import time
import micropython

from micropython import const
from machine import Timer
from network import (
    WLAN,
    STA_IF,
    STAT_GOT_IP,
    STAT_WRONG_PASSWORD,
    STAT_NO_AP_FOUND,
    STAT_CONNECT_FAIL,
)

from utilities.log import log_exception

IDLE = const(0)
CONNECTING = const(1)
CONNECTED = const(2)
FAILED = const(3)

_ATTEMPT_TTL_MS = const(10_000)
_RETRY_COOLDOWN_MS = const(1_000)
_CONNECTING_SLEEP_MS = const(100)
_TIMER_PERIOD_MS = const(500)


class WifiClient:
    """Encapsulates a single WiFi connection state machine.

    Instances share the firmware's single ``WLAN(STA_IF)`` interface; only
    the timer and state are per instance.  ``start_connect``'s virtual
    ``machine.Timer`` exists only while CONNECTING.
    """

    def __init__(self) -> None:
        self._state = IDLE
        self._wlan: WLAN | None = None
        self._timer: Timer | None = None
        self._ssid = ""
        self._password = ""
        self._attempt_start_ms = 0
        self._retry_after_ms = 0
        self._pending = False
        self._generation = 0
        self._tick_ref = self._tick
        self._timer_callback_ref = self._timer_callback

    @property
    def state(self) -> int:
        """Connect-attempt state: IDLE, CONNECTING, CONNECTED or FAILED."""
        return self._state

    def start_connect(self, ssid: str, password: str) -> None:
        """Non-blocking connect.

        Idempotent if already CONNECTING. From other states, resets first.

        Raises if no timer can be started, leaving the state FAILED so the next
        call retries; the join already begun may still bring the link up.
        """
        if self._state == CONNECTING:
            return

        self.reset()
        self._begin_connect(ssid, password)
        if self._state == FAILED:
            return

        self._pending = False
        try:
            self._timer = Timer(-1)
            self._timer.init(
                mode=Timer.PERIODIC,
                period=_TIMER_PERIOD_MS,
                callback=self._timer_callback_ref,
            )
        except Exception:
            self._state = FAILED
            self._stop_timer()
            raise

    def connect(self, ssid: str, password: str, timeout_ms: int = 300_000) -> int:
        """Blocking connect with timeout; returns CONNECTED or FAILED.

        A ``timeout_ms`` below ``_ATTEMPT_TTL_MS`` is raised to it.
        """
        if timeout_ms < _ATTEMPT_TTL_MS:
            timeout_ms = _ATTEMPT_TTL_MS

        self.reset()
        self._begin_connect(ssid, password)
        if self._state == FAILED:
            return FAILED

        deadline_ms = time.ticks_add(time.ticks_ms(), timeout_ms)

        while True:
            self._tick(self._generation)
            if self._state == CONNECTED:
                return CONNECTED
            if self._state == FAILED:
                return FAILED
            if time.ticks_diff(time.ticks_ms(), deadline_ms) >= 0:
                self.reset()
                return FAILED
            time.sleep_ms(_CONNECTING_SLEEP_MS)

    def is_connected(self) -> bool:
        """Return whether this client's link is up right now."""
        return self._wlan is not None and self._wlan.isconnected()

    def reset(self) -> None:
        """Abandon any connect attempt and return to IDLE, without disconnecting."""
        if self._timer is not None:
            self._timer.deinit()
            self._timer = None
        self._generation += 1
        self._state = IDLE
        self._wlan = None
        self._ssid = ""
        self._password = ""
        self._attempt_start_ms = 0
        self._retry_after_ms = 0
        self._pending = False

    def _begin_connect(self, ssid: str, password: str) -> None:
        if not ssid:
            self._state = FAILED
            return

        self._ssid = ssid
        self._password = password

        self._wlan = WLAN(STA_IF)
        if not self._wlan.active():
            self._wlan.active(True)

        if self._wlan.isconnected() and self._wlan.config("ssid") != ssid:
            self._wlan.disconnect()

        self._attempt_start_ms = time.ticks_ms()
        self._retry_after_ms = 0

        try:
            self._wlan.connect(ssid, password)
        except Exception as e:
            log_exception("[wifi] connect exception:", e)

        self._state = CONNECTING

    def _tick(self, gen: int) -> None:
        """Advance the connection state machine one step."""
        if gen != self._generation:
            return

        self._pending = False

        if self._state != CONNECTING or self._wlan is None:
            return

        now_ms = time.ticks_ms()

        if self._retry_after_ms and time.ticks_diff(now_ms, self._retry_after_ms) < 0:
            return

        wlan_status = self._wlan.status()

        if wlan_status == STAT_GOT_IP:
            self._state = CONNECTED
            self._stop_timer()
            return

        if wlan_status == STAT_WRONG_PASSWORD:
            self._wlan.disconnect()
            self._state = FAILED
            self._stop_timer()
            return

        needs_retry = False
        if wlan_status in (STAT_NO_AP_FOUND, STAT_CONNECT_FAIL):
            needs_retry = True
        elif time.ticks_diff(now_ms, self._attempt_start_ms) >= _ATTEMPT_TTL_MS:
            # STAT_CONNECTING, LINK_DOWN (0), NOIP (2) or any unexpected status that
            # persists past the attempt TTL.
            self._wlan.disconnect()
            needs_retry = True

        if needs_retry:
            self._retry_after_ms = time.ticks_add(now_ms, _RETRY_COOLDOWN_MS)
            self._attempt_start_ms = time.ticks_add(now_ms, _RETRY_COOLDOWN_MS)
            try:
                self._wlan.connect(self._ssid, self._password)
            except Exception as e:
                log_exception("[wifi] connect exception:", e)

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.deinit()
            self._timer = None

    def _timer_callback(self, _t) -> None:
        # _pending collapses firings queued behind blocking work into one scheduled run.
        if self._pending:
            return
        self._pending = True
        try:
            micropython.schedule(self._tick_ref, self._generation)
        except Exception:
            self._pending = False
