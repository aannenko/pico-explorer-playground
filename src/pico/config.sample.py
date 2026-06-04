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
BME690_TEMP_OFFSET = -1.7  # Temperature offset to apply to BME690 sensor readings
BME690_HUM_OFFSET = 5.0    # Humidity offset to apply to BME690 sensor readings
BME690_PRSR_OFFSET = 45    # Pressure offset (hPa) to apply to BME690 sensor readings

# Sensors-view band thresholds.  Each tuple holds 5 strictly ascending
# edges: ``(cap_min, t1, t2, t3, cap_max)``.  The inner three edges drive
# the icon-swap band classification (4 bands per row: blue/green/yellow/red
# style).  The outer two edges (``cap_min`` / ``cap_max``) bound the
# 24-hour history graph: a value at ``cap_max`` plots at the top of the row,
# ``cap_min`` at the bottom; values outside the range render as a pastel
# column only (no bright value pixel).
#
# bootstrap: schema v2
SENSOR_TEMP_BANDS = (16, 18, 25, 29, 31)              # °C: cold / cool / warm / hot
# bootstrap: schema v2
SENSOR_PRESSURE_BANDS = (980, 1000, 1013, 1025, 1040) # hPa: bracketing the 1013.25 hPa standard atmosphere
# bootstrap: schema v2
SENSOR_HUMIDITY_BANDS = (10, 30, 50, 70, 90)          # %RH: dry -> very humid
# bootstrap: schema v2
SENSOR_GAS_BANDS = (50, 100, 180, 280, 400)           # kΩ: polluted -> clean
