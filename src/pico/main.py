import gc
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

# Create the framebuffer before importing the app graph so it allocates while
# the heap is still unfragmented (the GC is non-compacting).
PICO_GRAPHICS = PicoGraphics(display=DISPLAY_PICO_EXPLORER, pen_type=PEN_P4)

# Before anything renders.
from displays.palette import program_palette  # noqa: E402

program_palette(PICO_GRAPHICS)

# Like the framebuffer, and for the same reason: the native code of these views, ring's geometry and the Sensors
# graph, takes the largest blocks the app graph allocates, and compiling it last could leave no free run that big.
import displays.ring  # noqa: F401, E402
import displays.sensors  # noqa: F401, E402

from app import build_app  # noqa: E402
from utilities.log import log_memory  # noqa: E402

APP = build_app(PICO_GRAPHICS, micropython.schedule)

gc.collect()
log_memory("[boot] memory after the first frame:")

APP.tick_scheduler.start()

# time.sleep_ms() allows scheduled callbacks to run while it waits.
# machine.idle() could be used instead, but it would wake the CPU too frequently.
_DISPATCH_INTERVAL_MS = const(10)
while True:
    time.sleep_ms(_DISPATCH_INTERVAL_MS)
    APP.button_dispatcher.dispatch_pending()

