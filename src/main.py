import micropython
import time

from graphics.colors import Colors
from graphics.geometry import Geometry
from graphics.timergraphics import TimerGraphics
from machine import RTC, Timer
from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER
from utilities import ntp, wifi

WORK_START_HOUR_UTC = 8  # 9 (+01:00)
WORK_END_HOUR_UTC = 17  # 18 (+01:00)
WORK_DURATION_SEC = (WORK_END_HOUR_UTC - WORK_START_HOUR_UTC) * 3600
REST_DURATION_SEC = (24 - (WORK_END_HOUR_UTC - WORK_START_HOUR_UTC)) * 3600

WIFI_SSID = "your_ssid_here"
WIFI_PASSWORD = "your_password_here"

DISPLAY = PicoGraphics(display=DISPLAY_PICO_EXPLORER)
DISPLAY_INFO = Geometry(DISPLAY)
COLORS = Colors(
    background=DISPLAY.create_pen(0, 0, 0),  # Black
    ring_color=DISPLAY.create_pen(0, 255, 0),  # Green
    primary_text_color=DISPLAY.create_pen(255, 255, 255),  # White
    secondary_text_color=DISPLAY.create_pen(160, 160, 160),  # Gray
)
TIMER_DISPLAY = TimerGraphics(DISPLAY_INFO, COLORS)


# Helpers
def _update_display(arg: int) -> None:
    TIMER_DISPLAY.ring_clear_next_segment()
    DISPLAY.update()


UPDATE_DISPLAY_REF = _update_display


def _schedule_update_display(timer: Timer) -> None:
    micropython.schedule(UPDATE_DISPLAY_REF, 0)


SCHEDULE_UPDATE_DISPLAY_REF = _schedule_update_display


def _connect_wifi() -> None:
    TIMER_DISPLAY.text_write(TIMER_DISPLAY.TEXT_CENTER, "wifi")
    DISPLAY.update()
    is_connected = wifi.try_connect(WIFI_SSID, WIFI_PASSWORD)
    if not is_connected:
        TIMER_DISPLAY.text_write(TIMER_DISPLAY.TEXT_CENTER, "wifi fail")
        DISPLAY.update()
        raise RuntimeError("Could not connect to WiFi")


CONNECT_WIFI_REF = _connect_wifi


def _sync_time() -> None:
    TIMER_DISPLAY.text_write(TIMER_DISPLAY.TEXT_CENTER, "sync time")
    DISPLAY.update()
    is_time_synced = ntp.try_sync_time()
    if not is_time_synced:
        TIMER_DISPLAY.text_write(TIMER_DISPLAY.TEXT_CENTER, "ntp fail")
        DISPLAY.update()
        raise RuntimeError("Could not sync time")


SYNC_TIME_REF = _sync_time


# Main logic
rtc = RTC()
while True:
    _connect_wifi()
    _sync_time()

    TIMER_DISPLAY.reset()
    TIMER_DISPLAY.text_write(TIMER_DISPLAY.TEXT_ABOVE_CENTER, "above")
    TIMER_DISPLAY.text_write(TIMER_DISPLAY.TEXT_BELOW_CENTER, "below")

    phase: str
    total_sec: int
    elapsed_sec: int

    _, _, _, _, hour, minute, second, _ = rtc.datetime()
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

    TIMER_DISPLAY.ring_clear_segments(elapsed_sec * DISPLAY_INFO.RING_SEGMENTS // total_sec)
    TIMER_DISPLAY.text_write(TIMER_DISPLAY.TEXT_CENTER, phase)
    DISPLAY.update()

    remaining_sec = total_sec - elapsed_sec
    if remaining_sec > 0:
        timer = Timer(
            -1,
            mode=Timer.PERIODIC,
            period=total_sec * 1000 // DISPLAY_INFO.RING_SEGMENTS,
            callback=SCHEDULE_UPDATE_DISPLAY_REF)

        time.sleep(remaining_sec)
        timer.deinit()

    TIMER_DISPLAY.ring_clear_next_segment()
    DISPLAY.update()
