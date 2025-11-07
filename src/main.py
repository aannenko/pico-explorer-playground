import micropython
import time

from graphics.colors import Colors
from graphics.geometry import Geometry
from graphics.timergraphics import TimerGraphics
from machine import RTC, Timer
from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER
from utilities import ntp, wifi


# Constants
TIME_ZONE_OFFSET_HOURS = const(1)  # UTC+01:00
WORK_START_HOUR_UTC = const(9 - TIME_ZONE_OFFSET_HOURS)
WORK_END_HOUR_UTC = const(18 - TIME_ZONE_OFFSET_HOURS)
WORK_DURATION_SEC = const((WORK_END_HOUR_UTC - WORK_START_HOUR_UTC) * 3600)
REST_DURATION_SEC = const((24 - (WORK_END_HOUR_UTC - WORK_START_HOUR_UTC)) * 3600)

WIFI_SSID = const("your_ssid_here")
WIFI_PASSWORD = const("your_password_here")


# Setup
DISPLAY = PicoGraphics(display=DISPLAY_PICO_EXPLORER)
TIMER_GRAPHICS = TimerGraphics(
    Geometry(DISPLAY),
    Colors(
        background=DISPLAY.create_pen(0, 0, 0),  # Black
        ring_color=DISPLAY.create_pen(0, 255, 0),  # Green
        primary_text_color=DISPLAY.create_pen(255, 255, 255),  # White
        secondary_text_color=DISPLAY.create_pen(160, 160, 160),  # Gray
    )
)

CLOCK = RTC()


# Helpers
def _update_ring(arg: int) -> None:
    TIMER_GRAPHICS.ring_clear_next_segment()
    DISPLAY.update()


UPDATE_RING_REF = _update_ring


def _schedule_update_ring(timer: Timer) -> None:
    micropython.schedule(UPDATE_RING_REF, 0)


SCHEDULE_UPDATE_RING_REF = _schedule_update_ring


def _connect_wifi() -> None:
    TIMER_GRAPHICS.text_write(TimerGraphics.TEXT_CENTER, "wifi")
    DISPLAY.update()
    is_connected = wifi.try_connect(WIFI_SSID, WIFI_PASSWORD)
    if not is_connected:
        TIMER_GRAPHICS.text_write(TimerGraphics.TEXT_CENTER, "wifi fail")
        DISPLAY.update()
        raise RuntimeError("Could not connect to WiFi")


CONNECT_WIFI_REF = _connect_wifi


def _sync_time() -> None:
    TIMER_GRAPHICS.text_write(TimerGraphics.TEXT_CENTER, "sync time")
    DISPLAY.update()
    is_time_synced = ntp.try_sync_time()
    if not is_time_synced:
        TIMER_GRAPHICS.text_write(TimerGraphics.TEXT_CENTER, "ntp fail")
        DISPLAY.update()
        raise RuntimeError("Could not sync time")


SYNC_TIME_REF = _sync_time


def _update_time(arg: int) -> None:
    _, _, _, _, hour, minute, second, _ = CLOCK.datetime()
    TIMER_GRAPHICS.text_write(
        TimerGraphics.TEXT_ABOVE_CENTER,
        f"{hour + TIME_ZONE_OFFSET_HOURS:02}:{minute:02}:{second:02}"
    )
    DISPLAY.update()


UPDATE_TIME_REF = _update_time


def _schedule_update_time(timer: Timer) -> None:
    micropython.schedule(UPDATE_TIME_REF, 0)


SCHEDULE_UPDATE_TIME_REF = _schedule_update_time


# Main logic
Timer(  # Clock timer
    -1,
    mode=Timer.PERIODIC,
    period=1000,
    callback=SCHEDULE_UPDATE_TIME_REF
)

while True:
    _connect_wifi()
    _sync_time()

    TIMER_GRAPHICS.reset()
    TIMER_GRAPHICS.text_write(TimerGraphics.TEXT_BELOW_CENTER, "below")

    phase: str
    total_sec: int
    elapsed_sec: int

    _, _, _, _, hour, minute, second, _ = CLOCK.datetime()
    if hour >= WORK_START_HOUR_UTC and hour < WORK_END_HOUR_UTC:
        phase = "work"
        total_sec = WORK_DURATION_SEC
        elapsed_sec = (hour - WORK_START_HOUR_UTC) * 3600 + minute * 60 + second
    else:
        phase = "rest"
        total_sec = REST_DURATION_SEC
        if hour >= WORK_END_HOUR_UTC:
            elapsed_sec = (hour - WORK_END_HOUR_UTC) * 3600 + minute * 60 + second
        else:
            elapsed_sec = ((24 - WORK_END_HOUR_UTC) + hour) * 3600 + minute * 60 + second

    if elapsed_sec < 0:
        elapsed_sec = 0
    elif elapsed_sec > total_sec:
        elapsed_sec = total_sec

    TIMER_GRAPHICS.ring_clear_segments(elapsed_sec * Geometry.RING_SEGMENTS // total_sec)
    TIMER_GRAPHICS.text_write(TimerGraphics.TEXT_CENTER, phase)
    DISPLAY.update()

    remaining_sec = total_sec - elapsed_sec
    if remaining_sec > 0:
        ring_timer = Timer(
            -1,
            mode=Timer.PERIODIC,
            period=total_sec * 1000 // Geometry.RING_SEGMENTS,
            callback=SCHEDULE_UPDATE_RING_REF
        )

        time.sleep(remaining_sec)
        ring_timer.deinit()

    TIMER_GRAPHICS.ring_clear_next_segment()
    DISPLAY.update()
