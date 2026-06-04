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

    Each instance owns its own ``WLAN`` handle, timer, and state, so
    multiple clients (or a test double) can coexist.

    Timer ownership: ``_timer`` is transient — created in
    ``start_connect()`` and destroyed as soon as the state machine leaves
    CONNECTING (on ``STAT_GOT_IP`` / ``STAT_WRONG_PASSWORD`` or via
    ``reset()``). See copilot-instructions.md virtual-timer budget.
    """

    def __init__(self) -> None:
        self._state: int = IDLE
        self._wlan = None  # WLAN | None
        self._timer = None  # Timer | None
        self._ssid: str = ""
        self._password: str = ""
        self._attempt_start_ms: int = 0
        self._retry_after_ms: int = 0
        self._pending: bool = False
        self._generation: int = 0
        # Cache bound methods used from IRQ context to avoid heap
        # allocation (and possible MemoryError) inside the timer callback.
        self._tick_ref = self._tick
        self._timer_callback_ref = self._timer_callback

    # --- Public API ---

    @property
    def state(self) -> int:
        return self._state

    def start_connect(self, ssid: str, password: str) -> None:
        """Non-blocking connect. Starts a timer that drives the state machine.

        Idempotent if already CONNECTING. From other states, resets first.
        """
        if self._state == CONNECTING:
            return

        self.reset()
        self._begin_connect(ssid, password)
        if self._state == FAILED:
            return

        self._pending = False
        self._timer = Timer(-1)
        self._timer.init(
            mode=Timer.PERIODIC,
            period=_TIMER_PERIOD_MS,
            callback=self._timer_callback_ref,
        )

    def connect(self, ssid: str, password: str, timeout_ms: int = 300_000) -> int:
        """Blocking connect with timeout. Returns final state."""
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
        return self._wlan is not None and self._wlan.isconnected()

    def reset(self) -> None:
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

    # --- Internals ---

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
            print("[wifi] connect exception:", e)

        self._state = CONNECTING

    def _tick(self, gen: int) -> None:
        """Advance connection state machine one step."""
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
            # STAT_CONNECTING, LINK_DOWN (0), NOIP (2), or any unexpected
            # status that persists past the attempt TTL — disconnect and retry
            self._wlan.disconnect()
            needs_retry = True

        if needs_retry:
            self._retry_after_ms = time.ticks_add(now_ms, _RETRY_COOLDOWN_MS)
            self._attempt_start_ms = time.ticks_add(now_ms, _RETRY_COOLDOWN_MS)
            try:
                self._wlan.connect(self._ssid, self._password)
            except Exception as e:
                print("[wifi] connect exception:", e)

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.deinit()
            self._timer = None

    def _timer_callback(self, _t) -> None:
        """Timer IRQ handler. Defers _tick to main thread."""
        if self._pending:
            return
        self._pending = True
        try:
            micropython.schedule(self._tick_ref, self._generation)
        except Exception:
            # RuntimeError if schedule queue is full; MemoryError if the
            # heap is locked.  Either way, clear _pending so the next
            # timer tick can retry instead of wedging the state machine.
            self._pending = False
