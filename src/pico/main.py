import machine
import micropython
import time

from displays import sensors, timer
from machine import Timer
from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER  # type: ignore
from pimoroni import Button  # type: ignore
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
BLACK = PICO_GRAPHICS.create_pen(0, 0, 0)
GRAY = PICO_GRAPHICS.create_pen(180, 180, 180)
WHITE = PICO_GRAPHICS.create_pen(255, 255, 255)
GREEN = PICO_GRAPHICS.create_pen(0, 255, 0)


def _status(text: str, subtext: str = "") -> None:
    global BLACK, GRAY, WHITE, PICO_GRAPHICS
    # Keep this independent from any particular view geometry.
    PICO_GRAPHICS.set_font(config.FONT)
    w, h = PICO_GRAPHICS.get_bounds()

    PICO_GRAPHICS.set_pen(BLACK)
    PICO_GRAPHICS.clear()

    PICO_GRAPHICS.set_pen(WHITE)
    tw = PICO_GRAPHICS.measure_text(text, scale=config.TEXT_SCALE)
    PICO_GRAPHICS.text(
        text,
        (w - tw) // 2,
        (h // 2) - (config.FONT_HEIGHT * config.TEXT_SCALE),
        scale=config.TEXT_SCALE,
    )

    if subtext:
        PICO_GRAPHICS.set_pen(GRAY)
        sw = PICO_GRAPHICS.measure_text(subtext, scale=config.TEXT_SCALE)
        PICO_GRAPHICS.text(subtext, (w - sw) // 2, (h // 2) + 5, scale=config.TEXT_SCALE)

    PICO_GRAPHICS.update()


TIMER_DISPLAY = timer.Display(
    renderer=timer.Renderer(
        geometry=timer.Geometry(
            pico_graphics=PICO_GRAPHICS,
            font=config.FONT,
            font_height=config.FONT_HEIGHT,
            text_scale=config.TEXT_SCALE,
        ),
        colors=timer.Colors(
            background=BLACK,
            ring=GREEN,
            primary_text=WHITE,
            secondary_text=GRAY,
        ),
    )
)

SENSORS_DISPLAY = sensors.Display(
    renderer=sensors.Renderer(
        geometry=sensors.Geometry(
            pico_graphics=PICO_GRAPHICS,
            font=config.FONT,
            font_height=config.FONT_HEIGHT,
            text_scale=config.TEXT_SCALE,
        ),
        colors=sensors.Colors(
            background=BLACK,
            header_text=WHITE,
            value_text=GREEN,
            secondary_text=GRAY,
        ),
    ),
    bme690_reader=bme690.BME690Reader(
        temp_offset=config.BME690_TEMP_OFFSET,
        hum_offset=config.BME690_HUM_OFFSET,
    ),
    sensor_read_delay_ms=config.SENSOR_READ_DELAY_MS,
    time_zone_offset=config.TIME_ZONE_OFFSET,
)

current_display_idx = 0
def _cycle_display() -> None:
    global current_display_idx
    if current_display_idx == 0:
        SENSORS_DISPLAY.deinitialize()
        TIMER_DISPLAY.initialize(
            eventfactory.work_week_loop(
                work_days={0, 1, 2, 3, 4},
                work_start_utc=(8, 0),
                work_end_utc=(17, 0),
            )
        )
        current_display_idx = 1
    else:
        TIMER_DISPLAY.deinitialize()
        SENSORS_DISPLAY.initialize()
        current_display_idx = 0


# BUTTON_A = Button(12)
# BUTTON_B = Button(13)
BUTTON_X = Button(14)
BUTTON_Y = Button(15)


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

SENSORS_DISPLAY.initialize()

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
    button_x_state = BUTTON_X.read()
    button_y_state = BUTTON_Y.read()
    if button_x_state or button_y_state:
        _cycle_display()
