"""Application composition: wire services, displays, and schedulers.

``build_app`` returns the long-lived objects ``main.py`` needs to start
and drive the app.  Splitting composition out of ``main.py`` keeps the
entry point minimal and makes the wiring testable on the host.
"""

from micropython import const
from machine import Pin

import config
import demo_streams
from displays import calendar, countdown, ring, sensors
from displays.manager import DisplayManager
from displays.palette import Palette, build_palette
from displays.status import StatusDisplay
from scheduling.event_window import EventWindow
from scheduling.stream import Stream
from services.button_poller import ButtonPoller
from services.countdown_timer import CountdownTimer
from services.explorer_buzzer import ExplorerBuzzer
from services.network_service import NetworkService
from services.pimoroni_bme690 import PimoroniBME690
from services.tick_scheduler import TickScheduler
from services.time_service import TimeService


_NET_SYNC_INTERVAL_MS = const(12 * 60 * 60 * 1000)
_BUTTON_A_PIN = const(12)
_BUTTON_B_PIN = const(13)
_BUTTON_X_PIN = const(14)
_BUTTON_Y_PIN = const(15)


class App:
    def __init__(
        self,
        display_manager: DisplayManager,
        tick_scheduler: TickScheduler,
        button_poller: ButtonPoller,
        network_service: NetworkService,
    ) -> None:
        self.display_manager = display_manager
        self.tick_scheduler = tick_scheduler
        self.button_poller = button_poller
        self.network_service = network_service


def _build_countdown_display(pico_graphics, palette: Palette, tick_scheduler: TickScheduler):
    buzzer = ExplorerBuzzer()
    timer = CountdownTimer(
        on_done=buzzer.play_alert,
        on_configure=buzzer.stop_alert,
        tick_scheduler=tick_scheduler,
    )
    return countdown.Display(
        renderer=ring.Renderer(
            geometry=ring.Geometry(
                pico_graphics=pico_graphics,
                font=config.FONT,
                font_height=config.FONT_HEIGHT,
                text_scale=config.TEXT_SCALE,
            ),
            colors=ring.Colors(
                background=palette.black,
                ring=palette.orange,
                primary_text=palette.white,
                secondary_text=palette.gray,
            ),
        ),
        countdown_timer=timer,
    )


def _build_sensors_display(pico_graphics, palette: Palette, bme690_reader, time_service: TimeService):
    return sensors.Display(
        renderer=sensors.Renderer(
            geometry=sensors.Geometry(
                pico_graphics=pico_graphics,
                font=config.FONT,
                font_height=config.FONT_HEIGHT,
                text_scale=config.TEXT_SCALE,
            ),
            colors=sensors.Colors(
                background=palette.black,
                header_text=palette.white,
                value_text=palette.green,
                secondary_text=palette.gray,
            ),
        ),
        bme690_reader=bme690_reader,
        time_service=time_service,
    )


def _build_calendar_display(pico_graphics, palette: Palette, time_service: TimeService):
    streams: list[Stream] = [demo_streams.build_work_week_stream(time_service)]
    streams.extend(demo_streams.build_demo_streams(time_service))

    windows: list[EventWindow] = []
    for s in streams:
        pen_a = pico_graphics.create_pen(*s.color_a)
        pen_b = pico_graphics.create_pen(*s.color_b)
        windows.append(EventWindow(events_iter=s.events_iter, color_a=pen_a, color_b=pen_b))

    return calendar.Display(
        renderer=calendar.Renderer(
            geometry=calendar.Geometry(
                pico_graphics=pico_graphics,
                header_font=config.FONT,
                header_font_height=config.FONT_HEIGHT,
                header_text_scale=config.TEXT_SCALE,
                bar_font=config.FONT,
                bar_font_height=config.FONT_HEIGHT,
                bar_text_scale=const(2),
            ),
            colors=calendar.Colors(
                background=palette.black,
                header_text=palette.white,
                axis_text=palette.white,
                empty_row=palette.dark_gray,
                now_line=palette.white,
            ),
        ),
        streams=windows,
        get_time=time_service.now,
    )


def build_app(pico_graphics, schedule_fn) -> App:
    """Compose services and displays; return them for ``main.py`` to drive.

    ``schedule_fn`` is ``micropython.schedule`` on-device; tests can pass
    a synchronous substitute.
    """
    palette = build_palette(pico_graphics)

    status_display = StatusDisplay(
        pico_graphics=pico_graphics,
        font=config.FONT,
        font_height=config.FONT_HEIGHT,
        text_scale=config.TEXT_SCALE,
        background=palette.black,
        foreground=palette.white,
        subtext_color=palette.gray,
    )

    tick_scheduler = TickScheduler()

    network_service = NetworkService(
        ssid=config.WIFI_SSID,
        password=config.WIFI_PASSWORD,
        status_fn=status_display.show,
        sync_interval_ms=_NET_SYNC_INTERVAL_MS,
        tick_scheduler=tick_scheduler,
    )
    network_service.connect_and_sync_initial()

    # TimeService must be created after NTP sync for accurate time.time().
    time_service = TimeService(
        tz_offset=config.TIME_ZONE_OFFSET,
        dst_start=config.DST_START,
        dst_end=config.DST_END,
        dst_offset=config.DST_OFFSET,
        tick_scheduler=tick_scheduler,
    )

    bme690_reader = PimoroniBME690(
        temp_offset=config.BME690_TEMP_OFFSET,
        hum_offset=config.BME690_HUM_OFFSET,
        sensor_read_delay_ms=config.SENSOR_READ_DELAY_MS,
        tick_scheduler=tick_scheduler,
    )

    sensors_display = _build_sensors_display(pico_graphics, palette, bme690_reader, time_service)
    countdown_display = _build_countdown_display(pico_graphics, palette, tick_scheduler)
    calendar_display = _build_calendar_display(pico_graphics, palette, time_service)

    display_manager = DisplayManager(
        displays=[sensors_display, countdown_display, calendar_display],
    )
    display_manager.initialize_current()
    tick_scheduler.register(display_manager.tick)

    button_poller = ButtonPoller(schedule=schedule_fn)
    button_poller.add(Pin(_BUTTON_A_PIN, Pin.IN, Pin.PULL_UP), display_manager.on_button_a_ref)
    button_poller.add(Pin(_BUTTON_B_PIN, Pin.IN, Pin.PULL_UP), display_manager.on_button_b_ref)
    button_poller.add(Pin(_BUTTON_X_PIN, Pin.IN, Pin.PULL_UP), display_manager.previous_ref)
    button_poller.add(Pin(_BUTTON_Y_PIN, Pin.IN, Pin.PULL_UP), display_manager.next_ref)

    return App(
        display_manager=display_manager,
        tick_scheduler=tick_scheduler,
        button_poller=button_poller,
        network_service=network_service,
    )
