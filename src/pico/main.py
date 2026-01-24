import machine
import micropython
import time

from displays import sensors, timer
from machine import Timer
from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER  # type: ignore
from scheduling import eventfactory
from sensors import bme690
from utilities import ntp, wifi

try:
    import config
except ImportError as exc:
    raise RuntimeError("Missing required module: config;" \
    " please create a config.py with your WiFi credentials.") from exc


# Setup
PICO_GRAPHICS = PicoGraphics(display=DISPLAY_PICO_EXPLORER)


def _status(text: str, subtext: str = "") -> None:
    # Keep this independent from any particular view geometry.
    PICO_GRAPHICS.set_font(config.FONT)
    w, h = PICO_GRAPHICS.get_bounds()

    bg = PICO_GRAPHICS.create_pen(0, 0, 0)
    white = PICO_GRAPHICS.create_pen(255, 255, 255)
    gray = PICO_GRAPHICS.create_pen(160, 160, 160)

    PICO_GRAPHICS.set_pen(bg)
    PICO_GRAPHICS.clear()

    scale = 3
    PICO_GRAPHICS.set_pen(white)
    tw = PICO_GRAPHICS.measure_text(text, scale=scale)
    PICO_GRAPHICS.text(
        text,
        (w - tw) // 2,
        (h // 2) - (config.FONT_HEIGHT * scale),
        scale=scale,
    )

    if subtext:
        PICO_GRAPHICS.set_pen(gray)
        sw = PICO_GRAPHICS.measure_text(subtext, scale=2)
        PICO_GRAPHICS.text(subtext, (w - sw) // 2, (h // 2) + 5, scale=2)

    PICO_GRAPHICS.update()

TIMER_RENDERER = timer.Renderer(
    geometry=timer.Geometry(
        pico_graphics=PICO_GRAPHICS,
        font=config.FONT,
        font_height=config.FONT_HEIGHT,
        text_scale=config.TEXT_SCALE,
    ),
    colors=timer.Colors(
        background=PICO_GRAPHICS.create_pen(0, 0, 0),  # Black
        ring=PICO_GRAPHICS.create_pen(0, 255, 0),  # Green
        primary_text=PICO_GRAPHICS.create_pen(255, 255, 255),  # White
        secondary_text=PICO_GRAPHICS.create_pen(180, 180, 180),  # Gray
    ),
)

TIMER_DISPLAY = timer.Display(TIMER_RENDERER)

SENSORS_RENDERER = sensors.Renderer(
    geometry=sensors.Geometry(
        pico_graphics=PICO_GRAPHICS,
        font=config.FONT,
        font_height=config.FONT_HEIGHT,
        text_scale=config.TEXT_SCALE,
    ),
    colors=sensors.Colors(
        background=PICO_GRAPHICS.create_pen(0, 0, 0),
        header_text=PICO_GRAPHICS.create_pen(255, 255, 255),
        value_text=PICO_GRAPHICS.create_pen(0, 255, 0),
        secondary_text=PICO_GRAPHICS.create_pen(180, 180, 180),
    ),
)

SENSORS_DISPLAY = sensors.Display(
    renderer=SENSORS_RENDERER,
    bme690_reader=bme690.BME690Reader(
        temp_offset=config.BME690_TEMP_OFFSET,
        hum_offset=config.BME690_HUM_OFFSET,
    ),
    sensor_read_delay_ms=config.SENSOR_READ_DELAY_MS,
    time_zone_offset=config.TIME_ZONE_OFFSET,
)


# Helpers
def _connect_wifi(throw_on_fail: bool = False) -> bool:
    _status("wifi")
    is_connected = wifi.try_connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    if not is_connected:
        if throw_on_fail:
            _status("wifi fail")
            raise RuntimeError("Could not connect to WiFi")
        now = time.gmtime()
        hour, minute = (now[3] + config.TIME_ZONE_OFFSET) % 24, now[4]
        _status("wifi", f"at {hour:02}:{minute:02}")
    return is_connected


def _sync_time(throw_on_fail: bool = False) -> bool:
    _status("sync time")
    is_time_synced = ntp.try_sync_time()
    if not is_time_synced:
        if throw_on_fail:
            _status("ntp fail")
            raise RuntimeError("Could not sync time")
        now = time.gmtime()
        hour, minute = (now[3] + config.TIME_ZONE_OFFSET) % 24, now[4]
        _status("sync time", f"at {hour:02}:{minute:02}")
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

START_VIEW = getattr(config, "START_VIEW", "sensors")
if START_VIEW == "sensors":
    SENSORS_DISPLAY.initialize()
else:
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
