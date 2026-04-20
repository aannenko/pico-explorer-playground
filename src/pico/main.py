import gc
import machine
import micropython

from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER, PEN_RGB332  # type: ignore

try:
    import config  # noqa: F401
except ImportError as exc:
    raise RuntimeError(
        "Missing required module: config; please create a config.py with your WiFi credentials."
    ) from exc

# Create the framebuffer and load the shared sprite sheet while the heap is
# still clean — MicroPython's GC is non-compacting, so importing the full
# `app` module graph first would fragment the heap and break the 16 KiB
# contiguous allocation load_spritesheet needs.
PICO_GRAPHICS = PicoGraphics(display=DISPLAY_PICO_EXPLORER, pen_type=PEN_RGB332)

from displays.shared import icons_symbols  # noqa: E402

icons_symbols.load(PICO_GRAPHICS)

from app import build_app  # noqa: E402

APP = build_app(PICO_GRAPHICS, micropython.schedule)
APP.tick_scheduler.start()

while True:
    machine.idle()
    APP.button_poller.poll_once()

