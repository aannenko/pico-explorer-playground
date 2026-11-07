"""Composition root: builds and wires the app's services and displays."""

from micropython import const
from machine import Pin

import config
import demo_streams
from displays import calendar, countdown, ring, sensors
from displays.manager import DisplayManager
from displays.palette import (
    BLACK,
    DARK_GRAY,
    GRAY,
    ORANGE,
    STREAM_COLORS,
    WHITE,
)
from displays.status import StatusDisplay
from hardware.explorer import (
    BUTTON_A_PIN,
    BUTTON_B_PIN,
    BUTTON_X_PIN,
    BUTTON_Y_PIN,
)
from scheduling.event_window import EventWindow, build_event_windows
from scheduling.providers import waste, work_week
from scheduling.stream import Stream
from services.fetch_machine import FetchCoordinator
from services.air_service import AirService
from services.button_poller import ButtonPoller
from services.countdown_timer import CountdownTimer
from services.explorer_buzzer import ExplorerBuzzer
from services.network_service import NetworkService
from services.pimoroni_bme690 import PimoroniBME690
from services.ring_history import RingHistory
from services.tick_scheduler import TickScheduler
from services.time_service import TimeService
from services.weather_service import WeatherService
from services.wifi_client import WifiClient


_SEC_PER_HOUR = const(3600)

_NET_SYNC_INTERVAL_MS = const(12 * 60 * 60 * 1000)

_STREAM_REFRESH_MS = const(30 * 60 * 1000)
# Forecast slack beyond the calendar window: covers scroll plus failed retries.
_STREAM_SLACK_REFRESHES = const(2)

# Derived here because app.py is the one place that sees both the calendar's
# future window (owned by displays.calendar) and the fetch cadence above.  The
# extra hour absorbs Open-Meteo's forecast_hours starting at the current hour.
_STREAM_HORIZON_SEC = (
    calendar.WINDOW_FUTURE_SEC
    + _STREAM_SLACK_REFRESHES * (_STREAM_REFRESH_MS // 1000)
    + _SEC_PER_HOUR
)
_STREAM_FORECAST_HOURS = (_STREAM_HORIZON_SEC + _SEC_PER_HOUR - 1) // _SEC_PER_HOUR

# Without past_hours, that start could leave part of the calendar's past window empty.
_STREAM_PAST_HOURS = (calendar.WINDOW_PAST_SEC + _SEC_PER_HOUR - 1) // _SEC_PER_HOUR


_SENSOR_BANDS_KEYS = (
    "SENSOR_TEMP_BANDS",
    "SENSOR_PRESSURE_BANDS",
    "SENSOR_HUMIDITY_BANDS",
    "SENSOR_GAS_BANDS",
)


def _validate_sensor_bands_or_halt(status_display: StatusDisplay) -> None:
    """Halt unless each ``SENSOR_*_BANDS`` holds 5 strictly ascending edges.

    The config loader validates only their structure, not order or uniqueness.
    Halting shows the error on ``status_display`` and raises ``SystemExit``,
    even for a scalar or edges of mixed types.
    """
    for name in _SENSOR_BANDS_KEYS:
        bands = getattr(config, name, None)
        try:
            ok = (
                bands is not None
                and len(bands) == 5
                and list(bands) == sorted(bands)
                and len(set(bands)) == 5
            )
        except (TypeError, ValueError):
            ok = False
        if not ok:
            print("config error:", name, "=", repr(bands))
            status_display.show("Bad config", "edit & reboot")
            raise SystemExit(1)


class App:
    """Handles to the long-lived objects of the composed app."""

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


def _build_countdown_display(pico_graphics, tick_scheduler: TickScheduler):
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
                font_height=config.FONT_HEIGHT_PX,
                text_scale=config.TEXT_SCALE,
            ),
            colors=ring.Colors(
                background=BLACK,
                ring=ORANGE,
                primary_text=WHITE,
                secondary_text=GRAY,
            ),
        ),
        countdown_timer=timer,
    )


def _build_sensors_display(
    bme690_reader,
    time_service: TimeService,
    geometry: sensors.Geometry,
    history: RingHistory,
):
    return sensors.Display(
        renderer=sensors.Renderer(
            geometry=geometry,
            colors=sensors.Colors(
                background=BLACK,
                header_text=WHITE,
                value_text=WHITE,
                secondary_text=GRAY,
            ),
        ),
        bme690_reader=bme690_reader,
        time_service=time_service,
        history=history,
        graph_height=geometry.graph_height,
        temp_bands=config.SENSOR_TEMP_BANDS,
        pressure_bands=config.SENSOR_PRESSURE_BANDS,
        humidity_bands=config.SENSOR_HUMIDITY_BANDS,
        gas_bands=config.SENSOR_GAS_BANDS,
    )


def _build_calendar_display(pico_graphics, time_service: TimeService, network_streams):
    # Calendar lays out 5 rows.
    streams = [
        work_week.build_stream(time_service),
        waste.build_stream(time_service, config.WASTE_SCHEDULE),
    ]
    streams.extend(network_streams)
    streams.extend(
        demo_streams.build_demo_streams(time_service, calendar.WINDOW_PAST_SEC)[: 5 - len(streams)]
    )

    windows = build_event_windows(STREAM_COLORS, streams)

    return calendar.Display(
        renderer=calendar.Renderer(
            geometry=calendar.Geometry(
                pico_graphics=pico_graphics,
                header_font=config.FONT,
                header_font_height=config.FONT_HEIGHT_PX,
                header_text_scale=config.TEXT_SCALE,
                bar_font=config.FONT,
                bar_font_height=config.FONT_HEIGHT_PX,
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
        event_windows=windows,
        get_local_time=time_service.now,
    )


def build_app(pico_graphics, schedule) -> App:  # schedule: (callback, arg) -> None
    """Compose the services and displays.

    Blocks through the initial WiFi connect and NTP sync, raising
    ``RuntimeError`` if either fails.  The returned app's ``tick_scheduler`` is
    not yet started.
    """
    status_display = StatusDisplay(
        pico_graphics=pico_graphics,
        font=config.FONT,
        font_height=config.FONT_HEIGHT_PX,
        text_scale=config.TEXT_SCALE,
        background=BLACK,
        foreground=WHITE,
        subtext_color=GRAY,
    )

    # Fail fast, before the network boot.
    _validate_sensor_bands_or_halt(status_display)

    tick_scheduler = TickScheduler()

    # Capture the first sensor sample before the network boot.
    bme690_reader = PimoroniBME690(
        temp_offset_c=config.BME690_TEMP_OFFSET_C,
        hum_offset_pct=config.BME690_HUM_OFFSET_PCT,
        prsr_offset_hpa=config.BME690_PRSR_OFFSET_HPA,
        read_period_ms=config.BME690_READ_PERIOD_MS,
    )
    sensors_geometry = sensors.Geometry(
        pico_graphics=pico_graphics,
        font=config.FONT,
        font_height=config.FONT_HEIGHT_PX,
        text_scale=config.TEXT_SCALE,
        tick_period_ms=tick_scheduler.tick_period_ms,
    )
    sensor_history = RingHistory(
        bme690_reader.read,
        metric_count=4,
        capacity=sensors_geometry.graph_width,
        ticks_per_commit=sensors_geometry.ticks_per_commit,
    )
    tick_scheduler.register(sensor_history.tick)

    wifi_client = WifiClient()
    network_service = NetworkService(
        ssid=config.WIFI_SSID,
        password=config.WIFI_PASSWORD,
        wifi=wifi_client,
        sync_interval_ms=_NET_SYNC_INTERVAL_MS,
        tick_scheduler=tick_scheduler,
    )
    network_service.connect_and_sync_initial(on_progress=status_display.show)
    del status_display

    time_service = TimeService(
        tz_offset_hours=config.TIME_ZONE_OFFSET_HOURS,
        dst_start_rule=config.DST_START_RULE,
        dst_end_rule=config.DST_END_RULE,
        dst_offset_hours=config.DST_OFFSET_HOURS,
        tick_scheduler=tick_scheduler,
    )

    fetch_coordinator = FetchCoordinator()
    weather_service = WeatherService(
        latitude=config.LATITUDE,
        longitude=config.LONGITUDE,
        prob_threshold_pct=config.PRECIP_PROB_THRESHOLD_PCT,
        uv_thresholds=config.UV_THRESHOLDS,
        wifi=wifi_client,
        coordinator=fetch_coordinator,
        schedule=schedule,
        interval_ms=_STREAM_REFRESH_MS,
        forecast_hours=_STREAM_FORECAST_HOURS,
        past_hours=_STREAM_PAST_HOURS,
        timeout_sec=config.HTTP_TIMEOUT_SEC,
        tick_scheduler=tick_scheduler,
    )
    weather_stream = Stream(
        weather_service.iter_events(),
        events_iter_factory=weather_service.iter_events,
        get_generation=lambda: weather_service.generation,
        get_status=lambda: weather_service.status,
    )

    air_service = AirService(
        latitude=config.LATITUDE,
        longitude=config.LONGITUDE,
        species=config.POLLEN_SPECIES,
        aqi_thresholds=config.AQI_THRESHOLDS,
        pollen_thresholds=config.POLLEN_THRESHOLDS,
        wifi=wifi_client,
        coordinator=fetch_coordinator,
        schedule=schedule,
        interval_ms=_STREAM_REFRESH_MS,
        forecast_hours=_STREAM_FORECAST_HOURS,
        past_hours=_STREAM_PAST_HOURS,
        timeout_sec=config.HTTP_TIMEOUT_SEC,
        tick_scheduler=tick_scheduler,
    )
    air_stream = Stream(
        air_service.iter_events(),
        events_iter_factory=air_service.iter_events,
        get_generation=lambda: air_service.generation,
        get_status=lambda: air_service.status,
    )

    sensors_display = _build_sensors_display(
        bme690_reader,
        time_service,
        sensors_geometry,
        sensor_history,
    )
    countdown_display = _build_countdown_display(pico_graphics, tick_scheduler)
    calendar_display = _build_calendar_display(
        pico_graphics, time_service, [weather_stream, air_stream]
    )

    display_manager = DisplayManager(
        displays=[sensors_display, countdown_display, calendar_display],
        tick_period_ms=tick_scheduler.tick_period_ms,
    )
    display_manager.initialize_current()
    tick_scheduler.register(display_manager.tick)

    button_poller = ButtonPoller(schedule=schedule)
    button_poller.add(Pin(BUTTON_A_PIN, Pin.IN, Pin.PULL_UP), display_manager.on_button_a_ref)
    button_poller.add(Pin(BUTTON_B_PIN, Pin.IN, Pin.PULL_UP), display_manager.on_button_b_ref)
    button_poller.add(Pin(BUTTON_X_PIN, Pin.IN, Pin.PULL_UP), display_manager.previous_ref)
    button_poller.add(Pin(BUTTON_Y_PIN, Pin.IN, Pin.PULL_UP), display_manager.next_ref)

    return App(
        display_manager=display_manager,
        tick_scheduler=tick_scheduler,
        button_poller=button_poller,
        network_service=network_service,
    )
