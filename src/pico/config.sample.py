"""Sample ``config.py`` for the Pico Explorer playground.

Copy this file to ``config.py`` (same directory) and fill in the WiFi
credentials for your network.  ``config.py`` is gitignored so your
secrets stay local; this sample is checked in as a template.
"""

from micropython import const


FONT = "bitmap8"           # default font when no override is set
FONT_HEIGHT = const(8)     # height of bitmap8 glyphs
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

# Sensors-view band thresholds. Each tuple holds 3 strict upper bounds in
# ascending order; readings classify into 4 bands (band 0 < bands[0],
# band 3 >= bands[-1]) and pick the matching low->high icon.
SENSOR_TEMP_BANDS = (12, 24, 28) # Temperature bands (°C): cold / cool / warm / hot.
SENSOR_PRESSURE_BANDS = (1000, 1013, 1025) # Pressure bands (hPa): around the 1013.25 hPa standard atmosphere.
SENSOR_HUMIDITY_BANDS = (30, 50, 70) # Humidity bands (%RH): dry -> very humid.
SENSOR_GAS_BANDS = (70, 140, 280) # Gas resistance bands (kΩ): polluted -> clean.
