"""Weather and modelled soil moisture from Open-Meteo (free, no API key).

The design documents named OpenWeather, which needs a paid key for history.
Open-Meteo gives the current conditions, a 7-day forecast and the past 3 months
(rain and modelled soil moisture) in a single free request.
"""
from __future__ import annotations

import logging
import time
from datetime import date

log = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes -> (description, icon name used by the front end)
WMO = {
    0: ("Clear sky", "sun"), 1: ("Mainly clear", "sun"), 2: ("Partly cloudy", "partly"),
    3: ("Overcast", "cloud"), 45: ("Fog", "fog"), 48: ("Rime fog", "fog"),
    51: ("Light drizzle", "rain"), 53: ("Drizzle", "rain"), 55: ("Heavy drizzle", "rain"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"), 67: ("Freezing rain", "rain"),
    71: ("Light snow", "cloud"), 73: ("Snow", "cloud"), 75: ("Heavy snow", "cloud"),
    80: ("Rain showers", "rain"), 81: ("Rain showers", "rain"), 82: ("Violent showers", "storm"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm, hail", "storm"), 99: ("Thunderstorm, hail", "storm"),
}

_cache: dict = {}


def describe(code):
    return WMO.get(int(code) if code is not None else -1, ("Unknown", "cloud"))


def _openmeteo(lat, lon, timeout):
    import requests

    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "timezone": "auto",
        "past_days": 92,
        "forecast_days": 8,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code,precipitation",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
        "precipitation_probability_max,et0_fao_evapotranspiration",
        "hourly": "soil_moisture_3_to_9cm",
    }
    r = requests.get(FORECAST_URL, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    hourly = data.get("hourly", {})
    soil_by_day: dict = {}
    for t, v in zip(hourly.get("time", []), hourly.get("soil_moisture_3_to_9cm", [])):
        if v is not None:
            soil_by_day.setdefault(t[:10], []).append(v)

    d = data["daily"]
    days = []
    for i, day in enumerate(d["time"]):
        soil = soil_by_day.get(day)
        days.append(
            {
                "date": day,
                "code": d["weather_code"][i],
                "tmax": d["temperature_2m_max"][i],
                "tmin": d["temperature_2m_min"][i],
                "rain_mm": d["precipitation_sum"][i],
                "rain_chance": (d.get("precipitation_probability_max") or [None] * len(d["time"]))[i],
                "et0_mm": (d.get("et0_fao_evapotranspiration") or [None] * len(d["time"]))[i],
                "soil_moisture": round(sum(soil) / len(soil), 3) if soil else None,
            }
        )
    c = data["current"]
    current = {
        "time": c.get("time"),
        "temperature": c.get("temperature_2m"),
        "humidity": c.get("relative_humidity_2m"),
        "wind_kmh": c.get("wind_speed_10m"),
        "code": c.get("weather_code"),
        "rain_mm": c.get("precipitation"),
    }
    return current, days


class WeatherUnavailable(RuntimeError):
    """Open-Meteo could not be reached."""


def get_weather(lat, lon, timeout=20):
    """Return {source, current, past (92 days), forecast (today + 7)}. Cached for 30 minutes.

    Raises WeatherUnavailable if the service cannot be reached (nothing is simulated).
    """
    key = (round(lat, 2), round(lon, 2))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    try:
        current, days = _openmeteo(lat, lon, timeout)
    except Exception as exc:
        log.warning("Open-Meteo not reachable: %s", exc)
        raise WeatherUnavailable(
            "Cannot reach the weather service right now. Please try again in a few minutes."
        ) from exc

    today = date.today().isoformat()
    for item in [current] + days:
        item["description"], item["icon"] = describe(item.get("code"))
    result = {
        "source": "open-meteo",
        "current": current,
        "past": [d for d in days if d["date"] < today],
        "forecast": [d for d in days if d["date"] >= today][:8],
    }
    _cache[key] = (time.time(), result)
    return result
