import machine
import micropython
import time

from displays import timer
from machine import Timer
from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER
from scheduling import eventfactory
from utilities import ntp, wifi

try:
    import config
except ImportError as exc:
    raise RuntimeError("Missing required module: config;" \
    " please create a config.py with your WiFi credentials.") from exc


# Setup
PICO_GRAPHICS = PicoGraphics(display=DISPLAY_PICO_EXPLORER)

TIMER_RENDERER = timer.Renderer(
    timer.Geometry(PICO_GRAPHICS),
    timer.Colors(
        background=PICO_GRAPHICS.create_pen(0, 0, 0),  # Black
        ring=PICO_GRAPHICS.create_pen(0, 255, 0),  # Green
        primary_text=PICO_GRAPHICS.create_pen(255, 255, 255),  # White
        secondary_text=PICO_GRAPHICS.create_pen(160, 160, 160),  # Gray
    ),
)

TIMER_DISPLAY = timer.Display(TIMER_RENDERER)


# Helpers
def _connect_wifi(throw_on_fail: bool = False) -> bool:
    TIMER_RENDERER.text_write(timer.TEXT_CENTER, "wifi")
    TIMER_RENDERER.update()
    is_connected = wifi.try_connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    if not is_connected:
        if throw_on_fail:
            TIMER_RENDERER.text_write(timer.TEXT_CENTER, "wifi fail")
            TIMER_RENDERER.update()
            raise RuntimeError("Could not connect to WiFi")
        now = time.gmtime()
        hour, minute = (now[3] + config.TIME_ZONE_OFFSET) % 24, now[4]
        TIMER_RENDERER.text_write(timer.TEXT_BELOW_CENTER, f"at {hour:02}:{minute:02}")
        TIMER_RENDERER.update()
    return is_connected


def _sync_time(throw_on_fail: bool = False) -> bool:
    TIMER_RENDERER.text_write(timer.TEXT_CENTER, "sync time")
    TIMER_RENDERER.update()
    is_time_synced = ntp.try_sync_time()
    if not is_time_synced:
        if throw_on_fail:
            TIMER_RENDERER.text_write(timer.TEXT_CENTER, "ntp fail")
            TIMER_RENDERER.update()
            raise RuntimeError("Could not sync time")
        now = time.gmtime()
        hour, minute = (now[3] + config.TIME_ZONE_OFFSET) % 24, now[4]
        TIMER_RENDERER.text_write(timer.TEXT_BELOW_CENTER, f"at {hour:02}:{minute:02}")
        TIMER_RENDERER.update()
    return is_time_synced


def _connect_wifi_sync_time_silent(_: int) -> None:
    if _connect_wifi(throw_on_fail=False):
        _sync_time(throw_on_fail=False)


CONNECT_WIFI_SYNC_TIME_SILENT_REF = _connect_wifi_sync_time_silent


def _schedule_connect_wifi_sync_time_silent(_: Timer) -> None:
    micropython.schedule(CONNECT_WIFI_SYNC_TIME_SILENT_REF, 0)


SCHEDULE_CONNECT_WIFI_SYNC_TIME_SILENT_REF = _schedule_connect_wifi_sync_time_silent


# Main logic
_connect_wifi(throw_on_fail=True)
_sync_time(throw_on_fail=True)

TWELVE_HOURS_IN_MS = const(12 * 60 * 60 * 1000)
Timer(  # Connect to WiFi and sync time every 12 hours
    -1,
    mode=Timer.PERIODIC,
    period=TWELVE_HOURS_IN_MS,
    callback=SCHEDULE_CONNECT_WIFI_SYNC_TIME_SILENT_REF,
)

TIMER_DISPLAY.initialize(
    eventfactory.work_week_loop(
        work_days={0, 1, 2, 3, 4},
        work_start_utc=(8, 0),
        work_end_utc=(17, 0),
    )
)

# # short test events for demo
# import time
# from scheduling.event import Event
# now = time.time()
# TIMER_DISPLAY.initialize(
#     iter(
#         [
#             Event("Event 1", now, 10),
#             Event("Event 2", now + 10, 5),
#             Event("Event 3", now + 15, 15)
#         ]
#     )
# )

while True:
    machine.idle()
