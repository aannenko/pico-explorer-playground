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
FONT_HEIGHT_PX = const(8)
TEXT_SCALE = const(3)

# WiFi credentials — override these in ``config.py``.  Booting with the
# placeholder defaults will fail at WiFi connect time.
WIFI_SSID = "YourSSID"
WIFI_PASSWORD = "YourPassword"

TIME_ZONE_OFFSET_HOURS = 1.0  # Prague winter time (UTC+1); fractional zones work, e.g. 5.5

# Daylight Saving Time rules: (month, week, weekday, hour)
# week: -1 = last occurrence; weekday: 0=Mon .. 6=Sun (MicroPython convention)
# Set them to your zone's rules, or DST_OFFSET_HOURS = 0 if it has no DST.
DST_START_RULE = (3, -1, 6, 2)  # Last Sunday of March at 02:00 (standard time)
DST_END_RULE = (10, -1, 6, 3)   # Last Sunday of October at 03:00 (DST time)
DST_OFFSET_HOURS = 1.0          # Added during DST (CEST = UTC+2)

# Socket timeout per HTTP connect/read, not a whole-fetch deadline; DNS lookups aren't covered.
HTTP_TIMEOUT_SEC = const(3)

BME690_READ_PERIOD_MS = const(5_000)
# Calibration offsets, added to the sensor's readings.
BME690_TEMP_OFFSET_C = -2.1
BME690_HUM_OFFSET_PCT = 8.0
BME690_PRSR_OFFSET_HPA = 45.0

# Sensors.  Each tuple holds 3 strictly ascending edges splitting a reading
# into 4 bands, which pick the icon in its quadrant; a value on an edge takes
# the band above it.
SENSOR_TEMP_BANDS = (18.0, 25.0, 29.0)            # °C: cold / cool / warm / hot
SENSOR_PRESSURE_BANDS = (1000.0, 1013.0, 1025.0)  # hPa: low -> high
SENSOR_HUMIDITY_BANDS = (30.0, 50.0, 70.0)        # %RH: dry -> very humid
SENSOR_GAS_BANDS = (100.0, 200.0, 350.0)          # kΩ: polluted -> clean

# Calendar: Weather forecast + UV row (Open-Meteo).
# The weather row mixes precipitation and UV (they rarely coincide).
# LATITUDE/LONGITUDE 0.0/0.0 disables fetching and showing weather and AQI.
# Precipitation is shown if probability >= PRECIP_PROB_THRESHOLD_PCT.
# UV_THRESHOLDS according to WHO UV index ``(warning, severe)``.
LATITUDE = 0.0
LONGITUDE = 0.0
PRECIP_PROB_THRESHOLD_PCT = const(30)
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
#   0=orange 1=sky 2=yellow 3=pink 4=blue 5=brown 6=gray 7=green 8=red
# period_weeks: 1=weekly, 2=biweekly, 0=once.  Set to [] to disable the row.
WASTE_SCHEDULE = [
    ("BIO",   5, (2026, 6,  4), 8, 0, 120, 2),
    ("PLAST", 2, (2026, 6,  5), 8, 0, 120, 2),
    ("MIXED", 6, (2026, 6, 10), 8, 0, 120, 2),
    ("PAPER", 1, (2026, 6, 12), 8, 0, 120, 2),
]
