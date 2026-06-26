import machine
import micropython

from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER, PEN_P4  # type: ignore

# Merge config_defaults + user config into ``sys.modules['config']`` before
# any consumer does ``import config``.
import config_bootstrap  # noqa: E402

config_bootstrap.apply_overrides()

import config  # noqa: F401, E402

# Create the framebuffer before importing the app graph so it allocates while
# the heap is still unfragmented (the GC is non-compacting).
PICO_GRAPHICS = PicoGraphics(display=DISPLAY_PICO_EXPLORER, pen_type=PEN_P4)

# Program the shared 16-colour language into the framebuffer's pen table once,
# before any view renders.  All pens downstream are slot indices 0-15.
from displays.palette import program_palette  # noqa: E402

program_palette(PICO_GRAPHICS)

from app import build_app  # noqa: E402

APP = build_app(PICO_GRAPHICS, micropython.schedule)
APP.tick_scheduler.start()

while True:
    machine.idle()
    APP.button_poller.poll_once()

