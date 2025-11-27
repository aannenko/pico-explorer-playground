import micropython
import time

from graphics.colors import Colors
from graphics.geometry import Geometry
from graphics.timergraphics import TimerGraphics
from machine import Timer
from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER
from scheduling import eventfactory
from utilities import ntp, wifi


# Constants
TIME_ZONE_OFFSET_HOURS = const(1)  # UTC+01:00 Prague Winter time

WIFI_SSID = "your_ssid_here"
WIFI_PASSWORD = "your_password_here"


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


# Helpers
def _connect_wifi(throw_on_fail: bool = False) -> None:
    TIMER_GRAPHICS.text_write(TimerGraphics.TEXT_CENTER, "wifi")
    DISPLAY.update()
    is_connected = wifi.try_connect(WIFI_SSID, WIFI_PASSWORD)
    if not is_connected:
        TIMER_GRAPHICS.text_write(TimerGraphics.TEXT_CENTER, "wifi fail")
        DISPLAY.update()
        if throw_on_fail:
            raise RuntimeError("Could not connect to WiFi")


def _sync_time(throw_on_fail: bool = False) -> None:
    TIMER_GRAPHICS.text_write(TimerGraphics.TEXT_CENTER, "sync time")
    DISPLAY.update()
    is_time_synced = ntp.try_sync_time()
    if not is_time_synced:
        TIMER_GRAPHICS.text_write(TimerGraphics.TEXT_CENTER, "ntp fail")
        DISPLAY.update()
        if throw_on_fail:
            raise RuntimeError("Could not sync time")


def _update_ring(arg: int) -> None:
    TIMER_GRAPHICS.ring_clear_next_segment()
    DISPLAY.update()


UPDATE_RING_REF = _update_ring


def _schedule_update_ring(timer: Timer) -> None:
    micropython.schedule(UPDATE_RING_REF, 0)


SCHEDULE_UPDATE_RING_REF = _schedule_update_ring


def _update_time(arg: int) -> None:
    _, _, _, hour, minute, second, _, _ = time.gmtime()
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
_connect_wifi(throw_on_fail=True)
_sync_time(throw_on_fail=True)

Timer(  # Clock timer
    -1,
    mode=Timer.PERIODIC,
    period=1000,
    callback=SCHEDULE_UPDATE_TIME_REF
)

for event in eventfactory.work_week_loop(
    work_days={0, 1, 2, 3, 4},
    work_start_utc=(8, 0),
    work_end_utc=(17, 0),
):
    _connect_wifi(throw_on_fail=False)
    _sync_time(throw_on_fail=False)

    _, _, _, hour, minute, second, wday, _ = time.gmtime()
    _, _, _, start_hour, start_minute, start_second, start_wday, _ = time.gmtime(event.start_timestamp)
    elapsed_sec = (
        (hour * 3600 + minute * 60 + second)
        - (start_hour * 3600 + start_minute * 60 + start_second)
        + ((wday - start_wday) % 7) * 86400
    )

    if elapsed_sec < 0:
        elapsed_sec = 0
    elif elapsed_sec > event.duration_sec:
        elapsed_sec = event.duration_sec

    text_center = event.name
    text_below = (
        "huf-huf" if event.name == "work"
        else "zzz" if event.name == "rest"
        else "yawn"
    )

    TIMER_GRAPHICS.reset()
    TIMER_GRAPHICS.ring_clear_segments(elapsed_sec * Geometry.RING_SEGMENTS // event.duration_sec)
    TIMER_GRAPHICS.text_write(TimerGraphics.TEXT_CENTER, text_center)
    TIMER_GRAPHICS.text_write(TimerGraphics.TEXT_BELOW_CENTER, text_below)
    DISPLAY.update()

    remaining_sec = event.duration_sec - elapsed_sec
    if remaining_sec > 0:
        ring_timer = Timer(
            -1,
            mode=Timer.PERIODIC,
            period=event.duration_sec * 1000 // Geometry.RING_SEGMENTS,
            callback=SCHEDULE_UPDATE_RING_REF
        )

        time.sleep(remaining_sec)
        ring_timer.deinit()

    TIMER_GRAPHICS.ring_clear_next_segment()
    DISPLAY.update()
