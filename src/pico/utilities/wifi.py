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

state = IDLE
_wlan: WLAN | None = None
_timer: Timer | None = None
_ssid = ""
_password = ""
_attempt_start_ms = 0
_retry_after_ms = 0
_pending = False
_generation = 0


def start_connect(ssid, password):
    """Non-blocking connect. Starts a timer that drives the state machine.

    Idempotent if already CONNECTING. From other states, resets first.
    """
    global _timer, _pending

    if state == CONNECTING:
        return

    reset()
    _begin_connect(ssid, password)
    if state == FAILED:
        return

    _pending = False
    _timer = Timer(-1)
    _timer.init(
        mode=Timer.PERIODIC,
        period=_TIMER_PERIOD_MS,
        callback=_timer_callback,
    )


def connect(ssid, password, timeout_ms=300_000):
    """Blocking connect with timeout. Returns final state."""
    if timeout_ms < _ATTEMPT_TTL_MS:
        timeout_ms = _ATTEMPT_TTL_MS

    reset()
    _begin_connect(ssid, password)
    if state == FAILED:
        return FAILED

    deadline_ms = time.ticks_add(time.ticks_ms(), timeout_ms)

    while True:
        _tick(_generation)
        if state == CONNECTED:
            return CONNECTED
        if state == FAILED:
            return FAILED
        if time.ticks_diff(time.ticks_ms(), deadline_ms) >= 0:
            reset()
            return FAILED
        time.sleep_ms(_CONNECTING_SLEEP_MS)


def is_connected():
    """Check actual WiFi hardware connectivity."""
    return _wlan is not None and _wlan.isconnected()


def reset():
    """Stop any active timer and return to IDLE."""
    global state, _wlan, _timer, _ssid, _password
    global _attempt_start_ms, _retry_after_ms, _pending, _generation
    if _timer is not None:
        _timer.deinit()
        _timer = None
    _generation += 1
    state = IDLE
    _wlan = None
    _ssid = ""
    _password = ""
    _attempt_start_ms = 0
    _retry_after_ms = 0
    _pending = False


def _begin_connect(ssid, password):
    """Set up WLAN and initiate first connection attempt."""
    global state, _wlan, _ssid, _password, _attempt_start_ms, _retry_after_ms

    if not ssid:
        state = FAILED
        return

    _ssid = ssid
    _password = password

    _wlan = WLAN(STA_IF)
    if not _wlan.active():
        _wlan.active(True)

    if _wlan.isconnected() and _wlan.config("ssid") != ssid:
        _wlan.disconnect()

    _attempt_start_ms = time.ticks_ms()
    _retry_after_ms = 0

    try:
        _wlan.connect(ssid, password)
    except Exception as e:
        print("[wifi] connect exception:", e)

    state = CONNECTING


def _tick(gen):
    """Advance connection state machine one step."""
    global state, _attempt_start_ms, _retry_after_ms, _pending

    if gen != _generation:
        return

    _pending = False

    if state != CONNECTING or _wlan is None:
        return

    now_ms = time.ticks_ms()

    if _retry_after_ms and time.ticks_diff(now_ms, _retry_after_ms) < 0:
        return

    wlan_status = _wlan.status()

    if wlan_status == STAT_GOT_IP:
        state = CONNECTED
        _stop_timer()
        return

    if wlan_status == STAT_WRONG_PASSWORD:
        _wlan.disconnect()
        state = FAILED
        _stop_timer()
        return

    needs_retry = False
    if wlan_status in (STAT_NO_AP_FOUND, STAT_CONNECT_FAIL):
        needs_retry = True
    elif time.ticks_diff(now_ms, _attempt_start_ms) >= _ATTEMPT_TTL_MS:
        # STAT_CONNECTING, LINK_DOWN (0), NOIP (2), or any unexpected
        # status that persists past the attempt TTL — disconnect and retry
        _wlan.disconnect()
        needs_retry = True

    if needs_retry:
        _retry_after_ms = time.ticks_add(now_ms, _RETRY_COOLDOWN_MS)
        _attempt_start_ms = time.ticks_add(now_ms, _RETRY_COOLDOWN_MS)
        try:
            _wlan.connect(_ssid, _password)
        except Exception as e:
            print("[wifi] connect exception:", e)


def _stop_timer():
    """Stop the private timer if running."""
    global _timer
    if _timer is not None:
        _timer.deinit()
        _timer = None


def _timer_callback(_t):
    """Timer IRQ handler. Defers _tick to main thread."""
    global _pending
    if _pending:
        return
    _pending = True
    try:
        micropython.schedule(_tick_ref, _generation)
    except RuntimeError:
        _pending = False


_tick_ref = _tick
