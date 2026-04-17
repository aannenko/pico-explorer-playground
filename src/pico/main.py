import machine
import micropython

from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER  # type: ignore

try:
    import config  # noqa: F401
except ImportError as exc:
    raise RuntimeError(
        "Missing required module: config; please create a config.py with your WiFi credentials."
    ) from exc

from app import build_app


PICO_GRAPHICS = PicoGraphics(display=DISPLAY_PICO_EXPLORER)
APP = build_app(PICO_GRAPHICS, micropython.schedule)
APP.tick_scheduler.start()

while True:
    machine.idle()
    APP.button_poller.poll_once()

