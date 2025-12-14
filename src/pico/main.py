import machine
import micropython

from displays.timerdisplay import TimerDisplay
from graphics.colors import Colors
from graphics.geometry import Geometry
from graphics.timergraphics import TimerGraphics
from machine import Timer
from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER
from scheduling import eventfactory
from utilities import ntp, wifi


# Constants
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
    ),
)

TIMER_DISPLAY = TimerDisplay(
    display=DISPLAY,
    graphics=TIMER_GRAPHICS,
    timezone_offset_hours=1,  # UTC+01:00 Prague Winter time
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


def _connect_wifi_sync_time_silent(_: int) -> None:
    _connect_wifi(throw_on_fail=False)
    _sync_time(throw_on_fail=False)


CONNECT_WIFI_SYNC_TIME_SILENT_REF = _connect_wifi_sync_time_silent


def _schedule_connect_wifi_sync_time_silent(_: Timer) -> None:
    micropython.schedule(CONNECT_WIFI_SYNC_TIME_SILENT_REF, 0)


SCHEDULE_CONNECT_WIFI_SYNC_TIME_SILENT_REF = _schedule_connect_wifi_sync_time_silent


# Main logic
_connect_wifi(throw_on_fail=True)
_sync_time(throw_on_fail=True)

twelve_hours_in_ms = const(12 * 60 * 60 * 1000)
Timer(  # Connect to WiFi and sync time every 12 hours
    -1,
    mode=Timer.PERIODIC,
    period=twelve_hours_in_ms,
    callback=SCHEDULE_CONNECT_WIFI_SYNC_TIME_SILENT_REF,
)

TIMER_DISPLAY.initialize(
    eventfactory.work_week_loop(
        work_days={0, 1, 2, 3, 4},
        work_start_utc=(8, 0),
        work_end_utc=(17, 0),
    )
)

# short test events for demo
# import time
# now = time.time()
# TIMER_DISPLAY.initialize(
#     iter(
#         [
#             eventfactory.Event(
#                 name="Event 1",
#                 start_timestamp=now,
#                 duration_sec=30,
#             ),
#             eventfactory.Event(
#                 name="Event 2",
#                 start_timestamp=now + 30,
#                 duration_sec=20,
#             ),
#             eventfactory.Event(
#                 name="Event 3",
#                 start_timestamp=now + 50,
#                 duration_sec=40,
#             ),
#         ]
#     )
# )

while True:
    machine.idle()
