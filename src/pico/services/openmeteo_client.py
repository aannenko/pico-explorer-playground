"""Shared Open-Meteo access for the network calendar streams.

Builds the two endpoint URLs (forecast + air-quality), runs the fetch via an
injected getter, and exposes the hourly-array helpers both consumers share.

Plain HTTP (not HTTPS) on purpose: the endpoints are public and keyless, and
on-device HTTPS isn't available on this build.
"""

import time

_FORECAST_URL = "http://api.open-meteo.com/v1/forecast"
_AIR_QUALITY_URL = "http://air-quality-api.open-meteo.com/v1/air-quality"

# ``hours`` (forecast_hours) and ``past_hours`` are supplied by the caller, not
# hardcoded here: both are derived in app.py from the calendar windows + refresh
# cadence (this module can't see either).  Keep the span small so each response
# body stays under ~1 KiB — larger bodies fail to allocate on the device.


def _build_url(
    base: str, lat: float, lon: float, metrics: str, hours: int, past_hours: int
) -> str:
    return (
        base
        + "?timezone=auto"
        + "&latitude=" + str(lat)
        + "&longitude=" + str(lon)
        + "&hourly=" + metrics
        + "&past_hours=" + str(past_hours)
        + "&forecast_hours=" + str(hours)
    )


def fetch_forecast(
    http_get, lat: float, lon: float, metrics: str, timeout_s: int, hours: int, past_hours: int
) -> dict:
    # http_get: (url, timeout_s) -> dict; may raise the typed http_client errors.
    return http_get(_build_url(_FORECAST_URL, lat, lon, metrics, hours, past_hours), timeout_s=timeout_s)


def fetch_air_quality(
    http_get, lat: float, lon: float, metrics: str, timeout_s: int, hours: int, past_hours: int
) -> dict:
    # http_get: (url, timeout_s) -> dict; may raise the typed http_client errors.
    return http_get(_build_url(_AIR_QUALITY_URL, lat, lon, metrics, hours, past_hours), timeout_s=timeout_s)


def parse_iso_local(text: str) -> int:
    """Parse a naive-local ``"YYYY-MM-DDTHH:MM"`` string to a local epoch.

    With ``timezone=auto`` the API returns already-local times, so ``mktime``
    of the components yields the local epoch directly (no DST math).
    """
    year = int(text[0:4])
    month = int(text[5:7])
    day = int(text[8:10])
    hour = int(text[11:13])
    minute = int(text[14:16])
    return time.mktime((year, month, day, hour, minute, 0, 0, 0))


def extract_hourly(payload: dict, keys) -> list:  # keys: Iterable[str]; -> list[list]
    """Return the requested ``hourly`` arrays, validating equal lengths.

    Raises ``KeyError`` for a missing key and ``ValueError`` when the arrays
    disagree in length, so a malformed payload makes the caller's fetch state
    machine back off instead of publishing a truncated snapshot.
    """
    hourly = payload["hourly"]
    arrays = [hourly[k] for k in keys]
    if arrays:
        n = len(arrays[0])
        for a in arrays:
            if len(a) != n:
                raise ValueError("Open-Meteo hourly arrays have mismatched lengths")
    return arrays
