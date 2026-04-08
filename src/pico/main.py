import machine
import micropython

from displays import sensors, events, countdown
from displays.manager import DisplayManager
from displays.status import StatusDisplay
from machine import Pin
from micropython import const
from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER  # type: ignore
from scheduling import event_factory
from services.sensors.pimoroni_bme690 import PimoroniBME690
from services.countdown_timer import CountdownTimer
from services.event_service import EventService
from services.button_poller import ButtonPoller
from services.utilities.explorer_buzzer import ExplorerBuzzer
from services.network_service import NetworkService
from utilities.tick_scheduler import TickScheduler

try:
    import config
except ImportError as exc:
    raise RuntimeError(
        "Missing required module: config; please create a config.py with your WiFi credentials."
    ) from exc


# Setup
PICO_GRAPHICS = PicoGraphics(display=DISPLAY_PICO_EXPLORER)
BLACK = PICO_GRAPHICS.create_pen(0, 0, 0)
GRAY = PICO_GRAPHICS.create_pen(180, 180, 180)
WHITE = PICO_GRAPHICS.create_pen(255, 255, 255)
GREEN = PICO_GRAPHICS.create_pen(0, 255, 0)
ORANGE = PICO_GRAPHICS.create_pen(255, 165, 0)

STATUS_DISPLAY = StatusDisplay(
    pico_graphics=PICO_GRAPHICS,
    font=config.FONT,
    font_height=config.FONT_HEIGHT,
    text_scale=config.TEXT_SCALE,
    background=BLACK,
    foreground=WHITE,
    subtext_color=GRAY,
)

TICK_SCHEDULER = TickScheduler()

BUZZER = ExplorerBuzzer()

COUNTDOWN_TIMER = CountdownTimer(
    on_done=BUZZER.play_alert,
    on_configure=BUZZER.stop_alert,
    tick_scheduler=TICK_SCHEDULER,
)

COUNTDOWN_DISPLAY = countdown.Display(
    renderer=events.Renderer(
        geometry=events.Geometry(
            pico_graphics=PICO_GRAPHICS,
            font=config.FONT,
            font_height=config.FONT_HEIGHT,
            text_scale=config.TEXT_SCALE,
        ),
        colors=events.Colors(
            background=BLACK,
            ring=ORANGE,
            primary_text=WHITE,
            secondary_text=GRAY,
        ),
    ),
    countdown_timer=COUNTDOWN_TIMER,
    tick_scheduler=TICK_SCHEDULER,
)

BME690_READER = PimoroniBME690(
    temp_offset=config.BME690_TEMP_OFFSET,
    hum_offset=config.BME690_HUM_OFFSET,
    sensor_read_delay_ms=config.SENSOR_READ_DELAY_MS,
    tick_scheduler=TICK_SCHEDULER,
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
    bme690_reader=BME690_READER,
    time_zone_offset=config.TIME_ZONE_OFFSET,
    tick_scheduler=TICK_SCHEDULER,
)

BUTTON_A = Pin(12, Pin.IN, Pin.PULL_UP)
BUTTON_B = Pin(13, Pin.IN, Pin.PULL_UP)
BUTTON_X = Pin(14, Pin.IN, Pin.PULL_UP)
BUTTON_Y = Pin(15, Pin.IN, Pin.PULL_UP)

NETWORK_SERVICE = NetworkService(
    ssid=config.WIFI_SSID,
    password=config.WIFI_PASSWORD,
    time_zone_offset=config.TIME_ZONE_OFFSET,
    status_fn=STATUS_DISPLAY.show,
    sync_interval_ms=const(12 * 60 * 60 * 1000),
    tick_scheduler=TICK_SCHEDULER,
)


# Main logic
NETWORK_SERVICE.connect_and_sync_initial()

# EventService must be created after NTP sync for correct timestamps
EVENT_SERVICE = EventService(
    events_iter=event_factory.work_week_loop(
        work_days={0, 1, 2, 3, 4},
        work_start_utc=(8, 0),
        work_end_utc=(17, 0),
    ),
    tick_scheduler=TICK_SCHEDULER,
)

EVENTS_DISPLAY = events.Display(
    renderer=events.Renderer(
        geometry=events.Geometry(
            pico_graphics=PICO_GRAPHICS,
            font=config.FONT,
            font_height=config.FONT_HEIGHT,
            text_scale=config.TEXT_SCALE,
        ),
        colors=events.Colors(
            background=BLACK,
            ring=GREEN,
            primary_text=WHITE,
            secondary_text=GRAY,
        ),
    ),
    event_service=EVENT_SERVICE,
    tick_scheduler=TICK_SCHEDULER,
)

DISPLAY_MANAGER = DisplayManager(
    displays=[SENSORS_DISPLAY, EVENTS_DISPLAY, COUNTDOWN_DISPLAY],
)

DISPLAY_MANAGER.initialize_current()
TICK_SCHEDULER.start()

BUTTON_POLLER = ButtonPoller(schedule=micropython.schedule)
BUTTON_POLLER.add(BUTTON_A, DISPLAY_MANAGER.on_button_a_ref)
BUTTON_POLLER.add(BUTTON_B, DISPLAY_MANAGER.on_button_b_ref)
BUTTON_POLLER.add(BUTTON_X, DISPLAY_MANAGER.previous_ref)
BUTTON_POLLER.add(BUTTON_Y, DISPLAY_MANAGER.next_ref)

while True:
    machine.idle()
    BUTTON_POLLER.poll_once()
