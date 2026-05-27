import gc
import machine
import micropython

from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER, PEN_RGB332  # type: ignore

# Ensure config.py exists and carries every key declared in config.sample.py
# *before* importing config — the import depends on attribute access against
# names that may have been added since the user's last sync.
import config_bootstrap  # noqa: E402

_config_state = config_bootstrap.ensure_config()
if _config_state == config_bootstrap.CONFIG_CREATED:
    raise RuntimeError(
        "config.py was missing — created one from config.sample.py. "
        "Edit it (especially WIFI_SSID / WIFI_PASSWORD) and reboot."
    )
if _config_state == config_bootstrap.CONFIG_PATCHED:
    print("config: appended missing keys from config.sample.py")

import config  # noqa: F401, E402

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

