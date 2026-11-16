import micropython
import time
from micropython import const

from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER, PEN_P4  # type: ignore

# The button IRQs run with the heap locked; without this buffer an exception
# raised there prints without its message.
micropython.alloc_emergency_exception_buf(100)

# Before any consumer does ``import config``.
import config_bootstrap

config_bootstrap.apply_overrides()

import config  # noqa: F401, E402

_DISPATCH_INTERVAL_MS = const(10)

# Create the framebuffer before importing the app graph so it allocates while
# the heap is still unfragmented (the GC is non-compacting).
PICO_GRAPHICS = PicoGraphics(display=DISPLAY_PICO_EXPLORER, pen_type=PEN_P4)

# Before anything renders.
from displays.palette import program_palette  # noqa: E402

program_palette(PICO_GRAPHICS)

from app import build_app  # noqa: E402

APP = build_app(PICO_GRAPHICS, micropython.schedule)
APP.tick_scheduler.start()

# Not machine.idle(): it returns on every interrupt, about 2,500 times a second
# here, far more often than presses need checking. sleep_ms still runs
# scheduled callbacks while it waits.
while True:
    time.sleep_ms(_DISPATCH_INTERVAL_MS)
    APP.button_dispatcher.dispatch_pending()

