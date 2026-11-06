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

TIME_ZONE_OFFSET_HOURS = 1.0  # Prague winter time (UTC+1); fractional zones work, e.g. 5.5

# Daylight Saving Time rules: (month, week, weekday, hour)
# week: -1 = last occurrence; weekday: 0=Mon .. 6=Sun (MicroPython convention)
# Set them to your zone's rules, or DST_OFFSET_HOURS = 0 if it has no DST.
DST_START = (3, -1, 6, 2)   # Last Sunday of March at 02:00 (standard time)
DST_END = (10, -1, 6, 3)    # Last Sunday of October at 03:00 (DST time)
DST_OFFSET_HOURS = 1.0      # Added during DST (CEST = UTC+2)

# Socket timeout (s) per HTTP connect/read, not a whole-fetch deadline; DNS lookups aren't covered.
HTTP_TIMEOUT_S = const(3)

SENSOR_READ_DELAY_MS = const(5_000)
BME690_TEMP_OFFSET = -2.1
BME690_HUM_OFFSET = 8.0
BME690_PRSR_OFFSET = 45.0

# Sensors.  Each tuple holds 5 strictly ascending edges:
# ``(cap_min, t1, t2, t3, cap_max)``.  The inner three edges drive
# the icon-swap band classification (4 bands per row).  The outer two
# edges (``cap_min`` / ``cap_max``) bound the 24-hour history graph: a value
# at ``cap_max`` plots at the top of the row, ``cap_min`` at the bottom;
# values outside the range render as a fill column only (no marker value
# pixel).
SENSOR_TEMP_BANDS = (16, 18, 25, 29, 31)              # °C: cold / cool / warm / hot
SENSOR_PRESSURE_BANDS = (980, 1000, 1013, 1025, 1040) # hPa: low -> high
SENSOR_HUMIDITY_BANDS = (10, 30, 50, 70, 90)          # %RH: dry -> very humid
SENSOR_GAS_BANDS = (50, 100, 200, 350, 500)           # kΩ: polluted -> clean

# Calendar: Weather forecast + UV row (Open-Meteo).
# The weather row mixes precipitation and UV (they rarely coincide).
# LATITUDE/LONGITUDE 0.0/0.0 disables fetching and showing weather and AQI.
# Precipitation is shown if probability >= PRECIP_PROB_THRESHOLD.
# UV_THRESHOLDS according to WHO UV index ``(warning, severe)``.
LATITUDE = 0.0
LONGITUDE = 0.0
PRECIP_PROB_THRESHOLD = const(30)
UV_THRESHOLDS = (6, 8)

# Calendar: air quality (Euro AQI scale) + pollen grains/m³ row (Open-Meteo).
# Shares LATITUDE/LONGITUDE above (0.0/0.0 keeps the row disabled).
# Each threshold tuple is ``(warning, severe)``: at/above the first edge
# shows a yellow bar, at/above the second a red one.
# POLLEN_SPECIES is variadic — add/remove Open-Meteo pollen names, without
# the ``_pollen`` suffix.
AQI_THRESHOLDS = (60, 80)
POLLEN_SPECIES = ["grass", "birch", "alder", "mugwort", "ragweed"]
POLLEN_THRESHOLDS = (50, 100)

# Calendar: waste collection schedule.  Each entry:
#   (label, color_index, (year, month, day), hour, minute, duration_min, period_weeks)
# label is shown on the bar; color_index picks the bar color, 0-based:
#   0=amber 1=sky 2=yellow 3=pink 4=sky 5=brown 6=gray
# period_weeks: 1=weekly, 2=biweekly, 0=once.  Set to [] to disable the row.
WASTE_SCHEDULE = [
    ("BIO",   5, (2026, 6,  4), 8, 0, 120, 2),
    ("PLAST", 2, (2026, 6,  5), 8, 0, 120, 2),
    ("MIXED", 6, (2026, 6, 10), 8, 0, 120, 2),
    ("PAPER", 1, (2026, 6, 12), 8, 0, 120, 2),
]
