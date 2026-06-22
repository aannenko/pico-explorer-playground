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
from displays.palette import (
    Palette,
    STREAM_COLORS,
    build_palette,
    build_sensor_band_pens,
    build_stream_pen_pairs,
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
from services._fetch_machine import FetchCoordinator
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


_NET_SYNC_INTERVAL_MS = const(12 * 60 * 60 * 1000)

# Single source of truth for the weather/air fetch cadence.
_STREAM_REFRESH_MS = const(30 * 60 * 1000)

# How many hours of forecast to request — derived here because app.py is the one
# place that sees both the calendar's future window (owned by displays.calendar)
# and the fetch cadence above.  Smallest horizon that keeps the window populated:
# ceil((future_window + 2*refresh + 1 h) / 1 h) — 2x refresh covers scroll + a
# couple of failed retries, +1 h absorbs the snap to the current hour boundary.
_STREAM_HORIZON_SEC = calendar.WINDOW_FUTURE_SEC + 2 * (_STREAM_REFRESH_MS // 1000) + 3600
_STREAM_FORECAST_HOURS = (_STREAM_HORIZON_SEC + 3599) // 3600

# How many past hours to request so the calendar's past window (left of the
# now-line) stays populated: the API's forecast_hours starts at the current
# hour, so without this the past strip would render blank.  ceil(past / 1 h).
_STREAM_PAST_HOURS = (calendar.WINDOW_PAST_SEC + 3599) // 3600


_SENSOR_BANDS_KEYS = (
    "SENSOR_TEMP_BANDS",
    "SENSOR_PRESSURE_BANDS",
    "SENSOR_HUMIDITY_BANDS",
    "SENSOR_GAS_BANDS",
)


def _validate_sensor_bands_or_halt(status_display: StatusDisplay) -> None:
    """Semantic backstop for ``SENSOR_*_BANDS`` — runs after the loader has
    already enforced *structural* shape (5-tuple of ints) via
    ``config_bootstrap.apply_overrides``.  This check covers what the loader
    intentionally doesn't: strictly ascending order and uniqueness.  Failures
    here are rendered on the panel before the long WiFi/NTP bootstrap, so a
    bad threshold doesn't manifest as a blank or frozen screen later.

    Tolerant of any input shape — wraps the comparisons in try/except so a
    scalar (``SENSOR_TEMP_BANDS = 14``) or non-comparable mixed types surface
    the same panel error instead of an uncaught traceback.
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
            # Full diagnostic to serial; short panel-friendly message on screen.
            print("config error:", name, "=", repr(bands))
            status_display.show("Bad config", "edit & reboot")
            raise SystemExit(1)


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


def _build_sensors_display(
    pico_graphics,
    palette: Palette,
    bme690_reader,
    time_service: TimeService,
    geometry: "sensors.Geometry",
    band_pens,
    history: RingHistory,
):
    """Construct the sensors Display from pre-built parts.

    Geometry, band pens, and history are built earlier in ``build_app`` so
    sensor capture can start before the blocking network sync.  This helper
    just wires the Display object once ``time_service`` (which needs NTP)
    is available.
    """
    return sensors.Display(
        renderer=sensors.Renderer(
            geometry=geometry,
            colors=sensors.Colors(
                background=palette.black,
                header_text=palette.white,
                value_text=palette.white,
                secondary_text=palette.gray,
            ),
        ),
        bme690_reader=bme690_reader,
        time_service=time_service,
        history=history,
        band_pens=band_pens,
        graph_height=geometry.graph_height,
        temp_bands=config.SENSOR_TEMP_BANDS,
        pressure_bands=config.SENSOR_PRESSURE_BANDS,
        humidity_bands=config.SENSOR_HUMIDITY_BANDS,
        gas_bands=config.SENSOR_GAS_BANDS,
    )


def _build_calendar_display(pico_graphics, palette: Palette, time_service: TimeService, network_streams):
    # Calendar lays out 5 rows: local generators, then network streams,
    # then demos fill any remaining slots.
    streams: list[Stream] = [
        work_week.build_stream(time_service),
        waste.build_stream(time_service, config.WASTE_SCHEDULE),
    ]
    streams.extend(network_streams)
    streams.extend(demo_streams.build_demo_streams(time_service)[: 5 - len(streams)])

    stream_palette = build_stream_pen_pairs(pico_graphics, STREAM_COLORS)
    windows: list[EventWindow] = build_event_windows(stream_palette, streams)

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

    # Done while ``status_display`` is still alive so a malformed band shows
    # on the panel rather than during the long network boot that follows.
    _validate_sensor_bands_or_halt(status_display)

    tick_scheduler = TickScheduler()

    # Build sensor + history BEFORE the blocking WiFi+NTP bootstrap so the
    # immediate first RingHistory commit captures a boot-time reading rather
    # than one taken 0–5 minutes later.  TickScheduler isn't running yet
    # (main.py calls .start() after build_app returns), so periodic commits
    # only kick in then.
    bme690_reader = PimoroniBME690(
        temp_offset=config.BME690_TEMP_OFFSET,
        hum_offset=config.BME690_HUM_OFFSET,
        prsr_offset=config.BME690_PRSR_OFFSET,
        sensor_read_delay_ms=config.SENSOR_READ_DELAY_MS,
    )
    sensors_geometry = sensors.Geometry(
        pico_graphics=pico_graphics,
        font=config.FONT,
        font_height=config.FONT_HEIGHT,
        text_scale=config.TEXT_SCALE,
        tick_period_ms=tick_scheduler.ms_per_tick,
    )
    sensors_band_pens = build_sensor_band_pens(pico_graphics)
    sensor_history = RingHistory(
        bme690_reader.read,
        num_metrics=4,
        capacity=sensors_geometry.graph_width,
        ticks_per_commit=sensors_geometry.ticks_per_commit,
    )
    tick_scheduler.register(sensor_history._tick_ref)

    wifi_client = WifiClient()
    network_service = NetworkService(
        ssid=config.WIFI_SSID,
        password=config.WIFI_PASSWORD,
        wifi=wifi_client,
        sync_interval_ms=_NET_SYNC_INTERVAL_MS,
        tick_scheduler=tick_scheduler,
    )
    network_service.connect_and_sync_initial(status_fn=status_display.show)
    # status_display is not retained; it was a boot-time overlay only.
    del status_display

    # TimeService must be created after NTP sync for accurate time.time().
    time_service = TimeService(
        tz_offset=config.TIME_ZONE_OFFSET,
        dst_start=config.DST_START,
        dst_end=config.DST_END,
        dst_offset=config.DST_OFFSET,
        tick_scheduler=tick_scheduler,
    )

    # Network calendar streams: long-lived services sharing one fetch
    # coordinator (single in-flight fetch across all of them).
    fetch_coordinator = FetchCoordinator()
    weather_service = WeatherService(
        latitude=config.LATITUDE,
        longitude=config.LONGITUDE,
        prob_threshold=config.PRECIP_PROB_THRESHOLD,
        uv_thresholds=config.UV_THRESHOLDS,
        wifi=wifi_client,
        coordinator=fetch_coordinator,
        schedule=schedule_fn,
        interval_ms=_STREAM_REFRESH_MS,
        forecast_hours=_STREAM_FORECAST_HOURS,
        past_hours=_STREAM_PAST_HOURS,
        timeout_s=config.HTTP_TIMEOUT_S,
        tick_scheduler=tick_scheduler,
    )
    weather_stream = Stream(
        weather_service.events_iter(),
        events_fn=weather_service.events_iter,
        generation_fn=lambda: weather_service.generation,
        status_fn=lambda: weather_service.status,
    )

    air_service = AirService(
        latitude=config.LATITUDE,
        longitude=config.LONGITUDE,
        species=config.POLLEN_SPECIES,
        aqi_thresholds=config.AQI_THRESHOLDS,
        pollen_thresholds=config.POLLEN_THRESHOLDS,
        wifi=wifi_client,
        coordinator=fetch_coordinator,
        schedule=schedule_fn,
        interval_ms=_STREAM_REFRESH_MS,
        forecast_hours=_STREAM_FORECAST_HOURS,
        past_hours=_STREAM_PAST_HOURS,
        timeout_s=config.HTTP_TIMEOUT_S,
        tick_scheduler=tick_scheduler,
    )
    air_stream = Stream(
        air_service.events_iter(),
        events_fn=air_service.events_iter,
        generation_fn=lambda: air_service.generation,
        status_fn=lambda: air_service.status,
    )

    sensors_display = _build_sensors_display(
        pico_graphics,
        palette,
        bme690_reader,
        time_service,
        sensors_geometry,
        sensors_band_pens,
        sensor_history,
    )
    countdown_display = _build_countdown_display(pico_graphics, palette, tick_scheduler)
    calendar_display = _build_calendar_display(
        pico_graphics, palette, time_service, [weather_stream, air_stream]
    )

    display_manager = DisplayManager(
        displays=[sensors_display, countdown_display, calendar_display],
        scheduler_period_ms=tick_scheduler.ms_per_tick,
    )
    display_manager.initialize_current()
    tick_scheduler.register(display_manager.tick)

    button_poller = ButtonPoller(schedule=schedule_fn)
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
