"""Open-Meteo access for hourly forecast and air-quality data."""

import time

# HTTP (not HTTPS) on purpose: no TLS handshake and its large contiguous-heap block.
_FORECAST_URL = "http://api.open-meteo.com/v1/forecast"
_AIR_QUALITY_URL = "http://air-quality-api.open-meteo.com/v1/air-quality"

# Keep ``forecast_hours`` and ``past_hours`` small, so each response body stays under ~1 KiB:
# larger bodies can fail to allocate on-device.


def _build_url(
    base: str, lat: float, lon: float, metrics: str, forecast_hours: int, past_hours: int
) -> str:
    return (
        base
        + "?timezone=auto"
        + "&latitude=" + str(lat)
        + "&longitude=" + str(lon)
        + "&hourly=" + metrics
        + "&past_hours=" + str(past_hours)
        + "&forecast_hours=" + str(forecast_hours)
    )


def is_location_set(latitude: float, longitude: float) -> bool:
    """Return whether the coordinates are set: 0.0/0.0, a point at sea, means unset."""
    return not (latitude == 0.0 and longitude == 0.0)


def fetch_forecast(
    http_get, lat: float, lon: float, metrics: str, timeout_sec: int, forecast_hours: int, past_hours: int
) -> dict:
    """Fetch hourly forecast ``metrics``, ``past_hours`` back to ``forecast_hours`` ahead."""
    # http_get: (url, timeout_sec) -> dict
    return http_get(
        _build_url(_FORECAST_URL, lat, lon, metrics, forecast_hours, past_hours), timeout_sec=timeout_sec
    )


def fetch_air_quality(
    http_get, lat: float, lon: float, metrics: str, timeout_sec: int, forecast_hours: int, past_hours: int
) -> dict:
    """Fetch hourly air-quality ``metrics``, ``past_hours`` back to ``forecast_hours`` ahead."""
    # http_get: (url, timeout_sec) -> dict
    return http_get(
        _build_url(_AIR_QUALITY_URL, lat, lon, metrics, forecast_hours, past_hours), timeout_sec=timeout_sec
    )


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


def extract_hourly(payload: dict, keys) -> list[list]:  # keys: Iterable[str]
    """Return the requested ``hourly`` arrays, in ``keys`` order.

    Raises ``KeyError`` for a missing key and ``ValueError`` for unequal array lengths.
    """
    hourly = payload["hourly"]
    arrays = [hourly[k] for k in keys]
    if arrays:
        n = len(arrays[0])
        for a in arrays:
            if len(a) != n:
                raise ValueError("Open-Meteo hourly arrays have mismatched lengths")
    return arrays
