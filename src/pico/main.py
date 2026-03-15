import machine

from displays import sensors, timer
from displays.manager import DisplayManager
from displays.status import StatusDisplay
from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER  # type: ignore
from pimoroni import Button  # type: ignore
from scheduling import eventfactory
from sensors import bme690
from utilities.network_service import NetworkService

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

STATUS_DISPLAY = StatusDisplay(
    pico_graphics=PICO_GRAPHICS,
    font=config.FONT,
    font_height=config.FONT_HEIGHT,
    text_scale=config.TEXT_SCALE,
    background=BLACK,
    foreground=WHITE,
    subtext_color=GRAY,
)

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
        sensor_read_delay_ms=config.SENSOR_READ_DELAY_MS,
    ),
    time_zone_offset=config.TIME_ZONE_OFFSET,
)

DISPLAY_MANAGER = DisplayManager(
    displays=[SENSORS_DISPLAY, TIMER_DISPLAY],
    initializers=[
        lambda: (),
        lambda: (
            eventfactory.work_week_loop(
                work_days={0, 1, 2, 3, 4},
                work_start_utc=(8, 0),
                work_end_utc=(17, 0),
            ),
        ),
    ],
)

# BUTTON_A = Button(12)
# BUTTON_B = Button(13)
BUTTON_X = Button(14)
BUTTON_Y = Button(15)

NETWORK_SERVICE = NetworkService(
    ssid=config.WIFI_SSID,
    password=config.WIFI_PASSWORD,
    time_zone_offset=config.TIME_ZONE_OFFSET,
    status_fn=STATUS_DISPLAY.show,
)


# Main logic
NETWORK_SERVICE.connect_and_sync_initial()

TWELVE_HOURS_IN_MS = const(12 * 60 * 60 * 1000)
NETWORK_SERVICE.start_periodic_sync(TWELVE_HOURS_IN_MS)

DISPLAY_MANAGER.initialize_current()

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
        DISPLAY_MANAGER.cycle()
