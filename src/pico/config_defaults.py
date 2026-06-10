"""Default configuration for the Pico Explorer playground.

This module is the schema and default values for the runtime ``config``
namespace.  At boot, ``config_bootstrap.apply_overrides()`` imports it
and layers user overrides from ``config.py`` on top (in-memory only —
neither file is rewritten).

To customise the device: ``cp src/pico/config_defaults.py
src/pico/config.py`` (or copy only the keys you want to override —
``config.py`` is sparse), edit it (at minimum set ``WIFI_SSID`` /
``WIFI_PASSWORD``), reboot.  ``config.py`` is git-ignored.
"""

from micropython import const


FONT = "bitmap8"
FONT_HEIGHT = const(8)
TEXT_SCALE = const(3)

# WiFi credentials — override these in ``config.py``.  Booting with the
# placeholder defaults will fail at WiFi connect time.
WIFI_SSID = "YourSSID"
WIFI_PASSWORD = "YourPassword"

TIME_ZONE_OFFSET = const(1)  # Prague winter time (UTC+1)

# Daylight Saving Time rules: (month, week, weekday, hour)
# week: -1 = last occurrence; weekday: 0=Mon .. 6=Sun (MicroPython convention)
DST_START = (3, -1, 6, 2)   # Last Sunday of March at 02:00 (standard time)
DST_END = (10, -1, 6, 3)    # Last Sunday of October at 03:00 (DST time)
DST_OFFSET = const(1)       # +1 hour during DST (CEST = UTC+2)

SENSOR_READ_DELAY_MS = const(5_000)
BME690_TEMP_OFFSET = -2.1
BME690_HUM_OFFSET = 8.0
BME690_PRSR_OFFSET = 45.0

# Sensors-view band thresholds.  Each tuple holds 5 strictly ascending
# edges: ``(cap_min, t1, t2, t3, cap_max)``.  The inner three edges drive
# the icon-swap band classification (4 bands per row: blue/green/yellow/red
# style).  The outer two edges (``cap_min`` / ``cap_max``) bound the
# 24-hour history graph: a value at ``cap_max`` plots at the top of the row,
# ``cap_min`` at the bottom; values outside the range render as a pastel
# column only (no bright value pixel).
SENSOR_TEMP_BANDS = (16, 18, 25, 29, 31)              # °C: cold / cool / warm / hot
SENSOR_PRESSURE_BANDS = (980, 1000, 1013, 1025, 1040) # hPa: bracketing the 1013.25 hPa standard atmosphere
SENSOR_HUMIDITY_BANDS = (10, 30, 50, 70, 90)          # %RH: dry -> very humid
SENSOR_GAS_BANDS = (50, 100, 180, 280, 400)           # kΩ: polluted -> clean

# Waste collection schedule.  Each entry:
#   (label, color_index, (year, month, day), hour, minute, duration_min, period_weeks)
# label is shown on the bar; color_index picks the bar color, 0-based:
#   0=amber 1=sky 2=yellow 3=pink 4=teal 5=red-brown 6=gray
# period_weeks: 1=weekly, 2=biweekly.  Set to [] to disable the row.
WASTE_SCHEDULE = [
    ("BIO",   5, (2026, 6,  4), 8, 0, 120, 2),
    ("PLAST", 2, (2026, 6,  5), 8, 0, 120, 2),
    ("MIXED", 6, (2026, 6, 10), 8, 0, 120, 2),
    ("PAPER", 1, (2026, 6, 12), 8, 0, 120, 2),
]
