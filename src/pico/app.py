"""Composition root: builds and wires the app's services and displays."""

from micropython import const
from machine import Pin
from picographics import PicoGraphics  # type: ignore

import config
from displays import calendar, countdown, ring, sensors
from displays.manager import DisplayManager
from displays.palette import (
    BLACK,
    GRAY,
    ORANGE,
    STREAM_BLUE,
    STREAM_BROWN,
    STREAM_GREEN,
    STREAM_PINK,
    STREAM_SKY,
    WHITE,
)
from displays.shared import _icons_data
from displays.status import StatusDisplay
from hardware.explorer import (
    BUTTON_A_PIN,
    BUTTON_B_PIN,
    BUTTON_X_PIN,
    BUTTON_Y_PIN,
)
from scheduling.providers import waste
from services.button_dispatcher import ButtonDispatcher
from services.countdown_timer import CountdownTimer
from services.explorer_buzzer import ExplorerBuzzer
from services.http_client import HttpClient
from services.network_service import NetworkService
from services.network_upkeep import NetworkUpkeep
from services.openmeteo_service import OpenMeteoService
from services.pimoroni_bme690 import PimoroniBME690
from services.sample_history import SampleHistory
from services.tick_scheduler import TickScheduler
from services.time_service import TimeService
from services.wifi_client import WifiClient


_SEC_PER_HOUR = const(3600)

_SECONDARY_TEXT_SCALE = const(2)

# Also how often ntptime queries pool.ntp.org, whose guidelines suggest at most 4-5 queries an hour.
_NETWORK_UPKEEP_PERIOD_MS = const(4 * 60 * 60 * 1000)

_STREAM_REFRESH_MS = const(60 * 60 * 1000)

_STREAM_FORECAST_HOURS = calendar.HORIZON_SEC // _SEC_PER_HOUR
# So a warning already in progress shows when it began, if that was within a day.
_STREAM_PAST_HOURS = const(24)


_SENSOR_BANDS_KEYS = (
    "SENSOR_TEMP_BANDS",
    "SENSOR_PRESSURE_BANDS",
    "SENSOR_HUMIDITY_BANDS",
    "SENSOR_GAS_BANDS",
)


def _validate_sensor_bands_or_halt(status_display: StatusDisplay) -> None:
    """Halt unless each ``SENSOR_*_BANDS`` holds 3 strictly ascending edges.

    The config loader validates only their structure, not order or uniqueness.
    Halting shows the error on ``status_display`` and raises ``SystemExit``,
    even for a scalar or edges of mixed types.
    """
    for name in _SENSOR_BANDS_KEYS:
        bands = getattr(config, name, None)
        try:
            ok = (
                bands is not None
                and len(bands) == 3
                and list(bands) == sorted(bands)
                and len(set(bands)) == 3
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
        button_dispatcher: ButtonDispatcher,
        network_service: NetworkService,
        network_upkeep: NetworkUpkeep,
    ) -> None:
        self.display_manager = display_manager
        self.tick_scheduler = tick_scheduler
        self.button_dispatcher = button_dispatcher
        self.network_service = network_service
        self.network_upkeep = network_upkeep


def _build_countdown_display(pico_graphics: PicoGraphics, tick_scheduler: TickScheduler) -> countdown.Display:
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
    pico_graphics: PicoGraphics,
    tick_scheduler: TickScheduler,
    bme690_reader: PimoroniBME690,
    time_service: TimeService,
) -> sensors.Display:
    geometry = sensors.Geometry(
        pico_graphics=pico_graphics,
        font=config.FONT,
        font_height=config.FONT_HEIGHT_PX,
        value_text_scale=config.TEXT_SCALE,
        label_text_scale=_SECONDARY_TEXT_SCALE,
        tick_period_ms=tick_scheduler.tick_period_ms,
    )
    history = SampleHistory(
        lambda: sensors.encode_reading(bme690_reader.read()),
        metric_count=len(_SENSOR_BANDS_KEYS),
        capacity=geometry.graph_columns,
        ticks_per_commit=geometry.ticks_per_commit,
    )
    tick_scheduler.register(history.tick)
    return sensors.Display(
        geometry=geometry,
        get_reading=bme690_reader.read,
        get_local_time=time_service.now,
        history=history,
        band_edges=tuple(getattr(config, name) for name in _SENSOR_BANDS_KEYS),
    )


def _calendar_stream_types() -> tuple[tuple[tuple[int, int, bytes], int], ...]:
    """Return the glyph and field colour index of each of the calendar's streams, in their order: waste, then the
    Open-Meteo service's precipitation, UV, AQI and a stream per pollen species."""
    return (
        (_icons_data.GLYPH_WASTE, STREAM_BROWN),
        (_icons_data.GLYPH_PRECIP, STREAM_BLUE),
        (_icons_data.GLYPH_SUN, STREAM_PINK),
        (_icons_data.GLYPH_AIR, STREAM_SKY),
    ) + ((_icons_data.GLYPH_FLOWER, STREAM_GREEN),) * len(config.POLLEN_THRESHOLDS)


def _build_calendar_geometry(pico_graphics: PicoGraphics) -> calendar.Geometry:
    return calendar.Geometry(
        pico_graphics=pico_graphics,
        font=config.FONT,
        font_height=config.FONT_HEIGHT_PX,
        header_text_scale=config.TEXT_SCALE,
        label_text_scale=_SECONDARY_TEXT_SCALE,
        glyph_width=max(glyph[0] for glyph, _ in _calendar_stream_types()),
    )


def _stream_event_cap(geometry: calendar.Geometry) -> int:
    """Return how many events a network stream keeps: as many as the calendar can show of one stream, to save heap.

    Once one of them ends, its slot can stay empty until the next refresh brings a later event.
    """
    return geometry.slot_count


def _build_calendar_display(
    geometry: calendar.Geometry,
    time_service: TimeService,
    meteo_streams: list,  # list[(int) -> list[Event]]
    get_refresh_failed,  # () -> bool
) -> calendar.Display:
    """Build the calendar of the waste stream and ``meteo_streams``, the Open-Meteo service's streams in its order."""
    types = _calendar_stream_types()
    glyph, color_index = types[0]
    # The waste stream first, so its events come before warnings that start with them.
    streams = [
        (
            glyph,
            color_index,
            waste.build_stream(time_service, config.WASTE_SCHEDULE, calendar.HORIZON_SEC, geometry.slot_count),
        )
    ]
    for i in range(len(meteo_streams)):
        glyph, color_index = types[i + 1]
        streams.append((glyph, color_index, meteo_streams[i]))
    return calendar.Display(
        geometry=geometry,
        streams=streams,
        get_utc_time=time_service.utc_now,
        to_local=time_service.to_local,
        get_refresh_failed=get_refresh_failed,
    )


def build_app(pico_graphics: PicoGraphics, schedule) -> App:  # schedule: (callback, arg) -> None
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
    time_service = TimeService(
        tz_offset_hours=config.TIME_ZONE_OFFSET_HOURS,
        dst_start_rule=config.DST_START_RULE,
        dst_end_rule=config.DST_END_RULE,
        dst_offset_hours=config.DST_OFFSET_HOURS,
    )

    # Capture the first sensor sample, and check the Sensors layout, before the network boot.
    bme690_reader = PimoroniBME690(
        temp_offset_c=config.BME690_TEMP_OFFSET_C,
        hum_offset_pct=config.BME690_HUM_OFFSET_PCT,
        prsr_offset_hpa=config.BME690_PRSR_OFFSET_HPA,
        read_period_ms=config.BME690_READ_PERIOD_MS,
    )
    sensors_display = _build_sensors_display(pico_graphics, tick_scheduler, bme690_reader, time_service)

    wifi_client = WifiClient()
    network_service = NetworkService(
        ssid=config.WIFI_SSID,
        password=config.WIFI_PASSWORD,
        wifi=wifi_client,
    )
    network_service.connect_initial(on_progress=status_display.show)

    time_service.sync_initial(on_progress=status_display.show)
    del status_display

    network_upkeep = NetworkUpkeep(
        wifi=wifi_client,
        start_reconnect=network_service.start_reconnect,
        sync_clock=time_service.sync,
        period_ms=_NETWORK_UPKEEP_PERIOD_MS,
        tick_scheduler=tick_scheduler,
    )

    http_client = HttpClient(wifi_client, config.HTTP_TIMEOUT_SEC)
    calendar_geometry = _build_calendar_geometry(pico_graphics)
    stream_event_cap = _stream_event_cap(calendar_geometry)
    openmeteo_service = OpenMeteoService(
        latitude=config.LATITUDE,
        longitude=config.LONGITUDE,
        prob_threshold_pct=config.PRECIP_PROB_THRESHOLD_PCT,
        uv_thresholds=config.UV_THRESHOLDS,
        aqi_thresholds=config.AQI_THRESHOLDS,
        pollen_thresholds=config.POLLEN_THRESHOLDS,
        http_client=http_client,
        interval_ms=_STREAM_REFRESH_MS,
        forecast_hours=_STREAM_FORECAST_HOURS,
        past_hours=_STREAM_PAST_HOURS,
        max_events=stream_event_cap,
        tick_scheduler=tick_scheduler,
    )

    countdown_display = _build_countdown_display(pico_graphics, tick_scheduler)
    # Warnings tie in this order: precipitation, UV, AQI, then each pollen species as configured.
    calendar_display = _build_calendar_display(
        calendar_geometry, time_service, openmeteo_service.build_streams(), openmeteo_service.refresh_failed
    )

    display_manager = DisplayManager(
        displays=[sensors_display, countdown_display, calendar_display],
        tick_period_ms=tick_scheduler.tick_period_ms,
    )
    display_manager.initialize_current()
    tick_scheduler.register(display_manager.tick)

    button_dispatcher = ButtonDispatcher(schedule=schedule)
    button_dispatcher.add(Pin(BUTTON_A_PIN, Pin.IN, Pin.PULL_UP), display_manager.on_button_a_ref)
    button_dispatcher.add(Pin(BUTTON_B_PIN, Pin.IN, Pin.PULL_UP), display_manager.on_button_b_ref)
    button_dispatcher.add(Pin(BUTTON_X_PIN, Pin.IN, Pin.PULL_UP), display_manager.previous_ref)
    button_dispatcher.add(Pin(BUTTON_Y_PIN, Pin.IN, Pin.PULL_UP), display_manager.next_ref)

    return App(
        display_manager=display_manager,
        tick_scheduler=tick_scheduler,
        button_dispatcher=button_dispatcher,
        network_service=network_service,
        network_upkeep=network_upkeep,
    )
