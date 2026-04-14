import machine
import micropython

from displays import sensors, ring, countdown, calendar
from displays.manager import DisplayManager
from displays.status import StatusDisplay
from machine import Pin
from micropython import const
from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER  # type: ignore
from scheduling import event_factory
from scheduling.event_window import EventWindow
from services.pimoroni_bme690 import PimoroniBME690
from services.countdown_timer import CountdownTimer
from services.button_poller import ButtonPoller
from services.explorer_buzzer import ExplorerBuzzer
from services.network_service import NetworkService
from services.tick_scheduler import TickScheduler
from services.time_service import TimeService

try:
    import config
except ImportError as exc:
    raise RuntimeError(
        "Missing required module: config; please create a config.py with your WiFi credentials."
    ) from exc


# Setup
PICO_GRAPHICS = PicoGraphics(display=DISPLAY_PICO_EXPLORER)
BLACK = PICO_GRAPHICS.create_pen(0, 0, 0)
GRAY = PICO_GRAPHICS.create_pen(190, 190, 190)
WHITE = PICO_GRAPHICS.create_pen(255, 255, 255)
GREEN = PICO_GRAPHICS.create_pen(0, 255, 0)
ORANGE = PICO_GRAPHICS.create_pen(255, 165, 0)

DARK_GRAY = PICO_GRAPHICS.create_pen(40, 40, 40)

_STREAM_0_A = PICO_GRAPHICS.create_pen(*calendar.STREAM_COLORS[0][0])
_STREAM_0_B = PICO_GRAPHICS.create_pen(*calendar.STREAM_COLORS[0][1])
_STREAM_1_A = PICO_GRAPHICS.create_pen(*calendar.STREAM_COLORS[1][0])
_STREAM_1_B = PICO_GRAPHICS.create_pen(*calendar.STREAM_COLORS[1][1])
_STREAM_2_A = PICO_GRAPHICS.create_pen(*calendar.STREAM_COLORS[2][0])
_STREAM_2_B = PICO_GRAPHICS.create_pen(*calendar.STREAM_COLORS[2][1])
_STREAM_3_A = PICO_GRAPHICS.create_pen(*calendar.STREAM_COLORS[3][0])
_STREAM_3_B = PICO_GRAPHICS.create_pen(*calendar.STREAM_COLORS[3][1])
_STREAM_4_A = PICO_GRAPHICS.create_pen(*calendar.STREAM_COLORS[4][0])
_STREAM_4_B = PICO_GRAPHICS.create_pen(*calendar.STREAM_COLORS[4][1])

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
    renderer=ring.Renderer(
        geometry=ring.Geometry(
            pico_graphics=PICO_GRAPHICS,
            font=config.FONT,
            font_height=config.FONT_HEIGHT,
            text_scale=config.TEXT_SCALE,
        ),
        colors=ring.Colors(
            background=BLACK,
            ring=ORANGE,
            primary_text=WHITE,
            secondary_text=GRAY,
        ),
    ),
    countdown_timer=COUNTDOWN_TIMER,
)

BME690_READER = PimoroniBME690(
    temp_offset=config.BME690_TEMP_OFFSET,
    hum_offset=config.BME690_HUM_OFFSET,
    sensor_read_delay_ms=config.SENSOR_READ_DELAY_MS,
    tick_scheduler=TICK_SCHEDULER,
)

BUTTON_A = Pin(12, Pin.IN, Pin.PULL_UP)
BUTTON_B = Pin(13, Pin.IN, Pin.PULL_UP)
BUTTON_X = Pin(14, Pin.IN, Pin.PULL_UP)
BUTTON_Y = Pin(15, Pin.IN, Pin.PULL_UP)

NETWORK_SERVICE = NetworkService(
    ssid=config.WIFI_SSID,
    password=config.WIFI_PASSWORD,
    status_fn=STATUS_DISPLAY.show,
    sync_interval_ms=const(12 * 60 * 60 * 1000),
    tick_scheduler=TICK_SCHEDULER,
)


# Main logic
NETWORK_SERVICE.connect_and_sync_initial()

# TimeService must be created after NTP sync for accurate time.time()
TIME_SERVICE = TimeService(
    tz_offset=config.TIME_ZONE_OFFSET,
    dst_start=config.DST_START,
    dst_end=config.DST_END,
    dst_offset=config.DST_OFFSET,
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
    time_service=TIME_SERVICE,
)

CALENDAR_STREAM = EventWindow(
    events_iter=event_factory.work_week_loop(
        work_days={0, 1, 2, 3, 4},
        work_start=(9, 0),
        work_end=(18, 0),
        time_service=TIME_SERVICE,
    ),
    color_a=_STREAM_0_A,
    color_b=_STREAM_0_B,
)

WEATHER_STREAM = EventWindow(
    events_iter=event_factory.random_weather_loop(
        start_timestamp=TIME_SERVICE.now() - 30 * 60,
        time_service=TIME_SERVICE,
    ),
    color_a=_STREAM_1_A,
    color_b=_STREAM_1_B,
)

_STREAM_START = TIME_SERVICE.now() - 30 * 60

TASKS_STREAM = EventWindow(
    events_iter=event_factory.random_event_loop(
        names=("code", "review", "deploy", "test", "debug"),
        durations=(15 * 60, 30 * 60, 45 * 60, 60 * 60),
        gap_chance=15,
        start_timestamp=_STREAM_START,
        time_service=TIME_SERVICE,
    ),
    color_a=_STREAM_2_A,
    color_b=_STREAM_2_B,
)

COMMS_STREAM = EventWindow(
    events_iter=event_factory.random_event_loop(
        names=("call", "standup", "retro", "chat"),
        durations=(15 * 60, 30 * 60, 60 * 60),
        gap_chance=40,
        start_timestamp=_STREAM_START,
        time_service=TIME_SERVICE,
    ),
    color_a=_STREAM_3_A,
    color_b=_STREAM_3_B,
)

FITNESS_STREAM = EventWindow(
    events_iter=event_factory.random_event_loop(
        names=("run", "walk", "gym", "yoga", "rest"),
        durations=(20 * 60, 30 * 60, 45 * 60, 60 * 60, 90 * 60),
        gap_chance=25,
        start_timestamp=_STREAM_START,
        time_service=TIME_SERVICE,
    ),
    color_a=_STREAM_4_A,
    color_b=_STREAM_4_B,
)

CALENDAR_DISPLAY = calendar.Display(
    renderer=calendar.Renderer(
        geometry=calendar.Geometry(
            pico_graphics=PICO_GRAPHICS,
            header_font=config.FONT,
            header_font_height=config.FONT_HEIGHT,
            header_text_scale=config.TEXT_SCALE,
            bar_font=config.FONT,
            bar_font_height=config.FONT_HEIGHT,
            bar_text_scale=const(2),
        ),
        colors=calendar.Colors(
            background=BLACK,
            header_text=WHITE,
            axis_text=WHITE,
            empty_row=DARK_GRAY,
            now_line=WHITE,
        ),
    ),
    streams=[CALENDAR_STREAM, WEATHER_STREAM, TASKS_STREAM, COMMS_STREAM, FITNESS_STREAM],
    get_time=TIME_SERVICE.now,
)

DISPLAY_MANAGER = DisplayManager(
    displays=[SENSORS_DISPLAY, COUNTDOWN_DISPLAY, CALENDAR_DISPLAY],
)

DISPLAY_MANAGER.initialize_current()
TICK_SCHEDULER.register(DISPLAY_MANAGER.tick)
TICK_SCHEDULER.start()

BUTTON_POLLER = ButtonPoller(schedule=micropython.schedule)
BUTTON_POLLER.add(BUTTON_A, DISPLAY_MANAGER.on_button_a_ref)
BUTTON_POLLER.add(BUTTON_B, DISPLAY_MANAGER.on_button_b_ref)
BUTTON_POLLER.add(BUTTON_X, DISPLAY_MANAGER.previous_ref)
BUTTON_POLLER.add(BUTTON_Y, DISPLAY_MANAGER.next_ref)

while True:
    machine.idle()
    BUTTON_POLLER.poll_once()
