"""Sample ``config.py`` for the Pico Explorer playground.

Copy this file to ``config.py`` (same directory) and fill in the WiFi
credentials for your network.  ``config.py`` is gitignored so your
secrets stay local; this sample is checked in as a template.
"""

from micropython import const


FONT = "bitmap6"           # default font when no override is set
FONT_HEIGHT = const(6)     # height of bitmap6 glyphs
TEXT_SCALE = const(3)      # default scale for fonts

# WiFi credentials — replace with your own network's SSID and password.
WIFI_SSID = "YourSSID"
WIFI_PASSWORD = "YourPassword"

TIME_ZONE_OFFSET = const(1)  # Prague winter time (UTC+1)

# Daylight Saving Time rules: (month, week, weekday, hour)
# week: -1 = last occurrence; weekday: 0=Mon .. 6=Sun (MicroPython convention)
DST_START = (3, -1, 6, 2)   # Last Sunday of March at 02:00 (standard time)
DST_END = (10, -1, 6, 3)    # Last Sunday of October at 03:00 (DST time)
DST_OFFSET = const(1)       # +1 hour during DST (CEST = UTC+2)

SENSOR_READ_DELAY_MS = const(5_000)  # milliseconds between sensor reads
BME690_TEMP_OFFSET = -1.2  # Temperature offset to apply to BME690 sensor readings
BME690_HUM_OFFSET = 5.0    # Humidity offset to apply to BME690 sensor readings
